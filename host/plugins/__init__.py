"""插件体系：Plugin 基类（只挂生命周期）＋ PluginContext 七口子 ＋ PluginManager。

引擎滤器是裸函数 filter(ctx, chain)——doFilter 不在 Plugin 基类上；
插件贡献滤器经 ctx.agent.add_filter 注册（裸函数进列表）。
"""
from .base import Plugin

__all__ = ["Plugin"]
