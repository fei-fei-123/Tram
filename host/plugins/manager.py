"""PluginManager：插件的 load / unload / enable / disable 与贡献物管理。

契约：manifest.json（声明挂哪些锚点 anchors／订阅哪些事件 events）
    ＋ plugin.py（行为；须暴露 create_plugin() -> Plugin 实例）。
manifest 声明的事件在 start 时自动接线到 on_<event> 方法（缺方法只告警）。
启停状态持久在 plugins 表（新插件默认 enabled=1）。
"""
import importlib.util
import json
import logging
import pathlib
import re

from ..events import EventBus
from ..storage import Database
from .base import Plugin
from .context import (
    AgentPort, ConfigPort, EventsPort, PluginContext, StatusPort, StorePort, UiPort, _Tracker,
)

_VALID_ID = re.compile(r"^[a-z][a-z0-9_-]*$")
_log = logging.getLogger("tram.plugins")


class PluginError(Exception):
    pass


class _Loaded:
    def __init__(self, plugin, ctx, manifest):
        self.plugin = plugin
        self.ctx = ctx
        self.manifest = manifest
        self.running = False


class PluginManager:
    def __init__(self, bus: EventBus, db: Database, plugins_root, services, stores_dir):
        self._bus = bus
        self._db = db
        self._root = pathlib.Path(plugins_root)
        self._services = services  # callable -> namespace(.messages/.turns)
        self._stores_dir = pathlib.Path(stores_dir)
        self._plugins = {}              # id -> _Loaded
        self._filters = []               # 插件贡献的滤器，注册序追加
        self._provider_slot = []         # 单槽：当前上交的 provider（空即无）
        self._ui_cards = []
        self._statuses = {}

    # ---- 查询口 ----
    def ui_cards(self):
        return [dict(c) for c in self._ui_cards]

    def status_of(self, plugin_id):
        return self._statuses.get(plugin_id)

    def is_loaded(self, plugin_id):
        return plugin_id in self._plugins

    def is_running(self, plugin_id):
        return plugin_id in self._plugins and self._plugins[plugin_id].running

    def chain_filters(self):
        """宿主（TurnService）取插件贡献的滤器（注册序；引擎装配为单一有序列表）。"""
        return list(self._filters)

    def provider(self):
        """当前上交的模型运行时（llm 插件 add_provider 放进来），无则 None。"""
        return self._provider_slot[0] if self._provider_slot else None

    # ---- 生命周期 ----
    def load(self, plugin_dir):
        path = pathlib.Path(plugin_dir)
        manifest = self._read_manifest(path)
        pid = manifest["id"]
        if pid in self._plugins:
            raise PluginError(f"plugin already loaded: {pid}")
        module = self._import_entry(path, manifest)
        factory = getattr(module, "create_plugin", None)
        if not callable(factory):
            raise PluginError(f"{pid}: plugin.py 须暴露 create_plugin() -> Plugin")
        plugin = factory()
        if not isinstance(plugin, Plugin):
            raise PluginError(f"{pid}: create_plugin() 须返回 host.plugins.base.Plugin 实例")
        plugin.manifest = manifest
        # plugins 表：启停状态持久；重载不覆盖 enabled（保留用户停用决定）
        self._db.execute(
            "INSERT INTO plugins (id, enabled, meta) VALUES (?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET meta=excluded.meta",
            (pid, 1, json.dumps({"name": manifest["name"], "version": manifest.get("version", "")},
                                ensure_ascii=False)))
        ctx = self._build_context(pid, manifest)
        self._plugins[pid] = _Loaded(plugin, ctx, manifest)
        try:
            ctx._set_scope("load")
            plugin.on_load(ctx)
        except Exception:
            self._plugins.pop(pid, None)
            ctx._dispose_all()
            raise
        self._bus.publish("plugin.loaded", {"plugin_id": pid, "name": manifest["name"],
                                            "version": manifest.get("version", "")})
        return pid

    def start(self, plugin_id):
        loaded = self._require(plugin_id)
        if loaded.running:
            return
        ctx = loaded.ctx
        ctx._set_scope("start")
        for ev in loaded.manifest.get("events", []):
            method_name = "on_" + ev.replace(".", "_")
            method = getattr(loaded.plugin, method_name, None)
            if not callable(method):
                ctx.log.warning("manifest 声明事件 %s，但插件没有 %s 方法", ev, method_name)
                continue
            ctx.events.subscribe(ev, lambda event, m=method, c=ctx: m(c, event))
        loaded.plugin.on_start(ctx)
        loaded.running = True

    def stop(self, plugin_id):
        loaded = self._require(plugin_id)
        if not loaded.running:
            return
        loaded.plugin.on_stop(loaded.ctx)
        loaded.ctx._dispose_scope("start")  # 收回 start 期贡献（滤器/订阅/卡片）
        loaded.running = False

    def unload(self, plugin_id):
        loaded = self._require(plugin_id)
        self.stop(plugin_id)  # 幂等
        loaded.ctx._set_scope("unload")
        loaded.plugin.on_unload(loaded.ctx)
        loaded.ctx._dispose_all()  # 关插件＝撤销其全部贡献物
        del self._plugins[plugin_id]
        self._statuses.pop(plugin_id, None)
        self._bus.publish("plugin.unloaded", {"plugin_id": plugin_id})

    def enable(self, plugin_id):
        loaded = self._require(plugin_id)
        self._db.execute("UPDATE plugins SET enabled=1 WHERE id=?", (plugin_id,))
        self._bus.publish("plugin.enabled", {"plugin_id": plugin_id})
        if not loaded.running:
            self.start(plugin_id)

    def disable(self, plugin_id):
        loaded = self._require(plugin_id)
        self._db.execute("UPDATE plugins SET enabled=0 WHERE id=?", (plugin_id,))
        if loaded.running:
            self.stop(plugin_id)
        self._bus.publish("plugin.disabled", {"plugin_id": plugin_id})

    def load_all(self):
        """扫描插件仓：逐个 load，按 plugins 表启停状态决定是否 start。"""
        ids = []
        if not self._root.exists():
            return ids
        for sub in sorted(self._root.iterdir()):
            if sub.is_dir() and (sub / "manifest.json").exists():
                pid = self.load(sub)
                ids.append(pid)
                if self._enabled_in_db(pid):
                    self.start(pid)
        return ids

    def unload_all(self):
        for pid in list(self._plugins):
            try:
                self.unload(pid)
            except Exception:  # 关停尽力而为，不让单个插件卡死宿主
                _log.exception("unload %s failed", pid)

    # ---- 内部 ----
    def _require(self, plugin_id):
        loaded = self._plugins.get(plugin_id)
        if loaded is None:
            raise PluginError(f"plugin not loaded: {plugin_id}")
        return loaded

    def _enabled_in_db(self, plugin_id):
        row = self._db.query_one("SELECT enabled FROM plugins WHERE id=?", (plugin_id,))
        return bool(row and row["enabled"])

    def _read_manifest(self, path):
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            raise PluginError(f"缺少 manifest.json：{path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PluginError(f"manifest.json 解析失败：{exc}") from exc
        for field in ("id", "name", "version"):
            if not manifest.get(field):
                raise PluginError(f"manifest 缺字段：{field}")
        if not _VALID_ID.match(manifest["id"]):
            raise PluginError(f"插件 id 不合法（^[a-z][a-z0-9_-]*$）：{manifest['id']}")
        return manifest

    def _import_entry(self, path, manifest):
        entry = manifest.get("entry", "plugin.py")
        entry_path = path / entry
        if not entry_path.exists():
            raise PluginError(f"入口文件不存在：{entry_path}")
        module_name = f"tram_plugin_{manifest['id']}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise PluginError(f"加载 {entry} 失败：{exc}") from exc
        return module

    def _build_context(self, pid, manifest):
        tracker = _Tracker()
        ports = {
            "ui": UiPort(pid, self._ui_cards, tracker),
            "events": EventsPort(self._bus, tracker),
            "status": StatusPort(pid, self._statuses),
            "agent": AgentPort(pid, self._filters, self._provider_slot, self._services, tracker),
            "store": StorePort(self._stores_dir / f"{pid}.json"),
            "config": ConfigPort(manifest.get("config", {})),
            "log": logging.getLogger(f"tram.plugin.{pid}"),
        }
        return PluginContext(ports, tracker)
