"""PluginManager＋hello 插件：三条改动路径、启停卸、贡献物撤销、store 持久。"""
import json
from pathlib import Path

import pytest

from host.plugins.manager import PluginError

ROOT = Path(__file__).resolve().parents[1]
HELLO = ROOT / "plugins" / "hello"


# ---- 三条改动路径 ----

def test_hello_exercises_three_paths(app, recorder):
    app.start()  # load_all：hello 默认 enabled → 自动 start
    assert app.plugins.is_running("hello")

    sess = app.sessions.create()
    app.messages.append(sess["id"], "user", "你好Tram")
    turn = app.turns.start(sess["id"])

    assert turn["status"] == "done"
    msgs = app.messages.list(sess["id"])
    assert [m["role"] for m in msgs] == ["user", "agent", "plugin"]
    # 页面记录原样；agent 消息＝洋葱（下沉注入→echo→上浮时间戳）＋「轮后改记录（edit）」的叠加
    assert msgs[0]["content"] == "你好Tram"
    assert msgs[1]["content"].startswith("你好Tram ·hello-sink [hello-onion ")
    assert msgs[1]["content"].endswith("] [hello-edit]")
    assert msgs[1]["edited"] is True
    # 路径 3：plugin 主动发言
    assert "第 1 次" in msgs[2]["content"]

    # 事件流：插件对 turn.finished 的贡献落在 finished 之后（订阅者天然滞后一拍）
    types = [e["type"] for e in recorder]
    assert "plugin.loaded" in types
    assert types[-3:] == ["turn.finished", "message.edited", "message.appended"]

    # trace 记的是 LLM/引擎视图：pre 滤器的改动可见（与页面显示不同）
    line = json.loads((app.data_dir / "traces" / "trace.jsonl")
                      .read_text(encoding="utf-8").strip().splitlines()[-1])
    assert line["messages_in"][-1]["content"].endswith(" ·hello-sink")


def test_disable_stops_contributions_then_enable_restores(app):
    app.start()
    sess = app.sessions.create()

    app.plugins.disable("hello")
    app.messages.append(sess["id"], "user", "ping")
    app.turns.start(sess["id"])
    msgs = app.messages.list(sess["id"])
    assert [m["role"] for m in msgs] == ["user", "agent"]
    assert msgs[1]["content"] == "ping"  # 无任何插件痕迹

    app.plugins.enable("hello")
    app.messages.append(sess["id"], "user", "pong")
    app.turns.start(sess["id"])
    msgs = app.messages.list(sess["id"])
    assert msgs[-2]["content"].startswith("pong ·hello-sink [hello-onion ")
    assert msgs[-2]["content"].endswith("] [hello-edit]")
    assert msgs[-1]["role"] == "plugin"


def test_unload_undoes_everything(app, recorder):
    app.start()
    sess = app.sessions.create()
    app.messages.append(sess["id"], "user", "第一轮")
    app.turns.start(sess["id"])

    app.plugins.unload("hello")
    assert recorder[-1]["type"] == "plugin.unloaded"
    assert app.plugins.ui_cards() == []
    assert app.plugins.chain_filters() == []

    app.messages.append(sess["id"], "user", "plain")
    app.turns.start(sess["id"])
    last = app.messages.list(sess["id"])[-1]
    assert last["role"] == "agent" and last["content"] == "plain"  # 纯 echo


def test_plugin_lifecycle_events_in_order(app, recorder):
    app.plugins.load(HELLO)
    app.plugins.disable("hello")
    app.plugins.enable("hello")
    app.plugins.unload("hello")
    assert [e["type"] for e in recorder] == [
        "plugin.loaded", "plugin.disabled", "plugin.enabled", "plugin.unloaded",
    ]


# ---- manager 通用 ----

def _write_plugin(root, pid, plugin_py, manifest_extra=None):
    d = root / pid
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"id": pid, "name": pid, "version": "0.1.0",
                "anchors": [], "events": [], **(manifest_extra or {})}
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (d / "plugin.py").write_text(plugin_py, encoding="utf-8")
    return d


_SCRATCH = '''\
from host.plugins.base import Plugin


def create_plugin():
    return Scratch()


class Scratch(Plugin):
    def on_start(self, ctx):
        boots = ctx.store.get("boots", 0) + 1
        ctx.store.set("boots", boots)
        ctx.status.set(f"boots:{boots}")
        ctx.ui.add_card("scratch", f"boot #{boots}")
'''


def test_store_and_status_survive_reload(app, tmp_path):
    pdir = _write_plugin(tmp_path, "scratch", _SCRATCH)
    app.plugins.load(pdir)
    app.plugins.start("scratch")
    assert app.plugins.status_of("scratch") == "boots:1"

    app.plugins.unload("scratch")  # store 是插件私有持久物：卸载不清
    assert app.plugins.ui_cards() == []

    app.plugins.load(pdir)
    app.plugins.start("scratch")
    assert app.plugins.status_of("scratch") == "boots:2"  # json 文件还在


def test_bad_plugins_rejected(app, tmp_path):
    # 缺 create_plugin
    d1 = _write_plugin(tmp_path, "nofactory", "X = 1\n")
    with pytest.raises(PluginError, match="create_plugin"):
        app.plugins.load(d1)
    assert not app.plugins.is_loaded("nofactory")

    # manifest 缺字段
    d2 = tmp_path / "badid"
    d2.mkdir()
    (d2 / "manifest.json").write_text(json.dumps({"name": "x", "version": "1"}), encoding="utf-8")
    (d2 / "plugin.py").write_text("", encoding="utf-8")
    with pytest.raises(PluginError, match="缺字段"):
        app.plugins.load(d2)

    # 重复加载
    app.plugins.load(HELLO)
    with pytest.raises(PluginError, match="already loaded"):
        app.plugins.load(HELLO)


_ONION2 = '''\
from host.plugins.base import Plugin


def create_plugin():
    return P()


class P(Plugin):
    def on_start(self, ctx):
        def outer(c, chain):
            chain.doFilter(c)  # 交棒：inner → echo → 尾
            c["content"] = f"{c['content']}-outer"
            return c["content"]

        def inner(c, chain):
            chain.doFilter(c)  # 交棒：echo → 尾
            c["content"] = f"{c['content']}-inner"
            return c["content"]

        ctx.agent.add_filter(outer)  # 只追加：注册序即运行序
        ctx.agent.add_filter(inner)
'''


def test_add_filter_appends_in_registration_order(app, tmp_path):
    pdir = _write_plugin(tmp_path, "onion2", _ONION2)
    app.plugins.load(pdir)
    app.plugins.start("onion2")

    sess = app.sessions.create()
    app.messages.append(sess["id"], "user", "echo me")
    app.turns.start(sess["id"])

    # outer 先注册先下沉，inner 后注册后下沉；上浮相反：inner 先回、outer 后回
    assert app.messages.list(sess["id"])[-1]["content"] == "echo me-inner-outer"
    assert len(app.plugins.chain_filters()) == 2
