"""SyncExecutor 单文件同步编排单元测试"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from file_sync_plugin2.services.sync_executor import SyncExecutor
from file_sync_plugin2.config import FileSyncConfig
from file_sync_plugin2.models.sync_result import SyncResult


@pytest.fixture
def mock_config():
    return FileSyncConfig(
        nextcloud_url="https://nc.example.com",
        nextcloud_username="user",
        nextcloud_password="pass",
        enabled_groups=["123456"],
    )


def _setup_plugin(mock_config, platform_avail=True, naming_result=None):
    """构造 mock plugin"""
    plugin = MagicMock()
    plugin.config = mock_config
    plugin.cloud_sync = MagicMock()
    plugin.naming_validator = MagicMock()
    plugin.context = MagicMock()

    if naming_result is not None:
        plugin.naming_validator.parse.return_value = naming_result

    if platform_avail:
        platform = MagicMock()
        platform.get_client = MagicMock(return_value=MagicMock())
        plugin.context.get_platform.return_value = platform
    else:
        plugin.context.get_platform.return_value = None
    return plugin


@pytest.mark.asyncio
async def test_sync_single_file_success(mock_config):
    """完整流程：下载成功 → 上传成功 → 返回 success=True"""
    naming = MagicMock(category="成片", project_name="项目A", version=1, is_valid=True, error_reason=None)
    plugin = _setup_plugin(mock_config, naming_result=naming)

    executor = SyncExecutor(plugin)
    # 手动 mock 内部的 FileDownloader
    with patch("file_sync_plugin2.services.file_downloader.FileDownloader") as MockDL:
        dl = MagicMock()
        MockDL.return_value = dl
        dl.download_file = AsyncMock(return_value=(True, "/tmp/test.mp4", None, None))
        plugin.cloud_sync.upload_file_direct.return_value = (True, None, None)

        result = await executor.sync_single_file(
            group_id="123456", target_path="/QQ群文件/test",
            file_id="file001", file_name="项目A-成片v1.mp4", file_size=1024
        )

    assert result.success is True
    assert result.failed_stage is None
    assert result.naming_category == "成片"
    assert result.naming_project == "项目A"
    plugin.cloud_sync.upload_file_direct.assert_called_once()


@pytest.mark.asyncio
async def test_sync_single_file_no_platform(mock_config):
    """无法获取QQ平台 → 返回 sync_no_platform"""
    naming = MagicMock(category=None, project_name=None, version=None, is_valid=None, error_reason=None)
    plugin = _setup_plugin(mock_config, platform_avail=False, naming_result=naming)

    executor = SyncExecutor(plugin)
    result = await executor.sync_single_file(
        group_id="123456", target_path="/test",
        file_id="file001", file_name="test.mp4", file_size=1024
    )

    assert result.success is False
    assert result.failed_stage == "sync_no_platform"


@pytest.mark.asyncio
async def test_sync_single_file_download_failure(mock_config):
    """下载失败 → 返回 download 错误阶段"""
    naming = MagicMock(category="素材", project_name="项目B", version=None, is_valid=True, error_reason=None)
    plugin = _setup_plugin(mock_config, naming_result=naming)

    executor = SyncExecutor(plugin)
    with patch("file_sync_plugin2.services.file_downloader.FileDownloader") as MockDL:
        MockDL.return_value.download_file = AsyncMock(
            return_value=(False, None, "download_network_error", "Connection refused")
        )
        result = await executor.sync_single_file(
            group_id="123456", target_path="/test",
            file_id="file001", file_name="test.mp4", file_size=1024
        )

    assert result.success is False
    assert result.failed_stage == "download_network_error"
    assert result.failed_detail == "Connection refused"


@pytest.mark.asyncio
async def test_sync_single_file_upload_failure(mock_config):
    """下载成功但上传失败 → 返回 upload 错误 + cleanup 被调用"""
    naming = MagicMock(category="成片", project_name="项目C", version=2, is_valid=True, error_reason=None)
    plugin = _setup_plugin(mock_config, naming_result=naming)

    executor = SyncExecutor(plugin)
    with patch("file_sync_plugin2.services.file_downloader.FileDownloader") as MockDL:
        dl = MagicMock()
        MockDL.return_value = dl
        dl.download_file = AsyncMock(return_value=(True, "/tmp/test.mp4", None, None))
        plugin.cloud_sync.upload_file_direct.return_value = (
            False, "upload_http_error", "HTTP 500: Server Error"
        )

        result = await executor.sync_single_file(
            group_id="123456", target_path="/test",
            file_id="file001", file_name="项目C-成片v2.mp4", file_size=2048
        )

    assert result.success is False
    assert result.failed_stage == "upload_http_error"
    assert "HTTP 500" in result.failed_detail
    dl.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_sync_single_file_exception(mock_config):
    """下载阶段抛出异常 → 返回 sync_exception + cleanup 被调用"""
    naming = MagicMock(category=None, project_name=None, version=None, is_valid=None, error_reason=None)
    plugin = _setup_plugin(mock_config, naming_result=naming)

    executor = SyncExecutor(plugin)
    with patch("file_sync_plugin2.services.file_downloader.FileDownloader") as MockDL:
        dl = MagicMock()
        MockDL.return_value = dl
        dl.download_file = AsyncMock(side_effect=RuntimeError("连接中断"))

        result = await executor.sync_single_file(
            group_id="123456", target_path="/test",
            file_id="file001", file_name="test.mp4", file_size=1024
        )

    assert result.success is False
    assert result.failed_stage == "sync_exception"
    assert "RuntimeError" in result.failed_detail
    dl.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_sync_single_file_no_naming_validator(mock_config):
    """没有命名验证器 → 降级结果，仍然继续同步"""
    plugin = _setup_plugin(mock_config)
    plugin.naming_validator = None  # 清除验证器

    executor = SyncExecutor(plugin)
    with patch("file_sync_plugin2.services.file_downloader.FileDownloader") as MockDL:
        dl = MagicMock()
        MockDL.return_value = dl
        dl.download_file = AsyncMock(return_value=(True, "/tmp/test.mp4", None, None))
        plugin.cloud_sync.upload_file_direct.return_value = (True, None, None)

        result = await executor.sync_single_file(
            group_id="123456", target_path="/test",
            file_id="file001", file_name="test.mp4", file_size=1024
        )

    assert result.success is True
    assert result.naming_category is None


@pytest.mark.asyncio
async def test_sync_single_file_result_fields(mock_config):
    """返回的 SyncResult 包含命名分析的所有字段"""
    naming = MagicMock(category="音频", project_name="项目D", version=3, is_valid=True, error_reason=None)
    plugin = _setup_plugin(mock_config, naming_result=naming)

    executor = SyncExecutor(plugin)
    with patch("file_sync_plugin2.services.file_downloader.FileDownloader") as MockDL:
        dl = MagicMock()
        MockDL.return_value = dl
        dl.download_file = AsyncMock(return_value=(True, "/tmp/test.flac", None, None))
        plugin.cloud_sync.upload_file_direct.return_value = (True, None, None)

        result = await executor.sync_single_file(
            group_id="999", target_path="/path", file_id="f999",
            file_name="项目D-音频v3.flac", file_size=5000
        )

    assert isinstance(result, SyncResult)
    assert result.group_id == "999"
    assert result.target_path == "/path"
    assert result.file_id == "f999"
    assert result.file_name == "项目D-音频v3.flac"
    assert result.file_size == 5000
    assert result.naming_category == "音频"
    assert result.naming_project == "项目D"
    assert result.naming_version == 3
    assert result.naming_is_valid is True
