import asyncio
from datetime import datetime
from typing import Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .config import FileSyncConfig, validate_config
from .utils.config_helpers import ensure_list
from .utils.constants import CN_TZ

from .services.cloud_sync import CloudSyncService
from .services.state_manager import StateManager
from .services.naming_validator import NamingValidator
from .models.sync_record import SyncRecord


@register("file_sync_plugin", "Developer", "QQ群文件自动同步NextCloud", "1.0.0")
class FileSyncPlugin(Star):
    """QQ群文件自动同步NextCloud插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.cfg = config
        self.name = "file_sync_plugin"
        self.config: Optional[FileSyncConfig] = None
        self.state_manager: Optional[StateManager] = None
        self.cloud_sync: Optional[CloudSyncService] = None
        self.filename_checker = None
        self.naming_validator: Optional[NamingValidator] = None
        self.notify_service = None
        self._sync_task: Optional[asyncio.Task] = None
        self._running = False

        # 命令处理器（延迟初始化）
        self._sync_cmd_handler = None
        self._diag_cmd_handler = None
        self._file_event_handler = None

        logger.info("========== FileSyncPlugin 初始化 ==========")

        try:
            if self.cfg is None:
                logger.error("插件配置未初始化，self.cfg 为 None")
                return

            self._init_config()
            self._init_services()
            self._start_sync_loop()

        except Exception as e:
            logger.error(f"初始化插件时发生异常: {e}", exc_info=True)

        logger.info("========== FileSyncPlugin 初始化完成 ==========")

    # ===== 初始化方法 =====

    def _init_config(self):
        """初始化配置"""
        plugin_config = dict(self.cfg)

        if not plugin_config:
            logger.error("插件配置为空，请检查配置")
            return

        # 处理列表字段
        plugin_config["enabled_groups"] = ensure_list(plugin_config.get("enabled_groups", []))
        plugin_config["file_type_whitelist"] = ensure_list(plugin_config.get("file_type_whitelist", ["*"]))

        # 处理数值字段
        for key, default, min_val in [
            ("sync_interval_minutes", 1440, 1),
            ("retry_max_attempts", 3, 1),
            ("retry_delay_seconds", 300, 60),
        ]:
            val = plugin_config.get(key, default)
            try:
                val = int(val)
            except (ValueError, TypeError):
                val = default
            if val < min_val:
                val = default
            plugin_config[key] = val

        # 检查必填字符串字段
        for key in ("nextcloud_url", "nextcloud_username", "nextcloud_password"):
            val = plugin_config.get(key, "")
            if not val or not str(val).strip():
                logger.warning(f"配置项 {key} 为空，部分功能可能不可用")

        self.config = validate_config(plugin_config)
        logger.info(f"配置验证成功 - 群: {self.config.enabled_groups}")

    def _init_services(self):
        """初始化服务"""
        if not self.config:
            return

        self.state_manager = StateManager()
        logger.info("状态管理器初始化完成")

        self.cloud_sync = CloudSyncService(self.config)
        logger.info("云同步服务初始化完成")

        # 初始化文件名检查器（新规范 + 旧兼容）
        if self.config.filename_check_enabled:
            from .services.naming_validator import NamingValidator
            from .services.filename_checker import FilenameChecker
            from .services.notify_service import NotifyService

            # 新规范验证器
            extra_cats = self.config.get_naming_extra_categories()
            self.naming_validator = NamingValidator(extra_categories=extra_cats if extra_cats else None)

            # 旧兼容层
            old_cats = self.config.get_filename_categories()
            self.filename_checker = FilenameChecker(
                template=self.config.filename_template,
                categories=old_cats if old_cats else {}
            )

            self.notify_service = NotifyService(
                template=self.config.filename_notify_template
            )
            logger.info(f"文件名检查器已启用（新规范 + 旧兼容）")
        else:
            logger.info("文件名检查未启用")

        self._running = True

    def _start_sync_loop(self):
        """启动定时同步循环"""
        if not self.config:
            return

        if self.config.sync_enabled:
            self._sync_task = asyncio.create_task(self._sync_loop())
            mode = "时间点" if self.config.has_time_points() else "间隔"
            logger.info(f"定时同步已启动（{mode}模式）")
        else:
            logger.info("同步功能已禁用（sync_enabled=false）")
            self._sync_task = None

    async def initialize(self):
        """可选的异步初始化方法（AstrBot 生命周期）"""
        logger.info("========== initialize() ==========")

        # 延迟初始化命令处理器（此时所有 handler 类已可用）
        from .handlers.sync_commands import SyncCommandHandler
        from .handlers.diagnostic_commands import DiagnosticCommandHandler
        from .handlers.file_events import FileEventHandler

        self._sync_cmd_handler = SyncCommandHandler(self)
        self._diag_cmd_handler = DiagnosticCommandHandler(self)
        self._file_event_handler = FileEventHandler(self)

        # 预热：从 NextCloud 远程文件列表填充 SQLite 查重数据
        if self.config and self.config.enabled_groups and self.cloud_sync and self.state_manager:
            logger.info("开始预热 SQLite 查重数据...")
            warmed_groups = 0
            for group_id in self.config.enabled_groups:
                try:
                    group_name_raw, _ = await self.get_group_info(group_id)
                    group_safe_name = group_name_raw.replace(" ", "_")
                    group_base_path = f"{self.config.base_path}/{group_safe_name}_{group_id}"
                    files_on_cloud = self.cloud_sync.list_remote_files(group_base_path)
                    if files_on_cloud:
                        self.state_manager.populate_from_remote_list(files_on_cloud, group_id)
                        logger.info(f"群 {group_id} 预热完成，写入 {len(files_on_cloud)} 条记录")
                        warmed_groups += 1
                    else:
                        logger.info(f"群 {group_id} 远程目录无文件，预热跳过")
                except Exception as e:
                    logger.warning(f"群 {group_id} 预热失败: {e}")
            logger.info(f"查重数据预热完成，共处理 {warmed_groups} 个群")

    async def terminate(self):
        """插件卸载时调用"""
        logger.info("========== 插件开始卸载 ==========")
        self._running = False

        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                logger.info("定时同步任务已取消")

        if self.state_manager:
            self.state_manager.close()
            logger.info("数据库连接已关闭")

        logger.info("========== 插件卸载完成 ==========")

    # ===== 定时同步循环 =====

    async def _sync_loop(self):
        """定时同步循环"""
        logger.info("定时同步循环启动")
        loop_count = 0

        while self._running:
            loop_count += 1
            logger.info(f"--- 定时同步第 {loop_count} 轮 ---")

            try:
                await self.sync_all_groups()
            except Exception as e:
                logger.error(f"定时同步执行失败: {e}", exc_info=True)

            if self._running:
                now = datetime.now(CN_TZ)
                wait_seconds = self.config.get_next_delay_seconds(now)
                logger.info(f"等待 {wait_seconds / 60:.1f} 分钟后下次同步")
                await asyncio.sleep(wait_seconds)

        logger.info("定时同步循环已停止")

    # ===== 命令处理器 =====

    @filter.command("同步文件")
    async def sync_files_command(self, event: AstrMessageEvent):
        """手动触发一次同步"""
        if not self._sync_cmd_handler:
            self._ensure_handlers()
        async for result in self._sync_cmd_handler.handle_sync_files(event):
            yield result

    @filter.command("同步状态")
    async def sync_status_command(self, event: AstrMessageEvent):
        """查看同步状态"""
        if not self._sync_cmd_handler:
            self._ensure_handlers()
        async for result in self._sync_cmd_handler.handle_sync_status(event):
            yield result

    @filter.command("同步统计")
    async def sync_stats_command(self, event: AstrMessageEvent):
        """查看同步统计"""
        if not self._sync_cmd_handler:
            self._ensure_handlers()
        async for result in self._sync_cmd_handler.handle_sync_stats(event):
            yield result

    @filter.command("同步调试")
    async def sync_debug_command(self, event: AstrMessageEvent):
        """调试命令"""
        if not self._sync_cmd_handler:
            self._ensure_handlers()
        async for result in self._sync_cmd_handler.handle_sync_debug(event):
            yield result

    @filter.command("诊断日志")
    async def diagnostic_logs_command(self, event: AstrMessageEvent):
        """查看诊断日志"""
        if not self._diag_cmd_handler:
            self._ensure_handlers()
        async for result in self._diag_cmd_handler.handle_diagnostic_logs(event):
            yield result

    @filter.command("清空诊断日志")
    async def clear_diagnostic_logs_command(self, event: AstrMessageEvent):
        """清空诊断日志"""
        if not self._diag_cmd_handler:
            self._ensure_handlers()
        async for result in self._diag_cmd_handler.handle_clear_diagnostic_logs(event):
            yield result

    def _ensure_handlers(self):
        """确保 handler 已初始化（从 __init__ 直接构建场景）"""
        from .handlers.sync_commands import SyncCommandHandler
        from .handlers.diagnostic_commands import DiagnosticCommandHandler
        from .handlers.file_events import FileEventHandler
        if not self._sync_cmd_handler:
            self._sync_cmd_handler = SyncCommandHandler(self)
        if not self._diag_cmd_handler:
            self._diag_cmd_handler = DiagnosticCommandHandler(self)
        if not self._file_event_handler:
            self._file_event_handler = FileEventHandler(self)

    # ===== 文件上传事件 =====

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_file_upload(self, event: AstrMessageEvent):
        """监听群文件上传消息，检测文件名是否合规"""
        if not self._file_event_handler:
            self._ensure_handlers()
        async for result in self._file_event_handler.handle_file_upload(event):
            yield result

    # ===== 同步核心逻辑 =====

    async def sync_all_groups(self) -> int:
        """同步所有配置的群，返回同步的群数量"""
        logger.info("开始同步所有群...")

        if not self.config or not self.config.sync_enabled:
            logger.info("同步功能未启用或未配置")
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
        platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            return (f"Group_{group_id}", group_id)

        client = platform.get_client()
        try:
            result = await client.api.call_action("get_group_info", group_id=int(group_id))
            group_name = result.get("group_name", f"Group_{group_id}")
            return (group_name, group_id)
        except Exception as e:
            logger.warning(f"获取群 {group_id} 信息失败: {e}")
            return (f"Group_{group_id}", group_id)

    async def _get_group_files(self, client, group_id: str) -> list:
        """获取群文件列表，尝试多种 API 端点以兼容不同后端"""
        api_endpoints = ["get_group_root_files", "get_group_file_list", "get_group_files"]

        for api_name in api_endpoints:
            try:
                result = await client.api.call_action(api_name, group_id=int(group_id))
                logger.debug(f"API {api_name} 成功")

                if isinstance(result, dict):
                    files = result.get("files", [])
                    if files or result.get("folders"):
                        return files
                if isinstance(result, list):
                    return result

            except Exception as e:
                error_msg = str(e)
                if "1404" in error_msg or "不支持" in error_msg:
                    logger.warning(f"API {api_name} 不被支持，尝试下一个")
                    continue
                else:
                    logger.error(f"API {api_name} 失败: {e}")
                    continue

        logger.error("所有文件列表 API 均失败")
        return []

    async def sync_group(self, group_id: str):
        """同步单个群的文件"""
        logger.info(f"开始同步群 {group_id}")

        platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            logger.error("无法获取QQ平台，跳过同步")
            return

        client = platform.get_client()
        group_name, group_id = await self.get_group_info(group_id)
        last_sync_time = self.state_manager.get_last_sync_time(group_id)

        self.state_manager.add_diagnostic_log("sync_state", f"群 {group_id} 同步状态", {
            "group_id": group_id,
            "last_sync_time": str(last_sync_time),
            "is_first_sync": last_sync_time is None,
        })

        files = await self._get_group_files(client, group_id)
        if not files:
            logger.warning(f"群 {group_id} 没有获取到文件")
            return

        logger.info(f"群 {group_id} 共有 {len(files)} 个文件")
        sync_time = datetime.now(CN_TZ)
        new_files_count = 0

        for file_info in files:
            file_id = file_info.get("file_id") or file_info.get("fileid") or file_info.get("id", "")
            file_name = file_info.get("file_name") or file_info.get("filename") or file_info.get("name", "")
            file_size = file_info.get("file_size") or file_info.get("size", 0)
            upload_time_ts = file_info.get("add_time") or file_info.get("upload_time") or file_info.get("create_time", 0)
            upload_time = datetime.fromtimestamp(upload_time_ts, tz=CN_TZ) if upload_time_ts else None

            # 类型过滤
            if not self.config.is_file_type_allowed(file_name):
                continue

            # 时间戳检查
            if last_sync_time and upload_time and upload_time <= last_sync_time:
                continue

            # 两层去重
            if self.state_manager.is_synced(file_id):
                continue
            if self.state_manager.is_synced_by_name_size(file_name, file_size, group_id):
                continue

            target_path = self.config.generate_target_path(group_name, group_id, file_name)
            success = await self._sync_single_file(
                group_id, target_path, file_id, file_name, file_size
            )

            if success:
                new_files_count += 1
                record = SyncRecord(
                    file_id=file_id, file_name=file_name, file_size=file_size,
                    group_id=group_id, target_path=target_path,
                    sync_time=datetime.now(CN_TZ)
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

    async def _sync_single_file(self, group_id: str, target_path: str,
                                 file_id: str, file_name: str, file_size: int) -> bool:
        """同步单个文件（委托给 SyncExecutor）"""
        from .services.sync_executor import SyncExecutor
        executor = SyncExecutor(self)
        return await executor.sync_single_file(
            group_id=group_id,
            target_path=target_path,
            file_id=file_id,
            file_name=file_name,
            file_size=file_size,
        )

    # ===== 重试队列 =====

    async def _notify_retry_failed(self, item: dict):
        """通知用户文件重试同步失败"""
        msg = (
            f"[文件同步] 重试失败通知\n"
            f"文件: {item['file_name']}\n"
            f"群号: {item['group_id']}\n"
            f"已尝试 {item['attempts']} 次，已达上限，不再重试"
        )
        logger.warning(msg)
        try:
            platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
            if platform and self.config and self.config.enabled_groups:
                client = platform.get_client()
                await client.api.call_action(
                    "send_group_msg",
                    group_id=int(self.config.enabled_groups[0]),
                    message=msg
                )
        except Exception as e:
            logger.error(f"发送重试失败通知失败: {e}")

    async def process_retry_queue(self):
        """处理重试队列"""
        if not self.state_manager:
            return

        pending = self.state_manager.get_pending_retries()
        if not pending:
            return

        logger.info(f"处理重试队列，共 {len(pending)} 个任务")
        for item in pending:
            logger.info(f"重试文件: {item['file_name']} ({item['attempts']}次尝试)")

            if item["attempts"] >= self.config.retry_max_attempts:
                logger.warning(f"文件 {item['file_name']} 重试次数超限，移出队列")
                self.state_manager.remove_from_retry_queue(item["file_id"])
                await self._notify_retry_failed(item)
                continue

            success = await self._sync_single_file(
                item["group_id"], item["target_path"],
                item["file_id"], item["file_name"], item["file_size"]
            )

            if success:
                logger.info(f"重试成功: {item['file_name']}")
                self.state_manager.remove_from_retry_queue(item["file_id"])
                record = SyncRecord(
                    file_id=item["file_id"], file_name=item["file_name"],
                    file_size=item["file_size"], group_id=item["group_id"],
                    target_path=item["target_path"], sync_time=datetime.now(CN_TZ)
                )
                self.state_manager.add_sync_record(record)
            else:
                logger.warning(f"重试失败: {item['file_name']}")
