# 时区统一与去重策略优化设计

日期: 2026-05-13

## 背景

当前插件存在两个问题：
1. 所有时间操作使用 `datetime.now()`（无时区），依赖服务器系统时区，无法保证北京时间
2. 去重策略不完整：`is_synced()` 方法存在但未在主循环调用，仅靠时间戳过滤可能遗漏重试队列中的文件

## 目标

1. 统一使用北京时间（东八区）
2. 实现双重去重：时间戳快速跳过 + file_id 兜底检查
3. 重试队列达到最大次数后通知用户

## 设计

### 一、时区统一

使用 `ZoneInfo("Asia/Shanghai")`（Python 3.9+ 标准库），替代 `datetime.now()`。

改动点：
- `main.py` — `sync_time = datetime.now()` → `datetime.now(CN_TZ)`
- `main.py` — `SyncRecord(sync_time=datetime.now())` → 带时区
- `main.py` — `datetime.fromtimestamp(upload_time_ts)` → `datetime.fromtimestamp(upload_time_ts, tz=CN_TZ)`
- `state_manager.py` — 重试队列 `next_retry`、`created_at`、`get_pending_retries` 的 `now`
- `state_manager.py` — `get_last_sync_time()` 返回值需带时区

在 `main.py` 顶部定义常量：
```python
from zoneinfo import ZoneInfo
CN_TZ = ZoneInfo("Asia/Shanghai")
```

SQLite 存储的 ISO 格式字符串会包含时区偏移（如 `+08:00`），读取时 `datetime.fromisoformat()` 可正确解析。

### 二、双重去重策略

在 `sync_group()` 的文件遍历循环中增加二级过滤：

```python
for file_info in files:
    file_id = ...
    file_name = ...
    upload_time = ...

    # 第一层：文件类型过滤
    if not self.config.is_file_type_allowed(file_name):
        continue

    # 第二层：时间戳快速跳过
    if last_sync_time and upload_time:
        if upload_time <= last_sync_time:
            continue

    # 第三层：file_id 兜底检查（新增）
    if self.state_manager.is_synced(file_id):
        continue

    # 执行同步...
```

效果：
- 时间戳过滤作为快速路径，大多数旧文件在此被跳过
- file_id 检查兜底，防止时间边界问题导致的重复同步
- 重试队列中的文件：因为没有成功的 sync_record，即使时间已前进，也会被重新尝试

### 三、重试失败通知

修改 `process_retry_queue()` 方法，当文件达到 `retry_max_attempts` 时：

1. 从 `retry_queue` 移除该记录
2. 通过 AstrBot 消息通知用户：文件名、群号、失败原因
3. 记录 WARNING 级别日志

通知方式：使用 `self.context.get_platform()` 获取消息平台，发送私信或群消息（取决于配置）。

## 不改变的部分

- 手动同步（`同步文件` 命令）保持与定时同步相同的增量逻辑
- `sync_records` 表结构不变，`file_id` 仍为主键
- `SyncRecord` 数据模型不变
- 重试队列逻辑不变（仅增加超限通知）

## 影响范围

- `file_sync_plugin2/main.py` — 时区常量、`sync_group()` 增加 `is_synced` 检查、`process_retry_queue()` 增加通知
- `file_sync_plugin2/services/state_manager.py` — 所有 `datetime.now()` 改为带时区
