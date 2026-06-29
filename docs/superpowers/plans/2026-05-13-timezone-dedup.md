# 时区统一与去重策略优化 实施规划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将所有时间操作统一为北京时间东八区，实现双重去重策略（时间戳+file_id），并在重试超限时通知用户。

**Architecture:** 在 state_manager.py 和 main.py 中将 `datetime.now()` 替换为 `datetime.now(CN_TZ)`（`CN_TZ = ZoneInfo("Asia/Shanghai")`）。在 sync_group 循环中增加 `is_synced(file_id)` 兜底检查。在 process_retry_queue 中对超限文件发送 AstrBot 消息通知。

**Tech Stack:** Python 3.9+ `zoneinfo.ZoneInfo`, SQLite, AstrBot API

---

### Task 1: state_manager.py 时区统一

**Files:**
- Modify: `file_sync_plugin2/services/state_manager.py`
- Test: `tests/test_state_manager.py`

- [ ] **Step 1: 添加时区常量和 import**

在 `state_manager.py` 顶部添加：
```python
from zoneinfo import ZoneInfo
CN_TZ = ZoneInfo("Asia/Shanghai")
```

- [ ] **Step 2: 修改 add_to_retry_queue 中的时间**

将第 90 行：
```python
next_retry = (datetime.now() + timedelta(seconds=delay_seconds)).isoformat()
```
改为：
```python
next_retry = (datetime.now(CN_TZ) + timedelta(seconds=delay_seconds)).isoformat()
```

将第 106 行 `datetime.now()` 改为 `datetime.now(CN_TZ)`。

- [ ] **Step 3: 修改 get_pending_retries 中的时间**

将第 111 行：
```python
now = datetime.now().isoformat()
```
改为：
```python
now = datetime.now(CN_TZ).isoformat()
```

- [ ] **Step 4: 修改 get_last_sync_time 确保返回带时区的 datetime**

将第 142 行：
```python
return datetime.fromisoformat(row[0])
```
改为：
```python
return datetime.fromisoformat(row[0])
```
注意：`datetime.fromisoformat()` 已能正确解析带时区偏移的 ISO 字符串（如 `2026-05-13T10:00:00+08:00`），无需额外处理。但如果旧数据不含时区信息，需要兼容。改为：
```python
dt = datetime.fromisoformat(row[0])
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=CN_TZ)
return dt
```

- [ ] **Step 5: 运行现有测试验证无回归**

Run: `pytest tests/test_state_manager.py -v`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add file_sync_plugin2/services/state_manager.py
git commit -m "feat: state_manager 时区统一为东八区"
```

---

### Task 2: main.py 时区统一

**Files:**
- Modify: `file_sync_plugin2/main.py`
- Test: `tests/test_plugin.py`

- [ ] **Step 1: 添加时区常量和 import**

在 `main.py` 顶部 import 区域添加：
```python
from zoneinfo import ZoneInfo
```

在 import 之后添加常量：
```python
CN_TZ = ZoneInfo("Asia/Shanghai")
```

- [ ] **Step 2: 修改 sync_group 中的时间**

将第 423 行：
```python
sync_time = datetime.now()
```
改为：
```python
sync_time = datetime.now(CN_TZ)
```

将第 433 行：
```python
upload_time = datetime.fromtimestamp(upload_time_ts) if upload_time_ts else None
```
改为：
```python
upload_time = datetime.fromtimestamp(upload_time_ts, tz=CN_TZ) if upload_time_ts else None
```

将第 458 行：
```python
sync_time=datetime.now()
```
改为：
```python
sync_time=datetime.now(CN_TZ)
```

- [ ] **Step 3: 修改 process_retry_queue 中的时间**

将第 573 行：
```python
sync_time=datetime.now()
```
改为：
```python
sync_time=datetime.now(CN_TZ)
```

- [ ] **Step 4: 运行现有测试验证无回归**

Run: `pytest tests/test_plugin.py -v`
Expected: 所有测试 PASS

- [ ] **Step 5: Commit**

```bash
git add file_sync_plugin2/main.py
git commit -m "feat: main.py 时区统一为东八区"
```

---

### Task 3: 双重去重 — sync_group 增加 is_synced 检查

**Files:**
- Modify: `file_sync_plugin2/main.py:426-442`
- Test: `tests/test_plugin.py`

- [ ] **Step 1: 编写测试 — 已同步文件应被跳过**

在 `tests/test_plugin.py` 中添加：
```python
@pytest.mark.asyncio
async def test_sync_group_skips_already_synced():
    """测试 sync_group 跳过已在 sync_records 中的文件"""
    from unittest.mock import MagicMock, AsyncMock
    from file_sync_plugin2.main import FileSyncPlugin

    mock_context = MagicMock()
    mock_platform = MagicMock()
    mock_client = MagicMock()

    mock_context.get_platform.return_value = mock_platform
    mock_platform.get_client.return_value = mock_client

    mock_client.api.call_action = AsyncMock(return_value={
        "files": [
            {"fileid": "file1", "filename": "doc.pdf", "size": 1024, "add_time": 9999999999},
        ]
    })

    plugin = FileSyncPlugin(mock_context, MagicMock())
    plugin.config = MagicMock()
    plugin.config.is_file_type_allowed = MagicMock(return_value=True)
    plugin.config.retry_queue_enabled = True
    plugin.config.retry_delay_seconds = 300
    plugin.state_manager = MagicMock()
    # is_synced 返回 True，表示已同步过
    plugin.state_manager.is_synced = MagicMock(return_value=True)
    plugin.state_manager.get_last_sync_time = MagicMock(return_value=None)
    plugin.state_manager.add_sync_record = MagicMock()
    plugin.state_manager.update_last_sync_time = MagicMock()

    plugin.sync_single_file = AsyncMock(return_value=True)

    await plugin.sync_group("123456")

    # 验证 sync_single_file 未被调用（文件被跳过）
    assert plugin.sync_single_file.call_count == 0
    # 验证 add_sync_record 未被调用
    assert plugin.state_manager.add_sync_record.call_count == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_plugin.py::test_sync_group_skips_already_synced -v`
Expected: FAIL（因为 is_synced 检查尚未添加到主循环）

- [ ] **Step 3: 在 sync_group 循环中添加 is_synced 检查**

在 `main.py` 第 442 行之后（时间戳检查 `continue` 之后），添加：
```python
            if self.state_manager.is_synced(file_id):
                logger.debug(f"跳过已同步文件: {file_name} (ID: {file_id})")
                continue
```

完整循环变为：
```python
        for file_info in files:
            file_id = file_info.get("file_id") or file_info.get("fileid") or file_info.get("id", "")
            file_name = file_info.get("file_name") or file_info.get("filename") or file_info.get("name", "")
            file_size = file_info.get("file_size") or file_info.get("size", 0)
            upload_time_ts = file_info.get("add_time") or file_info.get("upload_time") or file_info.get("create_time", 0)

            upload_time = datetime.fromtimestamp(upload_time_ts, tz=CN_TZ) if upload_time_ts else None

            if not self.config.is_file_type_allowed(file_name):
                logger.debug(f"跳过不允许的文件类型: {file_name}")
                continue

            if last_sync_time and upload_time:
                if upload_time <= last_sync_time:
                    logger.debug(f"跳过旧文件: {file_name} (上传时间: {upload_time})")
                    continue

            if self.state_manager.is_synced(file_id):
                logger.debug(f"跳过已同步文件: {file_name} (ID: {file_id})")
                continue

            target_path = self.config.generate_target_path(group_name, group_id, file_name)
            # ... 后续同步逻辑
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_plugin.py::test_sync_group_skips_already_synced -v`
Expected: PASS

- [ ] **Step 5: 运行全部测试确认无回归**

Run: `pytest tests/test_plugin.py -v`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add file_sync_plugin2/main.py tests/test_plugin.py
git commit -m "feat: sync_group 增加 is_synced 兜底去重检查"
```

---

### Task 4: 重试失败通知

**Files:**
- Modify: `file_sync_plugin2/main.py:540-557`

- [ ] **Step 1: 修改 process_retry_queue 超限处理逻辑**

将第 554-556 行：
```python
            if item["attempts"] >= self.config.retry_max_attempts:
                logger.warning(f"文件 {item['file_name']} 重试次数超限 ({item['attempts']}/{self.config.retry_max_attempts})，移出队列")
                self.state_manager.remove_from_retry_queue(item["file_id"])
                continue
```
改为：
```python
            if item["attempts"] >= self.config.retry_max_attempts:
                logger.warning(f"文件 {item['file_name']} 重试次数超限 ({item['attempts']}/{self.config.retry_max_attempts})，移出队列")
                self.state_manager.remove_from_retry_queue(item["file_id"])
                await self._notify_retry_failed(item)
                continue
```

- [ ] **Step 2: 添加 _notify_retry_failed 方法**

在 `process_retry_queue` 方法之前添加：
```python
    async def _notify_retry_failed(self, item: dict):
        """通知用户文件重试同步失败"""
        msg = (
            f"[文件同步] 重试失败通知\n"
            f"文件: {item['file_name']}\n"
            f"群号: {item['group_id']}\n"
            f"已尝试 {item['attempts']} 次，已达上限，不再重试"
        )
        logger.warning(msg)
        try:
            platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
            if platform:
                client = platform.get_client()
                # 尝试发送到配置的第一个群
                if self.config.enabled_groups:
                    await client.api.call_action(
                        "send_group_msg",
                        group_id=int(self.config.enabled_groups[0]),
                        message=msg
                    )
        except Exception as e:
            logger.error(f"发送重试失败通知失败: {e}")
```

- [ ] **Step 3: 运行全部测试确认无回归**

Run: `pytest tests/ -v`
Expected: 所有测试 PASS

- [ ] **Step 4: Commit**

```bash
git add file_sync_plugin2/main.py
git commit -m "feat: 重试超限文件通知用户"
```

---

### Task 5: 测试中 datetime 时区兼容

**Files:**
- Modify: `tests/test_state_manager.py`
- Modify: `tests/test_plugin.py`

- [ ] **Step 1: 更新测试中的 datetime.now() 调用**

在 `tests/test_state_manager.py` 中，将所有 `datetime.now()` 替换为带时区版本：

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")
```

将文件中所有 `datetime.now()` 替换为 `datetime.now(CN_TZ)`（约出现 10 处）。

- [ ] **Step 2: 运行全部测试**

Run: `pytest tests/ -v`
Expected: 所有测试 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_state_manager.py tests/test_plugin.py
git commit -m "test: 测试用例适配东八区时区"
```
