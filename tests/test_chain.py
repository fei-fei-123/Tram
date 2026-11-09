"""引擎链机制（形态.md 白名单 1、2、3）：交棒、短路、链尾、deps 可见。"""
from engine.chain import assemble


def test_handoff_order_and_tail_returns_content():
    order = []

    def f1(ctx, chain):
        order.append("f1")
        r = chain.doFilter(ctx)
        order.append("f1-back")
        return r

    def f2(ctx, chain):
        order.append("f2")
        ctx["content"] = "made-in-f2"
        return chain.doFilter(ctx)

    out = assemble([f1, f2]).doFilter({})
    assert out == "made-in-f2"
    assert order == ["f1", "f2", "f1-back"]  # 交棒即递归，返回值逐层收回


def test_short_circuit_skips_downstream():
    ran = []

    def stopper(ctx, chain):
        ran.append("stop")
        ctx["content"] = "short"
        return "short"  # 不交棒

    def never(ctx, chain):
        ran.append("never")

    out = assemble([stopper, never]).doFilter({})
    assert out == "short"
    assert ran == ["stop"]


def test_deps_visible_via_chain():
    deps = {"config": {"k": 1}, "store": {}}
    seen = {}

    def f(ctx, chain):
        seen["deps"] = chain.deps
        ctx["content"] = "x"
        return chain.doFilter(ctx)

    assemble([f], deps).doFilter({})
    assert seen["deps"] is deps  # 同一对象：deps 口子不复制、不扩签


def test_empty_chain_tail_returns_none():
    assert assemble([]).doFilter({"content": None}) is None
