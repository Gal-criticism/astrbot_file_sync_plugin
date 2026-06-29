"""QQ群文件扫描器 — 封装群文件 API 调用，兼容多种 OneBot 后端"""

from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class GroupFileInfo:
    """群文件信息"""
    def __init__(self, file_id: str, file_name: str, file_size: int,
                 upload_time: int, dead_time: int):
        self.file_id = file_id
        self.file_name = file_name
        self.file_size = file_size
        self.upload_time = upload_time
        self.dead_time = dead_time

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GroupFileInfo":
        """从API响应字典创建GroupFileInfo"""
        return cls(
            file_id=data.get("fileid", ""),
            file_name=data.get("filename", ""),
            file_size=data.get("size", 0),
            upload_time=data.get("upload_time", 0),
            dead_time=data.get("dead_time", 0)
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "fileid": self.file_id,
            "filename": self.file_name,
            "size": self.file_size,
            "upload_time": self.upload_time,
            "dead_time": self.dead_time
        }


class FileScanner:
    """QQ群文件扫描器 — 封装群文件 API 调用，兼容多种 OneBot 后端"""

    # 尝试的 API 端点列表（按优先级排序）
    API_ENDPOINTS = [
        "get_group_root_files",      # 标准 OneBot 11 端点
        "get_group_file_list",        # go-cqhttp 扩展端点
        "get_group_files",            # 部分后端使用
    ]

    def __init__(self, client):
        """初始化文件扫描器

        Args:
            client: aiocqhttp API 客户端
        """
        self.client = client

    async def list_files(self, group_id: str) -> list:
        """获取群文件列表（自动尝试多种 API 端点以兼容不同后端）

        Args:
            group_id: 群号

        Returns:
            文件信息列表（原始 dict 格式，兼容不同后端的字段名）
        """
        for api_name in self.API_ENDPOINTS:
            try:
                result = await self.client.api.call_action(api_name, group_id=int(group_id))
                logger.debug(f"API {api_name} 成功")

                if isinstance(result, dict):
                    files = result.get("files", [])
                    folders = result.get("folders", [])
                    if files or folders:
                        logger.info(f"群 {group_id} 获取到 {len(files)} 个文件, {len(folders)} 个文件夹")
                        return files
                if isinstance(result, list):
                    logger.info(f"群 {group_id} 获取到 {len(result)} 个项目")
                    return result

            except Exception as e:
                error_msg = str(e)
                if "1404" in error_msg or "不支持" in error_msg:
                    logger.warning(f"API {api_name} 不被支持，尝试下一个")
                    continue
                else:
                    logger.error(f"API {api_name} 失败: {e}")
                    continue

        logger.error("所有文件列表 API 均失败")
        return []

    async def get_group_file_list(self, group_id: str) -> List[GroupFileInfo]:
        """获取群文件列表（旧接口，封装为 GroupFileInfo 列表）"""
        try:
            result = await self.client.api.call_action(
                "get_group_file_list",
                group_id=int(group_id)
            )
            files = []
            for f in result.get("files", []):
                files.append(GroupFileInfo.from_dict(f))
            logger.info(f"获取群 {group_id} 文件列表成功，共 {len(files)} 个文件")
            return files
        except Exception as e:
            logger.error(f"获取群 {group_id} 文件列表失败: {e}")
            return []

    async def get_file_url(self, group_id: str, file_id: str) -> Optional[str]:
        """获取群文件下载链接

        尝试多种 API 端点以兼容不同后端
        """
        url_apis = ["get_group_file_url", "get_file_url"]
        for api_name in url_apis:
            try:
                url_result = await self.client.api.call_action(
                    api_name,
                    group_id=int(group_id),
                    file_id=file_id
                )
                file_url = url_result.get("url")
                if file_url:
                    logger.info(f"获取下载链接成功: {file_url[:100]}...")
                    return file_url
            except Exception as e:
                logger.warning(f"API {api_name} 失败: {e}")
                continue

        logger.error(f"无法获取文件下载链接: {file_id}")
        return None
