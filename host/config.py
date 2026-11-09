"""宿主配置层：config.json → 引擎配置。

名字→滤器函数的接线只在这一处（宿主装配层）；引擎层零注册表不变。
"""
import json
import pathlib

from engine.filters.echo import echo
from engine.filters.llm import llm
from engine.providers import OpenAICompatProvider

_FILTER_TABLE = {"echo": echo, "llm": llm}


def load_engine_config(path):
    # 读文件，没有就空手回去
    path = pathlib.Path(path)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    # 滤器名单 → 函数
    names = raw.get("filters", [])
    for name in names:
        if name not in _FILTER_TABLE:
            raise ValueError(f"未知滤器：{name}（可选：{'/'.join(_FILTER_TABLE)}）")
    cfg = {"filters": [_FILTER_TABLE[name] for name in names]}
    # provider
    p = raw.get("provider")
    if p:
        cfg["provider"] = OpenAICompatProvider(
            p["base_url"], p["model"],
            api_key=p.get("api_key") or None,
            timeout=p.get("timeout", 60))
    return cfg
