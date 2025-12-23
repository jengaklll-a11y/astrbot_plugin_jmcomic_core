import os
import re
import yaml
import asyncio
import traceback
import logging
import concurrent.futures
import jmcomic
from threading import Lock
from typing import Tuple, Optional, Set, List
from pathlib import Path
import img2pdf

from .utils import CosmosConfig, ResourceManager

logger = logging.getLogger("astrbot")

class JMClientFactory:
    """JM客户端工厂"""
    def __init__(self, config: CosmosConfig, resource_manager: ResourceManager):
        self.config = config
        self.rm = resource_manager
        self.option = self._create_option()

    def _create_option(self):
        # 构造配置字典
        option_dict = {
            "client": {
                "impl": "html",
                "domain": self.config.domain_list,
                "retry_times": 5,
                "postman": {
                    "meta_data": {
                        "proxies": {"https": self.config.proxy} if self.config.proxy else None,
                        "cookies": {"AVS": self.config.avs_cookie},
                        "headers": {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
                            "Referer": f"https://{self.config.domain_list[0]}/"
                        },
                    }
                },
            },
            "download": {
                "cache": True,
                "image": {"decode": True, "suffix": ".jpg"},
                "threading": {"image": self.config.max_threads, "photo": self.config.max_threads},
            },
            "dir_rule": {"base_dir": str(self.rm.downloads_dir)},
        }
        return jmcomic.create_option_by_str(yaml.safe_dump(option_dict, allow_unicode=True))

    def create_client(self):
        return self.option.new_jm_client()

    def create_client_with_domain(self, domain: str):
        """创建临时使用的特定域名客户端"""
        # 复制逻辑简化，核心是覆盖 domain
        opt = self._create_option()
        opt.client.domain = [domain]
        return opt.new_jm_client()

    def update_option(self):
        self.option = self._create_option()

class ComicDownloader:
    """下载管理器"""
    def __init__(self, factory: JMClientFactory, rm: ResourceManager, config: CosmosConfig):
        self.factory = factory
        self.rm = rm
        self.config = config
        self.downloading_comics: Set[str] = set()
        self.downloading_covers: Set[str] = set()
        self._lock = Lock()
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(config.max_threads, 20),
            thread_name_prefix="jm_download"
        )

    async def download_cover(self, album_id: str) -> Tuple[bool, str]:
        if album_id in self.downloading_covers:
            return False, "封面下载中"
        
        self.downloading_covers.add(album_id)
        try:
            client = self.factory.create_client()
            album = client.get_album_detail(album_id)
            if not album: return False, "漫画不存在"
            
            image = client.get_photo_detail(album[0].photo_id, True)[0]
            cover_path = self.rm.get_cover_path(album_id)
            
            # 删除旧封面
            if os.path.exists(cover_path): os.remove(cover_path)
            
            # 下载
            client.download_by_image_detail(image, cover_path)
            return True, cover_path
        except Exception as e:
            return False, str(e)
        finally:
            self.downloading_covers.discard(album_id)

    async def download_comic(self, album_id: str) -> Tuple[bool, Optional[str]]:
        """异步下载漫画入口"""
        with self._lock:
            if album_id in self.downloading_comics:
                return False, "正在下载中"
            self.downloading_comics.add(album_id)

        try:
            # 检查空间
            has_space, _ = self.rm.check_storage_space()
            if not has_space:
                self.rm.cleanup_old_files()
                if not self.rm.check_storage_space()[0]:
                    return False, "存储空间不足"

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._thread_pool, self._download_sync, album_id)
        finally:
            with self._lock:
                self.downloading_comics.discard(album_id)

    def _download_sync(self, album_id: str) -> Tuple[bool, Optional[str]]:
        """同步下载逻辑 (在线程池运行)"""
        try:
            logger.info(f"开始下载: {album_id}")
            option = self.factory.option
            
            # 核心下载尝试 (三层回退逻辑)
            try:
                # 1. 正常下载
                jmcomic.download_album(album_id, option)
            except Exception as e:
                logger.warning(f"主域名下载失败: {e}, 尝试备用域名...")
                success = False
                # 2. 备用域名重试
                for domain in self.config.domain_list[1:3]:
                    try:
                        backup_opt = self.factory._create_option() # 简化的创建方式
                        backup_opt.client.domain = [domain]
                        jmcomic.download_album(album_id, backup_opt)
                        success = True
                        break
                    except Exception:
                        continue
                
                if not success:
                    raise e # 抛出原始异常

            # PDF 转换
            self._convert_to_pdf(album_id)
            return True, None

        except Exception as e:
            logger.error(f"下载失败 {album_id}: {traceback.format_exc()}")
            return False, str(e)

    def _convert_to_pdf(self, album_id: str):
        """转换图片为PDF"""
        album_dir = self.rm.get_comic_folder(album_id)
        if not album_dir.exists(): return

        image_files = sorted(list(album_dir.glob("*.jpg")) + list(album_dir.glob("*.png")))
        if not image_files: return

        pdf_path = self.rm.get_pdf_path(album_id)
        with open(pdf_path, "wb") as f:
            f.write(img2pdf.convert([str(img) for img in image_files]))
        logger.info(f"PDF生成完毕: {pdf_path}")

    def get_total_pages(self, client, album) -> int:
        try:
            return sum(len(client.get_photo_detail(p.photo_id, False)) for p in album)
        except:
            return 0
            
    def shutdown(self):
        self._thread_pool.shutdown(wait=True)
