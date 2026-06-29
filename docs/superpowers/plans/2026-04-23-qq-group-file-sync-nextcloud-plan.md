# QQ群文件同步NextCloud插件 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建AstrBot插件，定时扫描QQ群文件夹并同步到NextCloud私有云盘

**Architecture:** 事件驱动架构，使用APScheduler定时任务触发，通过aiocqhttp API获取群文件列表，nc_py_api上传到NextCloud，SQLite记录同步状态

**Tech Stack:** AstrBot插件框架, nc_py_api, aiocqhttp OneBot API, APScheduler, SQLite

---

## 1. 项目结构

```
e:/githubproject/artbot_document_sys/
├── file_sync_plugin/                    # 插件主目录
│   ├── __init__.py
│   ├── plugin.py                        # 主插件类 FileSyncPlugin
│   ├── config.py                        # 配置模型和验证
│   ├── services/
│   │   ├── __init__.py
│   │   ├── cloud_sync.py                # NextCloud同步服务
│   │   ├── file_scanner.py              # QQ群文件扫描器
│   │   └── state_manager.py              # 同步状态管理(SQLite)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── sync_record.py               # 同步记录模型
│   │   └── retry_item.py                # 重试队列模型
│   └── utils/
│       ├── __init__.py
│       └── rename.py                     # 文件重命名工具
├── tests/
│   ├── __init__.py
│   ├── test_rename.py                    # 重命名逻辑测试
│   ├── test_state_manager.py             # 状态管理测试
│   └── test_cloud_sync.py                # 云同步服务测试
├── docs/
│   └── superpowers/
│       ├── specs/
│       └── plans/
└── nextcloud_task.py                     # 参考代码(已有)
```

---

## 2. 依赖安装

**Step 1: 创建项目结构并安装依赖**

```bash
mkdir -p e:/githubproject/artbot_document_sys/file_sync_plugin/services
mkdir -p e:/githubproject/artbot_document_sys/file_sync_plugin/models
mkdir -p e:/githubproject/artbot_document_sys/file_sync_plugin/utils
mkdir -p e:/githubproject/artbot_document_sys/tests
touch e:/githubproject/artbot_document_sys/file_sync_plugin/__init__.py
touch e:/githubproject/artbot_document_sys/file_sync_plugin/services/__init__.py
touch e:/githubproject/artbot_document_sys/file_sync_plugin/models/__init__.py
touch e:/githubproject/artbot_document_sys/file_sync_plugin/utils/__init__.py
touch e:/githubproject/artbot_document_sys/tests/__init__.py
```

**Step 2: 创建requirements.txt**

```
nc_py_api>=2.0.0
APScheduler>=3.10.0
```

---

## 3. 实施任务

### Task 1: 配置模块 (config.py)

**Files:**
- Create: `file_sync_plugin/config.py`

- [ ] **Step 1: 创建配置模型**

```python
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class FileSyncConfig(BaseModel):
    """插件配置模型"""
    nextcloud_url: str = Field(..., description="NextCloud WebDAV地址")
    nextcloud_username: str = Field(..., description="NextCloud用户名")
    nextcloud_password: str = Field(..., description="NextCloud应用密码")
    group_mappings: Dict[str, str] = Field(default_factory=dict, description="群号到云盘路径的映射")
    sync_interval_minutes: int = Field(default=5, ge=1, description="同步间隔(分钟)")
    file_type_whitelist: List[str] = Field(default_factory=lambda: ["*"], description="允许的文件类型")
    notify_on_success: bool = Field(default=False, description="成功时通知")
    notify_on_error: bool = Field(default=True, description="失败时通知")
    retry_queue_enabled: bool = Field(default=True, description="启用重试队列")
    retry_max_attempts: int = Field(default=3, ge=1, description="最大重试次数")
    retry_delay_seconds: int = Field(default=300, ge=60, description="重试间隔(秒)")

    def is_file_type_allowed(self, filename: str) -> bool:
        """检查文件类型是否允许"""
        if "*" in self.file_type_whitelist:
            return True
        ext = "." + filename.split(".")[-1].lower() if "." in filename else ""
        return ext.lower() in [x.lower() for x in self.file_type_whitelist]
```

- [ ] **Step 2: 创建配置验证函数**

```python
def validate_config(config: dict) -> FileSyncConfig:
    """验证并返回配置对象"""
    return FileSyncConfig(**config)
```

- [ ] **Step 3: 编写测试**

```python
# tests/test_config.py
import pytest
from file_sync_plugin.config import FileSyncConfig, validate_config

def test_file_type_whitelist_all():
    config = FileSyncConfig(
        nextcloud_url="https://nc.example.com",
        nextcloud_username="user",
        nextcloud_password="pass",
        file_type_whitelist=["*"]
    )
    assert config.is_file_type_allowed("anyfile.exe") == True
    assert config.is_file_type_allowed("document.pdf") == True

def test_file_type_whitelist_specific():
    config = FileSyncConfig(
        nextcloud_url="https://nc.example.com",
        nextcloud_username="user",
        nextcloud_password="pass",
        file_type_whitelist=[".pdf", ".docx"]
    )
    assert config.is_file_type_allowed("document.pdf") == True
    assert config.is_file_type_allowed("document.docx") == True
    assert config.is_file_type_allowed("evil.exe") == False

def test_validate_config_missing_required():
    with pytest.raises(Exception):
        validate_config({})
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_config.py -v`

- [ ] **Step 5: Commit**

```bash
git add file_sync_plugin/config.py tests/test_config.py
git commit -m "feat: add config model with validation"
```

---

### Task 2: 文件重命名工具 (utils/rename.py)

**Files:**
- Create: `file_sync_plugin/utils/rename.py`
- Test: `tests/test_rename.py`

- [ ] **Step 1: 编写重命名函数**

```python
from datetime import datetime
from pathlib import Path

def generate_unique_filename(original_name: str) -> str:
    """
    为避免文件名冲突，生成带时间戳的唯一文件名

    原文件名: 文档.docx
    输出: 文档_20260423_143052.docx
    """
    path = Path(original_name)
    stem = path.stem
    suffix = path.suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stem}_{timestamp}{suffix}"
```

- [ ] **Step 2: 编写测试**

```python
# tests/test_rename.py
import pytest
from file_sync_plugin.utils.rename import generate_unique_filename

def test_generate_unique_filename_with_extension():
    result = generate_unique_filename("文档.docx")
    assert result.startswith("文档_")
    assert result.endswith(".docx")
    assert len(result) == len("文档_YYYYMMDD_HHMMSS.docx")

def test_generate_unique_filename_no_extension():
    result = generate_unique_filename("无扩展名文件")
    assert result.startswith("无扩展名文件_")
    assert "." not in result

def test_generate_unique_filename_preserves_stem():
    result = generate_unique_filename("my_document_v2.pdf")
    assert result.startswith("my_document_v2_")
    assert result.endswith(".pdf")
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_rename.py -v`

- [ ] **Step 4: Commit**

```bash
git add file_sync_plugin/utils/rename.py tests/test_rename.py
git commit -m "feat: add file rename utility with timestamp"
```

---

### Task 3: 同步状态管理器 (services/state_manager.py)

**Files:**
- Create: `file_sync_plugin/services/state_manager.py`
- Test: `tests/test_state_manager.py`

- [ ] **Step 1: 创建同步记录模型**

```python
# file_sync_plugin/models/sync_record.py
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class SyncRecord:
    """同步记录"""
    file_id: str           # QQ群文件的file_id
    file_name: str         # 文件名
    file_size: int         # 文件大小
    group_id: str          # 群号
    target_path: str       # 云端目标路径
    sync_time: datetime    # 同步时间
    file_hash: Optional[str] = None  # 文件hash(可选)
    retry_count: int = 0   # 重试次数
```

- [ ] **Step 2: 创建状态管理器**

```python
# file_sync_plugin/services/state_manager.py
import sqlite3
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from file_sync_plugin.models.sync_record import SyncRecord

class StateManager:
    """同步状态管理器，使用SQLite存储"""

    def __init__(self, db_path: str = "file_sync_state.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_records (
                    file_id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    file_size INTEGER,
                    group_id TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    sync_time TEXT NOT NULL,
                    file_hash TEXT,
                    retry_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size INTEGER,
                    group_id TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    next_retry TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(file_id)
                )
            """)
            conn.commit()

    def is_synced(self, file_id: str) -> bool:
        """检查文件是否已同步"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM sync_records WHERE file_id = ?", (file_id,)
            )
            return cursor.fetchone() is not None

    def add_sync_record(self, record: SyncRecord):
        """添加同步记录"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sync_records
                (file_id, file_name, file_size, group_id, target_path, sync_time, file_hash, retry_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.file_id, record.file_name, record.file_size,
                record.group_id, record.target_path,
                record.sync_time.isoformat(), record.file_hash, record.retry_count
            ))
            conn.commit()

    def add_to_retry_queue(self, file_id: str, file_name: str, file_size: int,
                          group_id: str, target_path: str, delay_seconds: int = 300):
        """加入重试队列"""
        next_retry = datetime.now().timestamp() + delay_seconds
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO retry_queue
                (file_id, file_name, file_size, group_id, target_path, attempts, next_retry, created_at)
                VALUES (?, ?, ?, ?, ?, attempts + 1, ?, ?)
            """, (file_id, file_name, file_size, group_id, target_path, next_retry, datetime.now().isoformat()))
            conn.commit()

    def get_pending_retries(self) -> List[dict]:
        """获取待处理的重试项"""
        now = datetime.now().timestamp()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT file_id, file_name, file_size, group_id, target_path, attempts FROM retry_queue WHERE next_retry <= ?",
                (now,)
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def remove_from_retry_queue(self, file_id: str):
        """从重试队列移除"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM retry_queue WHERE file_id = ?", (file_id,))
            conn.commit()

    def get_sync_stats(self) -> dict:
        """获取同步统计"""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM sync_records").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM retry_queue").fetchone()[0]
            return {"total_synced": total, "pending_retries": pending}
```

- [ ] **Step 3: 编写测试**

```python
# tests/test_state_manager.py
import pytest
import tempfile
import os
from datetime import datetime
from file_sync_plugin.services.state_manager import StateManager
from file_sync_plugin.models.sync_record import SyncRecord

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)

def test_is_synced_false_when_empty(temp_db):
    manager = StateManager(temp_db)
    assert manager.is_synced("file123") == False

def test_is_synced_true_after_add(temp_db):
    manager = StateManager(temp_db)
    record = SyncRecord(
        file_id="file123", file_name="test.pdf", file_size=1024,
        group_id="group1", target_path="/test", sync_time=datetime.now()
    )
    manager.add_sync_record(record)
    assert manager.is_synced("file123") == True

def test_add_to_retry_queue(temp_db):
    manager = StateManager(temp_db)
    manager.add_to_retry_queue("file123", "test.pdf", 1024, "group1", "/test")
    pending = manager.get_pending_retries()
    assert len(pending) == 1
    assert pending[0]["file_id"] == "file123"

def test_get_sync_stats(temp_db):
    manager = StateManager(temp_db)
    stats = manager.get_sync_stats()
    assert stats["total_synced"] == 0
    assert stats["pending_retries"] == 0
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_state_manager.py -v`

- [ ] **Step 5: Commit**

```bash
git add file_sync_plugin/services/state_manager.py file_sync_plugin/models/sync_record.py tests/test_state_manager.py
git commit -m "feat: add state manager with SQLite for sync records and retry queue"
```

---

### Task 4: 云盘同步服务 (services/cloud_sync.py)

**Files:**
- Create: `file_sync_plugin/services/cloud_sync.py`
- Test: `tests/test_cloud_sync.py`

- [ ] **Step 1: 创建CloudSyncService**

```python
# file_sync_plugin/services/cloud_sync.py
from nc_py_api import NextCloud
from typing import Optional
import logging

from file_sync_plugin.config import FileSyncConfig
from file_sync_plugin.utils.rename import generate_unique_filename

logger = logging.getLogger(__name__)

class CloudSyncService:
    """NextCloud同步服务"""

    def __init__(self, config: FileSyncConfig):
        self.config = config
        self.nc: Optional[NextCloud] = None
        self._connect()

    def _connect(self):
        """建立NextCloud连接"""
        self.nc = NextCloud(
            nextcloud_url=self.config.nextcloud_url,
            nc_auth_user=self.config.nextcloud_username,
            nc_auth_pass=self.config.nextcloud_password,
        )

    def ensure_directory_exists(self, path: str) -> bool:
        """确保目录存在，不存在则创建"""
        try:
            if not self.nc.files.exists(path):
                self.nc.files.mkdir(path)
                logger.info(f"创建目录: {path}")
            return True
        except Exception as e:
            logger.error(f"创建目录失败 {path}: {e}")
            return False

    def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        try:
            return self.nc.files.exists(path)
        except Exception as e:
            logger.error(f"检查文件存在失败 {path}: {e}")
            return False

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """
        上传文件到NextCloud
        如果远程路径文件已存在，自动重命名
        """
        try:
            # 检查文件是否存在，如存在则重命名
            if self.file_exists(remote_path):
                original_name = remote_path.split("/")[-1]
                new_name = generate_unique_filename(original_name)
                remote_path = remote_path.rsplit("/", 1)[0] + "/" + new_name
                logger.info(f"文件已存在，重命名为: {new_name}")

            # 确保目录存在
            dir_path = remote_path.rsplit("/", 1)[0]
            if dir_path and not self.ensure_directory_exists(dir_path):
                return False

            # 上传文件
            with open(local_path, "rb") as f:
                self.nc.files.upload(remote_path, f)
            logger.info(f"上传成功: {remote_path}")
            return True
        except Exception as e:
            logger.error(f"上传文件失败 {remote_path}: {e}")
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """从NextCloud下载文件"""
        try:
            content = self.nc.files.download(remote_path)
            with open(local_path, "wb") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"下载文件失败 {remote_path}: {e}")
            return False
```

- [ ] **Step 2: 编写测试（需要mock nc_py_api）**

```python
# tests/test_cloud_sync.py
import pytest
from unittest.mock import Mock, patch, MagicMock
from file_sync_plugin.services.cloud_sync import CloudSyncService
from file_sync_plugin.config import FileSyncConfig

@pytest.fixture
def mock_config():
    return FileSyncConfig(
        nextcloud_url="https://nc.example.com",
        nextcloud_username="user",
        nextcloud_password="pass",
        group_mappings={"123": "/test"}
    )

@patch('file_sync_plugin.services.cloud_sync.NextCloud')
def test_cloud_sync_upload_success(mock_nextcloud, mock_config, tmp_path):
    # 创建测试文件
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"test content")

    mock_nc = MagicMock()
    mock_nc.files.exists.return_value = False
    mock_nextcloud.return_value = mock_nc

    service = CloudSyncService(mock_config)
    result = service.upload_file(str(test_file), "/test/test.pdf")

    assert result == True
    mock_nc.files.mkdir.assert_called_once_with("/test")

@patch('file_sync_plugin.services.cloud_sync.NextCloud')
def test_cloud_sync_upload_with_rename(mock_nextcloud, mock_config, tmp_path):
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"test content")

    mock_nc = MagicMock()
    mock_nc.files.exists.return_value = True  # 文件已存在
    mock_nc.files.mkdir.return_value = None
    mock_nextcloud.return_value = mock_nc

    service = CloudSyncService(mock_config)
    result = service.upload_file(str(test_file), "/test/test.pdf")

    assert result == True
    # 验证upload被调用且文件名包含时间戳
    call_args = mock_nc.files.upload.call_args
    uploaded_path = call_args[0][0]
    assert "test_" in uploaded_path and uploaded_path.endswith(".pdf")
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_cloud_sync.py -v`

- [ ] **Step 4: Commit**

```bash
git add file_sync_plugin/services/cloud_sync.py tests/test_cloud_sync.py
git commit -m "feat: add CloudSyncService for NextCloud upload operations"
```

---

### Task 5: QQ群文件扫描器 (services/file_scanner.py)

**Files:**
- Create: `file_sync_plugin/services/file_scanner.py`

- [ ] **Step 1: 创建FileScanner**

```python
# file_sync_plugin/services/file_scanner.py
from typing import List, Dict, Any, Optional
import logging
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

logger = logging.getLogger(__name__)

class GroupFileInfo:
    """群文件信息"""
    def __init__(self, file_id: str, file_name: str, file_size: int,
                 upload_time: int, dead_time: int):
        self.file_id = file_id
        self.file_name = file_name
        self.file_size = file_size
        self.upload_time = upload_time
        self.dead_time = dead_time

class FileScanner:
    """QQ群文件扫描器"""

    def __init__(self, event: AiocqhttpMessageEvent):
        self.event = event
        self.client = event.bot

    async def get_group_file_list(self, group_id: str) -> List[GroupFileInfo]:
        """
        获取群文件列表
        调用 OneBot API: get_group_file_list
        """
        try:
            result = await self.client.api.call_action(
                "get_group_file_list",
                group_id=int(group_id)
            )
            files = []
            for f in result.get("files", []):
                files.append(GroupFileInfo(
                    file_id=f["fileid"],
                    file_name=f["filename"],
                    file_size=f["size"],
                    upload_time=f.get("upload_time", 0),
                    dead_time=f.get("dead_time", 0)
                ))
            logger.info(f"获取群 {group_id} 文件列表成功，共 {len(files)} 个文件")
            return files
        except Exception as e:
            logger.error(f"获取群 {group_id} 文件列表失败: {e}")
            return []

    async def get_file_download_url(self, group_id: str, file_id: str) -> Optional[str]:
        """
        获取群文件下载链接
        调用 OneBot API: get_group_file_url
        """
        try:
            result = await self.client.api.call_action(
                "get_group_file_url",
                group_id=int(group_id),
                file_id=file_id
            )
            return result.get("url")
        except Exception as e:
            logger.error(f"获取文件下载链接失败: {e}")
            return None
```

- [ ] **Step 2: Commit**

```bash
git add file_sync_plugin/services/file_scanner.py
git commit -m "feat: add FileScanner for QQ group file operations"
```

---

### Task 6: 主插件类 (plugin.py)

**Files:**
- Create: `file_sync_plugin/plugin.py`

- [ ] **Step 1: 创建主插件类**

```python
# file_sync_plugin/plugin.py
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Comp

from file_sync_plugin.config import FileSyncConfig, validate_config
from file_sync_plugin.services.cloud_sync import CloudSyncService
from file_sync_plugin.services.file_scanner import FileScanner, GroupFileInfo
from file_sync_plugin.services.state_manager import StateManager
from file_sync_plugin.models.sync_record import SyncRecord

logger = logging.getLogger(__name__)

@register
class FileSyncPlugin(Star):
    """QQ群文件自动同步NextCloud插件"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.name = "file_sync_plugin"
        self.config: Optional[FileSyncConfig] = None
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.state_manager: Optional[StateManager] = None
        self.cloud_sync: Optional[CloudSyncService] = None

    async def initialize(self):
        """初始化插件"""
        logger.info("初始化 FileSyncPlugin...")

        # 加载配置
        plugin_config = self.context.get_plugin_config(self.name)
        self.config = validate_config(plugin_config)

        # 初始化服务
        self.state_manager = StateManager()
        self.cloud_sync = CloudSyncService(self.config)

        # 启动定时任务
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self.sync_all_groups,
            trigger=IntervalTrigger(minutes=self.config.sync_interval_minutes),
            id="sync_files",
            name="定时同步群文件"
        )
        self.scheduler.start()
        logger.info(f"定时同步任务已启动，间隔: {self.config.sync_interval_minutes}分钟")

    async def terminate(self):
        """插件卸载时调用"""
        if self.scheduler:
            self.scheduler.shutdown()

    @filter.command("同步文件")
    async def sync_files_command(self, event: AstrMessageEvent):
        """手动触发一次同步"""
        yield event.plain_result("开始同步...")
        await self.sync_all_groups()
        yield event.plain_result("同步完成")

    @filter.command("同步状态")
    async def sync_status_command(self, event: AstrMessageEvent):
        """查看同步状态"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return
        stats = self.state_manager.get_sync_stats()
        yield event.plain_result(
            f"已同步文件: {stats['total_synced']}\n"
            f"待重试: {stats['pending_retries']}"
        )

    @filter.command("同步统计")
    async def sync_stats_command(self, event: AstrMessageEvent):
        """查看同步统计"""
        if not self.state_manager:
            yield event.plain_result("状态管理器未初始化")
            return
        stats = self.state_manager.get_sync_stats()
        pending = self.state_manager.get_pending_retries()
        msg = f"已同步文件: {stats['total_synced']}\n待重试任务: {stats['pending_retries']}"
        if pending:
            msg += "\n\n待重试文件:"
            for p in pending[:5]:
                msg += f"\n- {p['file_name']} (尝试 {p['attempts']} 次)"
        yield event.plain_result(msg)

    async def sync_all_groups(self):
        """同步所有配置的群"""
        logger.info("开始同步所有群...")

        for group_id, target_path in self.config.group_mappings.items():
            try:
                await self.sync_group(group_id, target_path)
            except Exception as e:
                logger.error(f"同步群 {group_id} 失败: {e}")

        # 处理重试队列
        await self.process_retry_queue()

        logger.info("同步完成")

    async def sync_group(self, group_id: str, target_path: str):
        """同步单个群的文件"""
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

        # 获取平台客户端
        platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
        if not platform:
            logger.error("无法获取QQ平台")
            return

        client = platform.get_client()

        # 获取群文件列表
        try:
            result = await client.api.call_action("get_group_file_list", group_id=int(group_id))
        except Exception as e:
            logger.error(f"获取群 {group_id} 文件列表失败: {e}")
            return

        files = result.get("files", [])
        logger.info(f"群 {group_id} 共有 {len(files)} 个文件")

        for file_info in files:
            file_id = file_info["fileid"]
            file_name = file_info["filename"]
            file_size = file_info["size"]

            # 检查文件类型
            if not self.config.is_file_type_allowed(file_name):
                logger.debug(f"跳过不允许的文件类型: {file_name}")
                continue

            # 检查是否已同步
            if self.state_manager.is_synced(file_id):
                continue

            # 下载并上传
            success = await self.sync_single_file(
                group_id, target_path, file_id, file_name, file_size
            )

            if success:
                # 记录同步
                record = SyncRecord(
                    file_id=file_id,
                    file_name=file_name,
                    file_size=file_size,
                    group_id=group_id,
                    target_path=target_path,
                    sync_time=datetime.now()
                )
                self.state_manager.add_sync_record(record)
            else:
                # 加入重试队列
                if self.config.retry_queue_enabled:
                    self.state_manager.add_to_retry_queue(
                        file_id, file_name, file_size, group_id, target_path,
                        self.config.retry_delay_seconds
                    )

    async def sync_single_file(self, group_id: str, target_path: str,
                               file_id: str, file_name: str, file_size: int) -> bool:
        """同步单个文件"""
        try:
            # 获取下载链接
            platform = self.context.get_platform(filter.PlatformAdapterType.AIOCQHTTP)
            client = platform.get_client()
            url_result = await client.api.call_action(
                "get_group_file_url",
                group_id=int(group_id),
                file_id=file_id
            )
            file_url = url_result.get("url")
            if not file_url:
                logger.error(f"无法获取文件下载链接: {file_name}")
                return False

            # 下载到临时目录
            import tempfile
            import httpx
            temp_dir = Path(tempfile.gettempdir()) / "file_sync"
            temp_dir.mkdir(exist_ok=True)
            local_path = temp_dir / file_name

            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(file_url)
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    f.write(response.content)

            # 上传到NextCloud
            remote_path = f"{target_path}/{file_name}"
            upload_success = self.cloud_sync.upload_file(str(local_path), remote_path)

            # 清理临时文件
            local_path.unlink(missing_ok=True)

            return upload_success

        except Exception as e:
            logger.error(f"同步文件失败 {file_name}: {e}")
            return False

    async def process_retry_queue(self):
        """处理重试队列"""
        if not self.state_manager:
            return

        pending = self.state_manager.get_pending_retries()
        for item in pending:
            if item["attempts"] >= self.config.retry_max_attempts:
                logger.warning(f"文件 {item['file_name']} 重试次数超限，移出队列")
                self.state_manager.remove_from_retry_queue(item["file_id"])
                continue

            success = await self.sync_single_file(
                item["group_id"], item["target_path"],
                item["file_id"], item["file_name"], item["file_size"]
            )

            if success:
                self.state_manager.remove_from_retry_queue(item["file_id"])
                record = SyncRecord(
                    file_id=item["file_id"],
                    file_name=item["file_name"],
                    file_size=item["file_size"],
                    group_id=item["group_id"],
                    target_path=item["target_path"],
                    sync_time=datetime.now()
                )
                self.state_manager.add_sync_record(record)
```

- [ ] **Step 2: Commit**

```bash
git add file_sync_plugin/plugin.py
git commit -m "feat: add main FileSyncPlugin class with scheduler and sync logic"
```

---

### Task 7: 插件打包配置

**Files:**
- Create: `file_sync_plugin/__init__.py`
- Create: `file_sync_plugin/plugin.json`

- [ ] **Step 1: 创建__init__.py**

```python
from .plugin import FileSyncPlugin

__all__ = ["FileSyncPlugin"]
```

- [ ] **Step 2: 创建plugin.json**

```json
{
  "name": "file_sync_plugin",
  "version": "1.0.0",
  "description": "QQ群文件自动同步NextCloud",
  "author": "Your Name",
  "entry": "file_sync_plugin.plugin:FileSyncPlugin",
  "config": {
    "nextcloud_url": {
      "type": "str",
      "description": "NextCloud WebDAV地址",
      "required": true
    },
    "nextcloud_username": {
      "type": "str",
      "description": "NextCloud用户名",
      "required": true
    },
    "nextcloud_password": {
      "type": "str",
      "description": "NextCloud应用密码",
      "required": true
    },
    "group_mappings": {
      "type": "dict",
      "description": "群号到云盘路径的映射，格式: {\"群号\": \"/路径\"}",
      "required": true
    },
    "sync_interval_minutes": {
      "type": "int",
      "description": "同步间隔(分钟)",
      "default": 5
    },
    "file_type_whitelist": {
      "type": "list",
      "description": "允许的文件类型，如 [\".pdf\", \".docx\"]，留空或[\"*\"]表示所有类型",
      "default": ["*"]
    },
    "notify_on_success": {
      "type": "bool",
      "description": "成功时通知管理员",
      "default": false
    },
    "notify_on_error": {
      "type": "bool",
      "description": "失败时通知管理员",
      "default": true
    },
    "retry_queue_enabled": {
      "type": "bool",
      "description": "启用失败重试队列",
      "default": true
    },
    "retry_max_attempts": {
      "type": "int",
      "description": "最大重试次数",
      "default": 3
    },
    "retry_delay_seconds": {
      "type": "int",
      "description": "重试间隔(秒)",
      "default": 300
    }
  },
  "dependencies": {
    "nc_py_api": ">=2.0.0",
    "APScheduler": ">=3.10.0",
    "httpx": ">=0.24.0"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add file_sync_plugin/__init__.py file_sync_plugin/plugin.json
git commit -m "feat: add plugin metadata and packaging files"
```

---

## 4. 完整测试

**Step 1: 安装依赖**

```bash
pip install nc_py_api APScheduler httpx pytest pytest-asyncio
```

**Step 2: 运行所有测试**

```bash
pytest tests/ -v
```

**Step 3: 验证插件结构**

```bash
ls -la file_sync_plugin/
```

---

## 5. 部署说明

1. 将 `file_sync_plugin` 目录复制到 AstrBot 插件目录
2. 在 AstrBot 管理面板中启用插件
3. 配置 NextCloud 连接信息和群映射
4. 使用 `/同步文件` 命令手动触发首次同步

---

## 6. 设计覆盖检查

| 设计需求 | 实现位置 |
|---------|---------|
| 定时扫描群文件夹 | Task 6: plugin.py (AsyncIOScheduler) |
| 获取群文件列表 | Task 5: file_scanner.py |
| 同步到NextCloud | Task 4: cloud_sync.py |
| 多群配置映射 | Task 1: config.py + Task 6 |
| 文件重命名防冲突 | Task 2: rename.py |
| 重试队列机制 | Task 3: state_manager.py |
| 命令接口(/同步文件等) | Task 6: plugin.py |
| 同步状态记录 | Task 3: state_manager.py |

---

Plan saved to: `docs/superpowers/plans/2026-04-23-qq-group-file-sync-nextcloud-plan.md`
