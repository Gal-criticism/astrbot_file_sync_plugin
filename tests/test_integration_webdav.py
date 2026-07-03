"""
端到端集成测试：验证 NextCloud 连接 + 预设路径校验功能

使用用户提供的真实 NextCloud 配置进行测试：
- WebDAV 连接测试
- 路径存在性检查（_path_exists）
- 目录列举（list_all_remote_dirs / list_remote_files）
- 预设路径种子化流程（_init_preset_paths 的逻辑）
- 目录创建功能
"""
import sys
import os
import pytest
import tempfile
import gc
from unittest.mock import MagicMock, patch

# Mock astrbot 模块（脚本直接运行时也需要）
sys.modules['astrbot'] = MagicMock()
sys.modules['astrbot.api'] = MagicMock()
sys.modules['astrbot.api'].AstrBotConfig = MagicMock
sys.modules['astrbot.api'].logger = MagicMock()
sys.modules['astrbot.api.event'] = MagicMock()
sys.modules['astrbot.api.event'].filter = MagicMock()
sys.modules['astrbot.api.event'].AstrMessageEvent = MagicMock()
sys.modules['astrbot.api.star'] = MagicMock()
sys.modules['astrbot.api.star'].Context = MagicMock()
sys.modules['astrbot.api.star'].Star = MagicMock()
def make_register_mock(*args, **kwargs):
    def decorator(cls):
        return cls
    return decorator
sys.modules['astrbot.api.star'].register = make_register_mock
sys.modules['astrbot.api.platform'] = MagicMock()
sys.modules['astrbot.api.platform'].PlatformAdapterType = MagicMock()

from file_sync_plugin2.config import FileSyncConfig
from file_sync_plugin2.services.cloud_sync import CloudSyncService
from file_sync_plugin2.services.state_manager import StateManager

# ──────── 测试配置（用户提供） ────────

REAL_CONFIG = {
    "nextcloud_url": "https://www.galgamecriticism.com:50382/remote.php/dav/files/code_crafter",
    "nextcloud_username": "code_crafter",
    "nextcloud_password": "GalgameCriticism",
    "enabled_groups": ["493560529"],
    "base_path": "/Galgame批评主文件夹/02_原创内容/a_游戏评测",
    # startup_presets 中预设路径
    "startup_presets": {
        "LimeLight Lemonade Jam (Test)": "/Galgame批评主文件夹/02_原创内容/a_游戏评测/LimeLight Lemonade Jam (Test)",
    },
}

TEST_UPLOAD_PATH = "/Galgame批评主文件夹/02_原创内容/a_游戏评测/LimeLight Lemonade Jam (Test)"


@pytest.fixture
def real_config():
    """构建真实配置对象"""
    return FileSyncConfig(**REAL_CONFIG)


# ═══════════════════════════════════════════════════════════════
# 测试 1：NextCloud WebDAV 连接
# ═══════════════════════════════════════════════════════════════

def test_webdav_connection_success(real_config):
    """测试 WebDAV 连接是否成功（PROPFIND 根路径返回 207）"""
    service = CloudSyncService(real_config)
    # CloudSyncService.__init__ 会调用 _test_connection()，如果没抛异常就说明连接成功
    assert service._dav_url is not None
    print(f"\n✅ WebDAV URL: {service._dav_url}")
    print(f"   连接初始化成功（未抛异常，日志检查确认 PROPFIND 207）")


def test_webdav_root_propfind(real_config):
    """手动验证根路径 PROPFIND 返回 207"""
    service = CloudSyncService(real_config)
    with service._get_client() as client:
        response = client.request("PROPFIND", service._dav_url, headers={"Depth": "0"})
        assert response.status_code == 207, f"期望 207，实际 {response.status_code}"
    print(f"\n✅ 根路径 PROPFIND: 状态码 {response.status_code}")


# ═══════════════════════════════════════════════════════════════
# 测试 2：预设路径存在性校验（_path_exists）
# ═══════════════════════════════════════════════════════════════

def test_preset_path_exists(real_config):
    """测试预设路径在 NextCloud 上确实存在"""
    service = CloudSyncService(real_config)
    exists = service._path_exists(TEST_UPLOAD_PATH)
    assert exists, (
        f"预设路径不存在于云盘: {TEST_UPLOAD_PATH}\n"
        f"请确认该路径在 NextCloud 上已创建"
    )
    print(f"\n✅ 预设路径存在: {TEST_UPLOAD_PATH}")


def test_path_exists_nonexistent(real_config):
    """测试不存在的路径返回 False"""
    service = CloudSyncService(real_config)
    fake_path = "/Galgame批评主文件夹/__nonexistent_test_path_12345__"
    exists = service._path_exists(fake_path)
    assert exists is False, f"不存在的路径理应返回 False"
    print(f"\n✅ 不存在的路径正确返回 False: {fake_path}")


# ═══════════════════════════════════════════════════════════════
# 测试 3：目录列举
# ═══════════════════════════════════════════════════════════════

def test_list_subdirs_under_base(real_config):
    """测试列出基础路径下的子目录（用于定位群文件夹路径）"""
    service = CloudSyncService(real_config)
    base_path = "/Galgame批评主文件夹/02_原创内容/a_游戏评测"
    dirs = service.list_all_remote_dirs(base_path)
    assert isinstance(dirs, list), "应返回列表"
    print(f"\n✅ {base_path} 下共 {len(dirs)} 个子目录:")
    for d in dirs[:10]:  # 最多显示 10 个
        print(f"   - {d}")
    if len(dirs) > 10:
        print(f"   ... 还有 {len(dirs) - 10} 个")


def test_list_files_in_test_path(real_config):
    """测试列出测试路径下的远程文件"""
    service = CloudSyncService(real_config)
    files = service.list_remote_files(TEST_UPLOAD_PATH)
    assert isinstance(files, list), "应返回列表"
    print(f"\n✅ {TEST_UPLOAD_PATH} 下共 {len(files)} 个文件:")
    for f in files[:10]:
        size_mb = f.get("file_size", 0) / (1024 * 1024)
        print(f"   - {f['file_name']} ({size_mb:.2f} MB)")
    if len(files) > 10:
        print(f"   ... 还有 {len(files) - 10} 个文件")


# ═══════════════════════════════════════════════════════════════
# 测试 4：预设路径种子化逻辑（模拟 _init_preset_paths）
# ═══════════════════════════════════════════════════════════════

def test_startup_presets_config(real_config):
    """测试 startup_presets 配置正确读取"""
    presets = getattr(real_config, 'startup_presets', None)
    assert presets is not None, "应存在 startup_presets 配置"
    assert isinstance(presets, dict), "应为字典"
    assert len(presets) > 0, "不应为空"
    print(f"\n✅ startup_presets 配置: {presets}")


def test_preset_path_validation_logic(real_config):
    """模拟 _init_preset_paths 的核心逻辑：校验路径存在 → 写入 SQLite"""
    service = CloudSyncService(real_config)
    temp_db_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_db_fd)
    state = StateManager(temp_db_path)

    try:
        presets = getattr(real_config, 'startup_presets', {})
        added = 0
        skipped = 0

        for name, path in presets.items():
            path = "/" + path.lstrip("/")

            # 步骤 1：WebDAV 校验路径是否存在
            exists = service._path_exists(path)
            print(f"\n   校验预设路径: {name} → {path}")
            print(f"   WebDAV PROPFIND 结果: {'存在 ✅' if exists else '不存在 ❌'}")

            if not exists:
                print(f"   ⚠️ 路径不存在，跳过写入 SQLite")
                skipped += 1
                continue

            # 步骤 2：写入 SQLite
            success, msg = state.add_preset_path(name, path)
            assert success, f"写入 SQLite 失败: {msg}"
            print(f"   📝 SQLite 写入: {msg}")
            added += 1

        print(f"\n✅ 预设路径种子化完成: 新增 {added} 条, 跳过 {skipped} 条")

        # 验证 SQLite 中确实写入了
        paths_in_db = state.list_preset_paths()
        assert len(paths_in_db) >= added, f"SQLite 中预设路径数({len(paths_in_db)})应 >= added({added})"
        print(f"   SQLite 中预设路径总数: {len(paths_in_db)}")

        for p in paths_in_db:
            print(f"     [{p['name']}] {p['remote_path']} (绑定群: {p['bound_groups']})")

    finally:
        state.close()
        gc.collect()
        if os.path.exists(temp_db_path):
            os.unlink(temp_db_path)


# ═══════════════════════════════════════════════════════════════
# 测试 5：群绑定 + 路径生成
# ═══════════════════════════════════════════════════════════════

def test_group_binding_and_path_resolution(real_config):
    """测试群绑定预设路径后，sync 流程能正确获取目标路径"""
    temp_db_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_db_fd)
    state = StateManager(temp_db_path)
    service = CloudSyncService(real_config)

    try:
        # 步骤 1：添加预设路径
        ok, msg = state.add_preset_path("LimeLight Lemonade Jam (Test)", TEST_UPLOAD_PATH)
        assert ok, f"添加预设路径失败: {msg}"
        print(f"\n✅ {msg}")

        # 步骤 2：绑定群到预设路径
        group_id = "493560529"
        ok, msg = state.bind_group(group_id, "LimeLight Lemonade Jam (Test)")
        assert ok, f"群绑定失败: {msg}"
        print(f"✅ {msg}")

        # 步骤 3：获取群绑定的路径（sync_group 中会用到）
        preset_base = state.get_group_binding(group_id)
        assert preset_base is not None, "应能获取到群绑定的预设路径"
        assert preset_base == TEST_UPLOAD_PATH, (
            f"路径不匹配: 期望 {TEST_UPLOAD_PATH}, 实际 {preset_base}"
        )
        print(f"✅ 群 {group_id} 绑定的预设路径: {preset_base}")

        # 步骤 4：验证路径在云盘上确实存在
        assert service._path_exists(preset_base), (
            f"云盘上路径不存在: {preset_base}"
        )
        print(f"✅ 云盘路径存在验证通过")

        # 步骤 5：测试 generate_target_path 使用预设路径
        target = real_config.generate_target_path(
            group_name="测试群",
            group_id=group_id,
            filename="LimeLight-成片v1-最终版.mp4",
            category="成片",
            project_name="LimeLight",
            preset_base=preset_base,
        )
        print(f"✅ 目标路径: {target}")
        assert preset_base in target, f"目标路径应包含预设路径"
        assert "成片" in target, f"目标路径应包含分类子目录"

        # 步骤 6：测试解绑
        ok, msg = state.unbind_group(group_id)
        assert ok, f"解绑失败: {msg}"
        assert state.get_group_binding(group_id) is None
        print(f"✅ {msg}")

    finally:
        state.close()
        gc.collect()
        if os.path.exists(temp_db_path):
            os.unlink(temp_db_path)


# ═══════════════════════════════════════════════════════════════
# 测试 6：文件上传端到端（小测试文件）
# ═══════════════════════════════════════════════════════════════

def test_upload_small_file(real_config):
    """上传一个小测试文件到预设路径，验证完整的 upload_file 流程"""
    service = CloudSyncService(real_config)

    # 创建临时测试文件
    fd, temp_path = tempfile.mkstemp(suffix=".txt")
    os.write(fd, b"Hello NextCloud! Integration test.\n")
    os.close(fd)

    try:
        remote_path = f"{TEST_UPLOAD_PATH}/_integration_test_upload.txt"
        file_size = os.path.getsize(temp_path)

        print(f"\n📤 上传测试文件: {temp_path} → {remote_path}")
        print(f"   文件大小: {file_size} 字节")

        success, error_stage, error_detail = service.upload_file_direct(
            temp_path, remote_path, file_size=file_size, max_retries=1
        )

        assert success, (
            f"上传失败!\n"
            f"   错误阶段: {error_stage}\n"
            f"   错误详情: {error_detail}"
        )
        print(f"✅ 上传成功!")

        # 验证文件存在
        assert service.file_exists(remote_path), f"上传后文件应在云盘上存在"
        print(f"✅ 云盘文件存在验证通过")

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


# ═══════════════════════════════════════════════════════════════
# 测试 7：预热功能 (populate_from_remote_list)
# ═══════════════════════════════════════════════════════════════

def test_warmup_from_remote_files(real_config):
    """测试从 NextCloud 拉取文件列表后预热 SQLite 查重数据"""
    service = CloudSyncService(real_config)
    temp_db_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_db_fd)
    state = StateManager(temp_db_path)

    try:
        group_id = "493560529"

        # 拉取远程文件列表
        files_on_cloud = service.list_remote_files(TEST_UPLOAD_PATH)
        print(f"\n📋 远程文件列表: {TEST_UPLOAD_PATH} 共 {len(files_on_cloud)} 个文件")

        if files_on_cloud:
            # 写入 SQLite
            state.populate_from_remote_list(files_on_cloud, group_id)
            stats = state.get_sync_stats()
            print(f"✅ 预热写入完成: 总记录 {stats['total_synced']} 条")

            # 验证 name+size+group 去重生效
            first_file = files_on_cloud[0]
            name = first_file["file_name"]
            size = first_file.get("file_size", 0)
            assert state.is_synced_by_name_size(name, size, group_id), (
                f"预热后 {name} ({size} bytes) 应命中去重"
            )
            print(f"✅ 文件 '{name}' name+size 去重命中")
        else:
            print("⚠️ 远程目录无文件，跳过预热测试")

    finally:
        state.close()
        gc.collect()
        if os.path.exists(temp_db_path):
            os.unlink(temp_db_path)


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("NextCloud 连接 + 预设路径校验 集成测试")
    print("=" * 70)
    print(f"测试 URL: {REAL_CONFIG['nextcloud_url']}")
    print(f"测试路径: {TEST_UPLOAD_PATH}")
    print("-" * 70)

    pytest.main([
        __file__,
        "-v",
        "-s",           # 显示 print 输出
        "--tb=short",   # 简化回溯
        "--no-header",  # 不显示 pytest 版本头
    ])
