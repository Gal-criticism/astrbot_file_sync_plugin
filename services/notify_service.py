"""通知服务 - 发送@提醒消息（支持新旧命名规范 + 修正建议）"""

from typing import Optional, List, Any


class NotifyService:
    """通知服务 - 发送@提醒消息"""

    DEFAULT_TEMPLATE = (
        "@{sender} 你上传的文件「{filename}」格式不规范\n"
        "原因：{error_reason}\n"
        "正确格式：项目名称-分类v版本号-后缀.扩展名\n"
        "可用分类：{categories}"
    )

    DEPRECATED_HINT = (
        "\n⚠️ 你使用了旧格式「分类--名称」，请尽快迁移到新格式「项目名称-分类v版本号」"
    )

    def __init__(self, template: Optional[str] = None):
        self.template = template or self.DEFAULT_TEMPLATE

    def format_message(self, result,
                       categories_str: str = "",
                       deprecated_separator: bool = False) -> str:
        """根据模板和验证结果格式化消息

        Args:
            result: NamingResult 或 FileValidationResult 验证结果
            categories_str: 分类列表字符串
            deprecated_separator: 是否使用了旧分隔符
        """
        if self.template is None:
            template = self.DEFAULT_TEMPLATE
        else:
            template = self.template

        sender = getattr(result, 'sender_name', None) or getattr(result, 'sender_id', '') or '用户'
        filename = getattr(result, 'filename', '')
        error_reason = getattr(result, 'error_reason', '') or ''
        error_type = getattr(result, 'error_type', '') or ''

        # 收集所有错误
        errors = getattr(result, 'errors', []) or []
        if errors:
            error_lines = []
            for e in errors:
                error_lines.append(f"  · {e.get('reason', '')}")
            error_reason = "\n".join(error_lines) if error_lines else error_reason

        replacements = {
            "{sender}": sender,
            "{sender_id}": getattr(result, 'sender_id', '') or '',
            "{filename}": filename,
            "{error_reason}": error_reason,
            "{error_type}": error_type,
            "{template}": "项目名称-分类v版本号-后缀.扩展名",
            "{categories}": categories_str or "无限制",
        }

        message = template
        for key, value in replacements.items():
            message = message.replace(key, str(value))

        # 修正建议
        suggested_fix = getattr(result, 'suggested_fix', None)
        if suggested_fix:
            message += f"\n{suggested_fix}"

        # 旧格式提示
        deprecated = getattr(result, 'deprecated_separator', False) or deprecated_separator
        if deprecated:
            message += self.DEPRECATED_HINT

        return message

    def build_message_chain(self, result, categories_str: str = "") -> List[Any]:
        """构建消息链（包含 @ 组件）

        合规但 deprecated 时也发温和提醒。
        """
        try:
            import astrbot.api.message_components as Comp

            sender_id = getattr(result, 'sender_id', '') or ''
            filename = getattr(result, 'filename', '') or ''
            categories = categories_str or "无限制"
            deprecated = getattr(result, 'deprecated_separator', False)
            is_valid = getattr(result, 'is_valid', False)
            suggested_fix = getattr(result, 'suggested_fix', None)

            chain = [Comp.At(qq=sender_id)]

            # ── 情况1: 不合规 → 完整错误信息 ──
            if not is_valid:
                chain.append(Comp.Plain(text=f"你上传的文件「{filename}」格式不规范"))

                # 多错误逐条列出
                errors = getattr(result, 'errors', []) or []
                if errors:
                    chain.append(Comp.Plain(text="问题："))
                    for e in errors:
                        chain.append(Comp.Plain(text=f"  · {e.get('reason', '')}"))
                else:
                    error_reason = getattr(result, 'error_reason', '') or ''
                    chain.append(Comp.Plain(text=f"原因：{error_reason}"))

                chain.append(Comp.Plain(text="正确格式：项目名称-分类v版本号-后缀.扩展名"))
                chain.append(Comp.Plain(text=f"可用分类：{categories}"))

                if suggested_fix:
                    chain.append(Comp.Plain(text=suggested_fix))

                if deprecated:
                    chain.append(Comp.Plain(
                        text="⚠️ 你使用了旧格式「分类--名称」，请尽快迁移到新格式"
                    ))
            else:
                # ── 情况2: 合规但旧格式 → 温和提醒 ──
                if deprecated:
                    chain.append(Comp.Plain(
                        text=f"你上传的文件「{filename}」使用了旧格式「分类--名称」"
                    ))
                    chain.append(Comp.Plain(
                        text="⚠️ 该格式仍被接受，但建议迁移到新格式：项目名称-分类v版本号-后缀"
                    ))
                    if suggested_fix:
                        chain.append(Comp.Plain(text=suggested_fix))

            return chain

        except ImportError:
            deprecated = getattr(result, 'deprecated_separator', False)
            text = self.format_message(result, categories_str, deprecated)
            return [text]
