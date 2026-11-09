"""MessageService：消息落库与变更。

append / edit / delete / get / list → message.appended / message.edited / message.deleted
改＝edit（覆盖 content＋置 edited），删＝delete；每次操作必广播。
"""
import json
import uuid

from ..events import EventBus
from ..storage import Database, utcnow

ROLES = ("user", "agent", "plugin")


class MessageService:
    def __init__(self, bus: EventBus, db: Database):
        self._bus = bus
        self._db = db

    def append(self, session_id, role, content, meta=None):
        if role not in ROLES:
            raise ValueError(f"invalid role {role!r}：一期词表只有 user/agent/plugin")
        if self._db.query_one("SELECT id FROM sessions WHERE id=?", (session_id,)) is None:
            raise ValueError(f"session not found: {session_id}")
        msg = {
            "id": f"msg_{uuid.uuid4().hex}",
            "session_id": session_id,
            "role": role,
            "content": content,
            "attachments": [],
            "meta": meta or {},
            "edited": False,
            "created_at": utcnow(),
        }
        self._db.execute(
            "INSERT INTO messages (id, session_id, role, content, attachments, meta, edited, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (msg["id"], session_id, role, content, "[]", "{}", 0, msg["created_at"]),
        )
        self._bus.publish("message.appended", {"message": dict(msg)})
        return msg

    def get(self, message_id):
        row = self._db.query_one("SELECT * FROM messages WHERE id=?", (message_id,))
        return _to_message(row) if row else None

    def edit(self, message_id, content):
        msg = self._require(message_id)
        self._db.execute("UPDATE messages SET content=?, edited=1 WHERE id=?", (content, message_id))
        updated = {**msg, "content": content, "edited": True}
        self._bus.publish("message.edited", {"message": dict(updated)})
        return updated

    def delete(self, message_id):
        msg = self._require(message_id)
        self._db.execute("DELETE FROM messages WHERE id=?", (message_id,))
        self._bus.publish("message.deleted", {"message_id": message_id, "session_id": msg["session_id"]})

    def list(self, session_id):
        rows = self._db.query_all(
            "SELECT * FROM messages WHERE session_id=? ORDER BY created_at ASC, rowid ASC", (session_id,))
        return [_to_message(r) for r in rows]

    def list_recent(self, session_id, limit):
        """近期消息投影：最近 limit 条，按时间正序返回（TurnService 组 ctx 用）。"""
        rows = self._db.query_all(
            "SELECT * FROM messages WHERE session_id=?"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?", (session_id, limit))
        return [_to_message(r) for r in reversed(rows)]

    def _require(self, message_id):
        msg = self.get(message_id)
        if msg is None:
            raise KeyError(f"message not found: {message_id}")
        return msg


def _to_message(row):
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "attachments": json.loads(row["attachments"] or "[]"),
        "meta": json.loads(row["meta"] or "{}"),
        "edited": bool(row["edited"]),
        "created_at": row["created_at"],
    }
