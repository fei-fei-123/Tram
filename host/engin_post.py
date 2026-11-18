from engine.host_post import HostPost
from engine.session import SessionManager
from shared.events import SessionEvent
from shared.models import Message, Session


class EnginePost:
    """程序层暴露给通信层的口"""

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager

    def apply_ops(self, session: Session, changes: list):
        """回复结束：积压变更操作发程序层，逐条重放正式入库"""
        self._session_manager.apply_operations(session, changes)


class HostGateway(HostPost):

    def __init__(self, chain_manager: "ChainManager", turn_manager: "TurnManager") -> None:  # pyright: ignore[reportUndefinedVariable]
        self._chain_manager = chain_manager
        self._turn_manager = turn_manager

    def dispatch(self, session: Session, messages: list[Message], event: SessionEvent):
        """接受会话事件：回复走回复管线，其余直接跑链"""
        if event == SessionEvent.ON_REPLY:
            self._turn_manager.start_reply(session, messages)
        elif event == SessionEvent.ON_START:
            self._turn_manager.start_session(session, messages)
        elif event == SessionEvent.ON_TURN:
            # 虽然不知道有什么意义，但还是加上吧，说不定后续会用到
            self._turn_manager.start_turn()
        elif event == SessionEvent.ON_ARCHIVE:
            self._turn_manager.archive_session(session, messages)
        elif event == SessionEvent.ON_DELETE:
            self._turn_manager.delete_session(session, messages)
        elif event == SessionEvent.ON_PAUSE:
            self._turn_manager.pause_session(session, messages)
        elif event == SessionEvent.ON_RECOVER:
            self._turn_manager.recover_session(session, messages)
