import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .config import FileSyncConfig, validate_config
from .services.cloud_sync import CloudSyncService
from .services.state_manager import StateManager
from .models.sync_record import SyncRecord


@register("file_sync_plugin3", "Developer", "QQ群文件自动同步NextCloud", "1.0.0")
class FileSyncPlugin(Star):
    """QQ群文件自动同步NextCloud插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.cfg = config
        self.name = "file_sync_plugin3"
        self.config: Optional[FileSyncConfig] = None
        self.state_manager: Optional[StateManager] = None
        self.cloud_sync: Optional[CloudSyncService] = None
        self._sync_task: Optional[asyncio.Task] = None
        self._running = False

        logger.info("================================================================")
        logger.info("========== FileSyncPlugin __init__ 开始 ==========")
        logger.info(f"插件名称: {self.name}")
        logger.info(f"Context 类型: {type(self.context)}")
        logger.info(f"Config 类型: {type(self.cfg)}")
        logger.info(f"Config 内容: {self.cfg}")

        try:
            if self.cfg is None:
                logger.error("❌ 插件配置未初始化，self.cfg 为 None")
                return

            logger.info("✓ 配置对象存在，开始转换...")
            plugin_config = dict(self.cfg)
            logger.info(f"转换后的配置字典: {plugin_config}")

            if not plugin_config:
                logger.error("❌ 插件配置为空，请检查配置")
                return

            logger.info("✓ 开始验证配置...")
            self.config = validate_config(plugin_config)
            logger.info(f"✓ 配置验证成功")
            logger.info(f"  - enabled_groups: {self.config.enabled_groups}")
            logger.info(f"  - sync_interval_minutes: {self.config.sync_interval_minutes}")
            logger.info(f"  - base_path: {self.config.base_path}")
            logger.info(f"  - file_type_whitelist: {self.config.file_type_whitelist}")

            if not self.config.enabled_groups:
                logger.warning("⚠️ 配置中 enabled_groups 为空，请添加需要同步的群号")
            else:
                logger.info(f"✓ 已配置 {len(self.config.enabled_groups)} 个群: {self.config.enabled_groups}")

            logger.info("✓ 初始化状态管理器...")
            self.state_manager = StateManager()
            logger.info("✓ 状态管理器初始化完成")

            logger.info("✓ 初始化云同步服务...")
            self.cloud_sync = CloudSyncService(self.config)
            logger.info("✓ 云同步服务初始化完成")

            self._running = True
            logger.info("✓ 启动定时同步任务...")
            self._sync_task = asyncio.create_task(self._sync_loop())
            logger.info(f"✓ 定时同步任务已启动，间隔: {self.config.sync_interval_minutes}分钟")

        except Exception as e:
            logger.error(f"❌ 初始化插件时发生异常: {e}", exc_info=True)

        logger.info("========== FileSyncPlugin __init__ 结束 ==========")
        logger.info("================================================================")

    async def initialize(self):
        """可选的异步初始化方法"""
        logger.info("========== initialize() 被调用 ==========")
        logger.info(f"当前配置状态: {self.config is not None}")
        logger.info(f"状态管理器状态: {self.state_manager is not None}")
        logger.info(f"云同步服务状态: {self.cloud_sync is not None}")
        logger.info(f"定时任务状态: {self._sync_task is not None}")

    async def terminate(self):
        """插件卸载时调用"""
        logger.info("================================================================")
        logger.info("========== 插件开始卸载 ==========")
        logger.info(f"当前运行状态: {self._running}")
        logger.info(f"定时任务存在: {self._sync_task is not None}")

        self._running = False
        if self._sync_task:
            logger.info("正在取消定时同步任务...")
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                logger.info("✓ 定时同步任务已取消")

        if self.state_manager:
            logger.info("正在关闭数据库连接...")
            self.state_manager.close()
            logger.info("✓ 数据库连接已关闭")

        logger.info("========== 插件卸载完成 ==========")
        logger.info("================================================================")

    async def _sync_loop(self):
        """定时同步循环"""
        logger.info("========== 定时同步循环启动 ==========")
        logger.info(f"同步间隔: {self.config.sync_interval_minutes} 分钟")
        loop_count = 0

        while self._running:
            loop_count += 1
            logger.info(f"--- 定时同步第 {loop_count} 轮开始 ---")

            try:
                await self.sync_all_groups()
            except Exception as e:
                logger.error(f"❌ 定时同步任务执行失败: {e}", exc_info=True)

            if self._running:
                wait_seconds = self.config.sync_interval_minutes * 60
                logger.info(f"等待 {self.config.sync_interval_minutes} 分钟后进行下次同步")
                await asyncio.sleep(wait_seconds)

        logger.info("========== 定时同步循环已停止 ==========")

    @staticmethod
    def _write_file(file_path: Path, content: bytes) -> None:
        """同步写入文件（用于 asyncio.to_thread 包装）"""
        with open(file_path, "wb") as f:
            f.write(content)

    @filter.command("同步文件")
    async def sync_files_command(self, event: AstrMessageEvent):
        """手动触发一次同步"""
        logger.info("================================================================")
        logger.info("========== 收到手动同步命令 ==========")
        logger.info(f"发送者: {event.get_sender_name()}")
        logger.info(f"当前配置状态: {self.config is not None}")
        logger.info(f"当前状态管理器: {self.state_manager is not None}")
        logger.info(f"当前云同步服务: {self.cloud_sync is not None}")

        yield event.plain_result("开始同步...")
        synced_count = await self.sync_all_groups()

        if synced_count == 0:
            logger.info("手动同步完成，未处理任何群")
            yield event.plain_result("同步完成，但未处理任何群（请检查 enabled_groups 配置）")
        else:
            logger.info(f"手动同步完成，共处理 {synced_count} 个群")
            yield event.plain_result(f"同步完成，共处理 {synced_count} 个群")

        logger.info("========== 手动同步命令处理完毕 ==========")
        logger.info("================================================================")

    @filter.command("同步状态")
    async def sync_status_command(self, event: AstrMessageEvent):
        """查看同步状态"""
        logger.info("收到查看同步状态命令")
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return
        stats = self.state_manager.get_sync_stats()
        logger.info(f"同步状态: 已同步 {stats['total_synced']} 个文件，待重试 {stats['pending_retries']} 个")
        yield event.plain_result(
            f"已同步文件: {stats['total_synced']}\n"
            f"待重试: {stats['pending_retries']}"
        )

    @filter.command("同步统计")
    async def sync_stats_command(self, event: AstrMessageEvent):
        """查看同步统计"""
        logger.info("收到查看同步统计命令")
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return
        stats = self.state_manager.get_sync_stats()
        pending = self.state_manager.get_pending_retries()
        logger.info(f"同步统计: 已同步 {stats['total_synced']} 个文件，待重试 {len(pending)} 个")
        msg = f"已同步文件: {stats['total_synced']}\n待重试任务: {stats['pending_retries']}"
        if pending:
            msg += "\n\n待重试文件:"
            for p in pending[:5]:
                msg += f"\n- {p['file_name']} (尝试 {p['attempts']} 次)"
        yield event.plain_result(msg)

    async def sync_all_groups(self) -> int:
        """同步所有配置的群，返回同步的群数量"""
        logger.info("开始同步所有群...")

        if not self.config:
            logger.error("配置未初始化，跳过同步")
            return 0

        if not self.config.enabled_groups:
            logger.warning("未配置任何群号，跳过同步")
            return 0

        synced_count = 0
        for group_id in self.config.enabled_groups:
            try:
                await self.sync_group(group_id)
                synced_count += 1
            except Exception as e:
                logger.error(f"同步群 {group_id} 失败: {e}")

        await self.process_retry_queue()
        logger.info(f"同步完成，共处理 {synced_count} 个群")
        return synced_count

    async def get_group_info(self, group_id: str) -> tuple:
        """获取群信息，返回 (群名称, 群号)"""
        logger.debug(f"正在获取群 {group_id} 的信息")
        platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            logger.warning(f"无法获取QQ平台，使用默认群名 Group_{group_id}")
            return (f"Group_{group_id}", group_id)

        client = platform.get_client()
        try:
            result = await client.api.call_action(
                "get_group_info",
                group_id=int(group_id)
            )
            group_name = result.get("group_name", f"Group_{group_id}")
            logger.debug(f"获取到群信息: {group_name} ({group_id})")
            return (group_name, group_id)
        except Exception as e:
            logger.warning(f"获取群 {group_id} 信息失败: {e}，使用默认群名")
            return (f"Group_{group_id}", group_id)

    async def sync_group(self, group_id: str):
        """同步单个群的文件"""
        logger.info(f"开始同步群 {group_id}")
        platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            logger.error("无法获取QQ平台，跳过同步")
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
            logger.debug(f"正在获取群 {group_id} 的文件列表")
            result = await client.api.call_action(
                "get_group_file_list",
                group_id=int(group_id)
            )
        except httpx.HTTPError as e:
            logger.error(f"获取群 {group_id} 文件列表失败: {e}")
            return
        except Exception as e:
            logger.error(f"获取群 {group_id} 文件列表时发生未知错误: {e}", exc_info=True)
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
        logger.info(f"开始同步文件: {file_name} (ID: {file_id}, 大小: {file_size} 字节)")
        try:
            platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
            if not platform:
                logger.error(f"无法获取QQ平台，跳过文件 {file_name}")
                return False

            client = platform.get_client()
            logger.debug(f"正在获取文件 {file_name} 的下载链接")
            url_result = await client.api.call_action(
                "get_group_file_url",
                group_id=int(group_id),
                file_id=file_id
            )
            file_url = url_result.get("url")
            if not file_url:
                logger.error(f"无法获取文件下载链接: {file_name}")
                return False

            logger.debug(f"文件下载链接: {file_url[:50]}...")

            temp_dir = Path(tempfile.gettempdir()) / "file_sync"
            temp_dir.mkdir(exist_ok=True)
            local_path = temp_dir / file_name

            logger.debug(f"正在下载文件到本地: {local_path}")
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(file_url)
                response.raise_for_status()
                await asyncio.to_thread(self._write_file, local_path, response.content)
            logger.debug(f"文件下载完成，大小: {len(response.content)} 字节")

            remote_path = f"{target_path}/{file_name}"
            logger.debug(f"正在上传文件到NextCloud: {remote_path}")
            upload_success = await asyncio.to_thread(self.cloud_sync.upload_file, str(local_path), remote_path)

            local_path.unlink(missing_ok=True)

            if upload_success:
                logger.info(f"文件同步成功: {file_name}")
            else:
                logger.error(f"文件上传失败: {file_name}")

            return upload_success

        except httpx.HTTPError as e:
            logger.error(f"下载文件失败 {file_name}: {e}")
            return False
        except IOError as e:
            logger.error(f"文件IO操作失败 {file_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"同步文件失败 {file_name}: {e}", exc_info=True)
            return False

    async def process_retry_queue(self):
        """处理重试队列"""
        if not self.state_manager:
            logger.warning("状态管理器未初始化，跳过重试队列处理")
            return

        pending = self.state_manager.get_pending_retries()
        if not pending:
            logger.debug("重试队列为空")
            return

        logger.info(f"处理重试队列，共 {len(pending)} 个任务")
        for item in pending:
            logger.info(f"重试文件: {item['file_name']} (尝试次数: {item['attempts']})")
            if item["attempts"] >= self.config.retry_max_attempts:
                logger.warning(f"文件 {item['file_name']} 重试次数超限 ({item['attempts']}/{self.config.retry_max_attempts})，移出队列")
                self.state_manager.remove_from_retry_queue(item["file_id"])
                continue

            success = await self.sync_single_file(
                item["group_id"], item["target_path"],
                item["file_id"], item["file_name"], item["file_size"]
            )

            if success:
                logger.info(f"重试成功: {item['file_name']}")
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
            else:
                logger.warning(f"重试失败: {item['file_name']}")
