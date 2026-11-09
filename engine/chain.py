"""Tram 引擎 · doFilter 递归语义＋列表装配（机制白清单 1、2）。

滤器 ＝ 裸函数 filter(ctx, chain)：
- 处理 / 改写 ctx；
- 交棒：chain.doFilter(ctx)（继续下游）；
- 短路：不调用 chain.doFilter（终止本链，自己负责产出 content）。

deps 口子（机制 3）：{ config, store }，经 chain.deps 对滤器可见，签名永不再扩。
"""


def assemble(filters, deps=None):
    """列表装配：读有序列表建链。列表即顺序、即拓扑；改列表＝重装配。"""
    return Chain(filters, deps)


class Chain:
    def __init__(self, filters, deps=None):
        self._filters = list(filters)
        self.deps = deps if deps is not None else {"config": {}, "store": {}}

    def doFilter(self, ctx):
        return _Cursor(self._filters, self.deps, 0).doFilter(ctx)


class _Cursor:
    """交棒视图：filter 拿到的 chain 参数，只暴露 doFilter 与 deps。"""

    __slots__ = ("_filters", "_deps", "_i")

    def __init__(self, filters, deps, i):
        self._filters = filters
        self._deps = deps
        self._i = i

    @property
    def deps(self):
        return self._deps

    def doFilter(self, ctx):
        if self._i >= len(self._filters):
            return ctx.get("content")  # 链尾：content 由链上滤器负责产出
        nxt = _Cursor(self._filters, self._deps, self._i + 1)
        return self._filters[self._i](ctx, nxt)
