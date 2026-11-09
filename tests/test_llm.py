"""B 阶段：llm 滤器（Case 1 验收）＋ trace 升格＋llm 插件全路径。

llm 本体在 plugins/llm；这里经 importlib 取源码做引擎级单测，
外部依赖全部打桩隔离，不碰网。
"""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from engine import Engine, EngineError
from host.app import build_app

ROOT = Path(__file__).resolve().parents[1]


def _load_llm_module():
    spec = importlib.util.spec_from_file_location(
        "tram_plugin_llm_src", ROOT / "plugins" / "llm" / "plugin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


llm_mod = _load_llm_module()


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
    engine = Engine(tmp_path / "traces" / "trace.jsonl")
    ctx = {"messages": [{"role": "user", "content": "你好"}],
           "system": "你是测试助理", "meta": {}}

    content, trace_id = engine.run(ctx, filters=[llm_mod.llm], provider=fake, turn_id="turn_x")

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
    engine = Engine(tmp_path / "traces" / "t.jsonl")
    ctx = {"messages": [{"role": "user", "content": "hi"}], "system": "", "meta": {}}
    engine.run(ctx, filters=[llm_mod.llm], provider=fake)
    assert fake.calls == [[{"role": "user", "content": "hi"}]]


def test_missing_provider_chinese_error(tmp_path):
    engine = Engine(tmp_path / "traces" / "t.jsonl")
    with pytest.raises(EngineError, match="provider"):
        engine.run({"messages": [], "system": "", "meta": {}}, filters=[llm_mod.llm])


def test_provider_failure_still_recorded(tmp_path):
    engine = Engine(tmp_path / "traces" / "t.jsonl")
    with pytest.raises(RuntimeError, match="断网了"):
        engine.run({"messages": [{"role": "user", "content": "hi"}], "system": "", "meta": {}},
                   filters=[llm_mod.llm], provider=BoomProvider())
    lines = _read_trace(tmp_path / "traces" / "t.jsonl")
    # 失败也留痕：只有逐轮行（带 error），无 run 行
    assert len(lines) == 1 and lines[0]["kind"] == "llm.round"
    assert "断网了" in lines[0]["error"]


def test_llm_view_merge():
    ctx = {"messages": [{"role": "user", "content": "a"}], "system": "sys", "meta": {}}
    assert llm_mod.llm_view(ctx) == [{"role": "system", "content": "sys"},
                                     {"role": "user", "content": "a"}]


# ---- llm 插件全路径（本地假网关，走真 urllib＋真插件加载） ----

REPLY = "本地网关回复"


class _FakeOpenAI(BaseHTTPRequestHandler):
    """最小 OpenAI 兼容网关：任何 POST 都回固定 content。"""

    def do_POST(self):
        # 读掉请求体
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps({"choices": [{"message": {"content": REPLY}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_llm_plugin_full_path(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        # 插件仓只放 llmtest：manifest 配置指向假网关，行为代码复制自真 llm 插件
        root = tmp_path / "plugins"
        plug = root / "llmtest"
        plug.mkdir(parents=True)
        (plug / "manifest.json").write_text(json.dumps({
            "id": "llmtest", "name": "llmtest", "version": "0.1.0",
            "anchors": [], "events": [],
            "config": {"base_url": f"http://127.0.0.1:{port}", "model": "fake-model"},
        }, ensure_ascii=False), encoding="utf-8")
        (plug / "plugin.py").write_text(
            (ROOT / "plugins" / "llm" / "plugin.py").read_text(encoding="utf-8"),
            encoding="utf-8")
        app = build_app(tmp_path / "data", plugins_root=root, engine_config={})
        try:
            app.start()  # 加载即上交 provider＋注册滤器
            assert app.plugins.provider() is not None

            sess = app.sessions.create()
            app.messages.append(sess["id"], "user", "在吗")
            turn = app.turns.start(sess["id"])

            assert turn["status"] == "done"
            assert app.messages.list(sess["id"])[-1]["content"] == REPLY
            kinds = [rec["kind"] for rec in _read_trace(app.data_dir / "traces" / "trace.jsonl")]
            assert kinds == ["llm.round", "run"]  # 插件自管 provider 照样逐轮落 trace
        finally:
            app.shutdown()
    finally:
        server.shutdown()
