"""SQLite 单文件存储（stdlib sqlite3，无 ORM）。

三张表：sessions / messages / plugins（启停状态）。换存储是 Service 内部事，接口不变。
trace 不进库：沿用形态.md 的 jsonl（engine 层自转）。
"""
import sqlite3
import threading
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    attachments TEXT NOT NULL DEFAULT '[]',
    meta TEXT NOT NULL DEFAULT '{}',
    edited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE TABLE IF NOT EXISTS plugins (
    id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    meta TEXT NOT NULL DEFAULT '{}'
);
"""


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Database:
    """单连接＋锁：A 期单进程够用；线程安全由锁保证。"""

    def __init__(self, path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.rowcount

    def query_one(self, sql, params=()):
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def query_all(self, sql, params=()):
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        with self._lock:
            self._conn.close()
