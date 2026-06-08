"""
模拟 AstrBot 消息组件，在没有 AstrBot 环境的情况下测试消息解析逻辑
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from file_sync_plugin2.services.filename_checker import FilenameChecker
from file_sync_plugin2.services.notify_service import NotifyService
from file_sync_plugin2.models.validation_result import FileValidationResult
from dataclasses import dataclass, field
from typing import List, Optional, Any


# ===== Mock AstrBot 消息组件 =====

@dataclass
class MockFileComponent:
    """模拟 AstrBot 的 File 消息组件"""
    name: str = ""
    file_id: str = ""
    size: int = 0


@dataclass
class MockPlainComponent:
    """模拟 AstrBot 的 Plain 消息组件"""
    text: str = ""


@dataclass
class MockAtComponent:
    """模拟 AstrBot 的 At 消息组件"""
    qq: str = ""


@dataclass
class MockSender:
    """模拟发送者信息"""
    user_id: str = ""
    nickname: str = ""
    card: str = ""


@dataclass
class MockMessage:
    """模拟消息链"""
    chain: List[Any] = field(default_factory=list)


@dataclass
class MockRawMessage:
    """模拟原始消息"""
    data: dict = field(default_factory=dict)


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


# ===== 测试函数 =====

def extract_filename_from_event(event) -> Optional[str]:
    """从事件中提取文件名（模拟 main.py 中的逻辑）"""
    # 检查消息中是否包含 File 组件
    for seg in event.message_obj.message:
        if isinstance(seg, MockFileComponent):
            return seg.name

    # 尝试从 raw_message 获取
    raw = event.message_obj.raw_message
    if raw and isinstance(raw, dict):
        file_data = raw.get('file', {})
        if isinstance(file_data, dict):
            return file_data.get('name')
        return raw.get('filename')

    return None


def check_file_in_message(event) -> bool:
    """检查消息中是否包含 File 组件"""
    for seg in event.message_obj.message:
        if isinstance(seg, MockFileComponent):
            return True
    return False


def process_file_upload(event, checker: FilenameChecker, notify_service: NotifyService) -> Optional[dict]:
    """模拟处理文件上传的完整流程"""
    # 1. 检查是否有文件
    if not check_file_in_message(event):
        return None

    # 2. 提取文件名
    filename = extract_filename_from_event(event)
    if not filename:
        return None

    # 3. 验证文件名
    result = checker.validate(
        filename=filename,
        sender_id=event.sender_id,
        sender_name=event.sender_name,
        group_id=event.group_id
    )

    # 4. 如果不合规，生成通知消息
    if not result.is_valid:
        categories_str = checker.format_categories()
        return notify_service.build_message_chain(result, categories_str)

    return {"type": "valid", "filename": filename}


# ===== 测试用例 =====

def test_mock_file_component():
    """测试模拟 File 组件"""
    file_comp = MockFileComponent(name="素材--项目1.pdf", file_id="abc123", size=1024)
    assert file_comp.name == "素材--项目1.pdf"
    print("✅ Mock File 组件测试通过")


def test_extract_filename_from_file_component():
    """测试从 File 组件提取文件名"""
    msg_obj = MockMessageObj(
        message=[MockFileComponent(name="素材--项目1.pdf")],
        raw_message=None
    )
    event = MockEvent(
        message_obj=msg_obj,
        sender_id="123456",
        sender_name="测试用户",
        group_id="987654"
    )

    filename = extract_filename_from_event(event)
    assert filename == "素材--项目1.pdf"
    print("✅ 从 File 组件提取文件名测试通过")


def test_extract_filename_from_raw_message():
    """测试从原始消息提取文件名"""
    msg_obj = MockMessageObj(
        message=[],
        raw_message={"file": {"name": "成品--文档.pdf"}}
    )
    event = MockEvent(
        message_obj=msg_obj,
        sender_id="123456",
        sender_name="测试用户",
        group_id="987654"
    )

    filename = extract_filename_from_event(event)
    assert filename == "成品--文档.pdf"
    print("✅ 从原始消息提取文件名测试通过")


def test_check_file_in_message_true():
    """测试检测消息中的文件"""
    msg_obj = MockMessageObj(
        message=[MockPlainComponent(text="看看这个文件"), MockFileComponent(name="test.pdf")],
        raw_message=None
    )
    event = MockEvent(message_obj=msg_obj, sender_id="123", sender_name="用户", group_id="群1")

    assert check_file_in_message(event) is True
    print("✅ 检测消息中的文件测试通过")


def test_check_file_in_message_false():
    """测试无文件时返回 False"""
    msg_obj = MockMessageObj(
        message=[MockPlainComponent(text="普通消息")],
        raw_message=None
    )
    event = MockEvent(message_obj=msg_obj, sender_id="123", sender_name="用户", group_id="群1")

    assert check_file_in_message(event) is False
    print("✅ 无文件消息检测测试通过")


def test_full_workflow_invalid_filename():
    """完整流程：文件名不合规"""
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={"设计类": ["素材", "成品"]}
    )
    notify_service = NotifyService()

    msg_obj = MockMessageObj(
        message=[MockFileComponent(name="test.pdf")],
        raw_message=None
    )
    event = MockEvent(
        message_obj=msg_obj,
        sender_id="123456",
        sender_name="测试用户",
        group_id="987654"
    )

    result = process_file_upload(event, checker, notify_service)

    # 返回的是组件列表（无 AstrBot 时是字符串列表）
    assert result is not None
    assert isinstance(result, list)
    if result and isinstance(result[0], str):
        # 当 AstrBot 不可用时，返回文本列表
        assert "测试用户" in result[0] or "123456" in result[0]
    print("✅ 完整流程-不合规文件测试通过")


def test_full_workflow_valid_filename():
    """完整流程：文件名合规"""
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={"设计类": ["素材", "成品"]}
    )
    notify_service = NotifyService()

    msg_obj = MockMessageObj(
        message=[MockFileComponent(name="素材--项目1.pdf")],
        raw_message=None
    )
    event = MockEvent(
        message_obj=msg_obj,
        sender_id="123456",
        sender_name="测试用户",
        group_id="987654"
    )

    result = process_file_upload(event, checker, notify_service)

    assert result is not None
    assert isinstance(result, dict)
    assert result["type"] == "valid"
    assert result["filename"] == "素材--项目1.pdf"
    print("✅ 完整流程-合规文件测试通过")


def test_full_workflow_no_file():
    """完整流程：无文件消息"""
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={}
    )
    notify_service = NotifyService()

    msg_obj = MockMessageObj(
        message=[MockPlainComponent(text="普通文本消息")],
        raw_message=None
    )
    event = MockEvent(
        message_obj=msg_obj,
        sender_id="123456",
        sender_name="测试用户",
        group_id="987654"
    )

    result = process_file_upload(event, checker, notify_service)

    assert result is None
    print("✅ 完整流程-无文件消息测试通过")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    # 运行所有测试
    print("\n" + "="*50)
    print("运行 Mock 消息组件测试")
    print("="*50 + "\n")

    test_mock_file_component()
    test_extract_filename_from_file_component()
    test_extract_filename_from_raw_message()
    test_check_file_in_message_true()
    test_check_file_in_message_false()
    test_full_workflow_invalid_filename()
    test_full_workflow_valid_filename()
    test_full_workflow_no_file()

    print("\n" + "="*50)
    print("所有 Mock 测试通过!")
    print("="*50 + "\n")