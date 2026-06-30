import sqlite3
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from ..models.sync_record import SyncRecord
from ..utils.constants import CN_TZ

class StateManager:
    """同步状态管理器，使用SQLite存储"""

    def __init__(self, db_path: str = "file_sync_state.db"):
        self.db_path = db_path
        self._conn = None
        self._diagnostic_logs = []  # 诊断日志收集器
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
        # 预设路径表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS preset_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                remote_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        # 群绑定表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS group_bindings (
                group_id TEXT PRIMARY KEY,
                path_id INTEGER NOT NULL,
                bound_at TEXT NOT NULL,
                FOREIGN KEY (path_id) REFERENCES preset_paths(id)
            )
        """)
        conn.commit()

    def is_synced(self, file_id: str) -> bool:
        """检查文件是否已同步（基于 file_id）"""
        if not file_id:
            return False
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT 1 FROM sync_records WHERE file_id = ?", (file_id,)
        )
        return cursor.fetchone() is not None

    def is_synced_by_name_size(self, file_name: str, file_size: int, group_id: str) -> bool:
        """检查文件是否已同步（基于文件名+大小+群号）"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT 1 FROM sync_records WHERE file_name = ? AND file_size = ? AND group_id = ?",
            (file_name, file_size, group_id)
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
        """加入重试队列（UPSERT 原子操作，避免并发竞态）"""
        from datetime import timedelta
        next_retry = (datetime.now(CN_TZ) + timedelta(seconds=delay_seconds)).isoformat()
        conn = self._get_conn()

        conn.execute("""
            INSERT INTO retry_queue
                (file_id, file_name, file_size, group_id, target_path, attempts, next_retry, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(file_id) DO UPDATE SET
                attempts = attempts + 1,
                next_retry = excluded.next_retry,
                file_name = excluded.file_name,
                file_size = excluded.file_size,
                group_id = excluded.group_id,
                target_path = excluded.target_path
        """, (file_id, file_name, file_size, group_id, target_path, next_retry, datetime.now(CN_TZ).isoformat()))
        conn.commit()

    def get_pending_retries(self) -> List[dict]:
        """获取待处理的重试项"""
        now = datetime.now(CN_TZ).isoformat()
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
        """获取同步统计（总览）"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM sync_records").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM retry_queue").fetchone()[0]
        return {"total_synced": total, "pending_retries": pending}

    def get_sync_stats_by_group(self) -> dict:
        """获取分群同步统计"""
        conn = self._get_conn()

        # 获取每个群的同步文件数
        cursor = conn.execute(
            "SELECT group_id, COUNT(*) as count FROM sync_records GROUP BY group_id"
        )
        synced_by_group = {row[0]: row[1] for row in cursor.fetchall()}

        # 获取每个群的待重试数
        cursor = conn.execute(
            "SELECT group_id, COUNT(*) as count FROM retry_queue GROUP BY group_id"
        )
        pending_by_group = {row[0]: row[1] for row in cursor.fetchall()}

        # 获取每个群的最后同步时间
        cursor = conn.execute(
            "SELECT group_id, last_sync_time FROM last_sync_times"
        )
        last_sync_by_group = {row[0]: row[1] for row in cursor.fetchall()}

        # 合并数据
        all_groups = set(synced_by_group.keys()) | set(pending_by_group.keys()) | set(last_sync_by_group.keys())
        stats_by_group = {}
        for group_id in all_groups:
            stats_by_group[group_id] = {
                "synced": synced_by_group.get(group_id, 0),
                "pending": pending_by_group.get(group_id, 0),
                "last_sync_time": last_sync_by_group.get(group_id, None)
            }

        return stats_by_group

    def get_group_stats(self, group_id: str) -> dict:
        """获取指定群的详细统计"""
        conn = self._get_conn()

        # 获取该群的同步文件数
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sync_records WHERE group_id = ?", (group_id,)
        )
        synced = cursor.fetchone()[0]

        # 获取该群的待重试数
        cursor = conn.execute(
            "SELECT COUNT(*) FROM retry_queue WHERE group_id = ?", (group_id,)
        )
        pending = cursor.fetchone()[0]

        # 获取该群的最后同步时间
        cursor = conn.execute(
            "SELECT last_sync_time FROM last_sync_times WHERE group_id = ?", (group_id,)
        )
        row = cursor.fetchone()
        last_sync_time = row[0] if row else None

        # 获取该群最近同步的文件列表
        cursor = conn.execute(
            "SELECT file_name, file_size, sync_time FROM sync_records WHERE group_id = ? ORDER BY sync_time DESC LIMIT 10",
            (group_id,)
        )
        recent_files = [{"name": row[0], "size": row[1], "time": row[2]} for row in cursor.fetchall()]

        return {
            "group_id": group_id,
            "synced": synced,
            "pending": pending,
            "last_sync_time": last_sync_time,
            "recent_files": recent_files
        }

    def add_diagnostic_log(self, log_type: str, message: str, data: dict = None):
        """添加诊断日志"""
        log_entry = {
            "timestamp": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "type": log_type,
            "message": message,
            "data": data or {}
        }
        self._diagnostic_logs.append(log_entry)
        # 只保留最近 100 条日志
        if len(self._diagnostic_logs) > 100:
            self._diagnostic_logs = self._diagnostic_logs[-100:]

    def get_diagnostic_logs(self, log_type: str = None, limit: int = 50) -> List[dict]:
        """获取诊断日志"""
        if log_type:
            filtered = [log for log in self._diagnostic_logs if log["type"] == log_type]
        else:
            filtered = self._diagnostic_logs
        return filtered[-limit:]

    def clear_diagnostic_logs(self):
        """清空诊断日志"""
        self._diagnostic_logs.clear()

    def get_last_sync_time(self, group_id: str) -> Optional[datetime]:
        """获取指定群的上次同步时间"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT last_sync_time FROM last_sync_times WHERE group_id = ?",
            (group_id,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            dt = datetime.fromisoformat(row[0])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CN_TZ)
            return dt
        return None

    def update_last_sync_time(self, group_id: str, sync_time: datetime):
        """更新指定群的上次同步时间"""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO last_sync_times (group_id, last_sync_time)
            VALUES (?, ?)
        """, (group_id, sync_time.isoformat()))
        conn.commit()

    def populate_from_remote_list(self, remote_files: List[dict], group_id: str):
        """从 NextCloud 远程文件列表批量写入 SQLite，用于插件启动时预热查重数据

        remote_files: list of dict，每项包含 file_name, file_size, remote_path

        注意：预热数据主要用于 is_synced_by_name_size()（文件名+大小+群号去重），
        因为 QQ file_id 与 remote_path 不同 namespace，is_synced(file_id) 无法命中预热记录。
        但五层过滤中第4层 name+size 去重会生效，此场景已覆盖。
        """
        conn = self._get_conn()
        now = datetime.now(CN_TZ).isoformat()
        for item in remote_files:
            # 使用合成 file_id（remote_path 加前缀），避免与 QQ file_id namespace 冲突
            synthetic_file_id = f"warmup:{item['remote_path']}"
            conn.execute("""
                INSERT OR IGNORE INTO sync_records
                (file_id, file_name, file_size, group_id, target_path, sync_time)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                synthetic_file_id,
                item["file_name"],
                item.get("file_size", 0),
                group_id,
                item["remote_path"],
                now
            ))
        conn.commit()

    # ──────── 预设路径管理 ────────

    def add_preset_path(self, name: str, remote_path: str) -> tuple:
        """添加预设路径

        Returns:
            (success, message)
        """
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO preset_paths (name, remote_path, created_at) VALUES (?, ?, ?)",
                (name, remote_path, datetime.now(CN_TZ).isoformat())
            )
            conn.commit()
            return True, f"预设路径已添加: {name} → {remote_path}"
        except sqlite3.IntegrityError:
            # 名称已存在，更新路径
            conn.execute(
                "UPDATE preset_paths SET remote_path = ? WHERE name = ?",
                (remote_path, name)
            )
            conn.commit()
            return True, f"预设路径已更新: {name} → {remote_path}"

    def delete_preset_path(self, name: str) -> tuple:
        """删除预设路径

        如果该路径已绑定群，阻止删除。
        """
        conn = self._get_conn()
        # 查 id
        row = conn.execute("SELECT id FROM preset_paths WHERE name = ?", (name,)).fetchone()
        if not row:
            return False, f"预设路径不存在: {name}"
        path_id = row[0]
        # 查绑定
        binding = conn.execute(
            "SELECT group_id FROM group_bindings WHERE path_id = ?", (path_id,)
        ).fetchone()
        if binding:
            return False, f"路径 {name} 已绑定群 {binding[0]}，请先解绑"
        conn.execute("DELETE FROM preset_paths WHERE id = ?", (path_id,))
        conn.commit()
        return True, f"预设路径已删除: {name}"

    def list_preset_paths(self) -> List[dict]:
        """列出所有预设路径，包含各路径绑定的群号列表"""
        conn = self._get_conn()
        rows = conn.execute("SELECT id, name, remote_path, created_at FROM preset_paths ORDER BY name").fetchall()
        result = []
        for r in rows:
            groups = conn.execute(
                "SELECT group_id FROM group_bindings WHERE path_id = ?", (r[0],)
            ).fetchall()
            result.append({
                "id": r[0],
                "name": r[1],
                "remote_path": r[2],
                "created_at": r[3],
                "bound_groups": [g[0] for g in groups],
            })
        return result

    def get_preset_path_by_name(self, name: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, name, remote_path FROM preset_paths WHERE name = ?", (name,)
        ).fetchone()
        if row:
            return {"id": row[0], "name": row[1], "remote_path": row[2]}
        return None

    def get_preset_path_by_id(self, path_id: int) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, name, remote_path FROM preset_paths WHERE id = ?", (path_id,)
        ).fetchone()
        if row:
            return {"id": row[0], "name": row[1], "remote_path": row[2]}
        return None

    # ──────── 群绑定管理 ────────

    def bind_group(self, group_id: str, path_name: str) -> tuple:
        """绑定群到预设路径

        Returns:
            (success, message)
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, remote_path FROM preset_paths WHERE name = ?", (path_name,)
        ).fetchone()
        if not row:
            return False, f"预设路径不存在: {path_name}"
        path_id, remote_path = row
        conn.execute(
            "INSERT OR REPLACE INTO group_bindings (group_id, path_id, bound_at) VALUES (?, ?, ?)",
            (group_id, path_id, datetime.now(CN_TZ).isoformat())
        )
        conn.commit()
        return True, f"群 {group_id} 已绑定到 {path_name} ({remote_path})"

    def unbind_group(self, group_id: str) -> tuple:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT p.name FROM group_bindings g JOIN preset_paths p ON g.path_id = p.id WHERE g.group_id = ?",
            (group_id,)
        ).fetchone()
        if not row:
            return False, f"群 {group_id} 未绑定任何路径"
        conn.execute("DELETE FROM group_bindings WHERE group_id = ?", (group_id,))
        conn.commit()
        return True, f"群 {group_id} 已解除与 {row[0]} 的绑定"

    def get_group_binding(self, group_id: str) -> Optional[str]:
        """获取群绑定的预设路径（返回 remote_path），未绑定返回 None"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT p.remote_path FROM group_bindings g JOIN preset_paths p ON g.path_id = p.id WHERE g.group_id = ?",
            (group_id,)
        ).fetchone()
        return row[0] if row else None

    def get_group_binding_detail(self, group_id: str) -> Optional[dict]:
        """获取群绑定的预设路径详情"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT p.name, p.remote_path, g.bound_at FROM group_bindings g "
            "JOIN preset_paths p ON g.path_id = p.id WHERE g.group_id = ?",
            (group_id,)
        ).fetchone()
        if row:
            return {"name": row[0], "remote_path": row[1], "bound_at": row[2]}
        return None

    def list_group_bindings(self) -> List[dict]:
        """列出所有群绑定关系"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT g.group_id, p.name, p.remote_path, g.bound_at "
            "FROM group_bindings g JOIN preset_paths p ON g.path_id = p.id ORDER BY g.group_id"
        ).fetchall()
        return [
            {"group_id": r[0], "name": r[1], "remote_path": r[2], "bound_at": r[3]}
            for r in rows
        ]