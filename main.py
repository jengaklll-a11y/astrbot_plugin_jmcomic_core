from astrbot.api.message_components import Image, Plain, File
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import os
import json
import asyncio
import traceback
import random

from .utils import CosmosConfig, ResourceManager
from .core import JMClientFactory, ComicDownloader

@register("jm_cosmos", "GEMILUXVII", "全能型JM漫画下载与管理工具 (Refactored)", "1.1.0")
class JMCosmosPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.plugin_name = "jm_cosmos"
        
        # 1. 初始化资源管理
        self.rm = ResourceManager(self.plugin_name)
        self.rm.clear_cover_cache()
        
        # 2. 加载配置 (优先使用传入的 AstrBot 配置，否则使用默认)
        if config:
            self.config = CosmosConfig.from_dict(config)
        else:
            # 兼容旧逻辑：尝试读取本地配置或使用默认
            self.config = CosmosConfig.from_dict({}) 
            
        # 3. 初始化核心组件
        self.client_factory = JMClientFactory(self.config, self.rm)
        self.downloader = ComicDownloader(self.client_factory, self.rm, self.config)
        
        logger.info(f"JMCosmos 加载完成: {self.config.domain_list[0]}")

    @filter.command("jm")
    async def cmd_download(self, event: AstrMessageEvent, comic_id: str):
        """下载漫画: /jm [ID]"""
        if not comic_id.isdigit():
            yield event.plain_result("ID必须为纯数字")
            return

        yield event.plain_result(f"开始下载漫画 {comic_id}...")
        
        # 检查是否已存在 PDF
        pdf_path = self.rm.get_pdf_path(comic_id)
        if os.path.exists(pdf_path):
            yield event.plain_result("检测到缓存，直接发送...")
            await self._send_file(event, pdf_path, f"{comic_id}.pdf")
            return

        # 执行下载
        success, msg = await self.downloader.download_comic(comic_id)
        if not success:
            yield event.plain_result(f"下载失败: {msg}")
            return
            
        # 发送
        if os.path.exists(pdf_path):
            yield event.plain_result("下载完成，正在发送...")
            await self._send_file(event, pdf_path, f"{comic_id}.pdf")
        else:
            yield event.plain_result("下载完成但PDF生成失败，请检查日志。")

    @filter.command("jminfo")
    async def cmd_info(self, event: AstrMessageEvent, comic_id: str):
        """查看详情: /jminfo [ID]"""
        try:
            client = self.client_factory.create_client()
            album = client.get_album_detail(comic_id)
            
            # 下载封面
            success, cover_path = await self.downloader.download_cover(comic_id)
            if not success: cover_path = self.rm.get_cover_path(comic_id)
            
            msg = (f"📖: {album.title}\n🆔: {comic_id}\n"
                   f"🏷️: {', '.join(album.tags[:5])}\n"
                   f"📃: {self.downloader.get_total_pages(client, album)}页")
            
            chain = [Plain(msg)]
            if self.config.show_cover and os.path.exists(cover_path):
                chain.append(Image.fromFileSystem(cover_path))
            
            yield event.chain_result(chain)
        except Exception as e:
            yield event.plain_result(f"获取信息失败: {e}")

    @filter.command("jmconfig")
    async def cmd_config(self, event: AstrMessageEvent):
        """简易配置查看"""
        info = (f"当前配置:\n域 名: {self.config.domain_list}\n"
                f"代 理: {self.config.proxy}\n"
                f"线程数: {self.config.max_threads}")
        yield event.plain_result(info)

    async def _send_file(self, event: AstrMessageEvent, path: str, name: str):
        """统一的文件发送逻辑，保留了对 aiocqhttp 的特殊处理"""
        try:
            file_size_mb = os.path.getsize(path) / (1024 * 1024)
            if file_size_mb > 90:
                yield event.plain_result(f"⚠️ 文件过大 ({file_size_mb:.2f}MB)，发送可能失败")

            # aiocqhttp 特殊优化 (原版逻辑)
            if event.get_platform_name() == "aiocqhttp" and event.get_group_id():
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                if isinstance(event, AiocqhttpMessageEvent):
                    try:
                        await event.bot.upload_group_file(
                            group_id=event.get_group_id(), file=path, name=name
                        )
                        return # API 调用成功，直接返回
                    except Exception as e:
                        logger.warning(f"API上传失败，回退到普通发送: {e}")

            # 通用发送
            yield event.chain_result([File(name=name, file=path)])
            
        except Exception as e:
            logger.error(f"发送文件异常: {traceback.format_exc()}")
            yield event.plain_result(f"发送文件失败: {e}")

    async def terminate(self):
        """卸载清理"""
        if hasattr(self, 'downloader'):
            self.downloader.shutdown()
