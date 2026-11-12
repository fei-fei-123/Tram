"""PluginContext ＝ { ui, events, status, agent, store, config, log }。

七口子之外没有旁门。所有 add_*/subscribe 产生的句柄都进 tracker；
关插件＝撤销其全部贡献物（manager 调 _dispose_*，插件勿碰）。
句柄按生命周期作用域登记：on_load 里产生的随 unload 撤销，
on_start 里产生的随 stop 撤销——停而不卸即收回行为、保留存在。
"""
import json
import pathlib

from ..events import EventBus, Handle


class _Tracker:
    """贡献登记：按作用域记录，逆序撤销（后注册的先撤）。"""

    def __init__(self):
        self.scope = "load"
        self._items = []  # [(scope, handle)]

    def add(self, handle):
        self._items.append((self.scope, handle))

    def dispose(self, scope=None):
        keep = []
        for item_scope, handle in reversed(self._items):
            if scope is None or item_scope == scope:
                handle.dispose()
            else:
                keep.append((item_scope, handle))
        self._items = list(reversed(keep))


class PluginContext:
    def __init__(self, ports, tracker):
        self.ui = ports["ui"]
        self.events = ports["events"]
        self.status = ports["status"]
        self.agent = ports["agent"]
        self.store = ports["store"]
        self.config = ports["config"]
        self.log = ports["log"]
        self._tracker = tracker

    # —— manager 专用 ——
    def _set_scope(self, scope):
        self._tracker.scope = scope

    def _dispose_scope(self, scope):
        self._tracker.dispose(scope)

    def _dispose_all(self):
        self._tracker.dispose(None)


class EventsPort:
    """订阅宿主事件流（路径 2 的听筒；发言/改记录经 agent 口子）。"""

    def __init__(self, bus: EventBus, tracker: _Tracker):
        self._bus = bus
        self._tracker = tracker

    def subscribe(self, topic, fn):
        handle = self._bus.subscribe(topic, fn)
        self._tracker.add(handle)
        return handle


class UiPort:
    """声明式 UI 贡献：描述符由宿主内置组件库渲染（一期无自定义组件逃生舱）。"""

    def __init__(self, plugin_id, registry, tracker):
        self._plugin_id = plugin_id
        self._registry = registry  # manager 持有的卡片列表
        self._tracker = tracker

    def add_card(self, title, body, placement="panel"):
        card = {"plugin_id": self._plugin_id, "title": title, "body": body, "placement": placement}
        self._registry.append(card)

        def _remove():
            if card in self._registry:
                self._registry.remove(card)

        handle = Handle(_remove)
        self._tracker.add(handle)
        return handle


class AgentPort:
    """触达宿主 agent 能力：插件改「消息/会话」的三条合法路径入口＋模型运行时上交口。"""

    def __init__(self, plugin_id, filters_reg, provider_slot, services, tracker):
        self._plugin_id = plugin_id
        self._filters = filters_reg        # 插件贡献滤器列表，manager 持有
        self._provider_slot = provider_slot  # 单槽 [provider] 或空，manager 持有
        self._services = services          # callable -> namespace(.messages/.turns)，装配后期绑定
        self._tracker = tracker

    def add_filter(self, fn):
        """路径 1（引擎层）：注册滤器（裸函数 filter(ctx, chain)）。
        单签名只追加：注册序即运行序；位置需求将来走实例配置列表。"""
        bucket = self._filters
        bucket.append((self._plugin_id, fn))

        def _remove():
            if (self._plugin_id, fn) in bucket:
                bucket.remove((self._plugin_id, fn))

        handle = Handle(_remove)
        self._tracker.add(handle)
        return handle

    def add_provider(self, provider):
        """把本插件的模型运行时上交宿主：配置自管（manifest），宿主只包一层做逐轮 trace。
        滤器从 chain.deps.config.provider 取用；单槽，后上交替前。"""
        slot = self._provider_slot
        slot.clear()
        slot.append(provider)

        def _remove():
            if slot and slot[0] is provider:
                slot.clear()

        handle = Handle(_remove)
        self._tracker.add(handle)
        return handle

    def get_message(self, message_id):
        return self._services().messages.get(message_id)

    def edit_message(self, message_id, content):
        """路径 2（宿主层）的写手：改记录必经 MessageService.edit。"""
        return self._services().messages.edit(message_id, content)

    def speak(self, session_id, content, meta=None):
        """路径 3：主动发言——落库为 role=plugin 的 Message。"""
        return self._services().messages.append(session_id, "plugin", content, meta=meta)

    def start_turn(self, session_id, trigger="plugin"):
        """替用户/系统拉一轮（trigger 词表：user_message/plugin/system）。"""
        return self._services().turns.start(session_id, trigger=trigger)


class StorePort:
    """插件私有持久 kv（json 文件，不占宿主三张表；数据活过单次运行）。"""

    def __init__(self, path):
        self._path = pathlib.Path(path)
        self._data = None

    def _load(self):
        if self._data is None:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            else:
                self._data = {}
        return self._data

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def get(self, key, default=None):
        return self._load().get(key, default)

    def set(self, key, value):
        self._load()[key] = value
        self._save()

    def delete(self, key):
        self._load().pop(key, None)
        self._save()

    def keys(self):
        return sorted(self._load())


class StatusPort:
    """插件自报状态（状态栏/管理页显示用）。"""

    def __init__(self, plugin_id, statuses):
        self._plugin_id = plugin_id
        self._statuses = statuses

    def set(self, text):
        self._statuses[self._plugin_id] = str(text)

    def get(self):
        return self._statuses.get(self._plugin_id)


class ConfigPort:
    """只读配置（manifest.json 的 config 节）。"""

    def __init__(self, data):
        self._data = dict(data or {})

    @property
    def data(self):
        return dict(self._data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]
