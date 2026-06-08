from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime

class FileSyncConfig(BaseModel):
    """插件配置模型"""
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
        default="{category}--{name}",
        description="文件名模板格式"
    )
    filename_categories: dict = Field(
        default_factory=dict,
        description="分类白名单（分组），可选，留空则只检查格式"
    )
    filename_notify_template: Optional[str] = Field(
        default=None,
        description="@提醒模板"
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