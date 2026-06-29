"""通知服务 - 发送@提醒消息（支持新旧命名规范）"""

from typing import Optional, List, Any


class NotifyService:
    """通知服务 - 发送@提醒消息"""

    DEFAULT_TEMPLATE = (
        "@{sender} 你上传的文件「{filename}」格式不规范\n"
        "原因：{error_reason}\n"
        "正确格式：项目名称-分类v版本号-后缀.扩展名\n"
        "可用分类：{categories}"
    )

    DEPRECATED_TEMPLATE_HINT = (
        "\n⚠️ 你使用了旧格式「分类--名称」，请尽快迁移到新格式「项目名称-分类v版本号-后缀」"
    )

    def __init__(self, template: Optional[str] = None):
        """初始化通知服务

        Args:
            template: 通知模板，默认使用 DEFAULT_TEMPLATE
        """
        self.template = template or self.DEFAULT_TEMPLATE

    def format_message(self, result,
                       categories_str: str = "",
                       deprecated_separator: bool = False) -> str:
        """根据模板和验证结果格式化消息

        Args:
            result: NamingResult 或 FileValidationResult 验证结果
            categories_str: 分类列表字符串
            deprecated_separator: 是否使用了旧分隔符

        Returns:
            格式化后的消息文本
        """
        if self.template is None:
            template = self.DEFAULT_TEMPLATE
        else:
            template = self.template

        # 兼容两种 result 类型
        sender = getattr(result, 'sender_name', None) or getattr(result, 'sender_id', '') or '用户'
        filename = getattr(result, 'filename', '')
        error_reason = getattr(result, 'error_reason', '') or ''
        error_type = getattr(result, 'error_type', '') or ''

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

        # 如果是旧格式，附加迁移提示
        if deprecated_separator:
            message += self.DEPRECATED_TEMPLATE_HINT

        return message

    def build_message_chain(self, result, categories_str: str = "") -> List[Any]:
        """构建消息链（包含 @ 组件）

        Args:
            result: NamingResult 或 FileValidationResult 验证结果
            categories_str: 分类列表字符串

        Returns:
            List[BaseMessageComponent]: 消息组件列表
        """
        # 尝试导入 AstrBot 组件
        try:
            import astrbot.api.message_components as Comp

            sender_name = (
                getattr(result, 'sender_name', None)
                or getattr(result, 'sender_id', None)
                or "用户"
            )
            sender_id = getattr(result, 'sender_id', '') or ''
            filename = getattr(result, 'filename', '') or ''
            error_reason = getattr(result, 'error_reason', '') or ''
            categories = categories_str or "无限制"

            chain = [Comp.At(qq=sender_id)]
            chain.append(Comp.Plain(text=f"你上传的文件「{filename}」格式不规范"))
            chain.append(Comp.Plain(text=f"原因：{error_reason}"))
            chain.append(Comp.Plain(text="正确格式：项目名称-分类v版本号-后缀.扩展名"))
            chain.append(Comp.Plain(text=f"可用分类：{categories}"))

            # 旧格式提示
            deprecated = getattr(result, 'deprecated_separator', False)
            if deprecated:
                chain.append(Comp.Plain(
                    text="⚠️ 你使用了旧格式「分类--名称」，请尽快迁移到新格式"
                ))

            return chain

        except ImportError:
            # 如果无法导入 AstrBot 组件，返回纯文本消息
            deprecated = getattr(result, 'deprecated_separator', False)
            text = self.format_message(result, categories_str, deprecated)
            return [text]
