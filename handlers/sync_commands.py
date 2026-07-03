"""同步相关命令处理器"""

from astrbot.api import logger

from ..utils.command_parser import parse_angle_args, smart_split


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
        """查看同步状态（精简版，重定向到统计）"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return
        async for result in self.handle_sync_stats(event):
            yield result

    async def handle_sync_stats(self, event):
        """查看监听上传统计（按群展示）"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return

        group_id = event.get_group_id()  # 群聊时有值，私聊时为 None
        stats = self.state_manager.get_upload_stats_by_group(group_id=group_id)

        if not stats:
            yield event.plain_result("暂无监听上传记录")
            return

        msg = "=== 监听上传统计 ===\n"
        for g in stats:
            msg += f"\n群 {g['group_id']}:\n"
            msg += f"  成功同步: {g['success_count']} 个\n"
            msg += f"  同步失败: {g['fail_count']} 个\n"
            last = g['last_upload_time']
            msg += f"  最后上传: {last or '无'}\n"

            if g['recent_records']:
                msg += "\n最近上传:\n"
                for r in g['recent_records']:
                    icon = "✓" if r['status'] == 'success' else "✗"
                    sender = f"({r['sender_name']})" if r['sender_name'] else ""
                    detail = f" —— {r['detail']}" if r['detail'] else ""
                    msg += f"  {icon} {r['file_name']} {sender} {r['time'][:16]}{detail}\n"

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
          /预设路径 添加 <名称> <NextCloud路径>  — 添加（校验路径存在）
          /预设路径 删除 <名称>         — 删除预设路径
          /预设路径 列表             — 列出所有预设路径

          /绑定路径 <群号> <路径名称>    — 绑定群到预设路径
          /解绑路径 <群号>              — 解除绑定
          /绑定列表                     — 列出所有绑定关系
        """
        if not self.config:
            yield event.plain_result("配置未初始化")
            return

        args = smart_split(event.message_str)
        subcmd = args[1] if len(args) > 1 else "list"
        sm = self._plugin.state_manager

        # ── /预设路径 ──
        if subcmd in ("list", "列表"):
            paths = sm.list_preset_paths()
            if not paths:
                yield event.plain_result("当前无预设路径\n\n用法: /预设路径 添加 <名称> <路径>")
                return
            msg = "=== 预设路径 ===\n"
            for p in paths:
                bound = f"[绑定: {', '.join(p['bound_groups'])}]" if p["bound_groups"] else "[未绑定]"
                msg += f"  {p['name']} → {p['remote_path']} {bound}\n"
            msg += "\n用法: /预设路径 添加 <名称> <路径>\n"
            msg += "      /绑定路径 <群号> <路径名称>"
            yield event.plain_result(msg)

        elif subcmd == "添加":
            if len(args) < 4:
                yield event.plain_result("用法: /预设路径 添加 <名称> <NextCloud路径>\n例如: /预设路径 添加 项目A /客户/项目A")
                return

            angle_args = parse_angle_args(event.message_str, 2)
            if angle_args:
                name, path = angle_args[0], angle_args[1]
            else:
                name = args[2]
                path = " ".join(args[3:])  # fallback: 路径可能含空格

            path = "/" + path.lstrip("/")

            # 通过 WebDAV 校验路径存在
            if self.cloud_sync:
                if not self.cloud_sync._path_exists(path):
                    yield event.plain_result(f"路径不存在: {path}\n请确认 NextCloud 上存在此目录")
                    return

            result, msg = sm.add_preset_path(name, path)
            yield event.plain_result(msg)

        elif subcmd == "删除":
            if len(args) < 3:
                yield event.plain_result("用法: /预设路径 删除 <名称>")
                return
            name = parse_angle_args(event.message_str, 1)[0] if parse_angle_args(event.message_str, 1) else " ".join(args[2:])
            result, msg = sm.delete_preset_path(name)
            yield event.plain_result(msg)

        # ── /绑定路径 ──
        elif subcmd == "路径":
            if len(args) < 3:
                yield event.plain_result("用法: /绑定路径 <群号> <路径名称>\n例如: /绑定路径 123456 项目A")
                return
            angle_args = parse_angle_args(event.message_str, 2)
            if angle_args:
                gid, pname = angle_args[0], angle_args[1]
            else:
                gid = args[2]
                pname = " ".join(args[3:])
            result, msg = sm.bind_group(gid, pname)
            yield event.plain_result(msg)

        # ── /解绑路径 ──
        elif subcmd == "解绑":
            if len(args) < 3:
                yield event.plain_result("用法: /解绑路径 <群号>")
                return
            angle_args = parse_angle_args(event.message_str, 1)
            gid = angle_args[0] if angle_args else args[2]
            result, msg = sm.unbind_group(gid)
            yield event.plain_result(msg)

        # ── /绑定列表 ──
        elif subcmd == "绑定":
            bindings = sm.list_group_bindings()
            if not bindings:
                yield event.plain_result("当前无绑定关系\n\n用法: /绑定路径 <群号> <路径名称>")
                return
            msg = "=== 群绑定列表 ===\n"
            for b in bindings:
                msg += f"  群 {b['group_id']} → {b['name']} ({b['remote_path']}) [{b['bound_at']}]\n"
            yield event.plain_result(msg)

        else:
            yield event.plain_result(
                f"未知子命令: {subcmd}\n"
                "可用: /预设路径 列表/添加/删除\n"
                "      /绑定路径 <群号> <名称>\n"
                "      /解绑路径 <群号>\n"
                "      /绑定列表"
            )
