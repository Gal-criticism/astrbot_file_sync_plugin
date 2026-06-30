"""FileScanner.list_files 测试 (主入口方法，此前零测试) + config_helpers + file_downloader + models"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from file_sync_plugin2.services.file_scanner import FileScanner, GroupFileInfo


# ──────── FileScanner.list_files ────────

@pytest.mark.asyncio
async def test_list_files_dict_response():
    """API 返回 dict 且包含 files → 返回文件列表"""
    client = MagicMock()
    client.api.call_action = AsyncMock(return_value={
        "files": [{"fileid": "1", "filename": "a.pdf", "size": 100}],
        "folders": [],
    })
    scanner = FileScanner(client)
    files = await scanner.list_files("123456")
    assert len(files) == 1
    assert files[0]["filename"] == "a.pdf"


@pytest.mark.asyncio
async def test_list_files_list_response():
    """API 返回 list → 直接返回"""
    client = MagicMock()
    client.api.call_action = AsyncMock(return_value=[
        {"file_id": "1", "file_name": "a.pdf"},
    ])
    scanner = FileScanner(client)
    files = await scanner.list_files("123456")
    assert len(files) == 1


@pytest.mark.asyncio
async def test_list_files_empty_response():
    """API 返回空 dict → 尝试下一个 API"""
    client = MagicMock()
    client.api.call_action = AsyncMock(side_effect=[
        {"files": [], "folders": []},
        {"files": [{"fileid": "2"}], "folders": []},
    ])
    scanner = FileScanner(client)
    files = await scanner.list_files("123456")
    assert len(files) == 1


@pytest.mark.asyncio
async def test_list_files_all_api_fail():
    """所有 API 失败 → 返回空列表"""
    client = MagicMock()
    client.api.call_action = AsyncMock(side_effect=Exception("API error"))
    scanner = FileScanner(client)
    files = await scanner.list_files("123456")
    assert files == []


@pytest.mark.asyncio
async def test_list_files_api_with_1404():
    """API 返回 1404 错误 → 跳过，尝试下一个"""
    client = MagicMock()
    client.api.call_action = AsyncMock(side_effect=[
        Exception("API 1404: not supported"),
        {"files": [{"fileid": "1"}], "folders": []},
    ])
    scanner = FileScanner(client)
    files = await scanner.list_files("123456")
    assert len(files) == 1


@pytest.mark.asyncio
async def test_list_files_with_folders():
    """返回包含文件夹的响应 → 只取 files"""
    client = MagicMock()
    client.api.call_action = AsyncMock(return_value={
        "files": [{"fileid": "1"}],
        "folders": [{"id": "f1", "name": "子目录"}],
    })
    scanner = FileScanner(client)
    files = await scanner.list_files("123456")
    assert len(files) == 1


# ──────── FileScanner.get_file_url 回退 ────────

@pytest.mark.asyncio
async def test_get_file_url_fallback():
    """第一 API 失败，回退到第二 API"""
    client = MagicMock()
    client.api.call_action = AsyncMock(side_effect=[
        Exception("not supported"),
        {"url": "https://dl.example.com/file"},
    ])
    scanner = FileScanner(client)
    url = await scanner.get_file_url("123456", "file1")
    assert url == "https://dl.example.com/file"


@pytest.mark.asyncio
async def test_get_file_url_all_fail():
    """所有 URL API 失败 → 返回 None"""
    client = MagicMock()
    client.api.call_action = AsyncMock(side_effect=Exception("fail"))
    scanner = FileScanner(client)
    url = await scanner.get_file_url("123456", "file1")
    assert url is None


# ──────── GroupFileInfo edge cases ────────

def test_group_file_info_from_dict_missing_keys():
    info = GroupFileInfo.from_dict({})
    assert info.file_id == ""
    assert info.file_name == ""
    assert info.file_size == 0
    assert info.upload_time == 0
    assert info.dead_time == 0


def test_group_file_info_to_dict_roundtrip():
    info = GroupFileInfo("f1", "a.pdf", 100, 1000, 2000)
    d = info.to_dict()
    assert d["fileid"] == "f1"
    info2 = GroupFileInfo.from_dict(d)
    assert info2.file_id == info.file_id
    assert info2.file_name == info.file_name
    assert info2.file_size == info.file_size
