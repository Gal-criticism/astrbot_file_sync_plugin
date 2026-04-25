from nc_py_api import Nextcloud
from typing import Optional
import logging

from file_sync_plugin.config import FileSyncConfig
from file_sync_plugin.utils.rename import generate_unique_filename

logger = logging.getLogger(__name__)

class CloudSyncService:
    """NextCloud同步服务"""

    def __init__(self, config: FileSyncConfig):
        self.config = config
        self.nc: Optional[Nextcloud] = None
        self._connect()

    def _connect(self):
        """建立NextCloud连接"""
        try:
            self.nc = Nextcloud(
                nextcloud_url=self.config.nextcloud_url,
                nc_auth_user=self.config.nextcloud_username,
                nc_auth_pass=self.config.nextcloud_password,
            )
        except Exception as e:
            logger.error(f"连接NextCloud失败: {e}")
            self.nc = None

    def ensure_directory_exists(self, path: str) -> bool:
        """确保目录存在，不存在则创建"""
        try:
            if not self.nc.files.exists(path):
                self.nc.files.mkdir(path)
                logger.info(f"创建目录: {path}")
            return True
        except Exception as e:
            logger.error(f"创建目录失败 {path}: {e}")
            return False

    def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        try:
            return self.nc.files.exists(path)
        except Exception as e:
            logger.error(f"检查文件存在失败 {path}: {e}")
            return False

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """
        上传文件到NextCloud
        如果远程路径文件已存在，自动重命名
        """
        try:
            # 检查文件是否存在，如存在则重命名
            if self.file_exists(remote_path):
                original_name = remote_path.split("/")[-1]
                new_name = generate_unique_filename(original_name)
                remote_path = remote_path.rsplit("/", 1)[0] + "/" + new_name
                logger.info(f"文件已存在，重命名为: {new_name}")

            # 确保目录存在
            if "/" not in remote_path:
                logger.error(f"远程路径格式无效: {remote_path}")
                return False
            dir_path = remote_path.rsplit("/", 1)[0]
            if dir_path and not self.ensure_directory_exists(dir_path):
                return False

            # 上传文件
            with open(local_path, "rb") as f:
                self.nc.files.upload(remote_path, f)
            logger.info(f"上传成功: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"上传文件失败 {remote_path}: {e}")
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """从NextCloud下载文件"""
        try:
            content = self.nc.files.download(remote_path)
        except Exception as e:
            logger.error(f"下载文件失败 {remote_path}: {e}")
            return False
        try:
            with open(local_path, "wb") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"写入文件失败 {local_path}: {e}")
            return False