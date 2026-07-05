"""基于命名规范的文件名验证器

命名规范核心格式：
    {项目名称}-{分类}[v{版本号}][-{后缀}]

兼容旧格式（deprecated）：
    {分类}--{名称}

七大标准分类：文案 / 封面 / 成片 / 素材 / 音频 / 字幕 / 数据组测试

支持一次收集所有错误 + 推导修正建议。
"""

import re
from typing import Optional, List, Dict, Tuple

from ..models.naming_result import NamingResult


# ===== 分类定义 =====

# 分类关键词映射：子类型关键词 → 标准分类
CATEGORY_KEYWORD_MAP: Dict[str, str] = {
    # 文案/脚本
    "文案": "文案",
    "脚本": "文案",
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

# 七大标准分类
STANDARD_CATEGORIES = ["文案", "封面", "成片", "素材", "音频", "字幕", "数据组测试"]

# 分类 → 允许的扩展名（不含工程文件的压缩包格式）
CATEGORY_EXTENSIONS: Dict[str, List[str]] = {
    "文案": ["docx", "pdf"],
    "封面": ["png", "jpg", "jpeg", "psd"],
    "成片": ["mp4"],
    "素材": ["png", "jpg", "jpeg", "psd", "gif", "svg",
             "ai", "eps", "cdr",
             "mp4", "mov", "avi", "webm"],
    "音频": ["wav", "flac", "mp3", "aac"],
    "字幕": ["ass"],
    "数据组测试": ["*"],
}

# 分类 → 工程文件允许的扩展名（仅成片、音频有独立工程子目录）
ENGINEERING_EXTENSIONS: Dict[str, List[str]] = {
    "成片": ["zip", "rar", "7z"],
    "音频": ["zip", "rar", "7z"],
}

# 分类 → 云盘存储子目录名（一级分类目录）
CATEGORY_SUBDIRS: Dict[str, str] = {
    "文案": "文案",
    "封面": "封面",
    "成片": "成片",
    "素材": "素材",
    "音频": "音频",
    "字幕": "字幕",
    "数据组测试": "数据组测试",
}

# 工程后缀识别正则：匹配 工程 / 工程v1 / 工程-PR2022 / 工程v2-PR 等
ENGINEERING_PATTERN = re.compile(
    r'^工程(v\d+)?(-[a-zA-Z0-9]+)?$',  # 工程、工程v1、工程-PR2022、工程v2-PR
    re.IGNORECASE
)

# 需要二级"工程"子目录的分类
CATEGORIES_WITH_ENGINEERING_SUBDIR = {"成片", "音频"}


def _has_engineering_suffix(suffixes: List[str]) -> bool:
    """检查后缀列表中是否包含工程标记"""
    for s in suffixes:
        s_stripped = s.strip()
        if ENGINEERING_PATTERN.match(s_stripped):
            return True
    return False

# 版本号正则：匹配 v1, v2, v99 等
VERSION_PATTERN = re.compile(r'v(\d+)')


class NamingValidator:
    """文件名命名规范验证器

    支持两种格式：
    1. 新格式（推荐）：项目名称-分类[v版本号][-后缀].扩展名
    2. 旧格式（兼容）：分类--名称.扩展名

    一次验证收集所有错误，并推导修正建议。
    """

    # 分隔符：新格式用 -，旧格式用 --
    NEW_SEPARATOR = "-"
    DEPRECATED_SEPARATOR = "--"

    def __init__(self, extra_categories: Optional[Dict[str, Dict]] = None):
        """初始化验证器"""
        self._keyword_map = dict(CATEGORY_KEYWORD_MAP)
        self._extensions = _deep_copy_dict(CATEGORY_EXTENSIONS)
        self._eng_extensions = dict(ENGINEERING_EXTENSIONS)
        self._subdirs = dict(CATEGORY_SUBDIRS)

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
        """验证文件名是否合规（一次收集所有错误）

        Returns:
            NamingResult，其中:
            - is_valid: 是否完全合规
            - errors: 所有错误的列表
            - suggested_fix: 修正建议示例
        """
        base_args = {
            "filename": filename,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "group_id": group_id,
        }

        # 1. 基本检查
        if not filename or not filename.strip():
            result = NamingResult(is_valid=False, error_type="empty", error_reason="文件名为空", **base_args)
            result.add_error("empty", "文件名为空")
            return result

        # 2. 提取扩展名
        extension = self._extract_extension(filename)
        stem = filename
        if extension:
            stem = filename[:-(len(extension) + 1)]

        # 3. 检测分隔符，走对应验证路径
        is_deprecated = self.DEPRECATED_SEPARATOR in filename
        has_new = self.NEW_SEPARATOR in stem

        if is_deprecated:
            result = self._validate_deprecated(stem, extension, base_args)
        elif has_new:
            result = self._validate_new(stem, extension, base_args)
        else:
            result = NamingResult(is_valid=False, extension=extension, **base_args)
            result.add_error("format_error",
                             "缺少分隔符，请使用格式：项目名称-分类v版本号-后缀.扩展名")

            # ── 素材兜底: 无分隔符无法分类，但扩展名是图片/视频 → 自动归入素材 ──
            if extension:
                material_extensions = self._extensions.get("素材", [])
                ext_lower = extension.lower()
                if ext_lower in [e.lower() for e in material_extensions] or "*" in material_extensions:
                    result = NamingResult(
                        is_valid=True,
                        category="素材",
                        project_name=stem,
                        extension=extension,
                        **base_args,
                    )
                    result.suggested_fix = None
                    return result

        # 4. 生成修正建议
        result.suggested_fix = self._generate_fix_suggestion(result)
        return result

    def parse(self, filename: str) -> NamingResult:
        """仅解析文件名，不进行严格校验"""
        return self.validate(filename)

    def extract_category(self, filename: str) -> Optional[str]:
        """从文件名提取标准分类"""
        result = self.parse(filename)
        return result.category

    def get_target_subdir(self, result: NamingResult) -> str:
        """根据分类结果返回云盘子目录名

        新规范目录层级：
        - 项目名称/
          - 文案/
          - 封面/
          - 成片/
            - 工程/      # 成片-工程或成片v1-工程后缀
          - 素材/
          - 音频/
            - 工程/      # 音频-工程后缀
          - 字幕/
          - 数据组测试/

        返回相对于群文件夹的子路径，如 "项目A/成片/工程"
        """
        category = result.category
        project_name = result.project_name
        if not category:
            return "其他"

        # 一级分类目录
        segments = [category]

        # 判断是否属于工程子目录
        is_engineering = result.is_engineering or _has_engineering_suffix(result.suffixes)
        if is_engineering and category in CATEGORIES_WITH_ENGINEERING_SUBDIR:
            segments.append("工程")

        # 拼入项目名作为最顶层
        if project_name and project_name != category:
            segments.insert(0, project_name)
        elif project_name and project_name == category:
            # deprecated 格式用文件名后半段作为项目名
            if result.filename and self.DEPRECATED_SEPARATOR in result.filename:
                parts = result.filename.split(self.DEPRECATED_SEPARATOR, 1)
                if len(parts) >= 2 and parts[1].strip():
                    stem = parts[1].rsplit(".", 1)[0] if "." in parts[1] else parts[1]
                    segments.insert(0, stem.strip())

        return "/".join(segments)

    def format_categories(self) -> str:
        """格式化分类列表为展示字符串"""
        cats = list(self._subdirs.keys())
        return "、".join(cats)

    def is_extension_allowed(self, category: str, extension: str, is_engineering: bool = False) -> bool:
        """检查扩展名是否属于该分类允许的范围

        工程文件（is_engineering=True）使用 ENGINEERING_EXTENSIONS 校验，
        普通文件使用 CATEGORY_EXTENSIONS 校验。
        """
        if is_engineering and category in ENGINEERING_EXTENSIONS:
            allowed = ENGINEERING_EXTENSIONS[category]
            return extension.lower() in [e.lstrip(".").lower() for e in allowed]
        if category not in self._extensions:
            return True
        allowed = self._extensions[category]
        if "*" in allowed:
            return True
        return extension.lower() in [e.lstrip(".").lower() for e in allowed]

    # ===== 私有：新格式解析（收集全部错误）=====

    def _validate_new(self, stem: str, extension: Optional[str], base_args: dict) -> NamingResult:
        """验证新格式（- 分隔符），收集所有错误"""
        parts = [p.strip() for p in stem.split(self.NEW_SEPARATOR) if p.strip()]
        errors = []
        project_name = None
        category = None
        version = None
        suffixes = []

        # 检查格式完整性
        if len(parts) < 2:
            result = NamingResult(is_valid=False, extension=extension, **base_args)
            result.add_error("format_error", "格式不正确，至少需要「项目名称-分类」")
            result.suggested_fix = self._generate_fix_suggestion(result)
            return result

        # 扫描分类
        cat_index, category, keyword = self._find_category_in_parts(parts)
        if category is None:
            errors.append({
                "type": "category_not_found",
                "reason": f"未识别到有效分类，可用分类：{self.format_categories()}"
            })

        # 提取项目名称（过滤掉版本号-only 的 parts，如 "项目A-v1-成片" 中的 v1）
        if category:
            proj_parts = parts[:cat_index] if cat_index > 0 else [parts[0]]
            filtered = [p for p in proj_parts if not VERSION_PATTERN.fullmatch(p.strip().lower())]
            project_name = self.NEW_SEPARATOR.join(filtered) if filtered else proj_parts[0]
        else:
            project_name = parts[0]

        # 提取版本号（检查分类部件中嵌入的版本号，以及项目名与分类之间独立版本号部件）
        if category and cat_index < len(parts):
            version = self._extract_version(parts[cat_index])
            # 如果分类部件中没有版本号，检查项目名与分类之间的版本号-only 部件
            if version is None and cat_index > 1:
                for vpart in reversed(parts[1:cat_index]):
                    v = self._extract_version(vpart)
                    if v is not None:
                        version = v
                        break

        # 后缀
        if category and cat_index < len(parts):
            suffixes = parts[cat_index + 1:]

        _is_engineering = _has_engineering_suffix(suffixes)

        # 扩展名校验（区分工程文件和普通文件）
        if extension and category:
            if _is_engineering and category in ENGINEERING_EXTENSIONS:
                if not self.is_extension_allowed(category, extension, is_engineering=True):
                    allowed = ENGINEERING_EXTENSIONS[category]
                    allowed_str = "、".join([f".{e}" for e in allowed])
                    errors.append({
                        "type": "extension_mismatch",
                        "reason": f"分类「{category}」的工程文件不支持 .{extension} 格式，工程文件允许：{allowed_str}"
                    })
            elif not _is_engineering:
                if not self.is_extension_allowed(category, extension):
                    allowed = self._extensions.get(category, ["*"])
                    allowed_str = "、".join([f".{e}" for e in (allowed if "*" not in allowed else [])])
                    if "*" in allowed:
                        allowed_str = "无限制"
                    errors.append({
                        "type": "extension_mismatch",
                        "reason": f"分类「{category}」不支持 .{extension} 格式，允许：{allowed_str}"
                    })

        # 组装结果
        result = NamingResult(
            is_valid=len(errors) == 0 and category is not None,
            category=category, project_name=project_name,
            version=version, suffixes=suffixes, extension=extension,
            is_engineering=_is_engineering,
            **base_args,
        )

        # 解析工程版本号和软件版本
        if result.is_engineering:
            for s in suffixes:
                s_stripped = s.strip()
                m = ENGINEERING_PATTERN.match(s_stripped)
                if m:
                    ver_str = m.group(1)  # v2 → "v2"
                    if ver_str:
                        result.engineering_version = int(ver_str.lstrip('v').lstrip('V'))
                    sw = m.group(2)  # -PR2022
                    if sw:
                        result.software_version = sw.lstrip('-')
                    break

        for e in errors:
            result.add_error(e["type"], e["reason"])

        # 数据组测试覆盖：任何格式都通过
        if category == "数据组测试":
            result.is_valid = True
            result.errors.clear()

        return result

    # ===== 私有：旧格式兼容解析（收集全部错误）=====

    def _validate_deprecated(self, stem: str, extension: Optional[str], base_args: dict) -> NamingResult:
        """验证旧格式（-- 分隔符，deprecated），收集所有错误"""
        parts = [p.strip() for p in stem.split(self.DEPRECATED_SEPARATOR, 1) if p.strip()]
        errors = []

        if len(parts) < 2:
            result = NamingResult(
                is_valid=False, extension=extension, deprecated_separator=True, **base_args
            )
            result.add_error("format_error", "格式不正确，缺少 -- 后内容")
            return result

        category_keyword = parts[0]
        category = self._resolve_category(category_keyword)
        if category is None:
            errors.append({
                "type": "category_not_in_whitelist",
                "reason": f"分类「{category_keyword}」不在允许列表中，可用：{self.format_categories()}"
            })

        # 扩展名校验
        if extension and category and not self.is_extension_allowed(category, extension):
            allowed = self._extensions.get(category, ["*"])
            allowed_str = "、".join([f".{e}" for e in (allowed if "*" not in allowed else [])])
            if "*" in allowed:
                allowed_str = "无限制"
            errors.append({
                "type": "extension_mismatch",
                "reason": f"分类「{category}」不支持 .{extension} 格式，允许：{allowed_str}"
            })

        # 名称部分解析
        name_part = parts[1]
        version = self._extract_version(name_part)
        name_suffixes = []
        if version:
            ver_match = VERSION_PATTERN.search(name_part)
            if ver_match:
                clean_name_end = ver_match.end()
                remaining = name_part[clean_name_end:].lstrip(self.NEW_SEPARATOR)
                if remaining:
                    name_suffixes = [s.strip() for s in remaining.split(self.NEW_SEPARATOR) if s.strip()]

        result = NamingResult(
            is_valid=len(errors) == 0 and category is not None,
            category=category, project_name=category_keyword,
            version=version, suffixes=name_suffixes, extension=extension,
            deprecated_separator=True,
            is_engineering=_has_engineering_suffix(name_suffixes),
            **base_args,
        )
        for e in errors:
            result.add_error(e["type"], e["reason"])

        return result

    # ===== 修正建议生成 =====

    def _generate_fix_suggestion(self, result: NamingResult) -> Optional[str]:
        """根据解析结果和错误类型生成修正建议示例

        策略：
        - 有分类无分隔符 → 推导项目名，拼接标准格式
        - 格式正确但扩展名错 → 替换扩展名
        - 分类不识别 → 给出已知分类和格式模板
        - deprecated → 迁移到新格式

        返回一行或多行建议字符串。
        """
        suggestions = []

        # 情况1: deprecated 格式 → 迁移建议
        if result.deprecated_separator and result.category and result.project_name:
            # 旧格式 "分类--名称" → 新格式 "项目-分类-名称"
            stem = result.filename.rsplit(".", 1)[0] if result.extension else result.filename
            parts = stem.split(self.DEPRECATED_SEPARATOR, 1)
            if len(parts) >= 2:
                cat = parts[0].strip()
                name = parts[1].strip()
                name = name.lstrip("-")
                ver_str = f"v{result.version}" if result.version else "v1"
                ext = f".{result.extension}" if result.extension else ""
                new_name = f"{cat}-{name}-{ver_str}{ext}" if name else f"{cat}-项目名称-{ver_str}{ext}"
                suggestions.append(f"👉 建议改为：{new_name}")

        # 情况2: 完全无分隔符
        has_any_sep = self.NEW_SEPARATOR in result.filename or self.DEPRECATED_SEPARATOR in result.filename
        if not has_any_sep:
            ext = f".{result.extension}" if result.extension else ""
            stem_no_ext = result.filename.rsplit(".", 1)[0] if result.extension else result.filename
            # 尝试按常见模式推导
            suggestions.append(f"👉 正确格式：你的项目名-分类v1-后缀{ext}")
            suggestions.append(f"   例如：{stem_no_ext}-成片v1{ext} 或 {stem_no_ext}-素材{ext}")
            suggestions.append(f"   可用分类：{self.format_categories()}")

        # 情况3: 有分类但扩展名不匹配
        if result.category and result.extension:
            ext_error = any(e["type"] == "extension_mismatch" for e in result.errors)
            if ext_error and result.category in self._extensions:
                allowed = self._extensions[result.category]
                if "*" not in allowed and allowed:
                    first_ok = allowed[0]
                    corrected = result.filename.rsplit(".", 1)[0] + "." + first_ok
                    suggestions.append(f"👉 建议改为：{corrected}")

        # 情况4: 分类未识别但有分隔符
        cat_error = any(e["type"] in ("category_not_found", "category_not_in_whitelist")
                        for e in result.errors)
        if cat_error:
            suggestions.append(f"👉 分类必须为以下之一：{self.format_categories()}")
            suggestions.append(f"   正确格式：项目名称-分类v1.扩展名")
            suggestions.append(f"   例如：我的项目-成片v1.mp4")

        return "\n".join(suggestions) if suggestions else None

    # ===== 辅助方法 =====

    def _find_category_in_parts(self, parts: List[str]) -> Tuple[int, Optional[str], Optional[str]]:
        """从左向右扫描部件（跳过索引0的项目名部分），找到第一个匹配的分类关键词

        优先匹配最靠近项目名的分类，避免后缀中的关键词意外覆盖正确分类。
        """
        for i in range(1, len(parts)):
            part = parts[i]
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
        if text in self._keyword_map:
            return self._keyword_map[text]

        for keyword, category in sorted(self._keyword_map.items(), key=lambda x: -len(x[0])):
            if text.startswith(keyword):
                return category

        negative_prefixes = {"无", "非", "不", "未"}
        for keyword, category in sorted(self._keyword_map.items(), key=lambda x: -len(x[0])):
            if keyword in text:
                idx = text.index(keyword)
                if idx > 0:
                    prev_part = text[:idx].rsplit('-', 1)[-1] if '-' in text[:idx] else text[:idx]
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
