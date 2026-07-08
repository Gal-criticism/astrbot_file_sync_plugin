"""同步结果模型 — 记录单文件同步的完整结果，替代简单的 bool 返回值"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class SyncResult:
    """单文件同步的详细结果

    用于 `/诊断日志` 中精确展示失败原因，以及命名规范分析。
    """
    success: bool
    file_name: str
    file_id: str
    file_size: int
    group_id: str
    target_path: str

    # ── 失败阶段 ──
    failed_stage: Optional[str] = None
    # 可选值:
    #   "download_no_url"       — 无法获取下载链接
    #   "download_http_error"   — HTTP 状态错误 (4xx/5xx)
    #   "download_network_error"— HTTP 连接/超时
    #   "download_size_mismatch"— 文件大小不匹配
    #   "download_file_missing" — 下载的文件不存在于本地
    #   "upload_http_error"     — 上传 HTTP 错误
    #   "upload_timeout"        — 上传超时
    #   "upload_network_error"  — 连接错误
    #   "upload_mkdir_failed"   — 目录创建失败
    #   "upload_unknown"        — 未知上传错误

    # ── 失败详情 ──
    failed_detail: Optional[str] = None
    # 如 HTTP 状态码、异常类型、错误消息等

    # ── 查重 ──
    already_synced: bool = False
    # True → 查重命中，跳过下载/上传，非错误

    # ── 命名规范分析 ──
    naming_category: Optional[str] = None      # 识别的分类
    naming_project: Optional[str] = None       # 项目名称
    naming_version: Optional[int] = None        # 版本号
    naming_is_valid: Optional[bool] = None     # 是否合规
    naming_error: Optional[str] = None         # 不合规原因

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "file_name": self.file_name,
            "file_id": self.file_id,
            "file_size": self.file_size,
            "group_id": self.group_id,
            "target_path": self.target_path,
            "failed_stage": self.failed_stage,
            "failed_detail": self.failed_detail,
            "category": self.naming_category,
            "project": self.naming_project,
            "version": self.naming_version,
            "naming_valid": self.naming_is_valid,
            "naming_error": self.naming_error,
            "already_synced": self.already_synced,
        }
