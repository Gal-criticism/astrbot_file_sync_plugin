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
    """QQ群文件扫描器"""

    def __init__(self, client):
        """
        初始化文件扫描器
        client: aiocqhttp客户端，通过 event.bot 获取
        """
        self.client = client

    async def get_group_file_list(self, group_id: str) -> List[GroupFileInfo]:
        """
        获取群文件列表
        调用 OneBot API: get_group_file_list
        """
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

    async def get_group_file_url(self, group_id: str, file_id: str) -> Optional[str]:
        """
        获取群文件下载链接
        调用 OneBot API: get_group_file_url
        """
        try:
            result = await self.client.api.call_action(
                "get_group_file_url",
                group_id=int(group_id),
                file_id=file_id
            )
            url = result.get("url")
            if url:
                logger.info(f"获取文件下载链接成功: {file_id}")
            return url
        except Exception as e:
            logger.error(f"获取文件下载链接失败: {e}")
            return None