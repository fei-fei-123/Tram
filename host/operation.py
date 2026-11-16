from copy import deepcopy
from dataclasses import dataclass, replace
from sqlite3 import Connection

from shared.models import Message, Session

@dataclass
class Context:
    """上下文"""
    session: Session
    messages: list[Message]

    @classmethod
    def create(cls, session: Session, messages: list[Message]) -> 'Context':
        """创建上下文"""
        # 深拷贝
        msg_clones = []
        for m in messages:
            c = replace(m)
            c.options = deepcopy(m.options)
            msg_clones.append(c)

        return cls(
            session=replace(session),
            messages=msg_clones,
        )

class OperationDB:
    """操作数据库"""
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

class OperationLog:
    """操作日志"""
    def __init__(self, db: OperationDB) -> None:
        self._db = db

class OperationManager:
    """操作管理器"""
    def __init__(self, opLog: OperationLog) -> None:
        self._opLog = opLog
        self._context = None

    def set_context(self, session: Session, messages: list[Message]) -> None:
        """设置上下文"""
        self._context = Context.create(session, messages)

