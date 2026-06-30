"""config_helpers, file_downloader, notify_service, naming_result, sync_result 补充测试"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from file_sync_plugin2.utils.config_helpers import ensure_list
from file_sync_plugin2.models.naming_result import NamingResult
from file_sync_plugin2.models.sync_result import SyncResult


# ──────── ensure_list ────────

def test_ensure_list_already_list():
    assert ensure_list(["a", "b"]) == ["a", "b"]


def test_ensure_list_string():
    assert ensure_list("a,b,c") == ["a", "b", "c"]


def test_ensure_list_json_array_string():
    assert ensure_list('["a", "b"]') == ["a", "b"]


def test_ensure_list_none():
    assert ensure_list(None) == []


def test_ensure_list_int():
    assert ensure_list(42) == []


def test_ensure_list_nested_json():
    """嵌套 JSON 字符串列表递归展开"""
    result = ensure_list('["a", "[\\"b\\", \\"c\\"]"]')
    assert "a" in result
    assert "b" in result
    assert "c" in result


def test_ensure_list_nested_list():
    """嵌套 Python list 递归展开"""
    result = ensure_list(["a", ["b", ["c"]]])
    assert result == ["a", "b", "c"]


def test_ensure_list_empty_string_in_list_skipped():
    result = ensure_list(["a", "", "b"])
    assert result == ["a", "b"]


def test_ensure_list_whitespace_string_skipped():
    result = ensure_list(["a", "   ", "b"])
    assert result == ["a", "b"]


# ──────── NamingResult ────────

def test_naming_result_post_init_syncs_to_shortcut():
    """errors 有值 → 自动同步到 error_type/error_reason"""
    r = NamingResult(is_valid=False, filename="bad.txt",
                     errors=[{"type": "format_error", "reason": "格式错误"}])
    assert r.error_type == "format_error"
    assert r.error_reason == "格式错误"


def test_naming_result_post_init_back_syncs_to_errors():
    """error_type 有值但 errors 空 → 自动同步到 errors"""
    r = NamingResult(is_valid=False, filename="bad.txt",
                     error_type="empty", error_reason="文件名为空")
    assert len(r.errors) == 1
    assert r.errors[0]["type"] == "empty"


def test_naming_result_add_error():
    r = NamingResult(is_valid=True, filename="ok.pdf")
    r.add_error("cat_not_found", "找不到分类")
    assert len(r.errors) == 1
    assert r.error_type == "cat_not_found"


def test_naming_result_add_error_multiple():
    r = NamingResult(is_valid=True, filename="ok.pdf",
                     error_type="first", error_reason="第一错误")
    r.add_error("second", "第二错误")
    assert len(r.errors) == 2
    assert r.error_type == "first"  # 不覆盖已有错误类型


def test_naming_result_to_legacy():
    r = NamingResult(is_valid=True, filename="test.mp4",
                     category="成片", error_type=None)
    legacy = r.to_legacy()
    assert legacy.is_valid is True
    assert legacy.filename == "test.mp4"
    assert legacy.category == "成片"


# ──────── SyncResult ────────

def test_sync_result_success():
    r = SyncResult(
        success=True, file_name="a.mp4", file_id="f1", file_size=100,
        group_id="g1", target_path="/t",
        naming_category="成片", naming_project="项目A",
        naming_version=1, naming_is_valid=True,
    )
    assert r.success is True
    assert r.failed_stage is None


def test_sync_result_failure():
    r = SyncResult(
        success=False, file_name="a.mp4", file_id="f1", file_size=100,
        group_id="g1", target_path="/t",
        failed_stage="download_network_error", failed_detail="timeout",
    )
    assert r.success is False
    assert r.failed_stage == "download_network_error"


def test_sync_result_to_dict():
    r = SyncResult(success=True, file_name="a.mp4", file_id="f1",
                   file_size=100, group_id="g1", target_path="/t")
    d = r.to_dict()
    assert d["success"] is True
    assert d["file_name"] == "a.mp4"
