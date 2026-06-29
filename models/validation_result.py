"""文件名验证结果模型（兼容旧版）

@deprecated 请使用 NamingResult 替代
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FileValidationResult:
    """文件名验证结果"""
    is_valid: bool
    filename: str
    category: Optional[str] = None
    error_type: Optional[str] = None
    error_reason: Optional[str] = None
    sender_id: str = ""
    sender_name: str = ""
    group_id: str = ""
