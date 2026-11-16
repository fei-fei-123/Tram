from dataclasses import dataclass, field
from enum import Enum

class OperationType(str, Enum):
    """操作类型"""
    READ = "read"
    ADD = "add"
    WRITE = "write"
    DELETE = "delete"
    NEW_TURN = "new_turn"

class OperationObjectType(str, Enum):
    """操作对象类型"""
    SESSION = "session"
    MESSAGE = "message"
    REPLY = "reply"

@dataclass
class Operation:
    """操作体"""
    object_type: OperationObjectType
    type: OperationType
    object_id: str = ""     # message时为消息id，其余留空
    role: str = "PLUGIN"    # 仅add有效，可指定任意角色
    content: str = ""       # add/write时为消息内容
    options: dict = field(default_factory=dict)   # add/write时随消息一并替换

@dataclass
class OperationResult:
    """操作结果"""
    ok: bool
    data: object = None
    reason: str = ""
