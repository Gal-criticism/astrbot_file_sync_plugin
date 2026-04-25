from datetime import datetime
from pathlib import Path


def generate_unique_filename(original_name: str) -> str:
    """
    为避免文件名冲突，生成带时间戳的唯一文件名

    原文件名: 文档.docx
    输出: 文档_20260423_143052_123456.docx (包含微秒确保唯一性)

    Args:
        original_name: 原文件名或路径

    Returns:
        带唯一时间戳的新文件名

    Raises:
        ValueError: 当输入为空或None时
    """
    if original_name is None:
        raise ValueError("文件名不能为None")
    if not isinstance(original_name, str) or original_name.strip() == "":
        raise ValueError("文件名不能为空字符串")

    path = Path(original_name)
    stem = path.stem
    suffix = path.suffix
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond:06d}"
    return f"{stem}_{timestamp}{suffix}"