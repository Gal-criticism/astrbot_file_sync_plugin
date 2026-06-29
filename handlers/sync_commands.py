"""同步相关命令处理器"""

from astrbot.api import logger


class SyncCommandHandler:
    """同步命令处理（/同步文件、/同步状态、/同步统计、/同步调试）"""

    def __init__(self, plugin):
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

    async def handle_sync_files(self, event):
        """手动触发一次同步"""
        logger.info("收到手动同步命令")

        if self.config and not self.config.sync_enabled:
            yield event.plain_result("同步功能已禁用，请在配置中启用 sync_enabled")
            return

        yield event.plain_result("开始同步...")
        synced_count = await self._plugin.sync_all_groups()

        if synced_count == 0:
            yield event.plain_result("同步完成，但未处理任何群（请检查 enabled_groups 配置）")
        else:
            yield event.plain_result(f"同步完成，共处理 {synced_count} 个群")

    async def handle_sync_status(self, event):
        """查看同步状态"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return
        stats = self.state_manager.get_sync_stats()
        yield event.plain_result(
            f"已同步文件: {stats['total_synced']}\n"
            f"待重试: {stats['pending_retries']}"
        )

    async def handle_sync_stats(self, event):
        """查看同步统计"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return

        args = event.message_str.strip().split()
        group_id = args[1] if len(args) > 1 else None

        if group_id:
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
            total_stats = self.state_manager.get_sync_stats()
            group_stats = self.state_manager.get_sync_stats_by_group()

            msg = "=== 同步统计总览 ===\n"
            msg += f"总同步文件: {total_stats['total_synced']}\n"
            msg += f"总待重试: {total_stats['pending_retries']}\n"
            msg += f"启用群数: {len(self.config.enabled_groups) if self.config else 0}\n"

            if group_stats:
                msg += "\n=== 分群统计 ===\n"
                for gid, stats in group_stats.items():
                    msg += f"\n群 {gid}:\n"
                    msg += f"  已同步: {stats['synced']}\n"
                    msg += f"  待重试: {stats['pending']}\n"
                    msg += f"  最后同步: {stats['last_sync_time'] or '从未同步'}\n"

        yield event.plain_result(msg)

    async def handle_sync_debug(self, event):
        """调试命令：检查后端支持的 API"""
        from astrbot.api.event import filter

        # 尝试获取 event 类型
        platform = self._plugin.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            yield event.plain_result("无法获取QQ平台")
            return

        client = platform.get_client()
        msg = "=== 后端 API 调试信息 ===\n"

        try:
            result = await client.api.call_action("get_supported_actions")
            actions = result if isinstance(result, list) else []
            file_apis = [a for a in actions if "file" in a.lower()]
            msg += f"支持的文件相关 API: {file_apis if file_apis else '无'}\n"
            msg += f"总支持 API 数量: {len(actions)}\n"
        except Exception as e:
            msg += f"获取支持的 API 失败: {e}\n"

        test_apis = ["get_group_root_files", "get_group_file_list", "get_group_files"]
        for api_name in test_apis:
            try:
                result = await client.api.call_action(
                    api_name,
                    group_id=int(self.config.enabled_groups[0]) if self.config and self.config.enabled_groups else 0
                )
                msg += f"{api_name}: 可用 (返回类型: {type(result).__name__})\n"
            except Exception as e:
                msg += f"{api_name}: 不可用 ({str(e)[:80]})\n"

        yield event.plain_result(msg)

    async def handle_preset_paths(self, event):
        """预设路径管理命令

        用法:
          /预设路径                — 列出所有预设路径
          /预设路径 添加 <项目名> <路径>  — 添加或修改预设路径
          /预设路径 删除 <项目名>         — 删除预设路径
        """
        if not self.config:
            yield event.plain_result("配置未初始化")
            return

        args = event.message_str.strip().split()
        subcmd = args[1] if len(args) > 1 else "list"
        presets = self.config.get_preset_paths()

        if subcmd == "list":
            if not presets:
                yield event.plain_result("当前未配置任何预设路径\n\n用法: /预设路径 添加 <项目名> <路径>")
                return
            msg = "=== 预设路径 ===\n"
            for name, path in presets.items():
                msg += f"  {name} → {path}\n"
            msg += "\n用法: /预设路径 添加 <项目名> <路径>\n"
            msg += "      /预设路径 删除 <项目名>"
            yield event.plain_result(msg)

        elif subcmd == "添加":
            if len(args) < 4:
                yield event.plain_result("用法: /预设路径 添加 <项目名> <路径>\n例如: /预设路径 添加 项目A /客户项目/项目A")
                return
            name = args[2]
            path = args[3]
            path = "/" + path.lstrip("/")
            presets[name] = path

            # 更新配置
            import json
            try:
                self.config.preset_paths = json.dumps(presets, ensure_ascii=False)
                yield event.plain_result(f"预设路径已更新: {name} → {path}")
                logger.info(f"预设路径已更新: {name} → {path}")
            except Exception as e:
                yield event.plain_result(f"更新预设路径失败: {e}")

        elif subcmd == "删除":
            if len(args) < 3:
                yield event.plain_result("用法: /预设路径 删除 <项目名>")
                return
            name = args[2]
            if name not in presets:
                yield event.plain_result(f"未找到预设路径: {name}")
                return
            removed = presets.pop(name)

            import json
            try:
                self.config.preset_paths = json.dumps(presets, ensure_ascii=False)
                yield event.plain_result(f"预设路径已删除: {name} (原路径: {removed})")
                logger.info(f"预设路径已删除: {name} (原路径: {removed})")
            except Exception as e:
                yield event.plain_result(f"删除预设路径失败: {e}")

        else:
            yield event.plain_result(f"未知子命令: {subcmd}\n可用: list(默认) / 添加 / 删除")
