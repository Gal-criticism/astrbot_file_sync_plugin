# 去重策略修复设计

## 问题描述

群文件没有变动时，同一个文件被重复同步并重命名（如 `文档整合_20260509_190231_869555.docx`），说明去重逻辑没有生效。

## 根本原因分析

### 可能的问题点

1. **file_id 获取失败** - API 返回字段名不匹配，file_id 为空字符串
2. **时间戳检查失败** - upload_time 或 last_sync_time 为 None
3. **last_sync_time 未更新** - 首次同步后没有正确更新
4. **upload_time 获取失败** - QQ群文件 API 没有返回正确的上传时间字段

### 诊断日志

已添加详细诊断日志，用于排查问题：

1. **文件信息诊断** - 打印每个文件的 file_id、file_size、upload_time 等
2. **时间戳检查诊断** - 打印跳过原因（旧文件/新文件/检查跳过）
3. **last_sync_time 诊断** - 打印查询结果和更新过程
4. **同步记录诊断** - 打印添加记录的详细信息

## 解决方案

### 双重去重机制

**第一层：file_id 去重**（现有逻辑）
- 基于群文件 API 返回的 file_id 判断
- 如果 file_id 为空，跳过此层检查

**第二层：文件名+大小+群号去重**（新增）
- 基于 `file_name + file_size + group_id` 组合判断
- 作为 file_id 去重的兜底机制
- 在实际场景中，同一群内文件名+大小组合足够唯一

### 为什么不用 hash？

- hash 需要下载文件后计算，浪费带宽
- 文件名+大小组合在实际场景中足够唯一
- 如果需要更严格的去重，可以后续添加

## 实现细节

### state_manager.py

新增方法：
```python
def is_synced_by_name_size(self, file_name: str, file_size: int, group_id: str) -> bool:
    """检查文件是否已同步（基于文件名+大小+群号）"""
    conn = self._get_conn()
    cursor = conn.execute(
        "SELECT 1 FROM sync_records WHERE file_name = ? AND file_size = ? AND group_id = ?",
        (file_name, file_size, group_id)
    )
    return cursor.fetchone() is not None
```

### main.py

在 `sync_group` 方法中添加第二层检查：
```python
# 第一层去重：基于 file_id
if self.state_manager.is_synced(file_id):
    logger.debug(f"跳过已同步文件(file_id): {file_name} (ID: {file_id})")
    continue

# 第二层去重：基于文件名+大小+群号
if self.state_manager.is_synced_by_name_size(file_name, file_size, group_id):
    logger.debug(f"跳过已同步文件(name+size): {file_name} (大小: {file_size})")
    continue
```

## 测试验证

1. 首次同步：文件正常上传
2. 第二次同步（无新文件）：文件被跳过，不会重复上传
3. 删除文件后重新上传：新 file_id，但文件名+大小相同，仍被跳过（预期行为）
4. 上传同名但不同大小的文件：被视为新文件，正常同步

## 诊断步骤

### 使用 `/诊断日志` 命令

1. 执行一次同步（`/同步文件`）
2. 查看诊断日志（`/诊断日志`）
3. 检查以下信息：
   - `file_id` 是否为空
   - `upload_time` 是否为 None
   - `last_sync_time` 是否正确更新
   - 文件是否被跳过及跳过原因

### 诊断日志类型

- `file_info` - 文件基本信息
- `check` - 检查结果（新文件/旧文件/跳过检查）
- `skip` - 跳过原因（文件类型不允许/旧文件/已同步）
- `sync_state` - 同步状态（last_sync_time 查询/更新）
- `sync_success` - 同步成功记录

## 文件变更

- `file_sync_plugin2/services/state_manager.py`
  - 新增 `is_synced_by_name_size` 方法
  - 新增 `get_sync_stats_by_group` 方法
  - 新增 `get_group_stats` 方法
  - 新增诊断日志收集功能

- `file_sync_plugin2/main.py`
  - 添加第二层去重检查
  - 添加诊断日志收集
  - 新增 `/诊断日志` 命令
  - 新增 `/清空诊断日志` 命令
  - 更新 `/同步统计` 命令，支持分级统计
  - 优化大文件下载（流式下载，动态超时）

- `file_sync_plugin2/services/cloud_sync.py`
  - 优化大文件上传（流式上传，动态超时）
  - 新增分块上传支持（针对 > 100MB 文件）
  - 新增断点续传支持
  - 新增文件大小限制（10GB）
  - 新增上传速度和进度日志
