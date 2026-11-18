"""GUI 临时桥：stdlib HTTP 服务，把宿主页三个入口接进 main.py 同一套逻辑"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from app import build
from shared.models import Message, RoleType

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "tram.db"
PLUGIN_DIR = ROOT / "plugins"
PORT = 8090

# 组装三层，进程内单实例（与 main.py 同款）
lifecycle, session_manager = build(str(DB_PATH), str(PLUGIN_DIR))


def msg_json(m: Message):
    return {"id": m.id, "role": m.role.value, "content": m.content, "created": m.created}


class Handler(BaseHTTPRequestHandler):

    def _send(self, code: int, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # 宿主页，每次现读方便改效果
        if self.path == "/":
            html = (ROOT / "gui.html").read_text(encoding="utf-8")
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 拉一个会话的全部消息
        if self.path.startswith("/api/messages"):
            sid = parse_qs(urlparse(self.path).query).get("sid", [""])[0]
            session = session_manager.get_session(sid)
            if session is None:
                self._send(404, {"error": "会话不存在"})
                return
            self._send(200, {"messages": [msg_json(m) for m in session_manager.list_messages(session)]})
            return

        self._send(404, {"error": "未知路径"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "请求体不是合法 JSON"})
            return

        # 开会话
        if self.path == "/api/session":
            try:
                session = lifecycle.on_start()
                self._send(200, {"id": session.id, "created": session.created})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return

        # 发消息并走一轮回复
        if self.path == "/api/message":
            try:
                session = session_manager.get_session(body.get("sid", ""))
                if session is None:
                    self._send(404, {"error": "会话不存在"})
                    return

                # 与 main.py 同款：入库 → 快照 → 走回复 → 差集即本轮新消息
                text = (body.get("text") or "").strip()
                session_manager.add_message(session, Message.create(RoleType.USER, text))
                before = {m.id for m in session_manager.list_messages(session)}
                lifecycle.on_reply(session)
                fresh = [m for m in session_manager.list_messages(session) if m.id not in before]
                self._send(200, {"messages": [msg_json(m) for m in fresh]})
            except Exception as e:
                self._send(500, {"error": str(e)})
            return

        self._send(404, {"error": "未知路径"})


if __name__ == "__main__":
    print("Tram GUI 桥启动，浏览器打开 http://127.0.0.1:%d" % PORT)
    # 单线程串行，贴合一期"会话内轮次串行"
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
