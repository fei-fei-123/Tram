import json
import time

from shared import db_manager
from shared.models import Message, RoleType


class MessageDB:
    """messages 表的 SQL 层。"""

    _DDL_TABLE = """
    CREATE TABLE IF NOT EXISTS messages (
        id         VARCHAR(64) PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        role       VARCHAR(16) NOT NULL,
        content    TEXT        NOT NULL,
        options    TEXT        NOT NULL,
        created    BIGINT      NOT NULL,
        modified   BIGINT      NOT NULL
    );
    """

    _DDL_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_messages_session
        ON messages (session_id, created);
    """

    # SQL
    _INSERT = "INSERT INTO messages (id, session_id, role, content, options, created, modified) VALUES (:id, :session_id, :role, :content, :options, :created, :modified);"
    _UPDATE = "UPDATE messages SET content = :content, options = :options, modified = :modified WHERE id = :id;"
    _SELECT = "SELECT * FROM messages WHERE id = :id;"
    _LIST_BY_SESSION = "SELECT * FROM messages WHERE session_id = :sid ORDER BY created;"
    _DELETE = "DELETE FROM messages WHERE id = :id;"
    _DELETE_BY_SESSION = "DELETE FROM messages WHERE session_id = :sid;"

    def __init__(self, db: db_manager.DBManager) -> None:
        self._conn = db

    def ensure_tables(self) -> None:
        """建表 + 建索引。"""
        self._conn.execute(self._DDL_TABLE)
        self._conn.execute(self._DDL_INDEX)

    def insert(self, message: Message, sid: str) -> None:
        """消息落库"""
        params = message.to_params()
        params["session_id"] = sid
        self._conn.execute(self._INSERT, params)

    def get(self, mid: str) -> Message | None:
        """按消息 id 查单条。"""
        row = self._conn.execute(self._SELECT, {"id": mid}).fetchone()
        if row is None:
            return None
        return self._to_message(row)

    def list_by_session(self, sid: str) -> list[Message]:
        """拉取一个会话的全部消息，按时间序。"""
        rows = self._conn.execute(self._LIST_BY_SESSION, {"sid": sid}).fetchall()
        return [self._to_message(row) for row in rows]

    def delete(self, mid: str) -> None:
        """抛弃单条消息。"""
        self._conn.execute(self._DELETE, {"id": mid})

    def delete_by_session(self, sid: str) -> None:
        """清空会话的全部消息"""
        self._conn.execute(self._DELETE_BY_SESSION, {"sid": sid})

    def update_content(self, mid: str, content: str, options: dict) -> None:
        """编辑消息内容"""
        self._conn.execute(self._UPDATE, {
            "id": mid,
            "content": content,
            # 整条替换语义，options一并覆盖
            "options": json.dumps(options, ensure_ascii=False),
            "modified": int(time.time()),
        })

    def _to_message(self, row) -> Message:
        """row → 实体"""
        return Message(
            id=row["id"],
            role=RoleType[row["role"]],
            content=row["content"],
            created=row["created"],
            modified=row["modified"],
            options=json.loads(row["options"]),
        )
