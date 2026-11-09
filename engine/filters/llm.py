"""llm 滤器：唯一智能环（B 期＝单轮直调；收回控制权/观察续轮是 Case 3，未做）。

provider 外置：经 deps.config.provider 注入，滤器只管组视图、产 content、交棒。
"""
from .. import EngineError


def llm_view(ctx):
    """注入后视图：system 非空才打头，后接会话消息投影。"""
    msgs = list(ctx.get("messages") or [])
    system = (ctx.get("system") or "").strip()
    if system:
        msgs.insert(0, {"role": "system", "content": system})
    return msgs


def llm(ctx, chain):
    # 取外置 provider
    provider = (chain.deps.get("config") or {}).get("provider")
    if provider is None:
        raise EngineError("llm 滤器需要 provider：请在引擎配置里给 provider")
    # 组 LLM 视图（system 打头）
    msgs = llm_view(ctx)
    # 发起请求、产 content
    resp = provider.chat(msgs) or {}
    ctx["content"] = resp.get("content") or ""
    # 交棒下游（响应侧滤器可加工）
    return chain.doFilter(ctx)
