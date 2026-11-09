"""LLM 插件：唯一智能环，普通一站。

配置自管（manifest.json 的 config 节，添加插件时配好，程序不代管）：
on_start 时自己构造 provider，经 agent.add_provider 上交宿主槽位——
引擎只把它包一层做逐轮 trace（机制 4），滤器仍从 chain.deps 槽取用。
"""
from engine import EngineError
from engine.providers import OpenAICompatProvider
from host.plugins.base import Plugin


def build_provider(cfg):
    # 按 manifest 配置造 provider
    key = cfg.get("api_key") or None
    return OpenAICompatProvider(
        cfg["base_url"], cfg["model"],
        api_key=key,
        timeout=cfg.get("timeout", 60))


def llm_view(ctx):
    # 注入后视图：system 非空才打头
    msgs = list(ctx.get("messages") or [])
    system = (ctx.get("system") or "").strip()
    if system:
        msgs.insert(0, {"role": "system", "content": system})
    return msgs


def llm(ctx, chain):
    # 取宿主槽位上的 provider（已被引擎包了 trace）
    provider = (chain.deps.get("config") or {}).get("provider")
    if provider is None:
        raise EngineError("llm 滤器需要 provider：先经 agent.add_provider 注册")
    # 组 LLM 视图（system 打头）
    msgs = llm_view(ctx)
    # 发起请求、产 content
    resp = provider.chat(msgs) or {}
    ctx["content"] = resp.get("content") or ""
    # 交棒下游（响应侧滤器可加工）
    return chain.doFilter(ctx)


def create_plugin():
    return LlmPlugin()


class LlmPlugin(Plugin):

    def on_start(self, ctx):
        # 自管配置 → 自造 provider → 上交宿主
        ctx.agent.add_provider(build_provider(ctx.config))
        # 本体滤器进列表（只追加）
        ctx.agent.add_filter(llm)
