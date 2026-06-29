"""基于命名规范的文件名验证器

命名规范核心格式：
    {项目名称}-{分类}[v{版本号}][-{后缀}]

兼容旧格式（deprecated）：
    {分类}--{名称}

六大标准分类：封面 / 成片 / 素材 / 音频 / 字幕 / 数据组测试
"""

import re
from typing import Optional, List, Dict, Tuple

from ..models.naming_result import NamingResult


# ===== 分类定义 =====

# 分类关键词映射：子类型关键词 → 标准分类
CATEGORY_KEYWORD_MAP: Dict[str, str] = {
    # 封面
    "封面": "封面",
    # 成片
    "成片": "成片",
    "成品": "成片",
    "预览": "成片",
    # 素材
    "素材": "素材",
    # 音频
    "录音": "音频",
    "音频": "音频",
    # 字幕
    "字幕": "字幕",
    # 数据组测试
    "数据组测试": "数据组测试",
}

# 六大标准分类
STANDARD_CATEGORIES = ["封面", "成片", "素材", "音频", "字幕", "数据组测试"]

# 分类 → 允许的扩展名
CATEGORY_EXTENSIONS: Dict[str, List[str]] = {
    "封面": ["png", "jpg", "jpeg", "psd"],
    "成片": ["mp4"],
    "素材": ["png", "jpg", "jpeg", "psd", "mp4", "mov", "avi", "webm", "gif", "svg",
             "ai", "eps", "cdr", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
             "zip", "rar", "7z", "txt"],
    "音频": ["wav", "flac", "mp3", "aac", "ogg", "wma", "m4a"],
    "字幕": ["ass", "srt", "vtt", "ssa"],
    "数据组测试": ["*"],  # 无限制
}

# 分类 → 云盘存储子目录名
CATEGORY_SUBDIRS: Dict[str, str] = {
    "封面": "封面",
    "成片": "成片",
    "素材": "素材",
    "音频": "音频",
    "字幕": "字幕",
    "数据组测试": "数据组测试",
}

# 版本号正则：匹配 v1, v2, v99 等
VERSION_PATTERN = re.compile(r'v(\d+)')


class NamingValidator:
    """文件名命名规范验证器

    支持两种格式：
    1. 新格式（推荐）：项目名称-分类[v版本号][-后缀].扩展名
    2. 旧格式（兼容）：分类--名称.扩展名
    """

    # 分隔符：新格式用 -，旧格式用 --
    NEW_SEPARATOR = "-"
    DEPRECATED_SEPARATOR = "--"

    def __init__(self, extra_categories: Optional[Dict[str, Dict]] = None):
        """初始化验证器

        Args:
            extra_categories: 额外的自定义分类配置，格式：
                {"自定义分类": {"extensions": ["pdf", "doc"]}, ...}
        """
        self._keyword_map = dict(CATEGORY_KEYWORD_MAP)
        self._extensions = _deep_copy_dict(CATEGORY_EXTENSIONS)
        self._subdirs = dict(CATEGORY_SUBDIRS)

        # 合并自定义分类
        if extra_categories:
            for cat_name, cat_config in extra_categories.items():
                self._keyword_map[cat_name] = cat_name
                self._subdirs[cat_name] = cat_name
                if "extensions" in cat_config:
                    self._extensions[cat_name] = cat_config["extensions"]
                if "keywords" in cat_config:
                    for kw in cat_config["keywords"]:
                        self._keyword_map[kw] = cat_name

    # ===== 公共方法 =====

    def validate(
        self,
        filename: str,
        sender_id: str = "",
        sender_name: str = "",
        group_id: str = ""
    ) -> NamingResult:
        """验证文件名是否合规

        Args:
            filename: 文件名（含扩展名）
            sender_id: 上传者 QQ 号
            sender_name: 上传者昵称
            group_id: 群号

        Returns:
            NamingResult 结果对象
        """
        base_args = {
            "filename": filename,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "group_id": group_id,
        }

        # 1. 基本检查
        if not filename or not filename.strip():
            return NamingResult(is_valid=False, error_type="empty", error_reason="文件名为空", **base_args)

        # 2. 提取扩展名
        extension = self._extract_extension(filename)
        stem = filename
        if extension:
            stem = filename[:-(len(extension) + 1)]

        # 3. 检测分隔符类型
        if self.DEPRECATED_SEPARATOR in filename:
            return self._validate_deprecated(stem, extension, base_args)
        elif self.NEW_SEPARATOR in stem:
            return self._validate_new(stem, extension, base_args)
        else:
            return NamingResult(
                is_valid=False,
                error_type="format_error",
                error_reason=f"缺少分隔符，请使用格式：项目名称-分类v版本号-后缀.扩展名",
                extension=extension,
                **base_args,
            )

    def parse(self, filename: str) -> NamingResult:
        """仅解析文件名，不进行严格校验"""
        return self.validate(filename)

    def extract_category(self, filename: str) -> Optional[str]:
        """从文件名提取标准分类"""
        result = self.parse(filename)
        return result.category

    def get_target_subdir(self, result: NamingResult) -> str:
        """根据分类结果返回云盘子目录名"""
        if result.category and result.category in self._subdirs:
            return self._subdirs[result.category]
        return "其他"

    def format_categories(self) -> str:
        """格式化分类列表为展示字符串"""
        cats = list(self._subdirs.keys())
        return "、".join(cats)

    def is_extension_allowed(self, category: str, extension: str) -> bool:
        """检查扩展名是否属于该分类允许的范围"""
        if category not in self._extensions:
            return True
        allowed = self._extensions[category]
        if "*" in allowed:
            return True
        return extension.lower() in [e.lstrip(".").lower() for e in allowed]

    def is_category_known(self, category: str) -> bool:
        """检查分类是否在已知分类中"""
        return category in self._subdirs

    # ===== 私有：新格式解析 =====

    def _validate_new(self, stem: str, extension: Optional[str], base_args: dict) -> NamingResult:
        """验证新格式（- 分隔符）"""
        parts = [p.strip() for p in stem.split(self.NEW_SEPARATOR) if p.strip()]
        if len(parts) < 2:
            return NamingResult(
                is_valid=False, error_type="format_error",
                error_reason="格式不正确，至少需要 项目名称-分类",
                extension=extension, **base_args,
            )

        # 从右向左扫描，找到分类关键词
        cat_index, category, keyword = self._find_category_in_parts(parts)
        if category is None:
            return NamingResult(
                is_valid=False, error_type="category_not_found",
                error_reason=f"未识别到有效分类，可用分类：{self.format_categories()}",
                extension=extension, **base_args,
            )

        # 提取项目名称（分类关键词之前的部分）
        project_name = self.NEW_SEPARATOR.join(parts[:cat_index]) if cat_index > 0 else parts[0]

        # 从分类所在部分提取版本号
        cat_part = parts[cat_index]
        version = self._extract_version(cat_part)

        # 剩余部分作为后缀
        suffix_parts = parts[cat_index + 1:]
        suffixes = suffix_parts

        # ===== 扩展名校验 =====
        if extension and not self.is_extension_allowed(category, extension):
            allowed = self._extensions.get(category, [])
            return NamingResult(
                is_valid=False, category=category, project_name=project_name,
                version=version, suffixes=suffixes, extension=extension,
                error_type="extension_mismatch",
                error_reason=f"分类「{category}」不支持 .{extension} 格式，允许：{', '.join(allowed)}",
                **base_args,
            )

        # ===== 数据组测试：任何格式都允许 =====
        if category == "数据组测试":
            return NamingResult(
                is_valid=True, category=category, project_name=project_name,
                version=version, suffixes=suffixes, extension=extension,
                **base_args,
            )

        return NamingResult(
            is_valid=True, category=category, project_name=project_name,
            version=version, suffixes=suffixes, extension=extension,
            **base_args,
        )

    # ===== 私有：旧格式兼容解析 =====

    def _validate_deprecated(self, stem: str, extension: Optional[str], base_args: dict) -> NamingResult:
        """验证旧格式（-- 分隔符，deprecated）"""
        parts = [p.strip() for p in stem.split(self.DEPRECATED_SEPARATOR, 1) if p.strip()]
        if len(parts) < 2:
            return NamingResult(
                is_valid=False, error_type="format_error",
                error_reason=f"缺少分隔符，请使用格式：项目名称-分类v版本号-后缀.扩展名",
                extension=extension, **base_args,
            )

        category_keyword = parts[0]
        category = self._resolve_category(category_keyword)

        # 检查分类是否在已知列表中
        if category is None:
            return NamingResult(
                is_valid=False, error_type="category_not_in_whitelist",
                error_reason=f"分类「{category_keyword}」不在允许列表中",
                project_name=category_keyword, extension=extension,
                deprecated_separator=True, **base_args,
            )

        # 扩展名校验
        if extension and not self.is_extension_allowed(category, extension):
            allowed = self._extensions.get(category, ["*"])
            return NamingResult(
                is_valid=False, category=category, project_name=category_keyword,
                extension=extension, deprecated_separator=True,
                error_type="extension_mismatch",
                error_reason=f"分类「{category}」不支持 .{extension} 格式，允许：{', '.join(allowed)}",
                **base_args,
            )

        # 解析名称部分
        name_part = parts[1]
        version = self._extract_version(name_part)

        # 去掉名称部分中的版本标记
        name_suffixes = []
        clean_name = name_part
        ver_match = VERSION_PATTERN.search(name_part)
        if ver_match:
            clean_name = name_part[:ver_match.start()].rstrip(self.NEW_SEPARATOR)
            remaining = name_part[ver_match.end():].lstrip(self.NEW_SEPARATOR)
            if remaining:
                name_suffixes = [s.strip() for s in remaining.split(self.NEW_SEPARATOR) if s.strip()]

        return NamingResult(
            is_valid=True, category=category, project_name=category_keyword,
            version=version, suffixes=name_suffixes, extension=extension,
            deprecated_separator=True,
            **base_args,
        )

    # ===== 辅助方法 =====

    def _find_category_in_parts(self, parts: List[str]) -> Tuple[int, Optional[str], Optional[str]]:
        """从右向左扫描部件，找到第一个匹配的分类关键词"""
        for i in range(len(parts) - 1, -1, -1):
            part = parts[i]
            # 去掉版本号后检查关键词
            part_no_version = VERSION_PATTERN.sub('', part).strip('-')
            category = self._resolve_category(part_no_version)
            if category:
                return i, category, part_no_version
        return -1, None, None

    def _resolve_category(self, text: str) -> Optional[str]:
        """将文本解析为标准分类

        匹配策略（按优先级）：
        1. 精确匹配
        2. 前缀匹配（如 "录音v1" 以 "录音" 开头）
        3. 包含匹配 + 排除否定前缀（如"无字幕"包含"字幕"但排除"无"前缀）
        """
        # 精确匹配
        if text in self._keyword_map:
            return self._keyword_map[text]

        # 前缀匹配（text 以关键词开头，如 "录音v1"、"视频封面"）
        for keyword, category in sorted(self._keyword_map.items(), key=lambda x: -len(x[0])):
            if text.startswith(keyword):
                return category

        # 对包含匹配做否定前缀检查，防止误匹配
        # 如 "无字幕" 不应匹配 "字幕"，"非录音" 不应匹配 "录音"
        negative_prefixes = {"无", "非", "不", "未"}
        for keyword, category in sorted(self._keyword_map.items(), key=lambda x: -len(x[0])):
            if keyword in text:
                # 检查关键词前面是否紧接否定前缀
                idx = text.index(keyword)
                if idx > 0:
                    prefix_char = text[idx - 1]
                    # 获取前面的词素
                    prev_part = text[:idx].rsplit('-', 1)[-1] if '-' in text[:idx] else text[:idx]
                    # 检查前面的词素是否为否定前缀
                    is_negated = any(prev_part.strip() == np for np in negative_prefixes)
                    if is_negated:
                        continue
                return category
        return None

    @staticmethod
    def _extract_version(text: str) -> Optional[int]:
        """从文本中提取版本号"""
        match = VERSION_PATTERN.search(text)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_extension(filename: str) -> Optional[str]:
        """提取文件扩展名（不含点）"""
        if "." not in filename:
            return None
        ext = filename.rsplit(".", 1)[-1].lower()
        return ext if ext else None


def _deep_copy_dict(d: dict) -> dict:
    """深拷贝一个简单字典（值中包含列表）"""
    import copy
    return copy.deepcopy(d)
