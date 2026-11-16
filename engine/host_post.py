from shared.events import SessionEvent
from shared.models import Message, Session


class HostPost:
    
    def dispatch(self, session: Session, message:Message, event: SessionEvent):
        pass