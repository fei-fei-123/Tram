"""EventBus：宿主事件总线。

纪律：一切变更必经服务 → 必广播；页面与插件都是事件流的普通订阅者。
同步派发，订阅序即派发序；订阅者异常向上抛（A 期策略：fail loud）。
"""
import threading
from datetime import datetime, timezone


class Handle:
    """贡献句柄：dispose() 幂等，撤销一次贡献。"""

    def __init__(self, dispose_fn):
        self._dispose_fn = dispose_fn
        self._done = False

    def dispose(self):
        if not self._done:
            self._done = True
            self._dispose_fn()


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs = []  # [(topic, fn)]；topic 精确匹配或 "*" 全收

    def subscribe(self, topic, fn):
        entry = (topic, fn)
        with self._lock:
            self._subs.append(entry)

        def _remove():
            with self._lock:
                if entry in self._subs:
                    self._subs.remove(entry)

        return Handle(_remove)

    def publish(self, type_, payload=None):
        event = {
            "type": type_,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }
        with self._lock:
            subs = [fn for (topic, fn) in self._subs if topic == type_ or topic == "*"]
        for fn in subs:
            fn(event)  # 不持锁回调：嵌套 publish 安全
        return event
