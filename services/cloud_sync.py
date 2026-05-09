import httpx
import logging

from ..config import FileSyncConfig
from ..utils.rename import generate_unique_filename

logger = logging.getLogger(__name__)


def _build_dav_url(nextcloud_url: str, username: str) -> str:
    """构建 WebDAV URL
    支持格式:
    - https://example.com/remote.php/dav/files/username -> https://example.com/remote.php/dav/files/username
    - https://example.com -> https://example.com/remote.php/dav/files/username
    """
    url = nextcloud_url.rstrip("/")
    if "/remote.php/dav/files/" in url:
        # 已经包含完整路径，但可能用户名不对，修正之
        base = url.split("/remote.php/dav/files/")[0]
        return f"{base}/remote.php/dav/files/{username}"
    return f"{url}/remote.php/dav/files/{username}"


class CloudSyncService:
    """NextCloud同步服务 - 使用 httpx 直接调用 WebDAV API"""

    def __init__(self, config: FileSyncConfig):
        self.config = config
        self._dav_url = _build_dav_url(config.nextcloud_url, config.nextcloud_username)
        self._username = config.nextcloud_username
        self._password = config.nextcloud_password
        logger.info(f"NextCloud WebDAV URL: {self._dav_url}")
        self._test_connection()

    def _test_connection(self):
        """测试 WebDAV 连接"""
        try:
            with self._get_client() as client:
                response = client.request("PROPFIND", self._dav_url, headers={"Depth": "0"})
                if response.status_code == 207:
                    logger.info("NextCloud WebDAV 连接成功")
                else:
                    logger.warning(f"NextCloud WebDAV 连接返回状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"连接NextCloud失败: {e}")

    def _get_client(self) -> httpx.Client:
        """获取 httpx 客户端"""
        return httpx.Client(
            auth=(self._username, self._password),
            verify=False,
            timeout=60,
        )

    def _path_exists(self, path: str) -> bool:
        """通过 WebDAV PROPFIND 检查路径是否存在"""
        try:
            url = f"{self._dav_url}{path}"
            logger.debug(f"检查路径是否存在: {url}")
            with self._get_client() as client:
                response = client.request("PROPFIND", url, headers={"Depth": "0"})
                exists = response.status_code == 207
                logger.debug(f"路径 {path} 存在: {exists}")
                return exists
        except Exception as e:
            logger.warning(f"检查路径存在时发生异常 {path}: {type(e).__name__}: {e}")
            return False

    def ensure_directory_exists(self, path: str) -> bool:
        """确保目录存在，不存在则创建（支持多层嵌套目录）"""
        if not path:
            return True

        path = path.strip("/")
        if not path:
            return True

        try:
            current_path = ""
            for segment in path.split("/"):
                if not segment:
                    continue
                current_path += "/" + segment
                if not self._path_exists(current_path):
                    url = f"{self._dav_url}{current_path}"
                    with self._get_client() as client:
                        response = client.request("MKCOL", url)
                        if response.status_code in (201, 405):
                            logger.info(f"目录就绪: {current_path} (状态码: {response.status_code})")
                        else:
                            logger.error(f"创建目录失败 {current_path}: 状态码 {response.status_code}")
                            return False
            return True
        except Exception as e:
            logger.error(f"创建目录失败 {path}: {type(e).__name__}: {e}", exc_info=True)
            return False

    def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        return self._path_exists(path)

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """上传文件到NextCloud（使用 WebDAV PUT）"""
        logger.info(f"开始上传文件: {local_path} -> {remote_path}")

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

            # 上传文件 (WebDAV PUT)
            url = f"{self._dav_url}{remote_path}"
            with open(local_path, "rb") as f:
                file_content = f.read()
            logger.info(f"文件大小: {len(file_content)} 字节, 目标: {url}")

            with self._get_client() as client:
                response = client.put(url, content=file_content)
                if response.status_code in (201, 204):
                    logger.info(f"上传成功: {remote_path} (状态码: {response.status_code})")
                    return True
                else:
                    logger.error(f"上传失败: {remote_path} (状态码: {response.status_code}, 响应: {response.text[:200]})")
                    return False

        except Exception as e:
            logger.error(f"上传文件失败 {remote_path}: {type(e).__name__}: {e}", exc_info=True)
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """从NextCloud下载文件"""
        try:
            url = f"{self._dav_url}{remote_path}"
            with self._get_client() as client:
                response = client.get(url)
                if response.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    return True
                else:
                    logger.error(f"下载文件失败 {remote_path}: 状态码 {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"下载文件失败 {remote_path}: {e}")
            return False
