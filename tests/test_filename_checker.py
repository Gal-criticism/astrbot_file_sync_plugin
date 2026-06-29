import pytest
import sys
sys.path.insert(0, '..')
from file_sync_plugin2.services.filename_checker import FilenameChecker

@pytest.fixture
def checker_no_categories():
    """无分类白名单的检查器"""
    return FilenameChecker(template="{category}--{name}", categories={})

@pytest.fixture
def checker_with_categories():
    """有分类白名单的检查器"""
    return FilenameChecker(
        template="{category}--{name}",
        categories={
            "设计类": ["素材", "成品", "草稿"],
            "文档类": ["报告", "合同"]
        }
    )

def test_validate_valid_filename_no_categories(checker_no_categories):
    result = checker_no_categories.validate("素材--项目1.pdf")
    assert result.is_valid is True
    assert result.filename == "素材--项目1.pdf"
    assert result.category == "素材"

def test_validate_missing_separator(checker_no_categories):
    result = checker_no_categories.validate("素材项目1.pdf")
    assert result.is_valid is False
    assert result.error_type == "format_error"
    assert "缺少分隔符" in result.error_reason

def test_validate_category_not_in_whitelist(checker_with_categories):
    result = checker_with_categories.validate("其他--项目1.pdf")
    assert result.is_valid is False
    assert result.error_type == "category_not_in_whitelist"
    assert "分类「其他」不在允许列表中" in result.error_reason

def test_validate_category_in_whitelist(checker_with_categories):
    result = checker_with_categories.validate("素材--项目1.pdf")
    assert result.is_valid is True
    assert result.category == "素材"

def test_extract_category():
    checker = FilenameChecker(template="{category}--{name}", categories={})
    assert checker.extract_category("素材--项目1.pdf") == "素材"
    # 注意："成品" 被规范解析为 "成片"（标准分类）
    assert checker.extract_category("成品--文档.pdf") == "成片"
    assert checker.extract_category("无分隔符.txt") is None

def test_extract_category_multiple_separators():
    """多个 -- 分隔符，只取第一个"""
    checker = FilenameChecker(template="{category}--{name}", categories={})
    assert checker.extract_category("素材--子分类--项目1.pdf") == "素材"

def test_format_categories_empty():
    checker = FilenameChecker(template="{category}--{name}", categories={})
    assert checker.format_categories() == ""

def test_format_categories_with_groups():
    checker = FilenameChecker(
        template="{category}--{name}",
        categories={"设计类": ["素材", "成品"], "文档类": ["报告"]}
    )
    formatted = checker.format_categories()
    assert "素材" in formatted
    assert "成品" in formatted
    assert "报告" in formatted