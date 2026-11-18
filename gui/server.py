"""GUI 服务层：FastAPI + WebSocket，桥接 engine/host（复用 app.build）。"""
import sys
from pathlib import Path

# 保证从任意 cwd（如 gui/web）启动都能导入仓库根下的包
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import build
from shared.models import Message, RoleType

DB_PATH = ROOT / "data" / "tram.db"
PLUGIN_DIR = ROOT / "plugins"
DIST_DIR = Path(__file__).resolve().parent / "web" / "dist"

app = FastAPI(title="Tram GUI")

# 进程内单实例（与 main.py 同款）
lifecycle, session_manager = build(str(DB_PATH), str(PLUGIN_DIR))
session = lifecycle.on_start()


@app.on_event("startup")
def startup():
    (ROOT / "data").mkdir(exist_ok=True)


@app.get("/api/health")
def health():
    return {"ok": True, "session": session.id}


@app.get("/api/sessions")
def sessions():
    # 占位：engine 侧会话列表接口待接入，先回当前会话
    return [{"id": session.id, "active": True}]


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        while True:
            data = await sock.receive_json()
            if data.get("type") != "chat":
                await sock.send_json({"type": "error", "message": f"unknown type: {data.get('type')}"})
                continue

            text = (data.get("content") or "").strip()
            if not text:
                continue

            session_manager.add_message(session, Message.create(RoleType.USER, text))
            before = {m.id for m in session_manager.list_messages(session)}

            # engine 生命周期是同步阻塞的，放线程池避免卡死事件循环
            import anyio
            await anyio.to_thread.run_sync(lifecycle.on_reply, session)

            for m in session_manager.list_messages(session):
                if m.id not in before:
                    await sock.send_json({
                        "type": "message",
                        "id": m.id,
                        "role": m.role.value,
                        "content": m.content,
                        "created": m.created,
                    })
            await sock.send_json({"type": "done"})
    except WebSocketDisconnect:
        return


# 生产模式：托管前端构建产物（存在才挂载）
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(DIST_DIR / "index.html")


def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
