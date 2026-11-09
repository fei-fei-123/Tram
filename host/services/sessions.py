"""SessionService：会话的身份与元数据（会话不是消息容器）。

create / rename / archive / list → session.created / session.updated
"""
import json
import uuid

from ..events import EventBus
from ..storage import Database, utcnow


class SessionService:
    def __init__(self, bus: EventBus, db: Database):
        self._bus = bus
        self._db = db

    def create(self, title=None):
        session = {
            "id": f"sess_{uuid.uuid4().hex}",
            "title": title or "新会话",
            "status": "active",
            "meta": {},
            "created_at": utcnow(),
        }
        self._db.execute(
            "INSERT INTO sessions (id, title, status, meta, created_at) VALUES (?,?,?,?,?)",
            (session["id"], session["title"], session["status"], "{}", session["created_at"]),
        )
        self._bus.publish("session.created", {"session": dict(session)})
        return session

    def get(self, session_id):
        row = self._db.query_one("SELECT * FROM sessions WHERE id=?", (session_id,))
        return _to_session(row) if row else None

    def rename(self, session_id, title):
        session = self._require(session_id)
        self._db.execute("UPDATE sessions SET title=? WHERE id=?", (title, session_id))
        updated = {**session, "title": title}
        self._bus.publish("session.updated", {"session": dict(updated), "changed": ["title"]})
        return updated

    def archive(self, session_id):
        session = self._require(session_id)
        self._db.execute("UPDATE sessions SET status='archived' WHERE id=?", (session_id,))
        updated = {**session, "status": "archived"}
        self._bus.publish("session.updated", {"session": dict(updated), "changed": ["status"]})
        return updated

    def list(self, status=None):
        if status is None:
            rows = self._db.query_all("SELECT * FROM sessions ORDER BY created_at ASC, rowid ASC")
        else:
            rows = self._db.query_all(
                "SELECT * FROM sessions WHERE status=? ORDER BY created_at ASC, rowid ASC", (status,))
        return [_to_session(r) for r in rows]

    def _require(self, session_id):
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")
        return session


def _to_session(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "meta": json.loads(row["meta"] or "{}"),
        "created_at": row["created_at"],
    }
