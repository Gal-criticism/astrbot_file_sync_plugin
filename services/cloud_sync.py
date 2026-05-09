from nc_py_api import Nextcloud
from typing import Optional
import logging

from ..config import FileSyncConfig
from ..utils.rename import generate_unique_filename

logger = logging.getLogger(__name__)


def _extract_base_url(url: str, username: str) -> str:
    """从 NextCloud URL 中提取基础 URL
    支持格式:
    - https://example.com/remote.php/dav/files/username -> https://example.com
    - https://example.com -> https://example.com
    """
    url = url.rstrip("/")
    if "/remote.php/dav/files/" in url:
        return url.split("/remote.php/dav/files/")[0]
    return url


class CloudSyncService:
    """NextCloud同步服务"""

    def __init__(self, config: FileSyncConfig):
        self.config = config
        self.nc: Optional[Nextcloud] = None
        self._base_url = _extract_base_url(config.nextcloud_url, config.nextcloud_username)
        logger.info(f"NextCloud 基础 URL: {self._base_url}")
        self._connect()

    def _connect(self):
        """建立NextCloud连接"""
        try:
            self.nc = Nextcloud(
                nextcloud_url=self._base_url,
                nc_auth_user=self.config.nextcloud_username,
                nc_auth_pass=self.config.nextcloud_password,
            )
            logger.info("NextCloud 连接成功")
        except Exception as e:
            logger.error(f"连接NextCloud失败: {e}")
            self.nc = None

    def _path_exists(self, path: str) -> bool:
        """检查路径是否存在（兼容新版 nc_py_api）"""
        try:
            # 尝试使用 find 方法（如果存在）
            if hasattr(self.nc.files, 'find'):
                result = self.nc.files.find(path)
                return result is not None
            # 尝试使用 by_path 方法
            elif hasattr(self.nc.files, 'by_path'):
                self.nc.files.by_path(path)
                return True
            # 尝试使用 listdir 检查父目录
            elif hasattr(self.nc.files, 'listdir'):
                parent = path.rsplit("/", 1)[0] if "/" in path else "/"
                name = path.rsplit("/", 1)[-1]
                items = self.nc.files.listdir(parent)
                for item in items:
                    if hasattr(item, 'name') and item.name == name:
                        return True
                    elif hasattr(item, 'user_path') and item.user_path == path:
                        return True
                return False
            else:
                # 最后尝试：直接尝试操作，捕获异常判断
                self.nc.files.listdir(path)
                return True
        except Exception as e:
            # 404 表示不存在，其他异常按存在处理（保守策略）
            if "404" in str(e) or "NotFound" in str(e):
                return False
            logger.debug(f"检查路径存在时发生异常 {path}: {e}")
            return False

    def ensure_directory_exists(self, path: str) -> bool:
        """确保目录存在，不存在则创建（支持多层嵌套目录）"""
        if not path:
            return True

        # 规范化路径，确保以 / 开头
        path = path.strip("/")
        if not path:
            return True

        try:
            # 逐层检查并创建目录
            current_path = ""
            for segment in path.split("/"):
                if not segment:
                    continue
                current_path += "/" + segment
                if not self._path_exists(current_path):
                    self.nc.files.mkdir(current_path)
                    logger.info(f"创建目录: {current_path}")
            return True
        except Exception as e:
            logger.error(f"创建目录失败 {path}: {e}")
            return False

    def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        try:
            return self._path_exists(path)
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