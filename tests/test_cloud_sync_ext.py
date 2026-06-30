"""cloud_sync 上传错误路径测试：重试、超时、网络错误、文件不存等

使用 patch on _get_client 代替 @patch httpx，避免 httpx 异常类被 mock 破坏。
"""
import pytest
import tempfile
import os
from unittest.mock import MagicMock

from file_sync_plugin2.services.cloud_sync import CloudSyncService
from file_sync_plugin2.config import FileSyncConfig


@pytest.fixture
def mock_config():
    return FileSyncConfig(
        nextcloud_url="https://nc.example.com",
        nextcloud_username="user",
        nextcloud_password="pass",
        enabled_groups=["123456"],
    )


@pytest.fixture
def temp_file():
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.write(fd, b"x" * 1000)
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def _make_client():
    """构造 mock httpx 客户端（带 context manager）"""
    c = MagicMock()
    c.__enter__ = MagicMock(return_value=c)
    c.__exit__ = MagicMock(return_value=False)
    return c


def _setup_upload_test(mock_config, file_exists=True, mkcol_ok=True):
    """创建 CloudSyncService 并替换 _get_client

    Args:
        file_exists: 远程文件是否存在
        mkcol_ok: 目录创建是否成功
    Returns:
        (service, mock_client)
    """
    service = CloudSyncService(mock_config)
    mock_client = _make_client()

    def req_side(method, url, **kwargs):
        r = MagicMock()
        if method == "MKCOL":
            r.status_code = 201 if mkcol_ok else 500
        elif method == "PROPFIND":
            r.status_code = 207 if file_exists else 404
        else:
            r.status_code = 404
        return r
    mock_client.request.side_effect = req_side
    service._get_client = lambda timeout=300: mock_client
    return service, mock_client


# ──────── 上传错误路径 ────────

def test_upload_local_file_missing(mock_config):
    """本地文件不存 → upload_local_missing"""
    service = CloudSyncService(mock_config)
    mock_client = _make_client()
    service._get_client = lambda timeout=300: mock_client
    result = service.upload_file_direct("/nonexistent/file.mp4", "/test/file.mp4", 100)
    assert result[0] is False
    assert result[1] == "upload_local_missing"


def test_upload_path_without_slash_auto_fix(mock_config, temp_file):
    """remote_path 缺少前导 / 自动补齐"""
    service, mock_client = _setup_upload_test(mock_config)
    put_resp = MagicMock()
    put_resp.status_code = 201
    mock_client.put.return_value = put_resp

    service = CloudSyncService(mock_config)
    mock_client = _make_client()
    service._get_client = lambda timeout=300: mock_client
    mock_client.request.return_value = MagicMock(status_code=201)
    mock_put = MagicMock(status_code=201)
    mock_client.put.return_value = mock_put

    success, err, detail = service.upload_file_direct(temp_file, "test/file.mp4", 100)
    assert success is True


def test_upload_mkdir_failure(mock_config, temp_file):
    """目录创建失败 → upload_mkdir_failed"""
    service, mock_client = _setup_upload_test(mock_config, file_exists=False, mkcol_ok=False)
    success, err, detail = service.upload_file_direct(temp_file, "/test/f.mp4", 100)
    assert success is False
    assert err == "upload_mkdir_failed"


def test_upload_invalid_path_no_slash(mock_config, temp_file):
    """remote_path 无 / 的情况"""
    service = CloudSyncService(mock_config)
    mock_client = _make_client()
    service._get_client = lambda timeout=300: mock_client
    mock_client.request.return_value = MagicMock(status_code=404)
    success, err, detail = service.upload_file_direct(temp_file, "nopath", 100)
    assert success is False


def test_upload_timeout_no_more_retry(mock_config, temp_file):
    """超时后重试耗尽 → upload_timeout"""
    service, mock_client = _setup_upload_test(mock_config)
    mock_client.put.side_effect = __import__("httpx").TimeoutException("timeout")

    success, err, detail = service.upload_file_direct(temp_file, "/test/f.mp4", 100, max_retries=1)
    assert success is False
    assert err == "upload_timeout"


def test_upload_http_error_no_more_retry(mock_config, temp_file):
    """HTTP 错误后重试耗尽 → upload_network_error"""
    service, mock_client = _setup_upload_test(mock_config)
    mock_client.put.side_effect = __import__("httpx").HTTPError("connection failed")

    success, err, detail = service.upload_file_direct(temp_file, "/test/f.mp4", 100, max_retries=2)
    assert success is False
    assert err == "upload_network_error"


def test_upload_connection_error(mock_config, temp_file):
    """ConnectionError → upload_network_error"""
    service, mock_client = _setup_upload_test(mock_config)
    mock_client.put.side_effect = ConnectionError("refused")

    success, err, detail = service.upload_file_direct(temp_file, "/test/f.mp4", 100, max_retries=1)
    assert success is False
    assert err == "upload_network_error"
    assert "refused" in detail.lower()


def test_upload_unknown_exception(mock_config, temp_file):
    """未知异常 → upload_unknown"""
    service, mock_client = _setup_upload_test(mock_config)
    mock_client.put.side_effect = RuntimeError("unexpected")

    success, err, detail = service.upload_file_direct(temp_file, "/test/f.mp4", 100)
    assert success is False
    assert err == "upload_unknown"


def test_upload_retry_then_success(mock_config, temp_file):
    """首次超时，重试成功"""
    service, mock_client = _setup_upload_test(mock_config)
    call_count = [0]

    def put_side(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            raise __import__("httpx").TimeoutException("timeout")
        return MagicMock(status_code=201)
    mock_client.put.side_effect = put_side

    success, err, detail = service.upload_file_direct(temp_file, "/test/f.mp4", 100, max_retries=2)
    assert success is True
    assert call_count[0] == 2


def test_upload_http_500_retry_exhausted(mock_config, temp_file):
    """HTTP 500 重试耗尽 → upload_http_error"""
    service, mock_client = _setup_upload_test(mock_config)
    bad_resp = MagicMock(status_code=500, text="Internal Server Error")
    mock_client.put.return_value = bad_resp

    success, err, detail = service.upload_file_direct(temp_file, "/test/f.mp4", 100, max_retries=1)
    assert success is False
    assert err == "upload_http_error"
    assert "500" in detail


def test_upload_204_success(mock_config, temp_file):
    """PUT 返回 204 也视为成功"""
    service, mock_client = _setup_upload_test(mock_config)
    mock_client.put.return_value = MagicMock(status_code=204)

    success, err, detail = service.upload_file_direct(temp_file, "/test/f.mp4", 100)
    assert success is True


# ──────── list_all_remote_dirs ────────

def test_list_all_remote_dirs(mock_config):
    """列出所有远程目录不崩溃"""
    service = CloudSyncService(mock_config)
    mock_client = _make_client()
    service._get_client = lambda timeout=300: mock_client

    def req_side(method, url, **kwargs):
        r = MagicMock(status_code=207)
        r.text = f"""<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
            <d:response><d:href>/remote.php/dav/files/user/</d:href>
                <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
            <d:response><d:href>/remote.php/dav/files/user/a/</d:href>
                <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
        </d:multistatus>"""
        return r
    mock_client.request.side_effect = req_side

    dirs = service.list_all_remote_dirs("/test")
    assert isinstance(dirs, list)


# ──────── download_file error ────────

def test_download_file_exception(mock_config, temp_file):
    """下载时抛异常 → 返回 False"""
    service = CloudSyncService(mock_config)
    mock_client = _make_client()
    service._get_client = lambda timeout=300: mock_client
    mock_client.get.side_effect = RuntimeError("connection lost")

    result = service.download_file("/test/f.mp4", temp_file)
    assert result is False


# ──────── _path_exists exception ────────

def test_path_exists_exception(mock_config):
    """_path_exists 抛出异常返回 False"""
    service = CloudSyncService(mock_config)
    mock_client = _make_client()
    service._get_client = lambda timeout=300: mock_client
    mock_client.request.side_effect = ConnectionError("fail")

    assert service.file_exists("/test") is False
