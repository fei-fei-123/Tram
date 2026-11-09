"""真模型冒烟：起一台宿主（读仓库 config.json），发一轮，打印回复与 trace 行。

用法：python scripts\\smoke_llm.py [提示词]
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host.app import build_app


def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else "用一句话自我介绍，不要思考过程"
    data_dir = Path(tempfile.mkdtemp(prefix="tram_smoke_"))
    app = build_app(data_dir)  # 缺省读仓库 config.json → 真模型
    try:
        if app.engine._config.get("provider") is None:
            print("没读到 provider：先写好仓库根 config.json")
            return 1
        sess = app.sessions.create("冒烟")
        app.messages.append(sess["id"], "user", prompt)
        turn = app.turns.start(sess["id"])
        print(f"data_dir: {data_dir}")
        print(f"turn: {turn['status']} | trace_id: {turn['trace_id']}")
        for m in app.messages.list(sess["id"]):
            print(f"[{m['role']}] {m['content']}")
        trace_file = app.data_dir / "traces" / "trace.jsonl"
        for line in trace_file.read_text(encoding="utf-8").strip().splitlines():
            rec = json.loads(line)
            print(f"trace: {rec['kind']} | round={rec.get('round')} | "
                  f"视图条数={len(rec.get('request', {}).get('messages', rec.get('messages_in', []) or []))}")
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
