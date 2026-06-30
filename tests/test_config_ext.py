"""config.py 补充测试：get_next_delay_seconds, _extract_category_from_filename 等"""
import pytest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from file_sync_plugin2.config import FileSyncConfig, validate_config

CN_TZ = ZoneInfo("Asia/Shanghai")


def _make_config(**overrides):
    defaults = dict(
        nextcloud_url="https://nc.example.com",
        nextcloud_username="user",
        nextcloud_password="pass",
        enabled_groups=["123456"],
    )
    defaults.update(overrides)
    return FileSyncConfig(**defaults)


# ──────── validate_sync_time_points ────────

def test_validate_sync_time_points_valid():
    cfg = _make_config(sync_time_points=["08:00", "12:00", "23:59"])
    assert cfg.sync_time_points == ["08:00", "12:00", "23:59"]


def test_validate_sync_time_points_invalid_ignored():
    cfg = _make_config(sync_time_points=["08:00", "invalid", "25:00", "12:00"])
    assert cfg.sync_time_points == ["08:00", "12:00"]


def test_validate_sync_time_points_empty():
    cfg = _make_config(sync_time_points=[])
    assert cfg.sync_time_points == []


def test_validate_sync_time_points_none():
    cfg = _make_config()  # sync_time_points default is []
    assert cfg.sync_time_points == []


# ──────── has_time_points ────────

def test_has_time_points_true():
    cfg = _make_config(sync_time_points=["08:00"])
    assert cfg.has_time_points() is True


def test_has_time_points_false():
    cfg = _make_config(sync_time_points=[])
    assert cfg.has_time_points() is False


# ──────── get_next_delay_seconds ────────

def test_get_next_delay_interval_mode():
    """不使用时间点 → 使用 sync_interval_minutes"""
    cfg = _make_config(sync_interval_minutes=60)
    now = datetime(2026, 6, 30, 10, 0, tzinfo=CN_TZ)
    delay = cfg.get_next_delay_seconds(now)
    assert delay == 3600


def test_get_next_delay_with_time_point_later_today():
    """今天还有时间点 → 返回差值"""
    cfg = _make_config(sync_time_points=["12:00"])
    now = datetime(2026, 6, 30, 10, 0, tzinfo=CN_TZ)
    delay = cfg.get_next_delay_seconds(now)
    assert delay == 2 * 3600  # 12:00 - 10:00 = 2h


def test_get_next_delay_nearest_time_point():
    """多个时间点，取最近的下一个"""
    cfg = _make_config(sync_time_points=["08:00", "12:00", "18:00"])
    now = datetime(2026, 6, 30, 11, 0, tzinfo=CN_TZ)
    delay = cfg.get_next_delay_seconds(now)
    assert delay == 3600  # 12:00 - 11:00


def test_get_next_delay_crosses_midnight():
    """今天的时间点都已过 → 到明天第一个"""
    cfg = _make_config(sync_time_points=["08:00", "12:00"])
    now = datetime(2026, 6, 30, 15, 0, tzinfo=CN_TZ)
    delay = cfg.get_next_delay_seconds(now)
    assert delay == 17 * 3600  # 08:00 tomorrow = 17h later


# ──────── get_category_subdir ────────

def test_get_category_subdir_standard():
    cfg = _make_config()
    assert cfg.get_category_subdir("封面") == "封面"
    assert cfg.get_category_subdir("成片") == "成片"
    assert cfg.get_category_subdir("素材") == "素材"
    assert cfg.get_category_subdir("音频") == "音频"
    assert cfg.get_category_subdir("字幕") == "字幕"
    assert cfg.get_category_subdir("数据组测试") == "数据组测试"


def test_get_category_subdir_custom():
    cfg = _make_config(naming_extra_categories='{"其他分类": {"extensions": ["txt"]}}')
    assert cfg.get_category_subdir("其他分类") == "其他分类"


def test_get_category_subdir_fallback():
    cfg = _make_config()
    assert cfg.get_category_subdir("未知分类") == "其他"


# ──────── get_file_type ────────

def test_get_file_type():
    assert FileSyncConfig.get_file_type("test.pdf") == "pdf"
    assert FileSyncConfig.get_file_type("test.PDF") == "pdf"
    assert FileSyncConfig.get_file_type("test") == "other"
    assert FileSyncConfig.get_file_type("a.b.c") == "c"


# ──────── _extract_category_from_filename ────────

def test_extract_category_new_format():
    cfg = _make_config()
    assert cfg._extract_category_from_filename("项目A-成片v1.mp4") == "成片"
    assert cfg._extract_category_from_filename("项目A-封面.png") == "封面"


def test_extract_category_deprecated_format():
    cfg = _make_config()
    assert cfg._extract_category_from_filename("素材--参考图.png") == "素材"


def test_extract_category_unknown():
    cfg = _make_config()
    assert cfg._extract_category_from_filename("随便起的文件名.txt") is None


def test_extract_category_no_extension():
    cfg = _make_config()
    assert cfg._extract_category_from_filename("项目A-成片v1") == "成片"


# ──────── get_naming_extra_categories ────────

def test_get_naming_extra_categories_default():
    cfg = _make_config()
    assert cfg.get_naming_extra_categories() == {}


def test_get_naming_extra_categories_parsed():
    cfg = _make_config(naming_extra_categories='{"文档": {"extensions": ["pdf"]}}')
    result = cfg.get_naming_extra_categories()
    assert "文档" in result
    assert result["文档"]["extensions"] == ["pdf"]


def test_get_naming_extra_categories_invalid_json():
    cfg = _make_config(naming_extra_categories="not json")
    assert cfg.get_naming_extra_categories() == {}


# ──────── get_filename_categories ────────

def test_get_filename_categories_default():
    cfg = _make_config()
    assert cfg.get_filename_categories() == {}


# ──────── get_preset_paths deprecated ────────

def test_get_preset_paths_deprecated():
    cfg = _make_config()
    assert cfg.get_preset_paths() == {}


def test_have_preset_paths_deprecated():
    cfg = _make_config()
    assert cfg.have_preset_paths() is False


# ──────── is_file_type_allowed ────────

def test_is_file_type_allowed_wildcard():
    cfg = _make_config(file_type_whitelist=["*"])
    assert cfg.is_file_type_allowed("anything.txt") is True


def test_is_file_type_allowed_specific():
    cfg = _make_config(file_type_whitelist=["pdf", "mp4"])
    assert cfg.is_file_type_allowed("doc.pdf") is True
    assert cfg.is_file_type_allowed("video.mp4") is True
    assert cfg.is_file_type_allowed("image.jpg") is False


def test_is_file_type_allowed_case_insensitive():
    cfg = _make_config(file_type_whitelist=["PDF"])
    assert cfg.is_file_type_allowed("doc.pdf") is True
    assert cfg.is_file_type_allowed("doc.PDF") is True


# ──────── generate_target_path extra cases ────────

def test_generate_target_path_no_category():
    """无分类时使用 path_template"""
    cfg = _make_config(path_template="{group_name}_{group_id}/{file_type}")
    path = cfg.generate_target_path("测试群", "123456", "report.pdf")
    assert "测试群_123456" in path
    assert "pdf" in path


def test_generate_target_path_preset_with_category():
    """预设路径 + 分类 → 使用子目录"""
    cfg = _make_config()
    path = cfg.generate_target_path(
        "测试群", "123456", "项目A-成片v1.mp4",
        category="成片", project_name="项目A",
        preset_base="/客户/项目A"
    )
    assert "/客户/项目A" in path
    assert "成片" in path
    assert "项目A-成片v1.mp4" in path
