import json
import time
from copy import deepcopy
from dataclasses import dataclass, replace

from shared import db_manager
from shared.context import Operation, OperationObjectType, OperationResult, OperationType
from shared.models import Message, RoleType, Session

def _clone_message(message: Message) -> Message:
    """深拷贝一条消息"""
    clone = replace(message)
    clone.options = deepcopy(message.options)
    return clone

def _msg_json(message: Message) -> str:
    """消息的日志形态"""
    body = {
        "id": message.id,
        "role": message.role.value,
        "content": message.content,
        "options": message.options,
    }
    return json.dumps(body, ensure_ascii=False)

def _op_json(operation: Operation) -> str:
    """操作的日志形态"""
    body = {
        "object_type": operation.object_type.value,
        "object_id": operation.object_id,
        "type": operation.type.value,
        "role": operation.role,
        "content": operation.content,
        "options": operation.options,
    }
    return json.dumps(body, ensure_ascii=False)

def _val_json(value) -> str | None:
    """before/after的日志形态，空为null"""
    if value is None:
        return None
    if isinstance(value, Message):
        return _msg_json(value)
    if isinstance(value, list):
        return json.dumps([json.loads(_msg_json(m)) for m in value], ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)

@dataclass
class Context:
    """上下文"""
    session: Session
    messages: list[Message]

    @classmethod
    def create(cls, session: Session, messages: list[Message]) -> 'Context':
        """创建上下文"""
        msg_clones = [_clone_message(m) for m in messages]

        return cls(
            session=replace(session),
            messages=msg_clones,
        )

class OperationDB:
    """operation_log表的SQL层"""

    _DDL_TABLE = """
    CREATE TABLE IF NOT EXISTS operation_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id VARCHAR(64) NOT NULL,
        turn_id    VARCHAR(64) NOT NULL,
        plugin     VARCHAR(64) NOT NULL,
        operation  TEXT        NOT NULL,
        before     TEXT,
        after      TEXT,
        status     VARCHAR(16) NOT NULL
    );
    """

    _INSERT = "INSERT INTO operation_log (session_id, turn_id, plugin, operation, before, after, status) VALUES (:session_id, :turn_id, :plugin, :operation, :before, :after, :status);"
    _LIST_BY_SESSION = "SELECT * FROM operation_log WHERE session_id = :sid ORDER BY id;"

    def __init__(self, db: db_manager.DBManager) -> None:
        self._conn = db

    def ensure_tables(self) -> None:
        """建表"""
        self._conn.execute(self._DDL_TABLE)

    def append(self, record: dict) -> int | None:
        """写一条日志，返回日志序号"""
        cur = self._conn.execute(self._INSERT, record)
        return cur.lastrowid

    def list_by_session(self, sid: str) -> list[dict]:
        """拉一个会话的全部日志，按序号升序"""
        rows = self._conn.execute(self._LIST_BY_SESSION, {"sid": sid}).fetchall()
        return [dict(row) for row in rows]

class OperationLog:
    """操作日志"""

    def __init__(self, db: OperationDB) -> None:
        self._db = db

    def ensure_tables(self) -> None:
        """建表"""
        self._db.ensure_tables()

    def append(self, session_id: str, turn_id: str, plugin: str, operation: Operation, before, after, status: str) -> int | None:
        """写一条日志，返回日志序号"""
        record = {
            "session_id": session_id,
            "turn_id": turn_id,
            "plugin": plugin,
            "operation": _op_json(operation),
            "before": _val_json(before),
            "after": _val_json(after),
            "status": status,
        }
        return self._db.append(record)

class OperationManager:
    """操作受理器"""

    def __init__(self, opLog: OperationLog) -> None:
        self._opLog = opLog
        self._context: Context | None = None
        self._new_turn = False
        self._turn_id = ""
        self._pending: list[tuple[Operation, Message | None]] = []

    def set_context(self, session: Session, messages: list[Message]) -> None:
        """设置上下文，开新回复时调用"""
        self._context = Context.create(session, messages)
        self._new_turn = False
        self._pending = []

    def set_turn_id(self, turn_id: str) -> None:
        """设置当前轮次id"""
        self._turn_id = turn_id

    def submit_error(self, plugin:str="", error:str=""):
        """提交错误"""
        if self._context is None:
            session_id = turn_id = ""
            before = after = ""
        else:
            session_id = self._context.session.id
            turn_id = self._turn_id
            before = self._context.messages[-1] if self._context.messages else ""
            after = before
        op = Operation(
            object_type=OperationObjectType.ERROR,
            type=OperationType.ERROR,
            role="PLUGIN",
            content=error,
        )
        self._opLog.append(session_id, turn_id, plugin, op, before, after, "fail")
        

    def submit(self, plugin: str, operation: Operation) -> OperationResult:
        """插件提交操作：受理、改上下文、记日志"""
        if self._context is None:
            return OperationResult(False, None, "上下文未初始化")

        result, before, after = self._handle(operation)
        if result.ok and operation.type in _MUTATING:
            pending_op = operation
            if operation.type == OperationType.ADD:
                # add回填临时id
                pending_op = replace(operation, object_id=result.data)
            self._pending.append((pending_op, after if isinstance(after, Message) else None))
        self._opLog.append(self._context.session.id, self._turn_id, plugin, operation, before, after, "ok" if result.ok else "fail")
        return result

    def take_new_turn(self) -> bool:
        """读取续轮申请并复位"""
        requested = self._new_turn
        self._new_turn = False
        return requested

    def commit(self) -> list[tuple[Operation, Message | None]]:
        """回复结束：交出积压的变更操作，交程序层重放入库"""
        changes = self._pending
        self._pending = []
        self._context = None
        return changes

    # ============== 各操作的处理 ==============
    def _handle(self, operation: Operation):
        """按对象+类型分发，返回（结果，before，after）"""
        handler = _HANDLERS.get((operation.object_type, operation.type))
        if handler is None:
            return OperationResult(False, None, "非法操作组合"), None, None
        return handler(self, operation)

    def _find(self, mid: str) -> Message | None:
        """按id找工作集里的消息"""
        if self._context is None:
            return None
        for m in self._context.messages:
            if m.id == mid:
                return m
        return None

    def _session_read(self, operation: Operation):
        """读取全部消息的克隆列表"""
        if self._context is None:
            return OperationResult(False, None, "上下文未初始化"), None, None
        clones = [_clone_message(m) for m in self._context.messages]
        return OperationResult(True, clones, ""), None, None

    def _session_add(self, operation: Operation):
        """末尾追加一条消息，返回新消息id"""
        if self._context is None:
            return OperationResult(False, None, "上下文未初始化"), None, None
        if operation.role not in RoleType.__members__:
            return OperationResult(False, None, f"非法角色 {operation.role}"), None, None
        message = Message.create(RoleType[operation.role], operation.content, deepcopy(operation.options))
        self._context.messages.append(message)
        return OperationResult(True, message.id, ""), None, message

    def _session_delete(self, operation: Operation):
        """清空消息列表"""
        if self._context is None:
            return OperationResult(False, None, "上下文未初始化"), None, None
        removed = self._context.messages
        self._context.messages = []
        return OperationResult(True, len(removed), ""), removed, None

    def _message_read(self, operation: Operation):
        """读取单条消息的克隆"""
        message = self._find(operation.object_id)
        if message is None:
            return OperationResult(False, None, "消息不存在"), None, None
        return OperationResult(True, _clone_message(message), ""), None, None

    def _message_write(self, operation: Operation):
        """整条替换消息内容"""
        message = self._find(operation.object_id)
        if message is None:
            return OperationResult(False, None, "消息不存在"), None, None
        old = _clone_message(message)
        message.content = operation.content
        message.options = deepcopy(operation.options)
        message.modified = int(time.time())
        return OperationResult(True, None, ""), old, message

    def _message_delete(self, operation: Operation):
        """删除一条消息"""
        if self._context is None:
            return OperationResult(False, None, "上下文未初始化"), None, None
        message = self._find(operation.object_id)
        if message is None:
            return OperationResult(False, None, "消息不存在"), None, None
        self._context.messages.remove(message)
        return OperationResult(True, None, ""), message, None

    def _reply_new_turn(self, operation: Operation):
        """申请续轮"""
        self._new_turn = True
        return OperationResult(True, None, ""), None, None

_MUTATING = {OperationType.ADD, OperationType.WRITE, OperationType.DELETE}

_HANDLERS = {
    (OperationObjectType.SESSION, OperationType.READ): OperationManager._session_read,
    (OperationObjectType.SESSION, OperationType.ADD): OperationManager._session_add,
    (OperationObjectType.SESSION, OperationType.DELETE): OperationManager._session_delete,
    (OperationObjectType.MESSAGE, OperationType.READ): OperationManager._message_read,
    (OperationObjectType.MESSAGE, OperationType.WRITE): OperationManager._message_write,
    (OperationObjectType.MESSAGE, OperationType.DELETE): OperationManager._message_delete,
    (OperationObjectType.REPLY, OperationType.NEW_TURN): OperationManager._reply_new_turn,
}
