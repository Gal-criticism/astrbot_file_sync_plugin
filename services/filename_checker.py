"""文件名检查器（兼容旧 API）

@deprecated 请使用 NamingValidator 替代

此模块保留是为了向后兼容旧的调用方式（使用 -- 分隔符的 FilenameChecker）。
内部已重定向到 NamingValidator 实现。
"""

from typing import Optional, Dict, List

from .naming_validator import NamingValidator


class FilenameChecker:
    """文件名检查器（兼容旧 API）

    @deprecated 请直接使用 NamingValidator

    旧 API：
        checker = FilenameChecker(template="{category}--{name}", categories={...})
        result = checker.validate("素材--项目1.pdf")

    新 API：
        validator = NamingValidator(extra_categories={...})
        result = validator.validate("项目1-素材.pdf")
    """

    SEPARATOR = "--"  # 保持旧常量兼容

    def __init__(self, template: str = None, categories: Dict[str, List[str]] = None):
        """初始化（兼容旧构造函数签名）

        Args:
            template: 旧模板格式（已忽略，保留参数兼容）
            categories: 旧分类白名单，如 {"设计类": ["素材", "成品"]}
        """
        # 将旧的嵌套分类结构转为新格式
        extra = {}
        if categories:
            for group_name, cats in categories.items():
                for cat in cats:
                    if cat not in extra:
                        extra[cat] = {"keywords": [cat]}
                    else:
                        extra[cat]["keywords"].append(cat)

        self._validator = NamingValidator(extra_categories=extra if extra else None)
        self.template = template or "{project_name}-{category}v{version}-{suffix}.{ext}"
        self.categories = categories or {}

        # 保持旧的扁平化分类兼容
        self._all_categories = []
        if categories:
            for group_categories in categories.values():
                self._all_categories.extend(group_categories)

    def _flatten_categories(self) -> List[str]:
        """扁平化所有分类（兼容旧 API）"""
        return self._all_categories

    def validate(
        self,
        filename: str,
        sender_id: str = "",
        sender_name: str = "",
        group_id: str = ""
    ):
        """验证文件名（兼容旧返回类型 FileValidationResult）"""
        result = self._validator.validate(
            filename=filename,
            sender_id=sender_id,
            sender_name=sender_name,
            group_id=group_id,
        )
        return result.to_legacy()

    def extract_category(self, filename: str) -> Optional[str]:
        """从文件名提取分类（兼容旧 API）"""
        return self._validator.extract_category(filename)

    def format_categories(self) -> str:
        """格式化分类列表为字符串（兼容旧 API）"""
        if not self._all_categories:
            return ""
        return "、".join(self._all_categories)
