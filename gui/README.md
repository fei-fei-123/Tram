# gui — FastAPI + WebSocket / React

后端（`server.py`）：FastAPI，复用 `app.build()`（engine + host），与 `main.py` 同款逻辑。
前端（`web/`）：Vite + React，开发时 Vite 代理 `/api` 与 `/ws` 到后端。

## 启动

```bash
# 后端（在仓库根目录 D:\project\tram 下运行，保证 engine/host/shared 可导入）
python -m gui.server            # 默认 0.0.0.0:8100，可用 --port 覆盖

# 前端开发（另一个终端）
cd gui/web
npm install
npm run dev                     # http://localhost:5173

# 前端构建（产物由后端静态托管，生产可只跑后端）
npm run build                   # 输出 gui/web/dist
```

## 接口

- `GET /api/health` — 健康检查
- `GET /api/sessions` — 会话列表（脚手架占位）
- `WS  /ws` — 主通道：
  - 客户端发 `{"type": "chat", "content": "..."}`
  - 服务端回 `{"type": "message", ...}`（本轮新增消息逐条推送）、`{"type": "done"}`、`{"type": "error", ...}`
