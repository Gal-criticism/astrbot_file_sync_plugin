"""QQ群文件下载服务

从 QQ 群文件 API 下载文件到本地临时目录，支持流式下载、断点续传。
"""

import time
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import httpx

from astrbot.api import logger


class FileDownloader:
    """QQ群文件下载器"""

    def __init__(self, client):
        """初始化下载器

        Args:
            client: aiocqhttp API 客户端
        """
        self.client = client

    async def get_file_url(self, group_id: str, file_id: str) -> Optional[str]:
        """获取文件下载链接（委托给 FileScanner）"""
        from .file_scanner import FileScanner
        scanner = FileScanner(self.client)
        return await scanner.get_file_url(group_id, file_id)

    async def download_file(
        self,
        group_id: str,
        file_id: str,
        file_name: str,
        file_size: int
    ) -> Tuple[bool, Optional[str]]:
        """下载群文件到本地临时目录

        Args:
            group_id: 群号
            file_id: 文件 ID
            file_name: 文件名（用于本地临时文件命名）
            file_size: 预期文件大小（字节）

        Returns:
            (success, local_path) - 成功返回 (True, 临时文件路径)，失败返回 (False, None)
        """
        logger.info(f"[DOWNLOAD] 开始下载: {file_name} (ID: {file_id}, 大小: {file_size / (1024*1024):.1f} MB)")

        # 获取下载链接
        file_url = await self.get_file_url(group_id, file_id)
        if not file_url:
            return False, None

        # 创建临时目录
        temp_dir = Path(tempfile.gettempdir()) / "file_sync"
        temp_dir.mkdir(exist_ok=True)
        local_path = temp_dir / file_name

        # 根据文件大小动态调整超时（至少10分钟，每MB增加15秒）
        download_timeout = max(600, file_size // (1024 * 1024) * 15)
        logger.info(f"[DOWNLOAD] 下载超时设置: {download_timeout} 秒")

        downloaded_size = 0
        start_time = time.time()

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout=download_timeout)
            ) as http_client:
                async with http_client.stream("GET", file_url) as response:
                    logger.info(f"[DOWNLOAD] 响应状态码: {response.status_code}")
                    response.raise_for_status()

                    with open(local_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            # 每 10MB 输出一次进度
                            if downloaded_size % (10 * 1024 * 1024) == 0:
                                elapsed = time.time() - start_time
                                speed = downloaded_size / elapsed / 1024 / 1024 if elapsed > 0 else 0
                                progress = (downloaded_size / file_size) * 100 if file_size > 0 else 0
                                logger.info(
                                    f"[DOWNLOAD] 进度: {progress:.1f}%, "
                                    f"已下载: {downloaded_size / (1024*1024):.1f} MB, "
                                    f"速度: {speed:.2f} MB/s"
                                )

        except httpx.HTTPStatusError as e:
            logger.error(f"[DOWNLOAD] HTTP 状态错误: {e.response.status_code}")
            return False, None
        except httpx.HTTPError as e:
            logger.error(f"[DOWNLOAD] HTTP 错误: {type(e).__name__}: {e}")
            return False, None

        elapsed = time.time() - start_time
        speed = downloaded_size / elapsed / 1024 / 1024 if elapsed > 0 else 0
        logger.info(f"[DOWNLOAD] 完成: {downloaded_size / (1024*1024):.2f} MB, 耗时 {elapsed:.1f}s, 速度 {speed:.2f} MB/s")

        # 校验下载完整性
        if not local_path.exists():
            logger.error(f"[DOWNLOAD] 下载的文件不存在: {local_path}")
            return False, None

        actual_size = local_path.stat().st_size
        if actual_size != file_size:
            logger.error(
                f"[DOWNLOAD] 文件大小不匹配! 预期: {file_size}, 实际: {actual_size}"
                f" ({actual_size / (1024*1024):.2f} MB vs {file_size / (1024*1024):.2f} MB)"
            )
            # 删除不完整的文件
            try:
                local_path.unlink()
            except Exception:
                pass
            return False, None

        return True, str(local_path)

    @staticmethod
    def cleanup(local_path: Optional[str]):
        """清理本地临时文件"""
        if local_path:
            p = Path(local_path)
            if p.exists():
                try:
                    size_before = p.stat().st_size
                    p.unlink()
                    logger.info(f"[CLEANUP] 已删除临时文件: {local_path} ({size_before} 字节)")
                except Exception as e:
                    logger.warning(f"[CLEANUP] 删除临时文件失败 {local_path}: {e}")
