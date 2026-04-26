import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from astrbot.api import AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .config import FileSyncConfig, validate_config
from .services.cloud_sync import CloudSyncService
from .services.state_manager import StateManager
from .models.sync_record import SyncRecord

logger = logging.getLogger(__name__)


@register("file_sync_plugin2", "Developer", "QQ群文件自动同步NextCloud", "1.0.0", "")
class FileSyncPlugin(Star):
    """QQ群文件自动同步NextCloud插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.cfg = config
        self.name = "file_sync_plugin2"
        self.config: Optional[FileSyncConfig] = None
        self.state_manager: Optional[StateManager] = None
        self.cloud_sync: Optional[CloudSyncService] = None
        self._sync_task: Optional[asyncio.Task] = None
        self._running = False

    async def initialize(self):
        """初始化插件"""
        logger.info("初始化 FileSyncPlugin...")

        if self.cfg is None:
            logger.error("插件配置未初始化")
            return

        plugin_config = dict(self.cfg)
        if not plugin_config:
            logger.error("插件配置为空，请检查配置")
            return

        self.config = validate_config(plugin_config)

        self.state_manager = StateManager()
        self.cloud_sync = CloudSyncService(self.config)

        self._running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info(f"定时同步任务已启动，间隔: {self.config.sync_interval_minutes}分钟")

    async def terminate(self):
        """插件卸载时调用"""
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        if self.state_manager:
            self.state_manager.close()

    async def _sync_loop(self):
        """定时同步循环"""
        while self._running:
            try:
                await self.sync_all_groups()
            except Exception as e:
                logger.error(f"定时同步任务执行失败: {e}")

            await asyncio.sleep(self.config.sync_interval_minutes * 60)

    @staticmethod
    def _write_file(file_path: Path, content: bytes) -> None:
        """同步写入文件（用于 asyncio.to_thread 包装）"""
        with open(file_path, "wb") as f:
            f.write(content)

    @filter.command("同步文件")
    async def sync_files_command(self, event: AstrMessageEvent):
        """手动触发一次同步"""
        yield event.plain_result("开始同步...")
        await self.sync_all_groups()
        yield event.plain_result("同步完成")

    @filter.command("同步状态")
    async def sync_status_command(self, event: AstrMessageEvent):
        """查看同步状态"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return
        stats = self.state_manager.get_sync_stats()
        yield event.plain_result(
            f"已同步文件: {stats['total_synced']}\n"
            f"待重试: {stats['pending_retries']}"
        )

    @filter.command("同步统计")
    async def sync_stats_command(self, event: AstrMessageEvent):
        """查看同步统计"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return
        stats = self.state_manager.get_sync_stats()
        pending = self.state_manager.get_pending_retries()
        msg = f"已同步文件: {stats['total_synced']}\n待重试任务: {stats['pending_retries']}"
        if pending:
            msg += "\n\n待重试文件:"
            for p in pending[:5]:
                msg += f"\n- {p['file_name']} (尝试 {p['attempts']} 次)"
        yield event.plain_result(msg)

    async def sync_all_groups(self):
        """同步所有配置的群"""
        logger.info("开始同步所有群...")

        if not self.config:
            logger.error("配置未初始化")
            return

        for group_id in self.config.enabled_groups:
            try:
                await self.sync_group(group_id)
            except Exception as e:
                logger.error(f"同步群 {group_id} 失败: {e}")

        await self.process_retry_queue()
        logger.info("同步完成")

    async def get_group_info(self, group_id: str) -> tuple:
        """获取群信息，返回 (群名称, 群号)"""
        platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            return (f"Group_{group_id}", group_id)

        client = platform.get_client()
        try:
            result = await client.api.call_action(
                "get_group_info",
                group_id=int(group_id)
            )
            group_name = result.get("group_name", f"Group_{group_id}")
            return (group_name, group_id)
        except Exception as e:
            logger.warning(f"获取群 {group_id} 信息失败: {e}")
            return (f"Group_{group_id}", group_id)

    async def sync_group(self, group_id: str):
        """同步单个群的文件"""
        platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            logger.error("无法获取QQ平台")
            return

        client = platform.get_client()

        group_name, group_id = await self.get_group_info(group_id)
        logger.info(f"正在同步群: {group_name} ({group_id})")

        last_sync_time = self.state_manager.get_last_sync_time(group_id)
        if last_sync_time:
            logger.info(f"群 {group_id} 上次同步时间: {last_sync_time}")
        else:
            logger.info(f"群 {group_id} 首次同步，将同步所有文件")

        try:
            result = await client.api.call_action(
                "get_group_file_list",
                group_id=int(group_id)
            )
        except httpx.HTTPError as e:
            logger.error(f"获取群 {group_id} 文件列表失败: {e}")
            return

        files = result.get("files", [])
        logger.info(f"群 {group_id} 共有 {len(files)} 个文件")

        sync_time = datetime.now()
        new_files_count = 0

        for file_info in files:
            file_id = file_info.get("fileid")
            file_name = file_info.get("filename")
            file_size = file_info.get("size", 0)
            upload_time_ts = file_info.get("upload_time", 0)

            upload_time = datetime.fromtimestamp(upload_time_ts) if upload_time_ts else None

            if not self.config.is_file_type_allowed(file_name):
                logger.debug(f"跳过不允许的文件类型: {file_name}")
                continue

            if last_sync_time and upload_time:
                if upload_time <= last_sync_time:
                    logger.debug(f"跳过旧文件: {file_name} (上传时间: {upload_time})")
                    continue

            target_path = self.config.generate_target_path(group_name, group_id, file_name)

            success = await self.sync_single_file(
                group_id, target_path, file_id, file_name, file_size
            )

            if success:
                new_files_count += 1
                record = SyncRecord(
                    file_id=file_id,
                    file_name=file_name,
                    file_size=file_size,
                    group_id=group_id,
                    target_path=target_path,
                    sync_time=datetime.now()
                )
                self.state_manager.add_sync_record(record)
            else:
                if self.config.retry_queue_enabled:
                    self.state_manager.add_to_retry_queue(
                        file_id, file_name, file_size, group_id, target_path,
                        self.config.retry_delay_seconds
                    )

        self.state_manager.update_last_sync_time(group_id, sync_time)
        logger.info(f"群 {group_id} 同步完成，新增 {new_files_count} 个文件")

    async def sync_single_file(self, group_id: str, target_path: str,
                               file_id: str, file_name: str, file_size: int) -> bool:
        """同步单个文件"""
        try:
            platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
            client = platform.get_client()
            url_result = await client.api.call_action(
                "get_group_file_url",
                group_id=int(group_id),
                file_id=file_id
            )
            file_url = url_result.get("url")
            if not file_url:
                logger.error(f"无法获取文件下载链接: {file_name}")
                return False

            temp_dir = Path(tempfile.gettempdir()) / "file_sync"
            temp_dir.mkdir(exist_ok=True)
            local_path = temp_dir / file_name

            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(file_url)
                response.raise_for_status()
                await asyncio.to_thread(self._write_file, local_path, response.content)

            remote_path = f"{target_path}/{file_name}"
            upload_success = await asyncio.to_thread(self.cloud_sync.upload_file, str(local_path), remote_path)

            local_path.unlink(missing_ok=True)

            return upload_success

        except httpx.HTTPError as e:
            logger.error(f"下载文件失败 {file_name}: {e}")
            return False
        except IOError as e:
            logger.error(f"文件IO操作失败 {file_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"同步文件失败 {file_name}: {e}")
            return False

    async def process_retry_queue(self):
        """处理重试队列"""
        if not self.state_manager:
            return

        pending = self.state_manager.get_pending_retries()
        for item in pending:
            if item["attempts"] >= self.config.retry_max_attempts:
                logger.warning(f"文件 {item['file_name']} 重试次数超限，移出队列")
                self.state_manager.remove_from_retry_queue(item["file_id"])
                continue

            success = await self.sync_single_file(
                item["group_id"], item["target_path"],
                item["file_id"], item["file_name"], item["file_size"]
            )

            if success:
                self.state_manager.remove_from_retry_queue(item["file_id"])
                record = SyncRecord(
                    file_id=item["file_id"],
                    file_name=item["file_name"],
                    file_size=item["file_size"],
                    group_id=item["group_id"],
                    target_path=item["target_path"],
                    sync_time=datetime.now()
                )
                self.state_manager.add_sync_record(record)
