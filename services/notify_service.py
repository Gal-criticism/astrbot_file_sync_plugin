from typing import Optional, List, Any

class NotifyService:
    """通知服务 - 发送@提醒消息"""

    def __init__(self, template: Optional[str] = None):
        """
        初始化通知服务

        Args:
            template: 通知模板，默认使用 DEFAULT_TEMPLATE
        """
        self.template = template

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
        template = self.template or (
            "@{sender} 你上传的文件「{filename}」格式不规范 "
            "原因：{error_reason} "
            "正确格式：分类--项目名称 "
            "可用分类：{categories}"
        )
        replacements = {
            "{sender}": result.sender_name or result.sender_id or "用户",
            "{sender_id}": result.sender_id or "",
            "{filename}": result.filename or "",
            "{error_reason}": result.error_reason or "",
            "{error_type}": result.error_type or "",
            "{template}": "分类--项目名称",
            "{categories}": categories_str or "无限制",
        }

        message = template
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
        # 尝试导入 AstrBot 组件
        try:
            import astrbot.api.message_components as Comp

            sender_name = result.sender_name or result.sender_id or "用户"
            filename = result.filename or ""
            error_reason = result.error_reason or ""
            categories = categories_str or "无限制"

            # 构建多行消息，每行一个 Plain 组件
            chain = [Comp.At(qq=result.sender_id)]
            chain.append(Comp.Plain(text=f"你上传的文件「{filename}」格式不规范"))
            chain.append(Comp.Plain(text=f"原因：{error_reason}"))
            chain.append(Comp.Plain(text="正确格式：分类--项目名称"))
            chain.append(Comp.Plain(text=f"可用分类：{categories}"))

            return chain

        except ImportError:
            # 如果无法导入 AstrBot 组件，返回纯文本消息
            text = self.format_message(result, categories_str)
            return [text]