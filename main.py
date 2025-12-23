import os
import yaml
import json
import time
import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
from astrbot.api.star import StarTools

logger = logging.getLogger("astrbot")

@dataclass
class CosmosConfig:
    """Cosmos插件配置类"""
    domain_list: List[str]
    proxy: Optional[str]
    avs_cookie: str
    max_threads: int
    debug_mode: bool
    show_cover: bool

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "CosmosConfig":
        return cls(
            domain_list=config_dict.get("domain_list", ["18comic.vip", "jm365.xyz", "18comic.org"]),
            proxy=config_dict.get("proxy"),
            avs_cookie=config_dict.get("avs_cookie", ""),
            max_threads=int(config_dict.get("max_threads", 10)),
            debug_mode=bool(config_dict.get("debug_mode", False)),
            show_cover=bool(config_dict.get("show_cover", True)),
        )

class ResourceManager:
    """资源管理器，管理文件路径和创建必要的目录"""

    def __init__(self, plugin_name: str):
        self.base_dir = Path(StarTools.get_data_dir(plugin_name))
        self.downloads_dir = self.base_dir / "downloads"
        self.pdfs_dir = self.base_dir / "pdfs"
        self.logs_dir = self.base_dir / "logs"
        self.temp_dir = self.base_dir / "temp"
        self.covers_dir = self.base_dir / "covers"
        
        self.max_storage_size = 2 * 1024 * 1024 * 1024  # 2GB
        self.max_file_age_days = 30

        # 创建目录
        for dir_path in [self.downloads_dir, self.pdfs_dir, self.logs_dir, self.temp_dir, self.covers_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def check_storage_space(self) -> Tuple[bool, int]:
        total_size = sum(f.stat().st_size for f in self.base_dir.rglob('*') if f.is_file())
        return total_size < self.max_storage_size, total_size

    def cleanup_old_files(self) -> int:
        cutoff_time = time.time() - (self.max_file_age_days * 86400)
        cleaned_count = 0
        for file_path in self.base_dir.rglob('*'):
            if file_path.is_file() and file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    cleaned_count += 1
                except Exception as e:
                    logger.error(f"清理文件失败 {file_path}: {e}")
        return cleaned_count

    def get_storage_info(self) -> dict:
        has_space, total_size = self.check_storage_space()
        return {
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "max_size_mb": round(self.max_storage_size / (1024 * 1024), 2),
            "has_space": has_space,
            "usage_percent": round((total_size / self.max_storage_size) * 100, 2),
        }

    def get_comic_folder(self, comic_id: str) -> Path:
        """查找漫画文件夹，支持多种命名方式"""
        # 1. 尝试直接 ID 匹配
        id_path = self.downloads_dir / str(comic_id)
        if id_path.exists():
            return id_path

        # 2. 尝试模糊匹配
        if self.downloads_dir.exists():
            for item in self.downloads_dir.iterdir():
                if not item.is_dir(): continue
                # 精确格式匹配
                if (item.name.startswith(f"{comic_id}_") or 
                    item.name.endswith(f"_{comic_id}") or 
                    item.name.startswith(f"[{comic_id}]") or 
                    item.name == str(comic_id)):
                    return item
        
        # 默认返回
        return id_path

    def get_cover_path(self, comic_id: str) -> str:
        return str(self.covers_dir / f"{comic_id}.jpg")

    def get_pdf_path(self, comic_id: str) -> str:
        return str(self.pdfs_dir / f"{comic_id}.pdf")

    def clear_cover_cache(self) -> int:
        count = 0
        if self.covers_dir.exists():
            for f in self.covers_dir.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                        count += 1
                    except Exception:
                        pass
        return count
