import pytest
import sys
sys.path.insert(0, '..')
from file_sync_plugin2.services.filename_checker import FilenameChecker
from file_sync_plugin2.services.notify_service import NotifyService
from file_sync_plugin2.models.validation_result import FileValidationResult

def test_full_workflow_valid():
    """完整流程：合规文件 - 不发送通知"""
    # 1. 检查文件名
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={"设计类": ["素材", "成品"]}
    )
    result = checker.validate("素材--项目1.png", "123", "用户", "群1")

    assert result.is_valid is True
    assert result.category == "素材"

    # 2. 合规文件不发送通知（流程结束）
    assert result.error_reason is None

def test_full_workflow_invalid_format():
    """完整流程：无分隔符的图片自动归入素材"""
    # 1. 检查文件名
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={}
    )
    result = checker.validate("素材项目1.png", "123", "用户", "群1")

    assert result.is_valid is True
    assert result.category == "素材"

def test_full_workflow_invalid_category():
    """完整流程：分类不在白名单 - 发送@提醒"""
    # 1. 检查文件名
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={"设计类": ["素材", "成品"]}
    )
    result = checker.validate("其他--项目1.pdf", "123", "用户", "群1")

    assert result.is_valid is False
    assert result.error_type == "category_not_in_whitelist"

    # 2. 发送通知
    notify = NotifyService()
    message = notify.format_message(result, categories_str="素材、成品")

    assert "@用户" in message
    assert "其他" in message
    assert "不在允许列表中" in message

def test_notification_message_chain():
    """测试消息链构建"""
    result = FileValidationResult(
        is_valid=False,
        filename="test.pdf",
        error_type="format_error",
        error_reason="缺少分隔符",
        sender_id="123456",
        sender_name="测试用户"
    )

    notify = NotifyService()
    chain = notify.build_message_chain(result, "素材、成品")

    # 返回的是组件列表（当 AstrBot 不可用时是字符串列表）
    assert isinstance(chain, list)
    if chain and isinstance(chain[0], str):
        # 当 AstrBot 不可用时，返回文本
        assert "测试用户" in chain[0] or "123456" in chain[0]

def test_multiple_separators():
    """多个 -- 分隔符，只取第一个分类"""
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={}
    )
    result = checker.validate("素材--子分类--项目1.png")

    assert result.is_valid is True
    assert result.category == "素材"

def test_whitespace_in_category():
    """分类前后有空格"""
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={"设计类": ["素材"]}
    )
    result = checker.validate("  素材  --项目1.png")

    assert result.is_valid is True
    assert result.category == "素材"