from engine.lifecycle import Lifecycle
from engine.message import MessageDB
from engine.session import SessionDB, SessionManager
from host.chain import ChainManager
from host.engin_post import EnginePost, HostGateway
from host.operation import OperationDB, OperationLog, OperationManager
from host.plugin import PluginDB, PluginManager
from host.turn import TurnManager
from shared import db_manager
from shared.events import PluginEvent


def build(db_path: str, plugin_dir: str):
    """组装三层，返回生命周期入口与会话管理器"""
    # 库与表
    db = db_manager.db
    db.connect(db_path)
    session_db = SessionDB(db)
    session_db.ensure_tables()
    message_db = MessageDB(db)
    message_db.ensure_tables()
    op_db = OperationDB(db)
    op_db.ensure_tables()

    # 程序层
    session_manager = SessionManager(session_db, message_db)

    # 通信层
    op_manager = OperationManager(OperationLog(op_db))
    chain_manager = ChainManager(op_manager)
    plugin_manager = PluginManager(PluginDB(), plugin_dir, chain_manager)
    plugin_manager.load_plugin()
    # 通知插件装配链
    plugin_manager.run_method(PluginEvent.ON_LOAD)
    engine_post = EnginePost(session_manager)
    turn_manager = TurnManager(chain_manager, op_manager, engine_post)
    gateway = HostGateway(chain_manager, turn_manager)

    return Lifecycle(session_manager, gateway), session_manager
