"""TurnService：轮次——「程序忙不忙」的唯一事实来源。

start / cancel → turn.started / turn.finished
流程：组装 ctx（近期消息投影＋system＋meta）→ 引擎跑链 → 链出口 content
     → MessageService.append(role=agent) 落库广播 → turn.finished。
一个会话同一时刻至多一个进行中的 Turn。
"""
import uuid

from ..events import EventBus
from .messages import MessageService

TRIGGERS = ("user_message", "plugin", "system")


class TurnError(Exception):
    pass


class TurnRunningError(TurnError):
    pass


class TurnService:
    def __init__(self, bus: EventBus, messages: MessageService, engine, plugins=None, window=20):
        self._bus = bus
        self._messages = messages
        self._engine = engine
        self._plugins = plugins
        self._window = window
        self._running = {}  # session_id -> turn dict（运行态不落库，trace 指向 jsonl）

    def start(self, session_id, trigger="user_message"):
        if trigger not in TRIGGERS:
            raise ValueError(f"invalid trigger {trigger!r}：词表只有 {'/'.join(TRIGGERS)}")
        if session_id in self._running:
            raise TurnRunningError(f"session {session_id} 已有进行中的 Turn")
        recent = self._messages.list_recent(session_id, self._window)
        turn = {
            "id": f"turn_{uuid.uuid4().hex}",
            "session_id": session_id,
            "trigger": trigger,
            "input_msg_ids": [m["id"] for m in recent],
            "output_msg_ids": [],
            "status": "running",
            "trace_id": None,
        }
        self._running[session_id] = turn
        self._bus.publish("turn.started", {"turn": dict(turn)})
        ctx = {
            "messages": [{"role": m["role"], "content": m["content"]} for m in recent],
            "system": "",
            "meta": {"session_id": session_id, "turn_id": turn["id"]},
        }
        try:
            filters = self._plugins.chain_filters() if self._plugins else []
            content, trace_id = self._engine.run(ctx, filters=filters, turn_id=turn["id"])
            turn["trace_id"] = trace_id
        except Exception:
            turn["status"] = "failed"
            self._running.pop(session_id, None)
            self._bus.publish("turn.finished", {"turn": dict(turn)})
            raise
        if turn["status"] == "cancelled":
            # 链运行途中被 cancel（同步引擎拦不住链本身，结果作废不落库）
            self._running.pop(session_id, None)
            return dict(turn)
        out = self._messages.append(session_id, "agent", content)
        turn["output_msg_ids"] = [out["id"]]
        turn["status"] = "done"
        self._running.pop(session_id, None)
        self._bus.publish("turn.finished", {"turn": dict(turn)})
        return dict(turn)

    def cancel(self, session_id):
        turn = self._running.get(session_id)
        if turn is None:
            raise TurnError(f"session {session_id} 没有进行中的 Turn")
        turn["status"] = "cancelled"
        del self._running[session_id]
        self._bus.publish("turn.finished", {"turn": dict(turn)})
        return dict(turn)
