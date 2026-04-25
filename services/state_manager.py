import sqlite3
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from file_sync_plugin.models.sync_record import SyncRecord

class StateManager:
    """同步状态管理器，使用SQLite存储"""

    def __init__(self, db_path: str = "file_sync_state.db"):
        self.db_path = db_path
        self._conn = None
        self._init_db()

    def _get_conn(self):
        """获取数据库连接（复用模式）"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
        return self._conn

    def close(self):
        """关闭数据库连接"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
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
                file_id TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                file_size INTEGER,
                group_id TEXT NOT NULL,
                target_path TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                next_retry TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS last_sync_times (
                group_id TEXT PRIMARY KEY,
                last_sync_time TEXT NOT NULL
            )
        """)
        conn.commit()

    def is_synced(self, file_id: str) -> bool:
        """检查文件是否已同步"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT 1 FROM sync_records WHERE file_id = ?", (file_id,)
        )
        return cursor.fetchone() is not None

    def add_sync_record(self, record: SyncRecord):
        """添加同步记录"""
        conn = self._get_conn()
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
        from datetime import timedelta
        next_retry = (datetime.now() + timedelta(seconds=delay_seconds)).isoformat()
        conn = self._get_conn()

        # 先尝试UPDATE，累加attempts
        cursor = conn.execute("""
            UPDATE retry_queue SET attempts = attempts + 1, next_retry = ?,
            file_name = ?, file_size = ?, group_id = ?, target_path = ?
            WHERE file_id = ?
        """, (next_retry, file_name, file_size, group_id, target_path, file_id))

        # 如果没有更新任何行（记录不存在），则插入新记录
        if cursor.rowcount == 0:
            conn.execute("""
                INSERT INTO retry_queue
                (file_id, file_name, file_size, group_id, target_path, attempts, next_retry, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (file_id, file_name, file_size, group_id, target_path, 1, next_retry, datetime.now().isoformat()))
        conn.commit()

    def get_pending_retries(self) -> List[dict]:
        """获取待处理的重试项"""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT file_id, file_name, file_size, group_id, target_path, attempts FROM retry_queue WHERE next_retry <= ?",
            (now,)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def remove_from_retry_queue(self, file_id: str):
        """从重试队列移除"""
        conn = self._get_conn()
        conn.execute("DELETE FROM retry_queue WHERE file_id = ?", (file_id,))
        conn.commit()

    def get_sync_stats(self) -> dict:
        """获取同步统计"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM sync_records").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM retry_queue").fetchone()[0]
        return {"total_synced": total, "pending_retries": pending}

    def get_last_sync_time(self, group_id: str) -> Optional[datetime]:
        """获取指定群的上次同步时间"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT last_sync_time FROM last_sync_times WHERE group_id = ?",
            (group_id,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None

    def update_last_sync_time(self, group_id: str, sync_time: datetime):
        """更新指定群的上次同步时间"""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO last_sync_times (group_id, last_sync_time)
            VALUES (?, ?)
        """, (group_id, sync_time.isoformat()))
        conn.commit()