"""配置辅助工具函数"""

import json


def ensure_list(value) -> list:
    """确保值为列表类型，处理 JSON 字符串格式的列表

    AstrBot 可能以 JSON 字符串形式传入列表字段，此函数统一处理：
    - JSON 字符串 → 解析为列表
    - 逗号分隔字符串 → 按逗号分割
    - 嵌套字符串化的列表 → 递归展开
    """
    # 先处理外层类型
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
        except (json.JSONDecodeError, TypeError):
            pass
        if isinstance(value, str) and value.strip():
            value = [v.strip() for v in value.split(",")]

    if not isinstance(value, list):
        return []

    # 递归展开嵌套列表
    result = []
    for item in value:
        if isinstance(item, list):
            result.extend(ensure_list(item))
            continue
        if isinstance(item, str):
            # 尝试解析嵌套 JSON 字符串列表
            try:
                parsed = json.loads(item)
                if isinstance(parsed, list):
                    result.extend(ensure_list(parsed))
                    continue
            except (json.JSONDecodeError, TypeError):
                pass
            if item.strip():
                result.append(item.strip())
        else:
            result.append(item)
    return result
