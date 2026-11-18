from dataclasses import dataclass, field
import importlib.util
import json
import os

from host.chain import ChainManager
from shared import db_manager
from shared.events import PluginEvent, SessionEvent


@dataclass
class PluginMethod:
    """插件方法"""
    lifecycle: PluginEvent = PluginEvent.ON_LOAD
    name: str = ""
    args: list[dict] = field(default_factory=list) # 放到二期
    method: dict = field(default_factory=dict)


@dataclass
class Plugin:
    """插件实体"""
    # 基本属性
    id: str = ""
    name: str = ""
    description: str = ""
    version: str = ""
    path: str = ""
    # 配置属性
    enable: bool = True
    # 实例属性
    instance: object = None
    methods: dict[PluginEvent, list] = field(default_factory=dict)


@dataclass
class PluginView:
    """插件DTO"""
    id: str
    name: str
    description: str
    version: str
    enable: bool
    index: int
    events: list[str]


class PluginDB:
    """plugin_config 表：插件顺序与开关的持久化"""

    _DDL = """
    CREATE TABLE IF NOT EXISTS plugin_config (
        plugin_id TEXT PRIMARY KEY,
        position  INTEGER NOT NULL,
        enable    INTEGER NOT NULL DEFAULT 1
    );
    """
    _UPSERT = """
    INSERT INTO plugin_config (plugin_id, position, enable) VALUES (:pid, :pos, :enable)
    ON CONFLICT(plugin_id) DO UPDATE SET position = :pos, enable = :enable;
    """
    _LIST = "SELECT plugin_id, position, enable FROM plugin_config ORDER BY position;"

    def __init__(self, db: db_manager.DBManager) -> None:
        self._db = db

    def ensure_tables(self) -> None:
        """建表"""
        self._db.execute(self._DDL)

    def load(self) -> tuple[list[str], dict[str, bool], dict[str, int]]:
        """读取已保存的顺序、开关与持久化坐标"""
        rows = self._db.execute(self._LIST).fetchall()
        order = [row["plugin_id"] for row in rows]
        enables = {row["plugin_id"]: bool(row["enable"]) for row in rows}
        positions = {row["plugin_id"]: int(row["position"]) for row in rows}
        return order, enables, positions

    def save(self, order: list[str], positions: dict[str, int], enables: dict[str, bool]) -> None:
        """保存插件信息"""
        with self._db.transaction() as conn:
            for pid in order:
                conn.execute(self._UPSERT, {"pid": pid, "pos": positions[pid], "enable": int(enables.get(pid, True))})


class PluginAdminPost:
    """插件管理层"""

    def __init__(self, plugin_manager: "PluginManager") -> None:
        self._pm = plugin_manager

    def snapshot(self) -> list[PluginView]:
        """当前插件列表快照，按加载顺序排列"""
        return self._pm.snapshot()

    def move(self, plugin_id: str, to_index: int) -> list[PluginView]:
        """移动插件到指定位置"""
        self._pm.move(plugin_id, to_index)
        return self.snapshot()

    def move_up(self, plugin_id: str) -> list[PluginView]:
        """上移一位"""
        self._pm.move_up(plugin_id)
        return self.snapshot()

    def move_down(self, plugin_id: str) -> list[PluginView]:
        """下移一位"""
        self._pm.move_down(plugin_id)
        return self.snapshot()

    def set_enable(self, plugin_id: str, enabled: bool) -> list[PluginView]:
        """启用/停用插件"""
        self._pm.set_enable(plugin_id, enabled)
        return self.snapshot()


class PluginManager:
    """插件管理器"""

    def __init__(self, db: PluginDB, path: str, chain_manager: ChainManager):
        self.db = db
        self.path = path
        self.plugins: dict[str, Plugin] = {}   # id → 实体
        self.order: list[str] = []             # 有序列表
        # id -> position
        self._pos: dict[str, int] = {}
        # 插件方法注册表
        self.registrations: dict[str, dict[SessionEvent, list]] = {}
        self.chain_manager = chain_manager

    def load_plugin(self):
        """加载插件"""
        self.db.ensure_tables()
        saved_order, saved_enable, saved_pos = self.db.load()

        # 从插件目录中加载插件
        dirs = os.listdir(self.path)
        for dir in dirs:
            full_path = os.path.join(self.path, dir)
            if not os.path.isdir(full_path):
                continue
            manifest_path = os.path.join(full_path, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue
            # 读取插件清单
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            # 解析插件清单
            plugin = self._create_plugin(manifest, full_path)
            if plugin is not None:
                self.plugins[plugin.id] = plugin

        # 恢复已保存的顺序
        known = set(saved_order)
        self.order = [pid for pid in saved_order if pid in self.plugins]
        # 注册新增插件
        self.order += [pid for pid in self.plugins if pid not in known]
        for pid, plugin in self.plugins.items():
            plugin.enable = saved_enable.get(pid, plugin.enable)

        # 更新顺序
        self._pos = {pid: p for pid, p in self._pos.items() if pid in self.plugins}
        nxt = max(saved_pos.values(), default=-1) + 1
        for pid in self.order:
            if pid in saved_pos:
                self._pos[pid] = saved_pos[pid]
            else:
                self._pos[pid] = nxt
                nxt += 1
        self.save()

    def save(self):
        """持久化顺序与开关"""
        enables = {pid: self.plugins[pid].enable for pid in self.order}
        self.db.save(self.order, self._pos, enables)

    # ============== 用户操作 ==============

    def move(self, plugin_id: str, to_index: int):
        """移动插件到指定位置，并重算链装配"""
        if plugin_id not in self.plugins:
            raise ValueError(f"插件不存在: {plugin_id}")
        to_index = max(0, min(to_index, len(self.order) - 1))
        self.order.remove(plugin_id)
        self.order.insert(to_index, plugin_id)
        self._reindex()
        self.assemble_chains()
        self.save()

    def move_up(self, plugin_id: str):
        """上移一位；已在首位时原地不动"""
        if plugin_id in self.plugins:
            index = self.order.index(plugin_id)
            if index > 0:
                self.move(plugin_id, index - 1)

    def move_down(self, plugin_id: str):
        """下移一位；已在末位时原地不动"""
        if plugin_id in self.plugins:
            index = self.order.index(plugin_id)
            if index < len(self.order) - 1:
                self.move(plugin_id, index + 1)

    def set_enable(self, plugin_id: str, enabled: bool):
        """启用/停用"""
        if plugin_id not in self.plugins:
            raise ValueError(f"插件不存在: {plugin_id}")
        self.plugins[plugin_id].enable = enabled
        self.save()

    # ============== 链装配 ==============

    def is_open(self, plugin_id: str) -> bool:
        """启停门控：停用的插件在链执行时被跳过"""
        plugin = self.plugins.get(plugin_id)
        return plugin is not None and plugin.enable

    def record_registration(self, plugin_id: str, event: SessionEvent, method):
        """注册插件方法"""
        self.registrations.setdefault(plugin_id, {}).setdefault(event, []).append(method)

    def assemble_chains(self):
        """重新生成执行链"""
        chains: dict[SessionEvent, list[tuple[str, object]]] = {}
        # 按顺序读取方法
        for pid in self.order:
            for event, methods in self.registrations.get(pid, {}).items():
                for method in methods:
                    # 添加方法
                    chains.setdefault(event, []).append((pid, method))
        self.chain_manager.set_chains(chains)

    def run_method(self, event: PluginEvent):
        """运行方法"""
        for pid in self.order:
            for method in self.plugins[pid].methods.get(event, []):
                self.chain_manager.set_current(pid)
                method(self.chain_manager)

    def snapshot(self) -> list[PluginView]:
        """按当前顺序生成插件快照"""
        views: list[PluginView] = []
        for i, pid in enumerate(self.order):
            p = self.plugins[pid]
            views.append(PluginView(
                id=p.id,
                name=p.name,
                description=p.description,
                version=p.version,
                enable=p.enable,
                index=i,
                events=[e.value for e in self.registrations.get(pid, {})],
            ))
        return views

    # ====================== 私有方法 ====================== #

    def _reindex(self):
        """重新计算pos"""
        self._pos = {pid: i for i, pid in enumerate(self.order)}

    def _create_plugin(self, data: dict, full_path: str) -> Plugin | None:
        """创建插件实体"""
        try:
            instance = self._create_instance(data, full_path)
            if instance is None:
                return None

            methods = self._create_methods(instance, data)
            plugin = Plugin(
                id=data["id"],
                name=data["name"],
                description=data["description"],
                version=data["version"],
                path=data["entry"]["file"],
                instance=instance,
                methods=methods,
            )
            return plugin
        except Exception as e:
            print(e)
            return None

    def _create_instance(self, data: dict, full_path: str) -> object | None:
        """创建插件实例"""
        try:
            file = data["entry"]["file"]
            # 按路径加载插件文件
            spec = importlib.util.spec_from_file_location(data["id"], os.path.join(full_path, file))
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # 工厂造实例
            instance = getattr(module, data["entry"]["factory"])()
            return instance
        except Exception as e:
            print(e)
            return None

    def _create_methods(self, instance: object, data: dict) -> dict[PluginEvent, list]:
        """创建插件方法"""
        result: dict[PluginEvent, list] = {}
        for method in data["methods"]:
            try:
                event = PluginEvent(method["lifecycle"])
            except ValueError:
                continue
            result.setdefault(event, []).append(getattr(instance, method["method"]))
        return result
