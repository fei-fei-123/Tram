"""宿主配置层接线＋真实 HTTP 栈（本地假网关，不碰外网）。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from engine.filters.llm import llm
from host.app import build_app
from host.config import load_engine_config

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


def test_load_engine_config_wiring(tmp_path):
    f = tmp_path / "config.json"
    f.write_text(json.dumps({
        "filters": ["llm"],
        "provider": {"base_url": "http://127.0.0.1:1/v1", "model": "m"},
    }, ensure_ascii=False), encoding="utf-8")
    cfg = load_engine_config(f)
    assert cfg["filters"] == [llm]
    assert cfg["provider"].model == "m"


def test_load_engine_config_missing(tmp_path):
    assert load_engine_config(tmp_path / "nope.json") is None


def test_unknown_filter_chinese_error(tmp_path):
    f = tmp_path / "config.json"
    f.write_text(json.dumps({"filters": ["nope"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="未知滤器"):
        load_engine_config(f)


def test_vertical_through_real_http_stack(tmp_path):
    # 起本地假网关
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        # 写宿主配置 → 装配 → 跑一轮，全走真 urllib
        f = tmp_path / "config.json"
        f.write_text(json.dumps({
            "filters": ["llm"],
            "provider": {"base_url": f"http://127.0.0.1:{port}", "model": "fake-model"},
        }, ensure_ascii=False), encoding="utf-8")
        app = build_app(tmp_path, engine_config=load_engine_config(f))
        try:
            sess = app.sessions.create()
            app.messages.append(sess["id"], "user", "在吗")
            turn = app.turns.start(sess["id"])
            assert turn["status"] == "done"
            assert app.messages.list(sess["id"])[-1]["content"] == REPLY
        finally:
            app.shutdown()
    finally:
        server.shutdown()
