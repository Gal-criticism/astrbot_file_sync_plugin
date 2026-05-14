import asyncio
import json
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .config import FileSyncConfig, validate_config

CN_TZ = ZoneInfo("Asia/Shanghai")


def _ensure_list(value) -> list:
    """确保值为列表类型，处理 JSON 字符串格式的列表"""
    # 先处理外层类型
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
        except (json.JSONDecodeError, TypeError):
            pass
        if isinstance(value, str) and value.strip():
            value = [v.strip() for v in value.split(",")]

    if not isinstance(value, list):
        return []

    # 再处理列表内每个元素（可能嵌套了字符串化的列表）
    result = []
    for item in value:
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
                if isinstance(parsed, list):
                    result.extend(parsed)
                    continue
            except (json.JSONDecodeError, TypeError):
                pass
            if item.strip():
                result.append(item.strip())
        elif isinstance(item, list):
            result.extend(_ensure_list(item))
        else:
            result.append(item)
    return result


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

            # 处理 AstrBot 可能以 JSON 字符串传入的列表字段
            plugin_config["enabled_groups"] = _ensure_list(plugin_config.get("enabled_groups", []))
            plugin_config["file_type_whitelist"] = _ensure_list(plugin_config.get("file_type_whitelist", ["*"]))

            # 处理数值字段：AstrBot 可能传入字符串或 0，需要转换并替换为默认值
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

            # 处理必填字符串字段：AstrBot 可能传入空字符串
            for key in ("nextcloud_url", "nextcloud_username", "nextcloud_password"):
                val = plugin_config.get(key, "")
                if not val or not str(val).strip():
                    logger.warning(f"⚠️ 配置项 {key} 为空，部分功能可能不可用")

            logger.info(f"✓ 字段预处理完成: enabled_groups={plugin_config['enabled_groups']}, sync_interval={plugin_config['sync_interval_minutes']}分钟")

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
        if self.config.has_time_points():
            logger.info(f"同步模式: 时间点模式，时间点: {self.config.sync_time_points}")
        else:
            logger.info(f"同步模式: 间隔模式，间隔: {self.config.sync_interval_minutes} 分钟")
        loop_count = 0

        while self._running:
            loop_count += 1
            logger.info(f"--- 定时同步第 {loop_count} 轮开始 ---")

            try:
                await self.sync_all_groups()
            except Exception as e:
                logger.error(f"❌ 定时同步任务执行失败: {e}", exc_info=True)

            if self._running:
                from datetime import datetime
                now = datetime.now(CN_TZ)
                wait_seconds = self.config.get_next_delay_seconds(now)
                wait_minutes = wait_seconds / 60
                logger.info(f"等待 {wait_minutes:.1f} 分钟后进行下次同步")
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

        # 获取命令参数（群号）
        args = event.message_str.strip().split()
        group_id = args[1] if len(args) > 1 else None

        if group_id:
            # 查看指定群的详细统计
            stats = self.state_manager.get_group_stats(group_id)
            msg = f"=== 群 {group_id} 同步统计 ===\n"
            msg += f"已同步文件: {stats['synced']}\n"
            msg += f"待重试: {stats['pending']}\n"
            msg += f"最后同步: {stats['last_sync_time'] or '从未同步'}\n"

            if stats['recent_files']:
                msg += "\n最近同步文件:\n"
                for f in stats['recent_files']:
                    msg += f"- {f['name']} ({f['size']} 字节)\n"
        else:
            # 显示总览 + 分群统计
            total_stats = self.state_manager.get_sync_stats()
            group_stats = self.state_manager.get_sync_stats_by_group()

            msg = "=== 同步统计总览 ===\n"
            msg += f"总同步文件: {total_stats['total_synced']}\n"
            msg += f"总待重试: {total_stats['pending_retries']}\n"
            msg += f"启用群数: {len(self.config.enabled_groups)}\n"

            if group_stats:
                msg += "\n=== 分群统计 ===\n"
                for gid, stats in group_stats.items():
                    msg += f"\n群 {gid}:\n"
                    msg += f"  已同步: {stats['synced']}\n"
                    msg += f"  待重试: {stats['pending']}\n"
                    msg += f"  最后同步: {stats['last_sync_time'] or '从未同步'}\n"

        yield event.plain_result(msg)

    @filter.command("同步调试")
    async def sync_debug_command(self, event: AstrMessageEvent):
        """调试命令：检查后端支持的 API"""
        logger.info("收到调试命令")
        platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            yield event.plain_result("无法获取QQ平台")
            return

        client = platform.get_client()
        msg = "=== 后端 API 调试信息 ===\n"

        # 1. 检查支持的 API 列表
        try:
            result = await client.api.call_action("get_supported_actions")
            actions = result if isinstance(result, list) else []
            file_apis = [a for a in actions if "file" in a.lower()]
            msg += f"支持的文件相关 API: {file_apis if file_apis else '无'}\n"
            msg += f"总支持 API 数量: {len(actions)}\n"
        except Exception as e:
            msg += f"获取支持的 API 失败: {e}\n"

        # 2. 测试各个文件 API
        test_apis = [
            "get_group_root_files",
            "get_group_file_list",
            "get_group_files",
        ]
        for api_name in test_apis:
            try:
                result = await client.api.call_action(
                    api_name,
                    group_id=int(self.config.enabled_groups[0]) if self.config.enabled_groups else 0
                )
                msg += f"{api_name}: 可用 (返回类型: {type(result).__name__})\n"
            except Exception as e:
                error_msg = str(e)[:80]
                msg += f"{api_name}: 不可用 ({error_msg})\n"

        logger.info(f"调试信息: {msg}")
        yield event.plain_result(msg)

    @filter.command("诊断日志")
    async def diagnostic_logs_command(self, event: AstrMessageEvent):
        """查看诊断日志"""
        logger.info("收到查看诊断日志命令")
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return

        logs = self.state_manager.get_diagnostic_logs(limit=20)
        if not logs:
            yield event.plain_result("暂无诊断日志，请先执行一次同步")
            return

        msg = "=== 最近诊断日志 ===\n"
        for log in logs:
            msg += f"[{log['timestamp']}] {log['type']}: {log['message']}\n"
            if log['data']:
                for key, value in log['data'].items():
                    msg += f"  - {key}: {value}\n"
            msg += "\n"

        yield event.plain_result(msg)

    @filter.command("清空诊断日志")
    async def clear_diagnostic_logs_command(self, event: AstrMessageEvent):
        """清空诊断日志"""
        logger.info("收到清空诊断日志命令")
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return

        self.state_manager.clear_diagnostic_logs()
        yield event.plain_result("诊断日志已清空")

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

    async def _get_group_files(self, client, group_id: str) -> list:
        """获取群文件列表，尝试多种 API 端点以兼容不同后端"""
        # 尝试的 API 端点列表（按优先级排序）
        api_endpoints = [
            "get_group_root_files",      # 标准 OneBot 11 端点
            "get_group_file_list",        # go-cqhttp 扩展端点
            "get_group_files",            # 部分后端使用
        ]

        for api_name in api_endpoints:
            try:
                logger.debug(f"尝试 API: {api_name}, group_id={group_id}")
                result = await client.api.call_action(
                    api_name,
                    group_id=int(group_id)
                )
                logger.info(f"API {api_name} 调用成功")

                # 标准响应格式: {"files": [...], "folders": [...]}
                if isinstance(result, dict):
                    files = result.get("files", [])
                    folders = result.get("folders", [])
                    if files or folders:
                        logger.info(f"获取到 {len(files)} 个文件, {len(folders)} 个文件夹")
                        return files

                # 某些后端直接返回列表
                if isinstance(result, list):
                    logger.info(f"获取到 {len(result)} 个项目")
                    return result

                logger.warning(f"API {api_name} 返回格式异常: {type(result)}")
            except Exception as e:
                error_msg = str(e)
                if "1404" in error_msg or "不支持" in error_msg:
                    logger.warning(f"API {api_name} 不被支持，尝试下一个")
                    continue
                else:
                    logger.error(f"API {api_name} 调用失败: {e}")
                    continue

        logger.error(f"所有文件列表 API 均失败，当前后端可能不支持群文件操作")
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
        logger.info(f"正在同步群: {group_name} ({group_id})")

        last_sync_time = self.state_manager.get_last_sync_time(group_id)
        self.state_manager.add_diagnostic_log("sync_state", f"群 {group_id} 同步状态", {
            "group_id": group_id,
            "last_sync_time": str(last_sync_time),
            "is_first_sync": last_sync_time is None
        })
        if last_sync_time:
            logger.info(f"群 {group_id} 上次同步时间: {last_sync_time}")
        else:
            logger.info(f"群 {group_id} 首次同步，将同步所有文件")

        files = await self._get_group_files(client, group_id)
        if not files:
            logger.warning(f"群 {group_id} 没有获取到文件或文件列表 API 不可用")
            return

        logger.info(f"群 {group_id} 共有 {len(files)} 个文件")

        sync_time = datetime.now(CN_TZ)
        new_files_count = 0

        for file_info in files:
            # 兼容不同后端的字段命名格式
            file_id = file_info.get("file_id") or file_info.get("fileid") or file_info.get("id", "")
            file_name = file_info.get("file_name") or file_info.get("filename") or file_info.get("name", "")
            file_size = file_info.get("file_size") or file_info.get("size", 0)
            upload_time_ts = file_info.get("add_time") or file_info.get("upload_time") or file_info.get("create_time", 0)

            upload_time = datetime.fromtimestamp(upload_time_ts, tz=CN_TZ) if upload_time_ts else None

            # 收集诊断日志
            self.state_manager.add_diagnostic_log("file_info", f"文件: {file_name}", {
                "file_id": file_id,
                "file_size": file_size,
                "upload_time_ts": upload_time_ts,
                "upload_time": str(upload_time),
                "last_sync_time": str(last_sync_time),
                "raw_fields": list(file_info.keys())
            })

            if not self.config.is_file_type_allowed(file_name):
                self.state_manager.add_diagnostic_log("skip", f"跳过不允许的文件类型: {file_name}", {"reason": "file_type_not_allowed"})
                continue

            # 时间戳检查
            if last_sync_time and upload_time:
                if upload_time <= last_sync_time:
                    self.state_manager.add_diagnostic_log("skip", f"跳过旧文件: {file_name}", {
                        "reason": "old_file",
                        "upload_time": str(upload_time),
                        "last_sync_time": str(last_sync_time)
                    })
                    continue
                else:
                    self.state_manager.add_diagnostic_log("check", f"文件较新: {file_name}", {
                        "reason": "new_file",
                        "upload_time": str(upload_time),
                        "last_sync_time": str(last_sync_time)
                    })
            else:
                self.state_manager.add_diagnostic_log("check", f"跳过时间戳检查: {file_name}", {
                    "reason": "missing_time",
                    "has_last_sync_time": last_sync_time is not None,
                    "has_upload_time": upload_time is not None
                })

            # 第一层去重：基于 file_id
            if self.state_manager.is_synced(file_id):
                self.state_manager.add_diagnostic_log("skip", f"跳过已同步文件(file_id): {file_name}", {
                    "reason": "file_id_synced",
                    "file_id": file_id
                })
                continue

            # 第二层去重：基于文件名+大小+群号
            if self.state_manager.is_synced_by_name_size(file_name, file_size, group_id):
                self.state_manager.add_diagnostic_log("skip", f"跳过已同步文件(name+size): {file_name}", {
                    "reason": "name_size_synced",
                    "file_size": file_size
                })
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
                    sync_time=datetime.now(CN_TZ)
                )
                self.state_manager.add_diagnostic_log("sync_success", f"文件同步成功: {file_name}", {
                    "file_id": file_id,
                    "file_name": file_name,
                    "file_size": file_size,
                    "target_path": target_path
                })
                self.state_manager.add_sync_record(record)
            else:
                if self.config.retry_queue_enabled:
                    self.state_manager.add_to_retry_queue(
                        file_id, file_name, file_size, group_id, target_path,
                        self.config.retry_delay_seconds
                    )

        self.state_manager.add_diagnostic_log("sync_state", f"群 {group_id} 同步完成", {
            "group_id": group_id,
            "new_files_count": new_files_count,
            "sync_time": str(sync_time)
        })
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

            # 尝试多种 API 获取下载链接
            file_url = None
            url_apis = ["get_group_file_url", "get_file_url"]
            for api_name in url_apis:
                try:
                    url_result = await client.api.call_action(
                        api_name,
                        group_id=int(group_id),
                        file_id=file_id
                    )
                    file_url = url_result.get("url")
                    if file_url:
                        break
                except Exception as e:
                    logger.warning(f"API {api_name} 失败: {e}")
                    continue
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
            if platform:
                client = platform.get_client()
                # 尝试发送到配置的第一个群
                if self.config.enabled_groups:
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
                await self._notify_retry_failed(item)
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
                    sync_time=datetime.now(CN_TZ)
                )
                self.state_manager.add_sync_record(record)
            else:
                logger.warning(f"重试失败: {item['file_name']}")
