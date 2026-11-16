from dataclasses import dataclass, field

from enum import Enum
import json
import time
import uuid

class RoleType(str, Enum):
    """角色类型"""
    AI = "AI"
    PLUGIN = "PLUGIN"
    USER = "USER"
    SYSTEM = "SYSTEM"


class SessionType(str, Enum):
    """会话状态"""
    RUNNING = "RUNNING"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


@dataclass
class Message:
    """消息类型。created=发言时间；modified=最后编辑时间（编辑语义未定稿，默认流程当作不可变）"""
    id: str
    role: RoleType
    content: str
    created: int
    modified: int
    options: dict = field(default_factory=dict)

    @classmethod
    def create(cls, role: RoleType, content: str, options: dict | None = None) -> "Message":
        now = int(time.time())
        return cls(
            id=uuid.uuid4().hex,
            role=role,
            content=content,
            created=now,
            modified=now,
            options=options or {},
        )

    def to_params(self) -> dict:
        return {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            # 库里存JSON串
            "options": json.dumps(self.options, ensure_ascii=False),
            "created": self.created,
            "modified": self.modified,
        }


@dataclass
class Session:
    """会话"""
    id: str
    status: SessionType
    modified: int # 修改时间
    created: int # 创建时间

    @classmethod
    def create(cls) -> "Session":
        now = int(time.time())
        return cls(
            id=uuid.uuid4().hex,
            status=SessionType.RUNNING,
            modified=now,
            created=now,
        )

    def to_params(self) -> dict:
        return {
            "id": self.id,
            "status": self.status.value,
            "modified": self.modified,
            "created": self.created,
        }

