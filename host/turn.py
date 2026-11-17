import uuid

from host.chain import ChainManager
from shared.config import ConfigDB
from host.engin_post import EnginePost
from host.operation import OperationManager
from shared.events import SessionEvent
from shared.models import Message, Session


class TurnManager:
    """轮次管理器"""

    def __init__(self, chain_manager: ChainManager, operation_manager: OperationManager, engine_post: EnginePost, config_db: ConfigDB) -> None:
        self._turn_id = ""
        self._new_turn = False
        self._chain_manager = chain_manager
        self._operation_manager = operation_manager
        self._session = None
        self._engine_post = engine_post
        self._config_db = config_db

    def start_turn(self) -> None:
        """开始一个新轮次"""
        max_turn_count = int(self._config_db.get("MAX_TURN_COUNT") or "8")
        try:
            self._new_turn = True
            # 轮次开始
            while self._new_turn and max_turn_count > 0:
                self._turn_id = str(uuid.uuid4())
                self._new_turn = False
                self._operation_manager.set_turn_id(self._turn_id)
                self._chain_manager.run_chain(SessionEvent.ON_TURN)
                # 是否需要新轮次
                self._new_turn = self._operation_manager.take_new_turn()
                max_turn_count -= 1
        except Exception as e:
            self._operation_manager.submit_error(error="轮次未成功执行，见失败日志")
            print(e)

    def start_reply(self, session: Session, messages: list[Message]) -> None:
        """开始一个新回复"""
        try:
            self._session = session
            self._operation_manager.set_context(session, messages)
            self._chain_manager.run_chain(SessionEvent.ON_REPLY, self.start_turn)
        except Exception as e:
            self._operation_manager.submit_error(error="轮次生成失败，见失败日志")
            print(e)
        finally:
            self.complete_turn()

    def complete_turn(self) -> None:
        """完成当前轮次"""
        operations = self._operation_manager.commit()
        self._turn_id = ""
        self._new_turn = False
        if self._session is not None:
            self._engine_post.apply_ops(self._session, operations)
