"""宿主装配根：把存储、总线、引擎、三服务、插件管理器接成一台机器。

C 阶段 FastAPI 进程从这里拿 App；测试也从这里拿（tmp_path 即数据目录）。
宿主与引擎只在此处接线：服务收 engine 注入，引擎不知宿主存在。
"""
import pathlib
from types import SimpleNamespace

from engine import Engine

from .config import load_engine_config
from .events import EventBus
from .plugins.manager import PluginManager
from .services.messages import MessageService
from .services.sessions import SessionService
from .services.turns import TurnService
from .storage import Database

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class App:
    def start(self):
        """扫描插件仓并按启停状态拉起。"""
        return self.plugins.load_all()

    def shutdown(self):
        self.plugins.unload_all()
        self.db.close()


def build_app(data_dir, plugins_root=None, engine_config=None):
    data_dir = pathlib.Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    app = App()
    db = Database(data_dir / "tram.db")
    bus = EventBus()
    # 引擎配置：显式传参优先，否则读仓库根 config.json
    if engine_config is None:
        engine_config = load_engine_config(_REPO_ROOT / "config.json")
    engine = Engine(data_dir / "traces" / "trace.jsonl", config=engine_config)
    sessions = SessionService(bus, db)
    messages = MessageService(bus, db)

    def services():
        return app.services  # 装配完成后才可被插件触达

    plugins = PluginManager(bus, db, plugins_root or (_REPO_ROOT / "plugins"), services,
                            data_dir / "plugin_stores")
    turns = TurnService(bus, messages, engine, plugins)
    app.services = SimpleNamespace(sessions=sessions, messages=messages, turns=turns)
    app.bus = bus
    app.db = db
    app.engine = engine
    app.sessions = sessions
    app.messages = messages
    app.turns = turns
    app.plugins = plugins
    app.data_dir = data_dir
    return app
