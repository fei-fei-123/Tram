from shared.events import SessionEvent
from shared.models import Message, Session


class HostPost:
    """程序层调用通信层的口"""

    def dispatch(self, session: Session, messages: list[Message], event: SessionEvent):
        """派发会话生命周期事件"""
        pass
