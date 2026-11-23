from engine.lifecycle import Lifecycle
from engine.message import MessageDB
from engine.session import SessionDB, SessionManager
from host.chain import ChainManager
from host.engin_post import EnginePost, HostGateway
from host.operation import OperationDB, OperationLog, OperationManager
from host.plugin import PluginDB, PluginManager
from host.turn import TurnManager
from shared import db_manager
from shared.config import ConfigDB
from shared.events import PluginEvent

# 一次性种子的目标链序（目录扫描的字母序不符合需要）
_SEED_ORDER = ("prompt", "llm", "fs", "shell", "Tram-Plugin-NetworkSearch")
# 一次性停用的演示插件（hello 每轮强插消息且必续轮，会污染真实会话）
_SEED_DISABLE = ("hello", "byebye")


def _seed_defaults(config_db: ConfigDB, plugin_manager: PluginManager) -> None:
    """首次构建时的一次性种子：链序、停用演示插件、轮次上限"""
    if config_db.get("tram.core_seeded"):
        return
    index = 0
    for pid in _SEED_ORDER:
        if pid in plugin_manager.plugins:
            plugin_manager.move(pid, index)
            index += 1
    for pid in _SEED_DISABLE:
        if pid in plugin_manager.plugins and plugin_manager.is_open(pid):
            plugin_manager.set_enable(pid, False)
    # 仅在用户从未设置过时才写默认值，不覆盖用户调优
    if config_db.get("MAX_TURN_COUNT") is None:
        config_db.set("MAX_TURN_COUNT", "16")
    config_db.set("tram.core_seeded", "1")


def build(db_path: str, plugin_dir: str):
    """组装三层，返回生命周期入口与会话管理器"""
    # 库与表
    db = db_manager.db
    db.connect(db_path)
    session_db = SessionDB(db)
    session_db.ensure_tables()
    message_db = MessageDB(db)
    message_db.ensure_tables()
    config_db = ConfigDB(db)
    config_db.ensure_tables()
    op_db = OperationDB(db)
    op_db.ensure_tables()

    # 程序层
    session_manager = SessionManager(session_db, message_db)

    # 通信层
    op_manager = OperationManager(OperationLog(op_db))
    chain_manager = ChainManager(op_manager)
    plugin_manager = PluginManager(PluginDB(db), plugin_dir, chain_manager)
    # 注入：启停门控 + 归组注册表上报（避免 PluginManager ↔ ChainManager 相互依赖）
    chain_manager.is_open = plugin_manager.is_open
    chain_manager.on_register = plugin_manager.record_registration
    plugin_manager.load_plugin()
    # 通知插件装配链：onLoad 中注册进各事件链，注册顺序即用户配置顺序
    plugin_manager.run_methods(PluginEvent.ON_LOAD)
    # 首次构建：链序与默认值种子（用现有公开 API，不直写库）
    _seed_defaults(config_db, plugin_manager)
    engine_post = EnginePost(session_manager)
    turn_manager = TurnManager(chain_manager, op_manager, engine_post, config_db)
    gateway = HostGateway(chain_manager, turn_manager)

    return Lifecycle(session_manager, gateway), session_manager
