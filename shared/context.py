from dataclasses import dataclass, replace
from enum import Enum

from shared.models import Message, Session

class OperationType(str, Enum):
    """操作类型"""
    WRITE = "WRITE"
    ADD = "ADD"
    DELETE = "DELETE"
    READ = "READ"

class OperationObjectType(str, Enum):
    """操作对象类型"""
    MESSAGE = "MESSAGE"
    SESSION = "SESSION"
    

class Operation:
    """操作"""
    object_type: OperationObjectType
    object_id: str
    type: OperationType
    content: str
