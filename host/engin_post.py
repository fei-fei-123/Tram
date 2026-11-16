from engine.host_post import HostPost
from shared.events import SessionEvent
from shared.models import Message, Session


class EnginePost:
    """程序层暴露给通信层的口"""

    def apply_ops(self, session: Session, changes: list):
        """回复结束：积压变更操作发程序层，逐条重放正式入库"""
        pass

class HostGateway(HostPost):

    def dispatch(self, session: Session, message:Message, event: SessionEvent):
        """接受会话事件"""
        # if event == SessionEvent.ON_START:
        #     self._manager.create_session()
        # elif event == SessionEvent.ON_PAUSE:
        #     self._manager.pause_session(session)
        # elif event == SessionEvent.ON_RECOVER:
        #     self._manager.recover_session(session)
        # elif event == SessionEvent.ON_REPLY:
        #     self._manager.reply_session(session)
        # elif event == SessionEvent.ON_ARCHIVE:
        #     self._manager.archive_session(session)
        # elif event == SessionEvent.ON_DELETE:
        #     self._manager.delete_session(session)