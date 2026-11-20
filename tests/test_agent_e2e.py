"""端到端契约测试：mock 一个 OpenAI 协议服务，钉住"提示词即接口"工具协议。

场景：
  A. 工具循环：llm 出调用块 → fs 执行 → 结果消息 → llm 终答
  B. 服务不可达：优雅失败（PLUGIN 失败消息可见，不烧轮次）
  C. 无人应答的调用：llm 重试护栏注入 → 模型放弃调用直接作答

运行：在仓库根目录执行 `python tests/test_agent_e2e.py`
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import build  # noqa: E402
from shared import db_manager  # noqa: E402
from shared.models import Message, RoleType  # noqa: E402


class MockOpenAI:
    """极简 OpenAI 协议 mock：按上下文脚本化回复

    - 请求里已有结果消息 → 终答
    - 请求里带 llm 的护栏提示 → 放弃调用直接作答（场景 C 的断言点）
    - 否则 → 输出一个调用 self.tool 的 ```call 块
    """

    def __init__(self, tool: str):
        self.tool = tool

    def reply(self, messages: list[dict]) -> str:
        text = "\n".join(m.get("content", "") for m in messages)
        if "没有得到任何响应" in text:
            return "好的，我不再调用，直接作答：测试完成（护栏生效）。"
        if "[result id=" in text:
            return "已收到工具结果，测试完成。"
        cid = f"c{sum(1 for m in messages if m.get('role') == 'assistant')}"
        return (
            "我先调用工具查看：\n```call\n"
            + json.dumps({"tool": self.tool, "id": cid, "args": {}}, ensure_ascii=False)
            + "\n```"
        )


def start_mock(mock: MockOpenAI) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            content = mock.reply(body.get("messages", []))
            payload = json.dumps({
                "choices": [{"message": {"role": "assistant", "content": content}}],
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_reply(base_url: str):
    """构建一个全新实例（临时库）并完成一次回复，返回 (session, messages)"""
    tmp = tempfile.mkdtemp(prefix="tram-e2e-")
    os.environ["OPENAI_BASE_URL"] = base_url
    os.environ["OPENAI_API_KEY"] = "test-key"
    lifecycle, session_manager = build(os.path.join(tmp, "tram.db"), os.path.join(ROOT, "plugins"))
    session = lifecycle.on_start()
    session_manager.add_message(session, Message.create(RoleType.USER, "请列出工作区文件"))
    lifecycle.on_reply(session)
    return session, session_manager.list_messages(session)


def scenario_a():
    """A. 工具循环全链路"""
    mock = MockOpenAI("fs.list_dir")
    server = start_mock(mock)
    session, msgs = run_reply(f"http://127.0.0.1:{server.server_address[1]}/v1")
    server.shutdown()

    # 系统消息：人设 + fs 声明都进了黑板（且只有一条 SYSTEM）
    sys_msgs = [m for m in msgs if m.role == RoleType.SYSTEM]
    assert len(sys_msgs) == 1, f"SYSTEM 消息数异常: {len(sys_msgs)}"
    assert "Tram 助手" in sys_msgs[0].content, "prompt 人设缺失"
    assert "fs.list_dir" in sys_msgs[0].content, "fs 声明缺失"

    # 调用块 → 结果 → 终答
    calls = [m for m in msgs if m.role == RoleType.AI and "```call" in m.content]
    results = [m for m in msgs if m.role == RoleType.PLUGIN and m.content.startswith("[result id=")]
    finals = [m for m in msgs if m.role == RoleType.AI and "```call" not in m.content]
    assert calls, "缺少含调用块的 AI 消息"
    assert results and "ok=true" in results[0].content, f"fs 结果异常: {[m.content for m in results]}"
    assert finals, "缺少终答"

    # 种子：演示插件未参与
    assert not any(m.content == "Hello!" for m in msgs), "hello 未被停用"
    row = db_manager.db.execute(
        "SELECT value FROM config WHERE key = 'MAX_TURN_COUNT'").fetchone()
    assert row and row["value"] == "16", f"MAX_TURN_COUNT 种子异常: {row}"

    # 操作日志可复现
    row = db_manager.db.execute(
        "SELECT COUNT(*) AS c FROM operation_log WHERE session_id = :sid",
        {"sid": session.id}).fetchone()
    assert row["c"] > 0, "操作日志为空"
    print(f"A 工具循环全链路 …… 通过（{len(msgs)} 条消息）")


def scenario_b():
    """B. 服务不可达：优雅失败"""
    _, msgs = run_reply("http://127.0.0.1:9/v1")  # 9 = discard 端口，连接即拒
    fails = [m for m in msgs if m.role == RoleType.PLUGIN and m.content.startswith("LLM 调用失败")]
    assert fails, "缺少可见的失败消息"
    assert not [m for m in msgs if m.role == RoleType.AI], "失败时不应产出 AI 消息"
    print("B 服务不可达优雅失败 …… 通过")


def scenario_c():
    """C. 无人应答的调用：护栏生效"""
    mock = MockOpenAI("ghost.nothing")  # 没有任何插件会应答的工具
    server = start_mock(mock)
    _, msgs = run_reply(f"http://127.0.0.1:{server.server_address[1]}/v1")
    server.shutdown()

    ai_msgs = [m for m in msgs if m.role == RoleType.AI]
    assert len(ai_msgs) == 2, f"应恰好两轮 AI 消息: {len(ai_msgs)}"
    assert "```call" in ai_msgs[0].content, "首轮应含调用块"
    assert "```call" not in ai_msgs[1].content and "护栏生效" in ai_msgs[1].content, "护栏未生效"
    assert not [m for m in msgs if m.role == RoleType.PLUGIN], "无人应答时不应有结果消息"
    print("C 无人应答护栏生效 …… 通过")


if __name__ == "__main__":
    scenario_a()
    scenario_b()
    scenario_c()
    print("\n全部通过")
