"""命令消息解析工具函数"""

import re

_ANGLE_RE = re.compile(r"<([^>]+)>")


def smart_split(message: str) -> list[str]:
    """智能分割命令消息，支持 ``<...>`` 分组识别含空格的参数。

    优先提取 ``<...>`` 内的完整内容，剩余部分按空白分割。
    这解决了 ``split()`` 在路径/名称含空格时索引错位的经典问题。

    返回: ``[命令, 子命令, 参数1, 参数2, ...]``

    示例：

    >>> smart_split("/预设路径 添加 <项目 A> </客户/2024 报告>")
    ["/预设路径", "添加", "<项目 A>", "</客户/2024 报告>"]

    >>> smart_split("/预设路径 删除 项目A")
    ["/预设路径", "删除", "项目A"]
    """
    if not message:
        return []

    parts: list[str] = []
    rest = message.strip()
    while rest:
        # 尝试匹配 <...> 分组
        m = _ANGLE_RE.match(rest)
        if m:
            parts.append(rest[: m.end()])
            rest = rest[m.end() :].strip()
            continue
        # 按空白取第一个词
        space_idx = rest.find(" ")
        if space_idx == -1:
            parts.append(rest)
            break
        parts.append(rest[:space_idx])
        rest = rest[space_idx:].strip()

    return parts


def parse_angle_args(msg: str, min_count: int) -> list[str] | None:
    """提取 ``<...>`` 分组参数，数量不足时返回 ``None``。

    示例：

    >>> parse_angle_args("/预设路径 添加 <项目 A> </客户/2024 报告>", 2)
    ["项目 A", "/客户/2024 报告"]
    """
    groups = _ANGLE_RE.findall(msg)
    if len(groups) >= min_count:
        return [g.strip() for g in groups]
    return None
