"""Tram 引擎层（契约见 形态.md）。

机制白清单四件：doFilter 递归语义 / 列表装配 / deps 口子 / trace 写入。
宿主只经 Engine.run 触达引擎：输入 ctx（会话近期消息的投影），输出 content。
引擎不认识 Session/Message——域模型是宿主的。
"""
import uuid

from .chain import Chain, assemble
from .filters.echo import echo
from .trace import Tracer


class EngineError(Exception):
    pass


class Engine:
    """引擎门面：装配单一有序列表 → 跑链 → 写 trace。

    列表＝贡献段（插件 add_filter 只追加，注册序即运行序）＋核心段
    （实例配置 filters：滤器函数直接进列表，零注册表；缺省 echo）。
    deps ＝ { config, store }：实例私有，经 chain.deps 对滤器可见（签名永不再扩）。
    """

    def __init__(self, trace_path, config=None):
        self._tracer = Tracer(trace_path)
        self._config = dict(config or {})
        self.deps = {"config": self._config, "store": {}}  # store 活过单次运行

    def run(self, ctx, filters=(), turn_id=None):
        # 本轮 trace id：各行共用
        trace_id = f"trace_{uuid.uuid4().hex}"
        # provider 包一层，逐轮请求/响应落 trace
        provider = self._config.get("provider")
        traced = None
        if provider is not None:
            traced = _TracedProvider(provider, self._tracer, trace_id, turn_id)
        # 装配单一有序列表：贡献段在前，核心段在后；本轮 deps 带被追踪的 provider
        run_config = dict(self._config)
        if traced is not None:
            run_config["provider"] = traced
        deps = {"config": run_config, "store": self.deps["store"]}
        chain = assemble([*filters, *self._core_filters()], deps)
        chain.doFilter(ctx)
        content = ctx.get("content")
        # 收尾 run 行
        self._tracer.record({
            "kind": "run",
            "turn_id": turn_id,
            "messages_in": ctx.get("messages"),
            "content_out": content,
            "rounds": traced.rounds if traced is not None else 0,
        }, trace_id=trace_id)
        return content, trace_id

    def _core_filters(self):
        # 实例配置列表：滤器函数直接进列表，缺省 echo
        return self._config.get("filters") or (echo,)


class _TracedProvider:
    """provider 包一层：逐轮请求/响应记 trace（trace 系统自转，滤器无感）。"""

    def __init__(self, inner, tracer, trace_id, turn_id):
        self._inner = inner
        self._tracer = tracer
        self._trace_id = trace_id
        self._turn_id = turn_id
        self.rounds = 0

    def chat(self, messages):
        # 发起请求
        try:
            resp = self._inner.chat(messages)
        except Exception as exc:
            # 失败也记一轮
            self._tracer.record({
                "kind": "llm.round",
                "turn_id": self._turn_id,
                "round": self.rounds,
                "request": {"messages": messages},
                "error": str(exc),
            }, trace_id=self._trace_id)
            raise
        self.rounds += 1
        # 记本轮请求/响应
        self._tracer.record({
            "kind": "llm.round",
            "turn_id": self._turn_id,
            "round": self.rounds,
            "request": {"messages": messages},
            "response": resp,
        }, trace_id=self._trace_id)
        return resp
