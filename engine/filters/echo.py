"""A 期引擎 stub：echo——取最后一条 user 消息原样回，然后交棒下游。

作为 B 期 llm 滤器的替身，行为对齐形态.md：产出 content 后交棒（响应侧滤器
可继续加工）。短路语义本身由链支持，但核心滤器不短路。
"""


def echo(ctx, chain):
    for m in reversed(ctx.get("messages") or []):
        if m.get("role") == "user":
            ctx["content"] = m["content"]
            break
    else:
        ctx["content"] = ""
    return chain.doFilter(ctx)
