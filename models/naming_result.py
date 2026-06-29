"""文件名解析结果模型 - 基于新命名规范"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class NamingResult:
    """文件名解析与验证结果

    命名规范：{项目名称}-{分类}[v{版本号}][-{后缀}]

    示例：
        项目A-视频封面v1.png          → project_name=项目A, category=封面, version=1
        项目A-成片v2-无字幕.mp4       → project_name=项目A, category=成片, version=2, suffixes=["无字幕"]
        项目A-录音v1-处理v1.flac     → project_name=项目A, category=音频, version=1, suffixes=["处理v1"]
        项目A-字幕v1.ass             → project_name=项目A, category=字幕, version=1
        素材--参考图.png             → project_name=素材, category=素材, deprecated_separator=True (兼容旧格式)
    """
    is_valid: bool
    filename: str
    project_name: Optional[str] = None
    category: Optional[str] = None          # 标准六大分类之一
    version: Optional[int] = None           # 主版本号 (v1 → 1)
    suffixes: List[str] = field(default_factory=list)   # 后缀列表（如 ["无字幕", "工程"]）
    extension: Optional[str] = None         # 文件扩展名（不含点）
    deprecated_separator: bool = False       # 是否使用了旧的 -- 分隔符
    error_type: Optional[str] = None
    error_reason: Optional[str] = None
    sender_id: str = ""
    sender_name: str = ""
    group_id: str = ""

    def to_legacy(self) -> "FileValidationResult":
        """兼容转换：转为旧版 FileValidationResult"""
        from .validation_result import FileValidationResult
        return FileValidationResult(
            is_valid=self.is_valid,
            filename=self.filename,
            category=self.category,
            error_type=self.error_type,
            error_reason=self.error_reason,
            sender_id=self.sender_id,
            sender_name=self.sender_name,
            group_id=self.group_id,
        )
