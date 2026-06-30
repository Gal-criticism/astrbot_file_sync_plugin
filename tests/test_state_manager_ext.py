"""StateManager 缺失功能测试：预设路径、群绑定、诊断日志、预热、last_sync_time"""

import pytest
import tempfile
import os
import gc
from datetime import datetime
from zoneinfo import ZoneInfo

from file_sync_plugin2.services.state_manager import StateManager
from file_sync_plugin2.models.sync_record import SyncRecord

CN_TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    gc.collect()
    try:
        if os.path.exists(path):
            os.unlink(path)
    except PermissionError:
        pass


# ──────── last_sync_time ────────

def test_get_last_sync_time_none(temp_db):
    sm = StateManager(temp_db)
    assert sm.get_last_sync_time("group1") is None


def test_update_and_get_last_sync_time(temp_db):
    sm = StateManager(temp_db)
    now = datetime.now(CN_TZ)
    sm.update_last_sync_time("group1", now)
    result = sm.get_last_sync_time("group1")
    assert result is not None
    assert abs((result - now).total_seconds()) < 1


def test_update_last_sync_time_replace(temp_db):
    sm = StateManager(temp_db)
    t1 = datetime(2026, 1, 1, tzinfo=CN_TZ)
    t2 = datetime(2026, 6, 30, tzinfo=CN_TZ)
    sm.update_last_sync_time("group1", t1)
    sm.update_last_sync_time("group1", t2)
    result = sm.get_last_sync_time("group1")
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 30


# ──────── is_synced_by_name_size ────────

def test_is_synced_by_name_size_false_when_empty(temp_db):
    sm = StateManager(temp_db)
    assert sm.is_synced_by_name_size("test.pdf", 1024, "group1") is False


def test_is_synced_by_name_size_true_after_add(temp_db):
    sm = StateManager(temp_db)
    record = SyncRecord(
        file_id="f1", file_name="test.pdf", file_size=1024,
        group_id="group1", target_path="/t", sync_time=datetime.now(CN_TZ)
    )
    sm.add_sync_record(record)
    assert sm.is_synced_by_name_size("test.pdf", 1024, "group1") is True


def test_is_synced_by_name_size_wrong_group(temp_db):
    sm = StateManager(temp_db)
    record = SyncRecord(
        file_id="f1", file_name="test.pdf", file_size=1024,
        group_id="group1", target_path="/t", sync_time=datetime.now(CN_TZ)
    )
    sm.add_sync_record(record)
    assert sm.is_synced_by_name_size("test.pdf", 1024, "group2") is False


def test_is_synced_by_name_size_wrong_size(temp_db):
    sm = StateManager(temp_db)
    record = SyncRecord(
        file_id="f1", file_name="test.pdf", file_size=1024,
        group_id="group1", target_path="/t", sync_time=datetime.now(CN_TZ)
    )
    sm.add_sync_record(record)
    assert sm.is_synced_by_name_size("test.pdf", 2048, "group1") is False


# ──────── get_sync_stats_by_group ────────

def test_get_sync_stats_by_group_empty(temp_db):
    sm = StateManager(temp_db)
    stats = sm.get_sync_stats_by_group()
    assert stats == {}


def test_get_sync_stats_by_group_after_add(temp_db):
    sm = StateManager(temp_db)
    for i in range(3):
        sm.add_sync_record(SyncRecord(
            file_id=f"f{i}", file_name="t.pdf", file_size=100,
            group_id="g1", target_path="/t", sync_time=datetime.now(CN_TZ)
        ))
    sm.add_sync_record(SyncRecord(
        file_id="f_other", file_name="t.pdf", file_size=100,
        group_id="g2", target_path="/t", sync_time=datetime.now(CN_TZ)
    ))
    stats = sm.get_sync_stats_by_group()
    assert "g1" in stats
    assert "g2" in stats
    assert stats["g1"]["synced"] == 3
    assert stats["g2"]["synced"] == 1


# ──────── get_group_stats ────────

def test_get_group_stats_nonexistent(temp_db):
    sm = StateManager(temp_db)
    stats = sm.get_group_stats("nonexistent")
    assert stats["synced"] == 0
    assert stats["pending"] == 0
    assert stats["last_sync_time"] is None


def test_get_group_stats_with_data(temp_db):
    sm = StateManager(temp_db)
    now = datetime.now(CN_TZ)
    for i in range(2):
        sm.add_sync_record(SyncRecord(
            file_id=f"f{i}", file_name=f"t{i}.pdf", file_size=100,
            group_id="g1", target_path="/t", sync_time=now
        ))
    sm.update_last_sync_time("g1", now)
    sm.add_to_retry_queue("f_retry", "r.pdf", 200, "g1", "/t", delay_seconds=0)
    stats = sm.get_group_stats("g1")
    assert stats["synced"] == 2
    assert stats["pending"] == 1
    assert stats["last_sync_time"] is not None
    assert len(stats["recent_files"]) >= 2


# ──────── populate_from_remote_list ────────

def test_populate_from_remote_list_basic(temp_db):
    sm = StateManager(temp_db)
    remote_files = [
        {"remote_path": "/path/a.pdf", "file_name": "a.pdf", "file_size": 100},
        {"remote_path": "/path/b.pdf", "file_name": "b.pdf", "file_size": 200},
    ]
    sm.populate_from_remote_list(remote_files, "group1")
    assert sm.is_synced_by_name_size("a.pdf", 100, "group1") is True
    assert sm.is_synced_by_name_size("b.pdf", 200, "group1") is True


def test_populate_from_remote_list_dedup(temp_db):
    sm = StateManager(temp_db)
    dups = [
        {"remote_path": "/a.pdf", "file_name": "a.pdf", "file_size": 100},
        {"remote_path": "/a.pdf", "file_name": "a.pdf", "file_size": 200},
    ]
    sm.populate_from_remote_list(dups, "g1")
    # INSERT OR IGNORE 会静默跳过重复 remote_path
    cnt = sm.get_group_stats("g1")["synced"]
    assert cnt == 1


def test_populate_from_remote_list_missing_size(temp_db):
    sm = StateManager(temp_db)
    files = [{"remote_path": "/a.pdf", "file_name": "a.pdf"}]
    sm.populate_from_remote_list(files, "g1")
    assert sm.is_synced_by_name_size("a.pdf", 0, "g1") is True


# ──────── 预设路径 ────────

def test_add_preset_path(temp_db):
    sm = StateManager(temp_db)
    ok, msg = sm.add_preset_path("项目A", "/客户/项目A")
    assert ok is True
    assert "已添加" in msg


def test_add_preset_path_update_existing(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    ok, msg = sm.add_preset_path("项目A", "/客户/项目A_v2")
    assert ok is True
    assert "已更新" in msg


def test_list_preset_paths_empty(temp_db):
    sm = StateManager(temp_db)
    assert sm.list_preset_paths() == []


def test_list_preset_paths_with_entries(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    sm.add_preset_path("项目B", "/客户/项目B")
    paths = sm.list_preset_paths()
    assert len(paths) == 2
    names = {p["name"] for p in paths}
    assert names == {"项目A", "项目B"}
    for p in paths:
        assert [] == p["bound_groups"]


def test_delete_preset_path(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    ok, msg = sm.delete_preset_path("项目A")
    assert ok is True
    assert sm.list_preset_paths() == []


def test_delete_preset_path_nonexistent(temp_db):
    sm = StateManager(temp_db)
    ok, msg = sm.delete_preset_path("不存在")
    assert ok is False
    assert "不存在" in msg


def test_delete_preset_path_with_binding_blocked(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    sm.bind_group("123456", "项目A")
    ok, msg = sm.delete_preset_path("项目A")
    assert ok is False
    assert "已绑定" in msg


def test_get_preset_path_by_name(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    result = sm.get_preset_path_by_name("项目A")
    assert result is not None
    assert result["name"] == "项目A"
    assert result["remote_path"] == "/客户/项目A"


def test_get_preset_path_by_name_nonexistent(temp_db):
    sm = StateManager(temp_db)
    assert sm.get_preset_path_by_name("不存在") is None


def test_get_preset_path_by_id(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    paths = sm.list_preset_paths()
    pid = paths[0]["id"]
    result = sm.get_preset_path_by_id(pid)
    assert result is not None
    assert result["name"] == "项目A"


def test_get_preset_path_by_id_nonexistent(temp_db):
    sm = StateManager(temp_db)
    assert sm.get_preset_path_by_id(999) is None


# ──────── 群绑定 ────────

def test_bind_group(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    ok, msg = sm.bind_group("123456", "项目A")
    assert ok is True
    assert "已绑定" in msg


def test_bind_group_nonexistent_path(temp_db):
    sm = StateManager(temp_db)
    ok, msg = sm.bind_group("123456", "不存在")
    assert ok is False
    assert "不存在" in msg


def test_bind_group_rebind(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    sm.add_preset_path("项目B", "/客户/项目B")
    sm.bind_group("123456", "项目A")
    ok, msg = sm.bind_group("123456", "项目B")
    assert ok is True
    binding = sm.get_group_binding("123456")
    assert binding == "/客户/项目B"


def test_unbind_group(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    sm.bind_group("123456", "项目A")
    ok, msg = sm.unbind_group("123456")
    assert ok is True
    assert sm.get_group_binding("123456") is None


def test_unbind_group_not_bound(temp_db):
    sm = StateManager(temp_db)
    ok, msg = sm.unbind_group("123456")
    assert ok is False
    assert "未绑定" in msg


def test_get_group_binding_detail(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    sm.bind_group("123456", "项目A")
    detail = sm.get_group_binding_detail("123456")
    assert detail is not None
    assert detail["name"] == "项目A"
    assert detail["remote_path"] == "/客户/项目A"
    assert "bound_at" in detail


def test_get_group_binding_detail_none(temp_db):
    sm = StateManager(temp_db)
    assert sm.get_group_binding_detail("不存在") is None


def test_get_group_binding_none(temp_db):
    sm = StateManager(temp_db)
    assert sm.get_group_binding("不存在") is None


def test_list_group_bindings_empty(temp_db):
    sm = StateManager(temp_db)
    assert sm.list_group_bindings() == []


def test_list_group_bindings_with_data(temp_db):
    sm = StateManager(temp_db)
    sm.add_preset_path("项目A", "/客户/项目A")
    sm.add_preset_path("项目B", "/客户/项目B")
    sm.bind_group("111", "项目A")
    sm.bind_group("222", "项目B")
    all_b = sm.list_group_bindings()
    assert len(all_b) == 2
    gids = {b["group_id"] for b in all_b}
    assert gids == {"111", "222"}


# ──────── 诊断日志 ────────

def test_add_and_get_diagnostic_logs(temp_db):
    sm = StateManager(temp_db)
    sm.add_diagnostic_log("sync", "同步成功", {"file": "a.pdf"})
    sm.add_diagnostic_log("skip", "跳过", {"reason": "old"})
    logs = sm.get_diagnostic_logs()
    assert len(logs) == 2
    assert logs[0]["type"] == "sync"
    assert logs[1]["type"] == "skip"


def test_get_diagnostic_logs_filter_by_type(temp_db):
    sm = StateManager(temp_db)
    sm.add_diagnostic_log("sync", "a")
    sm.add_diagnostic_log("skip", "b")
    sm.add_diagnostic_log("sync", "c")
    logs = sm.get_diagnostic_logs(log_type="sync")
    assert len(logs) == 2
    assert all(l["type"] == "sync" for l in logs)


def test_get_diagnostic_logs_limit(temp_db):
    sm = StateManager(temp_db)
    for i in range(20):
        sm.add_diagnostic_log("sync", f"msg{i}")
    logs = sm.get_diagnostic_logs(limit=5)
    assert len(logs) == 5


def test_clear_diagnostic_logs(temp_db):
    sm = StateManager(temp_db)
    sm.add_diagnostic_log("sync", "a")
    sm.add_diagnostic_log("skip", "b")
    sm.clear_diagnostic_logs()
    assert sm.get_diagnostic_logs() == []


def test_diagnostic_log_trim_to_100(temp_db):
    sm = StateManager(temp_db)
    for i in range(110):
        sm.add_diagnostic_log("sync", f"msg{i}")
    assert len(sm._diagnostic_logs) == 100
    assert sm._diagnostic_logs[0]["message"] == "msg10"


def test_diagnostic_log_data_defaults_to_empty(temp_db):
    sm = StateManager(temp_db)
    sm.add_diagnostic_log("info", "no data")
    logs = sm.get_diagnostic_logs()
    assert logs[0]["data"] == {}


# ──────── close ────────

def test_close_releases_connection(temp_db):
    sm = StateManager(temp_db)
    sm.add_sync_record(SyncRecord(
        file_id="f1", file_name="t.pdf", file_size=1,
        group_id="g1", target_path="/t", sync_time=datetime.now(CN_TZ)
    ))
    sm.close()
    assert sm._conn is None
