from pydantic import BaseModel, Field
from typing import List, Optional

class FileSyncConfig(BaseModel):
    """插件配置模型"""
    nextcloud_url: str = Field(..., description="NextCloud WebDAV地址")
    nextcloud_username: str = Field(..., description="NextCloud用户名")
    nextcloud_password: str = Field(..., description="NextCloud应用密码")
    enabled_groups: List[str] = Field(default_factory=list, description="启用的群号列表")
    base_path: str = Field(default="/QQ群文件", description="云盘基础路径")
    path_template: str = Field(default="{group_name}_{group_id}/{file_type}", description="文件夹路径模板")
    sync_interval_minutes: int = Field(default=5, ge=1, description="同步间隔(分钟)")
    file_type_whitelist: List[str] = Field(default_factory=lambda: ["*"], description="允许的文件类型")
    notify_on_success: bool = Field(default=False, description="成功时通知")
    notify_on_error: bool = Field(default=True, description="失败时通知")
    retry_queue_enabled: bool = Field(default=True, description="启用重试队列")
    retry_max_attempts: int = Field(default=3, ge=1, description="最大重试次数")
    retry_delay_seconds: int = Field(default=300, ge=60, description="重试间隔(秒)")

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

    def generate_target_path(self, group_name: str, group_id: str, filename: str) -> str:
        """根据模板生成目标路径"""
        file_type = self.get_file_type(filename)
        path = self.path_template.format(
            group_name=group_name,
            group_id=group_id,
            file_type=file_type
        )
        # 清理特殊字符
        path = path.replace(" ", "_")
        return f"{self.base_path}/{path}"

def validate_config(config: dict) -> FileSyncConfig:
    """验证并返回配置对象"""
    return FileSyncConfig(**config)