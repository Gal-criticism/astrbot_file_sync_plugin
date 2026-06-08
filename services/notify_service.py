from typing import Optional, List, Any

class NotifyService:
    """通知服务 - 发送@提醒消息"""

    DEFAULT_TEMPLATE = (
        "@{sender} 你上传的文件「{filename}」格式不规范\n"
        "原因：{error_reason}\n"
        "正确格式：{template}\n"
        "可用分类：{categories}"
    )

    def __init__(self, template: Optional[str] = None):
        """
        初始化通知服务

        Args:
            template: 通知模板，默认使用 DEFAULT_TEMPLATE
        """
        self.template = template or self.DEFAULT_TEMPLATE

    def format_message(self, result,
                       categories_str: str = "") -> str:
        """
        根据模板和验证结果格式化消息

        Args:
            result: FileValidationResult 验证结果
            categories_str: 分类列表字符串

        Returns:
            格式化后的消息文本
        """
        replacements = {
            "{sender}": result.sender_name or result.sender_id or "用户",
            "{sender_id}": result.sender_id or "",
            "{filename}": result.filename or "",
            "{error_reason}": result.error_reason or "",
            "{error_type}": result.error_type or "",
            "{template}": "分类--项目名称",
            "{categories}": categories_str or "",
        }

        message = self.template
        for key, value in replacements.items():
            message = message.replace(key, value)

        return message

    def build_message_chain(self, result, categories_str: str = "") -> List[Any]:
        """
        构建消息链（包含 @ 组件）

        Args:
            result: FileValidationResult 验证结果
            categories_str: 分类列表字符串

        Returns:
            List[BaseMessageComponent]: 消息组件列表
        """
        text = self.format_message(result, categories_str)

        # 尝试导入 AstrBot 组件
        try:
            import astrbot.api.message_components as Comp

            # 如果模板以 @ 开头，拆分为 At + 文本
            if text.startswith("@"):
                parts = text.split(" ", 1)
                at_name = parts[0][1:]  # 去掉 @
                remaining_text = parts[1] if len(parts) > 1 else ""

                chain = [Comp.At(qq=result.sender_id)]
                if remaining_text:
                    chain.append(Comp.Plain(text=remaining_text))
                return chain
            else:
                return [Comp.Plain(text=text)]

        except ImportError:
            # 如果无法导入 AstrBot 组件，返回纯文本消息
            return [text]