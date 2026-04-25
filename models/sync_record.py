from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class SyncRecord:
    """同步记录"""
    file_id: str           # QQ群文件的file_id
    file_name: str         # 文件名
    file_size: int         # 文件大小
    group_id: str          # 群号
    target_path: str       # 云端目标路径
    sync_time: datetime    # 同步时间
    file_hash: Optional[str] = None  # 文件hash(可选)
    retry_count: int = 0   # 重试次数

    def __post_init__(self):
        """数据验证"""
        if not self.file_id or not self.file_id.strip():
            raise ValueError("file_id不能为空")
        if not self.file_name or not self.file_name.strip():
            raise ValueError("file_name不能为空")
        if self.file_size < 0:
            raise ValueError("file_size必须为非负数")