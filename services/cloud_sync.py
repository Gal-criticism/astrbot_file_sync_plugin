"""NextCloud WebDAV 同步服务

直接调用 NextCloud WebDAV API（PROPFIND、MKCOL、PUT），
支持流式上传、目录管理、远程文件列表。
"""

import time
import os
from pathlib import Path
from typing import Optional, List, Tuple
from urllib.parse import quote

import httpx

from ..config import FileSyncConfig
from ..utils.rename import generate_unique_filename
from astrbot.api import logger


def _build_dav_url(nextcloud_url: str, username: str) -> str:
    """构建 WebDAV URL

    支持格式:
    - https://example.com/remote.php/dav/files/username → 保持不变
    - https://example.com → 自动拼接 /remote.php/dav/files/username
    """
    url = nextcloud_url.rstrip("/")
    if "/remote.php/dav/files/" in url:
        base = url.split("/remote.php/dav/files/")[0]
        return f"{base}/remote.php/dav/files/{username}"
    return f"{url}/remote.php/dav/files/{username}"


class CloudSyncService:
    """NextCloud 同步服务 - 使用 httpx 直接调用 WebDAV API"""

    def __init__(self, config: FileSyncConfig):
        self.config = config
        self._dav_url = _build_dav_url(config.nextcloud_url, config.nextcloud_username)
        self._username = config.nextcloud_username
        self._password = config.nextcloud_password

        from urllib.parse import urlparse
        self._dav_path = urlparse(self._dav_url).path.rstrip('/')

        logger.info(f"NextCloud WebDAV URL: {self._dav_url}")
        if not self._dav_url.startswith("https://"):
            logger.warning("NextCloud 未使用 HTTPS 连接，密码以明文传输")
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
            logger.error(f"连接 NextCloud 失败: {e}")

    def _get_client(self, timeout: int = 300) -> httpx.Client:
        """获取 httpx 客户端"""
        return httpx.Client(
            auth=(self._username, self._password),
            verify=False,
            timeout=timeout,
        )

    # ===== 目录与文件检查 =====

    def _path_exists(self, path: str) -> bool:
        """通过 WebDAV PROPFIND 检查路径是否存在"""
        if not path.startswith("/"):
            path = "/" + path
        try:
            encoded_path = quote(path, safe="/")
            url = f"{self._dav_url}{encoded_path}"
            with self._get_client() as client:
                response = client.request("PROPFIND", url, headers={"Depth": "0"})
                return response.status_code == 207
        except Exception as e:
            logger.warning(f"检查路径存在时异常 {path}: {type(e).__name__}: {e}")
            return False

    def ensure_directory_exists(self, path: str) -> bool:
        """确保目录存在，不存在则逐层创建（支持多层嵌套目录）"""
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
                    encoded_current_path = quote(current_path, safe="/")
                    url = f"{self._dav_url}{encoded_current_path}"
                    with self._get_client() as client:
                        response = client.request("MKCOL", url)
                        if response.status_code in (201, 405):
                            logger.debug(f"目录就绪: {current_path} (状态码: {response.status_code})")
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

    # ===== 文件列表 =====

    @staticmethod
    def _extract_name_from_href(href: str) -> str:
        """从 href 路径末尾提取文件名/目录名，并做 URL 解码"""
        from urllib.parse import unquote
        path = href.rstrip('/')
        name = path.rsplit('/', 1)[-1] if '/' in path else path
        return unquote(name)

    def list_remote_files(self, remote_path: str) -> List[dict]:
        """递归列出远程目录下所有层级的文件（用于插件启动时预热 SQLite 查重数据）

        Returns:
            List[dict]: 文件列表，每项包含 file_name, file_size, remote_path
        """
        if not remote_path.startswith("/"):
            remote_path = "/" + remote_path

        result = []
        try:
            url = f"{self._dav_url}{remote_path}"
            logger.debug(f"列出远程文件: {url}")
            with self._get_client() as client:
                response = client.request("PROPFIND", url, headers={"Depth": "1"})
                if response.status_code != 207:
                    logger.warning(f"列出远程文件失败 {remote_path}: 状态码 {response.status_code}")
                    return result

                import re
                content = response.text
                entries = re.split(r'(?=<d:response>)', content)

                subdirs = []
                for entry in entries:
                    href_match = re.search(r'<d:href>([^<]+)</d:href>', entry)
                    if not href_match:
                        continue

                    href = href_match.group(1)
                    length_match = re.search(r'<d:getcontentlength>([^<]+)</d:getcontentlength>', entry)
                    is_collection = '<d:collection' in entry

                    relative = href.rstrip('/')
                    if relative.startswith(self._dav_path):
                        relative = relative[len(self._dav_path):] or '/'
                    if relative.rstrip('/') == remote_path.rstrip('/'):
                        continue

                    file_name = self._extract_name_from_href(href)
                    if not file_name:
                        continue

                    if is_collection:
                        subdirs.append(relative.rstrip('/'))
                    else:
                        result.append({
                            "file_name": file_name,
                            "file_size": int(length_match.group(1)) if length_match else 0,
                            "remote_path": href
                        })

                for subdir_rel in subdirs:
                    sub_result = self.list_remote_files(subdir_rel)
                    result.extend(sub_result)

        except Exception as e:
            logger.error(f"列出远程文件异常 {remote_path}: {type(e).__name__}: {e}")
        return result

    def list_all_remote_dirs(self, base_path: str) -> List[str]:
        """列出远程目录下所有子目录（不含文件，用于定位群文件夹路径）"""
        if not base_path.startswith("/"):
            base_path = "/" + base_path

        dirs = []
        try:
            url = f"{self._dav_url}{base_path}"
            with self._get_client() as client:
                response = client.request("PROPFIND", url, headers={"Depth": "1"})
                if response.status_code != 207:
                    return dirs

                import re
                content = response.text
                entries = re.split(r'(?=<d:response>)', content)
                for entry in entries:
                    if '<d:collection' not in entry:
                        continue
                    href_match = re.search(r'<d:href>([^<]+)</d:href>', entry)
                    if href_match:
                        href = href_match.group(1)
                        if href.rstrip('/') == base_path.rstrip('/'):
                            continue
                        normalized_href = href.rstrip('/')
                        normalized_base = base_path.rstrip('/')
                        if (normalized_href.startswith(normalized_base + '/')
                                and '/' not in normalized_href[len(normalized_base) + 1:]):
                            dirs.append(href.rstrip('/'))
        except Exception as e:
            logger.error(f"列出子目录异常 {base_path}: {type(e).__name__}: {e}")
        return dirs

    # ===== 核心：文件上传 =====

    def upload_file(self, local_path: str, remote_path: str,
                    file_size: int = 0, max_retries: int = 3) -> Tuple[bool, Optional[str], Optional[str]]:
        """上传文件到 NextCloud（统一入口，直接上传）

        Args:
            local_path: 本地文件路径
            remote_path: 远程目标路径
            file_size: 文件大小（字节），用于超时计算
            max_retries: 最大重试次数

        Returns:
            (success, error_stage, error_detail)
        """
        return self.upload_file_direct(local_path, remote_path, file_size, max_retries)

    def upload_file_direct(self, local_path: str, remote_path: str,
                           file_size: int = 0, max_retries: int = 3) -> Tuple[bool, Optional[str], Optional[str]]:
        """WebDAV PUT 直接上传文件（支持大文件流式传输）

        Args:
            local_path: 本地文件路径
            remote_path: 远程目标路径
            file_size: 文件大小（字节）
            max_retries: 最大重试次数

        Returns:
            (success, error_stage, error_detail)
            - success=True → 上传成功
            - success=False → error_stage 标识阶段，error_detail 描述原因
        """
        # 确保 remote_path 以 / 开头
        if not remote_path.startswith("/"):
            remote_path = "/" + remote_path
            logger.warning(f"[UPLOAD] remote_path 缺少开头的 /，已自动添加: {remote_path}")

        logger.info(f"[UPLOAD] 开始上传: {local_path} -> {remote_path}")
        logger.info(f"[UPLOAD] 文件大小: {file_size} 字节 ({file_size / (1024*1024):.2f} MB)")

        # 检查本地文件
        if not os.path.exists(local_path):
            logger.error(f"[UPLOAD] 本地文件不存在: {local_path}")
            return False, "upload_local_missing", f"文件不存在: {local_path}"

        actual_size = os.path.getsize(local_path)
        logger.info(f"[UPLOAD] 本地文件实际大小: {actual_size} 字节 ({actual_size / (1024*1024):.2f} MB)")

        for attempt in range(max_retries):
            logger.info(f"[UPLOAD] 第 {attempt + 1}/{max_retries} 次尝试")
            try:
                # 检查远程文件是否存在，如存在则重命名
                if self.file_exists(remote_path):
                    original_name = remote_path.split("/")[-1]
                    new_name = generate_unique_filename(original_name)
                    remote_path = remote_path.rsplit("/", 1)[0] + "/" + new_name
                    logger.info(f"[UPLOAD] 文件已存在，重命名为: {new_name}")

                # 确保目录存在
                if "/" not in remote_path:
                    logger.error(f"[UPLOAD] 远程路径格式无效: {remote_path}")
                    return False, "upload_mkdir_failed", f"路径格式无效: {remote_path}"
                dir_path = remote_path.rsplit("/", 1)[0]
                if dir_path and not self.ensure_directory_exists(dir_path):
                    logger.error(f"[UPLOAD] 创建目录失败: {dir_path}")
                    return False, "upload_mkdir_failed", f"创建目录失败: {dir_path}"

                # 上传文件 (WebDAV PUT)
                encoded_remote_path = quote(remote_path, safe="/")
                url = f"{self._dav_url}{encoded_remote_path}"

                # 根据文件大小动态调整超时（至少10分钟，每MB增加15秒）
                timeout = max(600, actual_size // (1024 * 1024) * 15)
                logger.info(f"[UPLOAD] 超时设置: {timeout} 秒, URL: {url}")

                start_time = time.time()
                with self._get_client(timeout=timeout) as client:
                    with open(local_path, "rb") as f:
                        response = client.put(url, content=f)
                    elapsed = time.time() - start_time

                    if response.status_code in (201, 204):
                        speed = actual_size / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        logger.info(
                            f"[UPLOAD] 上传成功: {remote_path} "
                            f"(状态码: {response.status_code}, 耗时: {elapsed:.1f}s, 速度: {speed:.2f} MB/s)"
                        )
                        return True, None, None
                    else:
                        logger.error(
                            f"[UPLOAD] 上传失败: 状态码 {response.status_code}, "
                            f"响应: {response.text[:200]}"
                        )
                        if attempt < max_retries - 1:
                            time.sleep(10)
                            continue
                        return False, "upload_http_error", f"HTTP {response.status_code}: {response.text[:100]}"

            except httpx.TimeoutException:
                logger.error(f"[UPLOAD] 上传超时 (第 {attempt + 1} 次)")
                if attempt < max_retries - 1:
                    time.sleep(30)
                    continue
                return False, "upload_timeout", f"超时 ({timeout}s), 第 {attempt + 1}/{max_retries} 次"
            except httpx.HTTPError as e:
                logger.error(f"[UPLOAD] HTTP 错误: {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(10)
                    continue
                return False, "upload_network_error", f"{type(e).__name__}: {e}"
            except ConnectionError as e:
                logger.error(f"[UPLOAD] 连接错误: {e}")
                if attempt < max_retries - 1:
                    time.sleep(10)
                    continue
                return False, "upload_network_error", f"ConnectionError: {e}"
            except Exception as e:
                logger.error(f"[UPLOAD] 未知错误: {type(e).__name__}: {e}", exc_info=True)
                return False, "upload_unknown", f"{type(e).__name__}: {e}"

        return False, "upload_unknown", "所有重试均已失败"

    # ===== 文件下载 =====

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """从 NextCloud 下载文件"""
        if not remote_path.startswith("/"):
            remote_path = "/" + remote_path
        try:
            encoded_remote_path = quote(remote_path, safe="/")
            url = f"{self._dav_url}{encoded_remote_path}"
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
