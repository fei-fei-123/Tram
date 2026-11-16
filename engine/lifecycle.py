from engine.session import SessionManager
from shared.events import SessionEvent
from shared.models import Message, Session


class Lifecycle:
    """会话级生命周期编排：状态迁移 + 事件派发。

    onTurn/回复主循环归 host 层（host 处理完通知 engine），engine 不触发。
    """

    # TODO host 未实现，接口定为 dispatch(session, messages, event)
    def __init__(self, manager: SessionManager, host) -> None:
        self._manager = manager
        self._host = host

    def on_start(self) -> Session:
        """会话开始"""
        session = self._manager.create_session()
        self._dispatch(session, [], SessionEvent.ON_START)
        return session

    def on_pause(self, session: Session):
        """会话暂停"""
        messages = self._manager.list_messages(session)
        self._dispatch(session, messages, SessionEvent.ON_PAUSE)

    def on_recover(self, session: Session):
        """会话恢复"""
        messages = self._manager.list_messages(session)
        self._dispatch(session, messages, SessionEvent.ON_RECOVER)

    def on_reply(self, session: Session):
        """会话回复"""
        messages = self._manager.list_messages(session)
        self._dispatch(session, messages, SessionEvent.ON_REPLY)

    def on_archive(self, session: Session):
        """会话归档"""
        messages = self._manager.list_messages(session)
        self._manager.archive_session(session)
        self._dispatch(session, messages, SessionEvent.ON_ARCHIVE)

    def on_delete(self, session: Session):
        """会话删除"""
        messages = self._manager.list_messages(session)
        self._manager.delete_session(session)
        self._dispatch(session, messages, SessionEvent.ON_DELETE)

    def _dispatch(self, session: Session, messages: list[Message], event: SessionEvent):
        """向通信层派发生命周期事件"""
        self._host.dispatch(session, messages, event)
