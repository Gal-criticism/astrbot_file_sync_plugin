"""诊断命令处理器"""

from astrbot.api import logger


class DiagnosticCommandHandler:
    """诊断命令处理（/诊断日志、/清空诊断日志）"""

    def __init__(self, plugin):
        self._plugin = plugin

    @property
    def state_manager(self):
        return self._plugin.state_manager

    async def handle_diagnostic_logs(self, event):
        """查看诊断日志"""
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

    async def handle_clear_diagnostic_logs(self, event):
        """清空诊断日志"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return

        self.state_manager.clear_diagnostic_logs()
        yield event.plain_result("诊断日志已清空")
