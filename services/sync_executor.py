"""单文件同步执行器

协调下载 → 上传 → 记录 的完整流程。
"""

import asyncio
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import filter

from ..utils.constants import CN_TZ


class SyncExecutor:
    """单文件同步流程协调器"""

    def __init__(self, plugin):
        """初始化

        Args:
            plugin: FileSyncPlugin 实例
        """
        self._plugin = plugin

    @property
    def config(self):
        return self._plugin.config

    @property
    def state_manager(self):
        return self._plugin.state_manager

    @property
    def cloud_sync(self):
        return self._plugin.cloud_sync

    async def sync_single_file(
        self,
        group_id: str,
        target_path: str,
        file_id: str,
        file_name: str,
        file_size: int
    ) -> bool:
        """同步单个文件：下载 → 上传 → 记录

        Args:
            group_id: 群号
            target_path: NextCloud 目标目录
            file_id: QQ 群文件 ID
            file_name: 文件名
            file_size: 文件大小（字节）

        Returns:
            是否同步成功
        """
        from .file_downloader import FileDownloader

        logger.info(f"[SYNC] 开始同步文件: {file_name} ({file_size / (1024*1024):.1f} MB)")

        # 获取 QQ 客户端
        platform = self._plugin.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            logger.error(f"[SYNC] 无法获取QQ平台")
            return False

        client = platform.get_client()
        downloader = FileDownloader(client)

        local_path = None
        try:
            # 1. 下载文件
            success, local_path = await downloader.download_file(
                group_id=group_id,
                file_id=file_id,
                file_name=file_name,
                file_size=file_size
            )
            if not success or not local_path:
                return False

            # 2. 上传到 NextCloud
            remote_path = f"{target_path}/{file_name}"
            logger.info(f"[SYNC] 准备上传: {remote_path}")

            upload_success = await asyncio.to_thread(
                self.cloud_sync.upload_file_direct,
                local_path, remote_path, file_size
            )

            if not upload_success:
                logger.error(f"[SYNC] 上传失败: {file_name}")
                return False

            logger.info(f"[SYNC] 文件同步成功: {file_name}")
            return True

        except Exception as e:
            logger.error(f"[SYNC] 同步文件异常 {file_name}: {e}", exc_info=True)
            return False
        finally:
            # 清理本地临时文件
            downloader.cleanup(local_path)
