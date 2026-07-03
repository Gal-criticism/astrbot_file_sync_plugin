"""测试文件上传事件 → 即时同步全流程

覆盖场景：
1. 命名合规 → 即时同步到网盘 + 发送成功消息
2. 命名合规（旧格式 deprecated）→ 即时同步 + 旧格式提醒
3. 命名不合规 → @提醒，不触发同步
4. 预设路径绑定 → 生成正确路径
5. 无 file_id 时跳过同步
6. file_size=0 时的下载完整性校验
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import dataclass, field
from typing import List, Optional, Any
import sys
import types
import logging


# ===== 预 Mock 整个 astrbot 模块树（覆盖根 conftest 的 MagicMock）=====
# 根 conftest.py 设 sys.modules['astrbot'] = MagicMock()，
# 导致 import astrbot.api.message_components 报 "not a package"。
# 这里用真实的 types.ModuleType 构建完整模块树。

def _make_module(name, **attrs):
    m = types.ModuleType(name)
    m.__path__ = []
    m.__package__ = name
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# 创建 astrbot 包树
# 注意：不覆盖 astrbot.api.star — root conftest 已设 Star=MockStar

_event_mod = _make_module("astrbot.api.event",
    filter=MagicMock(),
    AstrMessageEvent=MagicMock,
)

_platform_mod = _make_module("astrbot.api.platform",
    PlatformAdapterType=MagicMock(),
)

_api_mod = _make_module("astrbot.api",
    logger=logging.getLogger("astrbot"),
    AstrBotConfig=MagicMock,
    event=_event_mod,
    platform=_platform_mod,
)

_astrbot_mod = _make_module("astrbot", api=_api_mod)

# 注册到 sys.modules
for _mod in [_astrbot_mod, _api_mod, _event_mod, _platform_mod]:
    sys.modules[_mod.__name__] = _mod


class MockCompModule(types.ModuleType):
    """模拟 astrbot.api.message_components"""

    class File(dict):
        """File 组件（dict 子类确保 isinstance 匹配）"""
        def __init__(self, name="", id="", size=0, file_id="", file=""):
            super().__init__()
            self.name = name
            self.id = id
            self.size = size
            self.file_id = file_id
            self.file = file

    class Plain:
        def __init__(self, text=""):
            self.text = text

    class At:
        def __init__(self, qq=""):
            self.qq = qq


_mock_comp_module = MockCompModule("astrbot.api.message_components")
_mock_comp_module.__path__ = []
_api_mod.message_components = _mock_comp_module
sys.modules["astrbot.api.message_components"] = _mock_comp_module


class MockCompModule(types.ModuleType):
    """模拟 astrbot.api.message_components"""

    class File(dict):
        """File 组件（dict 子类确保 isinstance 匹配）"""
        def __init__(self, name="", id="", size=0, file_id="", file=""):
            super().__init__()
            self.name = name
            self.id = id
            self.size = size
            self.file_id = file_id
            self.file = file

    class Plain:
        def __init__(self, text=""):
            self.text = text

    class At:
        def __init__(self, qq=""):
            self.qq = qq


_mock_comp_module = MockCompModule("message_components")
_mock_comp_module.__path__ = []
_api_mod.message_components = _mock_comp_module
sys.modules["astrbot.api.message_components"] = _mock_comp_module


# ===== Mock 消息组件（兼容无 AstrBot 环境）=====

@dataclass
class MockFileComponent:
    """模拟 AstrBot 的 File 消息组件"""
    name: str = ""
    id: str = ""
    size: int = 0
    file_id: str = ""
    file: str = ""


@dataclass
class MockPlainComponent:
    """模拟 AstrBot 的 Plain 消息组件"""
    text: str = ""


@dataclass
class MockAtComponent:
    """模拟 AstrBot 的 At 消息组件"""
    qq: str = ""


@dataclass
class MockMessageObj:
    """模拟完整的消息对象"""
    message: List[Any] = field(default_factory=list)
    raw_message: Optional[dict] = None
    group_id: str = ""


@dataclass
class MockEvent:
    """模拟 AstrMessageEvent"""
    message_obj: MockMessageObj
    sender_id: str = ""
    sender_name: str = ""
    group_id: str = ""

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_sender_name(self) -> str:
        return self.sender_name

    def get_group_id(self) -> str:
        return self.group_id

    def chain_result(self, chain):
        """模拟 event.chain_result()"""
        return chain


# ===== Fixtures =====

@pytest.fixture
def mock_comp_module(monkeypatch):
    """Mock astrbot.api.message_components"""
    import sys
    modules = {
        "File": MockFileComponent,
        "Plain": MockPlainComponent,
        "At": MockAtComponent,
    }
    mock_module = type(sys)("message_components")
    for name, cls in modules.items():
        setattr(mock_module, name, cls)
    monkeypatch.setattr("astrbot.api.message_components", mock_module)
    return mock_module


@pytest.fixture
def mock_plugin():
    """创建模拟的插件实例"""
    plugin = MagicMock()

    # 配置
    plugin.config.filename_check_enabled = True
    plugin.config.enabled_groups = ["123456"]
    plugin.config.file_type_whitelist = ["*"]
    plugin.config.base_path = "/QQ群文件"
    plugin.config.generate_target_path = MagicMock(return_value="/QQ群文件/测试群_123456/成片")
    plugin.config._extract_category_from_filename = MagicMock(return_value="成片")

    # 命名验证器
    naming_validator = MagicMock()
    plugin.naming_validator = naming_validator

    # 通知服务
    plugin.notify_service = MagicMock()
    plugin.notify_service.build_message_chain = MagicMock()

    # state_manager
    plugin.state_manager = MagicMock()
    plugin.state_manager.get_group_binding = MagicMock(return_value=None)

    # sync_uploaded_file
    plugin.sync_uploaded_file = AsyncMock()

    return plugin


@pytest.fixture
def handler(mock_plugin, mock_comp_module):
    """创建 FileEventHandler 实例"""
    from file_sync_plugin2.handlers.file_events import FileEventHandler
    return FileEventHandler(mock_plugin)


def make_result(is_valid=True, deprecated_separator=False, category="成片",
                error_type=None, error_reason=None):
    """创建模拟的 NamingResult"""
    result = MagicMock()
    result.is_valid = is_valid
    result.deprecated_separator = deprecated_separator
    result.category = category
    result.error_type = error_type
    result.error_reason = error_reason
    result.suggested_fix = None
    return result


# ===== 测试：命名合规→即时同步 =====

class TestValidNamingSync:
    """命名合规 → 即时同步场景"""

    @pytest.mark.asyncio
    async def test_valid_new_format_triggers_sync(self, handler, mock_plugin):
        """合规新格式 → 触发同步 + 成功消息"""
        mock_plugin.naming_validator.validate.return_value = make_result(is_valid=True)

        mock_plugin.sync_uploaded_file.return_value = MagicMock(
            success=True, target_path="/QQ群文件/测试群_123456/成片/文件.mp4"
        )

        event = MockEvent(
            message_obj=MockMessageObj(
                message=[MockFileComponent(name="项目A-成片v1.mp4", id="file123", size=1024)]
            ),
            sender_id="111111",
            sender_name="用户A",
            group_id="123456"
        )

        results = []
        async for r in handler.handle_file_upload(event):
            results.append(r)

        # 验证 sync_uploaded_file 被调用
        mock_plugin.sync_uploaded_file.assert_awaited_once_with(
            group_id="123456",
            file_id="file123",
            file_name="项目A-成片v1.mp4",
            file_size=1024,
            sender_id="111111",
            sender_name="用户A",
        )

        # 验证返回了同步成功消息
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_valid_sync_failure_shows_error(self, handler, mock_plugin):
        """合规新格式但同步失败 → 失败消息"""
        mock_plugin.naming_validator.validate.return_value = make_result(is_valid=True)

        mock_sync_result = MagicMock(success=False, target_path="/test")
        mock_sync_result.failed_stage = "upload_http_error"
        mock_sync_result.failed_detail = "HTTP 503: Service Unavailable"
        mock_plugin.sync_uploaded_file.return_value = mock_sync_result

        event = MockEvent(
            message_obj=MockMessageObj(
                message=[MockFileComponent(name="项目A-成片v1.mp4", id="file123", size=1024)]
            ),
            sender_id="111111",
            sender_name="用户A",
            group_id="123456"
        )

        results = []
        async for r in handler.handle_file_upload(event):
            results.append(r)

        # 验证 sync_uploaded_file 仍被调用
        mock_plugin.sync_uploaded_file.assert_awaited_once()
        # 失败消息
        assert len(results) >= 1


# ===== 测试：命名不合规→只发提醒 =====

class TestInvalidNamingNoSync:
    """命名不合规 → 只发提醒，不触发同步"""

    @pytest.mark.asyncio
    async def test_invalid_naming_no_sync(self, handler, mock_plugin):
        """命名不合规 → @提醒，不触发同步"""
        mock_plugin.naming_validator.validate.return_value = make_result(
            is_valid=False, error_type="format_error", error_reason="缺少分隔符"
        )
        mock_plugin.naming_validator.format_categories.return_value = "封面、成片、素材"

        event = MockEvent(
            message_obj=MockMessageObj(
                message=[MockFileComponent(name="乱七八糟.mp4")]
            ),
            sender_id="111111",
            sender_name="用户A",
            group_id="123456"
        )

        results = []
        async for r in handler.handle_file_upload(event):
            results.append(r)

        # 验证 sync_uploaded_file 未被调用
        mock_plugin.sync_uploaded_file.assert_not_awaited()
        # 验证 build_message_chain 被调用（@提醒）
        mock_plugin.notify_service.build_message_chain.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_category_no_sync(self, handler, mock_plugin):
        """分类不可识别 → @提醒，不触发同步"""
        mock_plugin.naming_validator.validate.return_value = make_result(
            is_valid=False, category=None, error_type="category_not_found",
            error_reason="未识别到有效分类"
        )

        event = MockEvent(
            message_obj=MockMessageObj(
                message=[MockFileComponent(name="未知文件.pdf")]
            ),
            sender_id="111111", sender_name="用户A", group_id="123456"
        )

        results = []
        async for r in handler.handle_file_upload(event):
            results.append(r)

        mock_plugin.sync_uploaded_file.assert_not_awaited()


# ===== 测试：旧格式合规→同步+温和提醒 =====

class TestDeprecatedNamingSync:
    """旧格式合规 → 同步 + 温和提醒迁移"""

    @pytest.mark.asyncio
    async def test_deprecated_triggers_sync_and_hint(self, handler, mock_plugin):
        """旧格式合规 → 触发同步 + 返回温和提醒"""
        mock_plugin.naming_validator.validate.return_value = make_result(
            is_valid=True, deprecated_separator=True, category="素材",
        )

        mock_plugin.sync_uploaded_file.return_value = MagicMock(
            success=True, target_path="/QQ群文件/测试群_123456/素材/素材--文档.jpg"
        )

        event = MockEvent(
            message_obj=MockMessageObj(
                message=[MockFileComponent(name="素材--文档.jpg", id="file456", size=2048)]
            ),
            sender_id="222222", sender_name="用户B", group_id="123456"
        )

        results = []
        async for r in handler.handle_file_upload(event):
            results.append(r)

        # 验证同步被触发
        mock_plugin.sync_uploaded_file.assert_awaited_once()
        # 至少有同步结果消息
        assert len(results) >= 1


# ===== 测试：无 file_id 跳过同步 =====

class TestMissingFileId:
    """无 file_id 时跳过同步"""

    @pytest.mark.asyncio
    async def test_no_file_id_skips_sync(self, handler, mock_plugin):
        """file_id 完全缺失时跳过即时同步"""
        mock_plugin.naming_validator.validate.return_value = make_result(is_valid=True)

        event = MockEvent(
            message_obj=MockMessageObj(
                message=[MockFileComponent(name="项目A-成片v1.mp4")]  # 无 id
            ),
            sender_id="111111", sender_name="用户A", group_id="123456"
        )

        results = []
        async for r in handler.handle_file_upload(event):
            results.append(r)

        # 验证同步未被触发
        mock_plugin.sync_uploaded_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_file_id_from_raw_message_fallback(self, handler, mock_plugin):
        """File 组件中 file_id 为空（AstrBot 反序列化后丢失），
        且 raw_message 是完整 Event dict，内部 raw_message 字段含 CQ 码 → 应回退提取"""
        mock_plugin.naming_validator.validate.return_value = make_result(is_valid=True)

        mock_plugin.sync_uploaded_file.return_value = MagicMock(
            success=True, target_path="/QQ群文件/测试群_123456/项目A/音频/LimeLight Lemonade Jam (Test)-音频-柚子粗剪_516.mp3"
        )

        # 模拟真实场景：AstrBot 中 raw_message 是整个 OneBot Event dict，
        # Event['raw_message'] 是 CQ 码字符串，内含 file_id / file_size
        event_raw = {
            "self_id": 2661244897,
            "raw_message": "[CQ:file,file=LimeLight Lemonade Jam (Test)-音频-柚子粗剪_516.mp3,file_id=/16cad4aa-20f4-4efc-97d6-6ba96fcefcd3,file_size=14547597,url=https://example.com/download]",
            "group_id": 650663256,
            "group_name": "素材整理",
        }
        event = MockEvent(
            message_obj=MockMessageObj(
                message=[MockFileComponent(name="LimeLight Lemonade Jam (Test)-音频-柚子粗剪_516.mp3")],
                raw_message=event_raw
            ),
            sender_id="111111", sender_name="用户A", group_id="123456"
        )

        results = []
        async for r in handler.handle_file_upload(event):
            results.append(r)

        # 验证 sync_uploaded_file 被调用，file_id 和 file_size 来自 CQ 码
        mock_plugin.sync_uploaded_file.assert_awaited_once()
        call_kwargs = mock_plugin.sync_uploaded_file.call_args[1]
        expected_file_id = "/16cad4aa-20f4-4efc-97d6-6ba96fcefcd3"
        assert call_kwargs["file_id"] == expected_file_id, (
            f"file_id 应为 CQ 码中的 '{expected_file_id}'，实际为 '{call_kwargs['file_id']}'"
        )
        assert call_kwargs["file_name"] == "LimeLight Lemonade Jam (Test)-音频-柚子粗剪_516.mp3"
        assert call_kwargs["file_size"] == 14547597, (
            f"file_size 应为 14547597，实际为 {call_kwargs['file_size']}"
        )

    @pytest.mark.asyncio
    async def test_cq_raw_message_without_file_id(self, handler, mock_plugin):
        """CQ 码中没有 file_id → 仍然跳过即时同步"""
        mock_plugin.naming_validator.validate.return_value = make_result(is_valid=True)

        event_raw = {
            "raw_message": "[CQ:file,file=test.mp3,file_size=12345]",
        }
        event = MockEvent(
            message_obj=MockMessageObj(
                message=[MockFileComponent(name="test.mp3")],
                raw_message=event_raw
            ),
            sender_id="111111", sender_name="用户A", group_id="123456"
        )

        results = []
        async for r in handler.handle_file_upload(event):
            results.append(r)

        mock_plugin.sync_uploaded_file.assert_not_awaited()


# ===== 测试：预设路径生成 =====

class TestPresetPath:
    """预设路径绑定下的路径生成"""

    def test_generate_target_path_with_galgame_presets(self):
        """测试用户提供的预设路径"""
        from file_sync_plugin2.config import FileSyncConfig

        config = FileSyncConfig(
            nextcloud_url="https://nc.example.com",
            nextcloud_username="user",
            nextcloud_password="pass",
            base_path="/QQ群文件",
        )

        test_cases = [
            # (filename, category, project_name, preset_base, expected_contains)
            ("我的评测-成片v1.mp4", "成片", "我的评测",
             "/Galgame批评主文件夹/02_原创内容/a_游戏评测",
             "/Galgame批评主文件夹/02_原创内容/a_游戏评测/成片"),
            ("我的评测-成片v1-工程-PR2022.zip", "成片", "我的评测",
             "/Galgame批评主文件夹/02_原创内容/a_游戏评测",
             "工程"),  # 工程子目录
            ("游戏推荐-成片v1.mp4", "成片", "游戏推荐",
             "/Galgame批评主文件夹/02_原创内容/b_游戏推荐、科普、前瞻等",
             "/b_游戏推荐"),
            ("十大汉化-素材-参考图.png", "素材", "十大汉化",
             "/Galgame批评主文件夹/02_原创内容/c_十大汉化",
             "/c_十大汉化/素材"),
            ("方桌锐评-素材-参考图.png", "素材", "方桌锐评",
             "/Galgame批评主文件夹/02_原创内容/e_方桌锐评",
             "/e_方桌锐评/素材"),
            ("我的评测-录音v1.wav", "音频", "我的评测",
             "/Galgame批评主文件夹/02_原创内容/a_游戏评测",
             "/a_游戏评测/音频"),
            ("我的评测-字幕v1.ass", "字幕", "我的评测",
             "/Galgame批评主文件夹/02_原创内容/a_游戏评测",
             "/a_游戏评测/字幕"),
        ]

        for filename, category, project_name, preset_base, expected in test_cases:
            path = config.generate_target_path(
                "测试群", "123456", filename,
                category=category, project_name=project_name,
                preset_base=preset_base,
            )
            assert expected in path, f"路径 {path} 应包含 {expected}"
            # 文件名应该在末尾
            assert path.endswith(filename), f"路径应以 {filename} 结尾，实际: {path}"

    def test_generate_target_path_without_preset(self):
        """无预设路径时回退到 base_path 格式"""
        from file_sync_plugin2.config import FileSyncConfig

        config = FileSyncConfig(
            nextcloud_url="https://nc.example.com",
            nextcloud_username="user",
            nextcloud_password="pass",
            base_path="/QQ群文件",
        )

        path = config.generate_target_path(
            "Galgame批评", "123456", "我的评测-成片v1.mp4",
            category="成片", project_name="我的评测",
        )
        # generate_target_path 返回目录路径，不含文件名
        assert "/QQ群文件/Galgame批评_123456/我的评测/成片" in path

    def test_generate_target_path_engineering_subdir(self):
        """工程后缀延伸到 成片/工程/ 子目录"""
        from file_sync_plugin2.config import FileSyncConfig

        config = FileSyncConfig(
            nextcloud_url="https://nc.example.com",
            nextcloud_username="user",
            nextcloud_password="pass",
            base_path="/QQ群文件",
        )

        path = config.generate_target_path(
            "Galgame批评", "123456", "我的评测-成片v1-工程-PR2022.zip",
            category="成片", project_name="我的评测",
            preset_base="/Galgame批评主文件夹/02_原创内容/a_游戏评测",
        )
        assert "/a_游戏评测/成片/工程/" in path
        assert path.endswith("我的评测-成片v1-工程-PR2022.zip")

    def test_generate_target_path_no_category(self):
        """无分类时回退到 path_template"""
        from file_sync_plugin2.config import FileSyncConfig

        config = FileSyncConfig(
            nextcloud_url="https://nc.example.com",
            nextcloud_username="user",
            nextcloud_password="pass",
            base_path="/QQ群文件",
        )

        path = config.generate_target_path(
            "测试群", "123456", "readme.txt",
            category=None, project_name=None,
        )
        # 无分类时回退到 path_template 即 {group_name}_{group_id}/{file_type}
        assert "/QQ群文件/测试群_123456/txt" in path

    def test_generate_target_path_with_preset_no_category(self):
        """有预设路径但无分类 → 只拼接预设+文件名"""
        from file_sync_plugin2.config import FileSyncConfig

        config = FileSyncConfig(
            nextcloud_url="https://nc.example.com",
            nextcloud_username="user",
            nextcloud_password="pass",
        )

        path = config.generate_target_path(
            "测试群", "123456", "readme.txt",
            category=None, project_name=None,
            preset_base="/Galgame批评主文件夹/02_原创内容/a_游戏评测",
        )
        # 无分类时 category=None，path 回退到 base_path + 模板格式
        # 但 preset_base 有值，需要验证
        assert path is not None


# ===== sync_uploaded_file 和 sync_group 过滤测试已移到 tests/test_sync_uploaded_file.py =====
# 此处保留该注释以避免 conftest 导入冲突


# ===== 测试：文件下载器 file_size=0 =====

class TestDownloaderFileSizeZero:
    """file_size=0 时跳过完整性校验"""

    @pytest.mark.asyncio
    async def test_download_with_size_zero(self):
        """file_size 为 0 时跳过大小校验"""
        from file_sync_plugin2.services.file_downloader import FileDownloader

        mock_client = MagicMock()
        downloader = FileDownloader(mock_client)

        # Mock get_file_url
        downloader.get_file_url = AsyncMock(return_value="https://example.com/file")

        # Mock httpx stream response
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        async def mock_aiter_bytes(chunk_size=65536):
            yield b"hello"

        mock_response.aiter_bytes = mock_aiter_bytes

        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.__aexit__ = AsyncMock(return_value=None)

        mock_http_instance = MagicMock()
        mock_http_instance.stream = MagicMock(return_value=mock_stream)
        mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
        mock_http_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("file_sync_plugin2.services.file_downloader.httpx.AsyncClient") as mock_http:
            mock_http.return_value = mock_http_instance
            success, local_path, error_stage, error_detail = await downloader.download_file(
                group_id="123456",
                file_id="file123",
                file_name="test.txt",
                file_size=0,  # 关键：未知大小
            )

        # file_size=0 时不应触发大小校验
        assert success is True
        assert local_path is not None

    @pytest.mark.asyncio
    async def test_download_with_size_zero_but_no_url(self):
        """file_size=0 且无下载链接 → 报 dweownload_no_url"""
        from file_sync_plugin2.services.file_downloader import FileDownloader

        mock_client = MagicMock()
        downloader = FileDownloader(mock_client)
        downloader.get_file_url = AsyncMock(return_value=None)

        success, local_path, error_stage, error_detail = await downloader.download_file(
            group_id="123456", file_id="file123",
            file_name="test.txt", file_size=0,
        )
        assert success is False
        assert error_stage == "download_no_url"


# ===== sync_uploaded_file 和 sync_group 过滤测试已移到 tests/test_sync_uploaded_file.py =====

