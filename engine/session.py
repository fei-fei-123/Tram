from dataclasses import dataclass
import time
from typing import Literal

from engine.message import MessageDB
from shared import db_manager
from shared.context import Operation, OperationObjectType, OperationType
from shared.models import Message, Session, SessionType



@dataclass
class SessionQuery:
    """Session查询条件"""
    status: SessionType | None = None
    created_after: int | None = None
    created_before: int | None = None
    modified_before: int | None = None
    modified_after: int | None = None
    order_by: Literal["created", "modified"] | None = None
    desc: bool = False
    limit: int = 50
    offset: int = 0

    def to_params(self):
        return {
            "status": self.status,
            "created_after": self.created_after,
            "created_before": self.created_before,
            "modified_before": self.modified_before,
            "modified_after": self.modified_after,
            "order_by": self.order_by,
            "desc": self.desc,
            "limit": self.limit,
            "offset": self.offset
        }


class SessionDB:
    _PATH = "SESSION"

    _DDL = """
    CREATE TABLE IF NOT EXISTS sessions (
        id       VARCHAR(64) PRIMARY KEY,
        status   VARCHAR(16) DEFAULT 'RUNNING',
        modified BIGINT DEFAULT 0,
        created  BIGINT DEFAULT 0
    );
    """

    # SQL
    _SELECT = "SELECT * FROM sessions WHERE id = :sid;"
    _UPDATE  = "UPDATE sessions SET status = :status, modified = :modified, created = :created where id = :id;"
    _INSERT = "INSERT INTO sessions (id, status, modified, created) VALUES (:id, :status, :modified, :created);"
    
    def __init__(self, db:db_manager.DBManager) -> None:
        # DB
        self._conn = db 

    def ensure_tables(self) -> None:
        """建表"""
        self._conn.execute(self._DDL)

    def get(self, sid: str) -> Session | None:
        """查询Session"""
        row = self._conn.execute(self._SELECT, {"sid": sid}).fetchone()
        if row is None:
            return None
        return self._to_session(row)

    def _to_session(self, row) -> Session:
        """row → 实体"""
        return Session(
            id=row["id"],
            status=SessionType[row["status"]],
            modified=row["modified"],
            created=row["created"],
        )

    def update(self, session: Session):
        """更新Session信息"""
        self._conn.execute(self._UPDATE, session.to_params())

    def insert(self, session:Session):
        """添加Session"""
        self._conn.execute(self._INSERT, session.to_params())

    def list(self, options: SessionQuery | None = None) -> list[Session]:
        """按条件列出会话"""
        options = options or SessionQuery()

        # 条件拼装
        cond = []
        if options.status is not None:
            cond.append("status = :status")
        if options.modified_before is not None:
            cond.append("modified <= :modified_before")
        if options.modified_after is not None:
            cond.append("modified >= :modified_after")
        if options.created_before is not None:
            cond.append("created <= :created_before")
        if options.created_after is not None:
            cond.append("created >= :created_after")

        sql = "SELECT * FROM sessions"
        if cond:
            sql += " WHERE " + " AND ".join(cond)

        if options.order_by is not None:
            direction = "DESC" if options.desc else "ASC"
            sql += f" ORDER BY {options.order_by} {direction}"

        sql += " LIMIT :limit OFFSET :offset"

        rows = self._conn.execute(sql, options.to_params()).fetchall()
        return [self._to_session(row) for row in rows]



class SessionManager:

    def __init__(self, db: SessionDB, message_db: MessageDB) -> None:
        self._sessions: dict[str, Session] = {}
        self._db = db
        self._message_db = message_db


    # ============== 会话管理 ==============
    def get_session(self, sid: str) -> Session | None:
        """获取session信息"""
        session = self._sessions.get(sid)
        if session is None:
            session = self._db.get(sid=sid)
            if session is not None:
                self._sessions[sid] = session

        return session

    def delete_session(self, session:Session):
        """删除Session信息"""
        session.modified = int(time.time())
        session.status = SessionType.DELETED
        self._sessions[session.id] = session
        self._db.update(session=session)

    def archive_session(self, session: Session):
        """归档Session"""
        session.modified = int(time.time())
        session.status = SessionType.ARCHIVED
        self._sessions[session.id] = session
        self._db.update(session=session)

    def create_session(self) -> Session:
        """创建Session"""
        session = Session.create()
        self._db.insert(session=session)
        self._sessions[session.id] = session
        return session

    def list_session(self, options: SessionQuery | None = None) -> list[Session]:
        """列出符合条件的session"""
        return self._db.list(options)

    def update_session(self, session: Session):
        """更新Session信息"""
        session.modified = int(time.time())
        self._db.update(session=session)


    # ============== 消息管理 ==============
    def add_message(self, session: Session, message: Message):
        """添加消息到会话"""
        if session.status is not SessionType.RUNNING:
            raise ValueError(f"session {session.id} 状态为 {session.status.value}，拒收消息")
        session.modified = int(time.time())
        self._db.update(session=session)
        self._message_db.insert(message=message, sid=session.id)
        

    def list_messages(self, session: Session) -> list[Message]:
        """列出会话中的所有消息（纯读，无副作用）"""
        return self._message_db.list_by_session(sid=session.id)

    def delete_message(self, mid: str):
        """删除消息"""
        self._message_db.delete(mid=mid)

    def update_messages(self, session: Session, messages: list[Message]):
        """更新会话中的所有消息"""
        existing_messages = self._message_db.list_by_session(sid=session.id)
        msg_map:dict[str,Message] = {msg.id: msg for msg in existing_messages}
        for message in messages:
            old = msg_map.get(message.id)
            if old is None:
                continue
            if old.content != message.content or old.options != message.options:
                self._message_db.update_content(message.id, message.content, message.options)

    def update_message(self, message: Message):
        """更新会话中的消息"""
        self._message_db.update_content(message.id, message.content, message.options)

    def apply_operations(self, session: Session, changes: list[tuple[Operation, Message | None]]):
        """重放变更操作"""
        for operation, message in changes:
            if operation.type == OperationType.ADD and message is not None:
                self.add_message(session, message)
            elif operation.type == OperationType.WRITE and message is not None:
                self.update_message(message)
            elif operation.type == OperationType.DELETE and operation.object_type == OperationObjectType.SESSION:
                self._message_db.delete_by_session(sid=session.id)
            elif operation.type == OperationType.DELETE:
                # 删除没有实体类
                self.delete_message(operation.object_id)

        session.modified = int(time.time())
        self._db.update(session=session)

                

