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
            logger.debug(f"检查路径是否存在: {path}")
            # 尝试使用 find 方法（如果存在）
            if hasattr(self.nc.files, 'find'):
                logger.debug(f"使用 find 方法检查路径")
                result = self.nc.files.find(path)
                exists = result is not None
                logger.debug(f"find 结果: {exists}")
                return exists
            # 尝试使用 by_path 方法
            elif hasattr(self.nc.files, 'by_path'):
                logger.debug(f"使用 by_path 方法检查路径")
                self.nc.files.by_path(path)
                logger.debug(f"by_path 成功，路径存在")
                return True
            # 尝试使用 listdir 检查父目录
            elif hasattr(self.nc.files, 'listdir'):
                logger.debug(f"使用 listdir 方法检查路径")
                parent = path.rsplit("/", 1)[0] if "/" in path else "/"
                name = path.rsplit("/", 1)[-1]
                items = self.nc.files.listdir(parent)
                for item in items:
                    if hasattr(item, 'name') and item.name == name:
                        logger.debug(f"找到匹配项: {item.name}")
                        return True
                    elif hasattr(item, 'user_path') and item.user_path == path:
                        logger.debug(f"找到匹配项: {item.user_path}")
                        return True
                logger.debug(f"未找到匹配项")
                return False
            else:
                # 最后尝试：直接尝试操作，捕获异常判断
                logger.debug(f"使用 listdir 直接检查路径")
                self.nc.files.listdir(path)
                return True
        except Exception as e:
            # 404 表示不存在，其他异常按存在处理（保守策略）
            error_msg = str(e)
            if "404" in error_msg or "NotFound" in error_msg:
                logger.debug(f"路径不存在 (404): {path}")
                return False
            logger.warning(f"检查路径存在时发生异常 {path}: {type(e).__name__}: {e}")
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
                logger.debug(f"检查目录是否存在: {current_path}")
                exists = self._path_exists(current_path)
                logger.debug(f"目录 {current_path} 存在: {exists}")
                if not exists:
                    logger.info(f"创建目录: {current_path}")
                    self.nc.files.mkdir(current_path)
                    logger.info(f"目录创建成功: {current_path}")
            return True
        except Exception as e:
            logger.error(f"创建目录失败 {path}: {type(e).__name__}: {e}", exc_info=True)
            return False

    def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        try:
            logger.debug(f"检查文件是否存在: {path}")
            result = self._path_exists(path)
            logger.debug(f"文件存在检查结果: {result}")
            return result
        except Exception as e:
            logger.error(f"检查文件存在失败 {path}: {type(e).__name__}: {e}", exc_info=True)
            return False

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """
        上传文件到NextCloud
        如果远程路径文件已存在，自动重命名
        """
        logger.info(f"开始上传文件: {local_path} -> {remote_path}")
        try:
            # 检查文件是否存在，如存在则重命名
            logger.debug(f"检查远程文件是否存在: {remote_path}")
            file_exists = self.file_exists(remote_path)
            logger.debug(f"文件存在检查结果: {file_exists}")

            if file_exists:
                original_name = remote_path.split("/")[-1]
                new_name = generate_unique_filename(original_name)
                remote_path = remote_path.rsplit("/", 1)[0] + "/" + new_name
                logger.info(f"文件已存在，重命名为: {new_name}")

            # 确保目录存在
            if "/" not in remote_path:
                logger.error(f"远程路径格式无效: {remote_path}")
                return False
            dir_path = remote_path.rsplit("/", 1)[0]
            logger.debug(f"检查目录是否存在: {dir_path}")
            if dir_path and not self.ensure_directory_exists(dir_path):
                logger.error(f"目录创建失败: {dir_path}")
                return False

            # 上传文件
            logger.debug(f"正在打开本地文件: {local_path}")
            with open(local_path, "rb") as f:
                file_size = f.seek(0, 2)
                f.seek(0)
                logger.info(f"文件大小: {file_size} 字节")
                logger.debug(f"正在调用 nc.files.upload...")
                self.nc.files.upload(remote_path, f)
            logger.info(f"上传成功: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"上传文件失败 {remote_path}: {type(e).__name__}: {e}", exc_info=True)
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