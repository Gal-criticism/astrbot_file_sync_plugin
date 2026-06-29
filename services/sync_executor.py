"""单文件同步执行器

协调 命名分析 → 下载 → 上传 的完整流程，返回细化的 SyncResult。
"""

import asyncio
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import filter

from ..models.sync_result import SyncResult


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
    def naming_validator(self):
        return getattr(self._plugin, 'naming_validator', None)

    async def sync_single_file(
        self,
        group_id: str,
        target_path: str,
        file_id: str,
        file_name: str,
        file_size: int
    ) -> SyncResult:
        """同步单个文件：命名分析 → 下载 → 上传

        Args:
            group_id: 群号
            target_path: NextCloud 目标目录
            file_id: QQ 群文件 ID
            file_name: 文件名
            file_size: 文件大小（字节）

        Returns:
            SyncResult 包含成功/失败状态、失败阶段、命名分析结果
        """
        from .file_downloader import FileDownloader

        logger.info(f"[SYNC] 开始同步文件: {file_name} ({file_size / (1024*1024):.1f} MB)")

        # ── 命名规范分析 ──
        naming_result = self._analyze_naming(file_name)

        # 获取 QQ 客户端
        platform = self._plugin.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            logger.error(f"[SYNC] 无法获取QQ平台")
            return SyncResult(
                success=False, file_name=file_name, file_id=file_id,
                file_size=file_size, group_id=group_id, target_path=target_path,
                failed_stage="sync_no_platform", failed_detail="无法获取QQ平台",
                naming_category=naming_result.category, naming_project=naming_result.project_name,
                naming_version=naming_result.version, naming_is_valid=naming_result.is_valid,
                naming_error=naming_result.error_reason,
            )

        client = platform.get_client()
        downloader = FileDownloader(client)

        local_path = None
        try:
            # 1. 下载文件
            dl_success, local_path, dl_error, dl_detail = await downloader.download_file(
                group_id=group_id,
                file_id=file_id,
                file_name=file_name,
                file_size=file_size
            )
            if not dl_success:
                return SyncResult(
                    success=False, file_name=file_name, file_id=file_id,
                    file_size=file_size, group_id=group_id, target_path=target_path,
                    failed_stage=dl_error, failed_detail=dl_detail,
                    naming_category=naming_result.category, naming_project=naming_result.project_name,
                    naming_version=naming_result.version, naming_is_valid=naming_result.is_valid,
                    naming_error=naming_result.error_reason,
                )

            # 2. 上传到 NextCloud
            remote_path = f"{target_path}/{file_name}"
            logger.info(f"[SYNC] 准备上传: {remote_path}")

            upload_success, upload_error, upload_detail = await asyncio.to_thread(
                self._plugin.cloud_sync.upload_file_direct,
                local_path, remote_path, file_size
            )

            if not upload_success:
                return SyncResult(
                    success=False, file_name=file_name, file_id=file_id,
                    file_size=file_size, group_id=group_id, target_path=target_path,
                    failed_stage=upload_error, failed_detail=upload_detail,
                    naming_category=naming_result.category, naming_project=naming_result.project_name,
                    naming_version=naming_result.version, naming_is_valid=naming_result.is_valid,
                    naming_error=naming_result.error_reason,
                )

            logger.info(f"[SYNC] 文件同步成功: {file_name}")
            return SyncResult(
                success=True, file_name=file_name, file_id=file_id,
                file_size=file_size, group_id=group_id, target_path=target_path,
                naming_category=naming_result.category, naming_project=naming_result.project_name,
                naming_version=naming_result.version, naming_is_valid=naming_result.is_valid,
                naming_error=naming_result.error_reason,
            )

        except Exception as e:
            logger.error(f"[SYNC] 同步文件异常 {file_name}: {e}", exc_info=True)
            return SyncResult(
                success=False, file_name=file_name, file_id=file_id,
                file_size=file_size, group_id=group_id, target_path=target_path,
                failed_stage="sync_exception", failed_detail=f"{type(e).__name__}: {e}",
                naming_category=naming_result.category, naming_project=naming_result.project_name,
                naming_version=naming_result.version, naming_is_valid=naming_result.is_valid,
                naming_error=naming_result.error_reason,
            )
        finally:
            # 清理本地临时文件
            downloader.cleanup(local_path)

    def _analyze_naming(self, file_name: str) -> "NamingResult":
        """分析文件命名规范（用于诊断日志记录）"""
        if self.naming_validator:
            return self.naming_validator.parse(file_name)

        # 回退：降级结果
        from ..models.naming_result import NamingResult
        return NamingResult(is_valid=None, filename=file_name)
