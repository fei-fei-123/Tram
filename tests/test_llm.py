"""B 阶段：llm 滤器（Case 1 验收：原样回＋trace 多一行）＋ trace 升格＋宿主竖切。

外部依赖全部打桩隔离，不碰网。
"""
import json

import pytest

from engine import Engine, EngineError
from engine.filters.llm import llm, llm_view
from host.app import build_app


class FakeProvider:
    """假 provider：记下每次收到的视图，回固定 content。"""

    def __init__(self, reply="原样回的回复"):
        self.reply = reply
        self.calls = []

    def chat(self, messages):
        self.calls.append(list(messages))
        return {"content": self.reply}


class BoomProvider:
    """必炸 provider：模拟网络失败。"""

    def chat(self, messages):
        raise RuntimeError("断网了")


def _read_trace(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]


def test_case1_passthrough_and_trace(tmp_path):
    fake = FakeProvider("原样回的回复")
    engine = Engine(tmp_path / "traces" / "trace.jsonl",
                    config={"filters": [llm], "provider": fake})
    ctx = {"messages": [{"role": "user", "content": "你好"}],
           "system": "你是测试助理", "meta": {}}

    content, trace_id = engine.run(ctx, turn_id="turn_x")

    assert content == "原样回的回复"  # 请求原样回
    # LLM 视图：system 注入打头，消息投影原样跟随
    assert fake.calls == [[{"role": "system", "content": "你是测试助理"},
                           {"role": "user", "content": "你好"}]]
    # trace 多一行：逐轮行＋run 行，共用同一 trace_id
    lines = _read_trace(tmp_path / "traces" / "trace.jsonl")
    assert [line["kind"] for line in lines] == ["llm.round", "run"]
    assert all(line["trace_id"] == trace_id for line in lines)
    round_line, run_line = lines
    assert round_line["request"]["messages"] == fake.calls[0]  # 必记 LLM 视图
    assert round_line["response"] == {"content": "原样回的回复"}
    assert round_line["round"] == 1
    assert run_line["content_out"] == "原样回的回复"
    assert run_line["rounds"] == 1
    assert run_line["turn_id"] == "turn_x"


def test_no_system_no_system_message(tmp_path):
    fake = FakeProvider()
    engine = Engine(tmp_path / "traces" / "t.jsonl", config={"filters": [llm], "provider": fake})
    ctx = {"messages": [{"role": "user", "content": "hi"}], "system": "", "meta": {}}
    engine.run(ctx)
    assert fake.calls == [[{"role": "user", "content": "hi"}]]


def test_missing_provider_chinese_error(tmp_path):
    engine = Engine(tmp_path / "traces" / "t.jsonl", config={"filters": [llm]})
    with pytest.raises(EngineError, match="provider"):
        engine.run({"messages": [], "system": "", "meta": {}})


def test_provider_failure_still_recorded(tmp_path):
    engine = Engine(tmp_path / "traces" / "t.jsonl",
                    config={"filters": [llm], "provider": BoomProvider()})
    with pytest.raises(RuntimeError, match="断网了"):
        engine.run({"messages": [{"role": "user", "content": "hi"}], "system": "", "meta": {}})
    lines = _read_trace(tmp_path / "traces" / "t.jsonl")
    # 失败也留痕：只有逐轮行（带 error），无 run 行
    assert len(lines) == 1 and lines[0]["kind"] == "llm.round"
    assert "断网了" in lines[0]["error"]


def test_host_vertical_llm_as_member(tmp_path):
    fake = FakeProvider("引擎回的话")
    app = build_app(tmp_path, engine_config={"filters": [llm], "provider": fake})
    try:
        sess = app.sessions.create()
        app.messages.append(sess["id"], "user", "你好Tram")
        turn = app.turns.start(sess["id"])
        assert turn["status"] == "done"
        msgs = app.messages.list(sess["id"])
        assert len(msgs) == 2  # 没加载 hello，无洋葱后缀
        assert msgs[1]["role"] == "agent" and msgs[1]["content"] == "引擎回的话"
        assert turn["trace_id"].startswith("trace_")
    finally:
        app.shutdown()


def test_llm_view_merge():
    ctx = {"messages": [{"role": "user", "content": "a"}], "system": "sys", "meta": {}}
    assert llm_view(ctx) == [{"role": "system", "content": "sys"},
                             {"role": "user", "content": "a"}]
