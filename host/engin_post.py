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
        else:
            self._chain_manager.run_chain(event)
