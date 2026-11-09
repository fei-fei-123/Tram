"""回声兜底滤器：没人产出 content 时，取最后一条 user 消息原样回。

链上有 llm（或别的产出滤器）在前面时，content 已有，这里只交棒不覆盖——
没配智能环的宿主靠它保持能回话（机制基线）。
"""


def echo(ctx, chain):
    # 已有产出就不覆盖
    if ctx.get("content") is not None:
        return chain.doFilter(ctx)
    for m in reversed(ctx.get("messages") or []):
        if m.get("role") == "user":
            ctx["content"] = m["content"]
            break
    else:
        ctx["content"] = ""
    return chain.doFilter(ctx)
