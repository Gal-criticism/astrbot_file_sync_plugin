import pytest
import sys
sys.path.insert(0, '..')
from file_sync_plugin2.services.notify_service import NotifyService
from file_sync_plugin2.models.validation_result import FileValidationResult

@pytest.fixture
def default_template():
    return "@{sender} 你上传的文件「{filename}」格式不规范\n原因：{error_reason}\n正确格式：{template}\n可用分类：{categories}"

@pytest.fixture
def notify_service(default_template):
    return NotifyService(template=default_template)

def test_format_message_full(default_template):
    service = NotifyService(template=default_template)
    result = FileValidationResult(
        is_valid=False,
        filename="test.pdf",
        category=None,
        error_type="format_error",
        error_reason="缺少分隔符 '--'",
        sender_id="123456",
        sender_name="测试用户",
        group_id="987654"
    )
    message = service.format_message(result)
    assert "@测试用户" in message
    assert "「test.pdf」" in message
    assert "缺少分隔符 '--'" in message
    assert "分类--项目名称" in message

def test_format_message_with_categories():
    template = "@{sender} 可用分类：{categories}"
    service = NotifyService(template=template)
    result = FileValidationResult(
        is_valid=False,
        filename="test.pdf",
        category="其他",
        error_type="category_not_in_whitelist",
        error_reason="分类「其他」不在允许列表中",
        sender_id="123456",
        sender_name="用户",
        group_id="987654"
    )
    message = service.format_message(result, categories_str="素材、成品")
    assert "素材" in message
    assert "成品" in message

def test_format_message_empty_categories():
    service = NotifyService(template="{categories}")
    result = FileValidationResult(
        is_valid=False,
        filename="test.pdf",
        error_type="format_error",
        error_reason="缺少分隔符"
    )
    message = service.format_message(result, categories_str="")
    assert message.strip() == ""