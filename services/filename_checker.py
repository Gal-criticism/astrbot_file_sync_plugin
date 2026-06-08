from typing import Optional, Dict, List
from ..models.validation_result import FileValidationResult

class FilenameChecker:
    """文件名检查器"""

    SEPARATOR = "--"

    def __init__(self, template: str, categories: Dict[str, List[str]]):
        """
        初始化文件名检查器

        Args:
            template: 文件名模板格式，如 "{category}--{name}"
            categories: 分类白名单，如 {"设计类": ["素材", "成品"]}
        """
        self.template = template
        self.categories = categories
        self._all_categories = self._flatten_categories()

    def _flatten_categories(self) -> List[str]:
        """扁平化所有分类"""
        if not self.categories:
            return []
        result = []
        for group_categories in self.categories.values():
            result.extend(group_categories)
        return result

    def validate(
        self,
        filename: str,
        sender_id: str = "",
        sender_name: str = "",
        group_id: str = ""
    ) -> FileValidationResult:
        """
        验证文件名是否合规

        Args:
            filename: 文件名
            sender_id: 上传者 QQ 号
            sender_name: 上传者昵称
            group_id: 群号

        Returns:
            FileValidationResult: 验证结果
        """
        # 检查是否包含 -- 分隔符
        if self.SEPARATOR not in filename:
            return FileValidationResult(
                is_valid=False,
                filename=filename,
                category=None,
                error_type="format_error",
                error_reason=f"缺少分隔符 '{self.SEPARATOR}'",
                sender_id=sender_id,
                sender_name=sender_name,
                group_id=group_id
            )

        # 提取分类
        category = self.extract_category(filename)

        # 检查分类是否在白名单中（如果配置了白名单）
        if self._all_categories and category and category not in self._all_categories:
            return FileValidationResult(
                is_valid=False,
                filename=filename,
                category=category,
                error_type="category_not_in_whitelist",
                error_reason=f"分类「{category}」不在允许列表中",
                sender_id=sender_id,
                sender_name=sender_name,
                group_id=group_id
            )

        # 通过验证
        return FileValidationResult(
            is_valid=True,
            filename=filename,
            category=category,
            error_type=None,
            error_reason=None,
            sender_id=sender_id,
            sender_name=sender_name,
            group_id=group_id
        )

    def extract_category(self, filename: str) -> Optional[str]:
        """
        从文件名提取分类

        Args:
            filename: 文件名

        Returns:
            分类名称，如果无法提取则返回 None
        """
        if self.SEPARATOR not in filename:
            return None

        # 按 -- 分割，取第一部分作为分类
        parts = filename.split(self.SEPARATOR, 1)
        if len(parts) < 2:
            return None

        category = parts[0].strip()
        return category if category else None

    def format_categories(self) -> str:
        """
        格式化分类列表为字符串

        Returns:
            分类列表字符串，如 "素材、成品、草稿"
        """
        if not self._all_categories:
            return ""
        return "、".join(self._all_categories)