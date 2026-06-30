from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict
from datetime import datetime

# 六大标准分类的默认扩展名映射
DEFAULT_CATEGORY_EXTENSIONS = {
    "封面": ["png", "jpg", "jpeg", "psd"],
    "成片": ["mp4"],
    "素材": ["png", "jpg", "jpeg", "psd", "mp4", "mov", "avi", "webm", "gif", "svg",
             "ai", "eps", "cdr", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
             "zip", "rar", "7z", "txt"],
    "音频": ["wav", "flac", "mp3", "aac", "ogg", "wma", "m4a"],
    "字幕": ["ass", "srt", "vtt", "ssa"],
    "数据组测试": ["*"],
}


class FileSyncConfig(BaseModel):
    """插件配置模型"""
    sync_enabled: bool = Field(default=False, description="是否启用文件同步功能")
    nextcloud_url: str = Field(..., description="NextCloud WebDAV地址")
    nextcloud_username: str = Field(..., description="NextCloud用户名")
    nextcloud_password: str = Field(..., description="NextCloud应用密码")
    enabled_groups: List[str] = Field(default_factory=list, description="启用的群号列表")
    base_path: str = Field(default="/QQ群文件", description="云盘基础路径")
    path_template: str = Field(default="{group_name}_{group_id}/{file_type}", description="文件夹路径模板")
    sync_interval_minutes: int = Field(default=1440, ge=1, description="同步间隔(分钟)")
    sync_time_points: List[str] = Field(default_factory=list, description="同步时间点，格式: ['08:00', '12:00']")
    file_type_whitelist: List[str] = Field(default_factory=lambda: ["*"], description="允许的文件类型")
    notify_on_success: bool = Field(default=False, description="成功时通知")
    notify_on_error: bool = Field(default=True, description="失败时通知")
    retry_queue_enabled: bool = Field(default=True, description="启用重试队列")
    retry_max_attempts: int = Field(default=3, ge=1, description="最大重试次数")
    retry_delay_seconds: int = Field(default=300, ge=60, description="重试间隔(秒)")

    # 文件名检查相关配置
    filename_check_enabled: bool = Field(
        default=False,
        description="是否启用文件名检查"
    )
    filename_template: str = Field(
        default="{project_name}-{category}v{version}-{suffix}.{ext}",
        description="文件名模板格式（新规范）"
    )
    filename_categories: str = Field(
        default="{}",
        description="[deprecated] 旧分类白名单（分组），JSON格式字符串。请改用 naming_extra_categories"
    )
    naming_extra_categories: str = Field(
        default="{}",
        description="自定义扩展分类，JSON格式字符串，如 {\"我的分类\": {\"extensions\": [\"pdf\", \"doc\"], \"keywords\": [\"我的\"]}}"
    )
    filename_notify_template: Optional[str] = Field(
        default=None,
        description="@提醒模板"
    )

    # 预设路径（启动时自动种子化到 SQLite，运行时以 SQLite 为准）
    startup_presets: Dict[str, str] = Field(
        default_factory=dict,
        description="预设路径映射 {名称: NextCloud路径}，启动时自动校验并写入 SQLite。示例：{\"游戏评测\": \"/Galgame批评主文件夹/02_原创内容/a_游戏评测\"}"
    )

    @validator("sync_time_points", pre=True)
    def validate_sync_time_points(cls, v):
        """验证时间点格式"""
        if not v:
            return v
        validated = []
        for tp in v:
            try:
                # 支持 HH:MM 格式
                datetime.strptime(tp, "%H:%M")
                validated.append(tp)
            except ValueError:
                pass  # 忽略无效格式
        return validated

    def get_filename_categories(self) -> dict:
        """获取解析后的分类白名单（兼容旧 API）"""
        import json
        raw = self.filename_categories
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return {}

    def get_naming_extra_categories(self) -> dict:
        """获取解析后的自定义扩展分类"""
        import json
        raw = self.naming_extra_categories
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return {}

    def get_preset_paths(self) -> dict:
        """[deprecated] 旧 JSON 配置读取 — 预设路径已迁移到 SQLite。返回空。"""
        return {}

    def get_preset_path(self, project_name: str) -> Optional[str]:
        """根据项目名获取对应的预设路径

        匹配策略：
        1. 精确匹配 → 直接返回
        2. 文件名包含预设 key → 返回对应值
        3. 未匹配 → None（走回退路径）
        """
        if not project_name:
            return None
        presets = self.get_preset_paths()
        if not presets:
            return None
        # 精确匹配
        if project_name in presets:
            return presets[project_name]
        # 包含匹配（如 "项目A-子项目" 包含 "项目A"）
        for key, path in sorted(presets.items(), key=lambda x: -len(x[0])):
            if key in project_name:
                return path
        return None

    def have_preset_paths(self) -> bool:
        """[deprecated] 预设路径已迁移到 SQLite，返回 False"""
        return False

    def get_category_subdir(self, category: str) -> str:
        """根据分类返回云盘子目录名

        六大标准分类：封面 / 成片 / 素材 / 音频 / 字幕 / 数据组测试
        """
        standard_subdirs = {
            "封面": "封面",
            "成片": "成片",
            "素材": "素材",
            "音频": "音频",
            "字幕": "字幕",
            "数据组测试": "数据组测试",
        }
        if category in standard_subdirs:
            return standard_subdirs[category]
        # 自定义分类
        extra = self.get_naming_extra_categories()
        if category in extra:
            return category
        return "其他"

    def has_time_points(self) -> bool:
        """是否配置了时间点"""
        return len(self.sync_time_points) > 0

    def get_next_delay_seconds(self, now: datetime) -> int:
        """计算距离下次同步的秒数
        如果配置了时间点，返回距离最近时间点的秒数
        否则返回 sync_interval_minutes * 60
        """
        if not self.has_time_points():
            return self.sync_interval_minutes * 60

        current_time = now.strftime("%H:%M")
        current_minutes = now.hour * 60 + now.minute

        # 找到今天剩余的时间点
        min_delta = None
        for tp in self.sync_time_points:
            h, m = map(int, tp.split(":"))
            target_minutes = h * 60 + m
            delta = target_minutes - current_minutes
            if delta > 0:
                if min_delta is None or delta < min_delta:
                    min_delta = delta

        # 如果今天没有剩余时间点，计算到明天第一个时间点
        if min_delta is None:
            first_tp = self.sync_time_points[0]
            h, m = map(int, first_tp.split(":"))
            target_minutes = h * 60 + m
            min_delta = (24 * 60 - current_minutes) + target_minutes

        return min_delta * 60

    def is_file_type_allowed(self, filename: str) -> bool:
        """检查文件类型是否允许"""
        if "*" in self.file_type_whitelist:
            return True
        ext = self.get_file_type(filename)
        if not ext:
            return False
        return ext.lower() in [x.lstrip(".").lower() for x in self.file_type_whitelist]

    @staticmethod
    def get_file_type(filename: str) -> str:
        """获取文件扩展类型，如 .pdf -> pdf"""
        if "." not in filename:
            return "other"
        return filename.rsplit(".", 1)[-1].lower()

    def generate_target_path(self, group_name: str, group_id: str, filename: str,
                            category: Optional[str] = None,
                            project_name: Optional[str] = None,
                            preset_base: Optional[str] = None) -> str:
        """根据模板生成目标路径

        优先使用预设路径（从 SQLite group_bindings 查询）：
        - 匹配到 → {预设路径}/{分类}[/工程]/{文件名}
        - 未匹配 → {base_path}/{group_name}_{group_id}/{项目名}/{分类}[/工程]/{文件名}

        目录分级：
        项目名称/
        ├── 成片/
        │   └── 工程/
        ├── 素材/
        ├── 音频/
        │   └── 工程/
        ├── 字幕/
        └── 数据组测试/
        """
        from .services.naming_validator import NamingValidator

        if category is None:
            category = self._extract_category_from_filename(filename)

        # 调用方已传 preset_base，则使用它
        if category and preset_base:
            preset_base = preset_base.rstrip("/")
            validator = NamingValidator(extra_categories=self.get_naming_extra_categories())
            naming_info = validator.parse(filename)
            subdir = validator.get_target_subdir(naming_info)
            parts = subdir.split("/", 1)
            inner = parts[1] if len(parts) > 1 else ""
            if inner:
                return f"{preset_base}/{inner}/{filename}"
            else:
                return f"{preset_base}/{filename}"

        # 回退：使用 base_path + group 格式
        if category:
            validator = NamingValidator(extra_categories=self.get_naming_extra_categories())
            naming_info = validator.parse(filename)
            subdir = validator.get_target_subdir(naming_info)
            path = f"{group_name}_{group_id}/{subdir}"
        else:
            file_type = self.get_file_type(filename)
            path = self.path_template.format(
                group_name=group_name,
                group_id=group_id,
                file_type=file_type
            )
        path = path.replace(" ", "_")
        return f"{self.base_path}/{path}"

    @staticmethod
    def _extract_category_from_filename(filename: str) -> Optional[str]:
        """从文件名中提取标准分类（用于目标路径生成）"""
        from .services.naming_validator import CATEGORY_KEYWORD_MAP
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename

        # 检查旧格式 --
        if "--" in stem:
            parts = stem.split("--", 1)
            keyword = parts[0].strip()
            if keyword in CATEGORY_KEYWORD_MAP:
                return CATEGORY_KEYWORD_MAP[keyword]

        # 检查新格式 -
        parts = [p.strip() for p in stem.split("-") if p.strip()]
        for i in range(len(parts) - 1, -1, -1):
            part = parts[i]
            # 去掉版本号
            import re
            part_clean = re.sub(r'v\d+', '', part).strip('-')
            if part_clean in CATEGORY_KEYWORD_MAP:
                return CATEGORY_KEYWORD_MAP[part_clean]

        return None


def validate_config(config: dict) -> FileSyncConfig:
    """验证并返回配置对象"""
    return FileSyncConfig(**config)
