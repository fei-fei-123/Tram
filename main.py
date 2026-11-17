from pathlib import Path

from app import build
from shared.models import Message, RoleType

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "tram.db"
PLUGIN_DIR = ROOT / "plugins"


def main():
    (ROOT / "data").mkdir(exist_ok=True)
    lifecycle, session_manager = build(str(DB_PATH), str(PLUGIN_DIR))
    session = lifecycle.on_start()

    print("Tram 启动，会话", session.id)
    print("回车对话，exit 退出\n")

    while True:
        try:
            text = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break
        if not text:
            continue
        if text == "exit":
            break

        # 用户消息入库
        session_manager.add_message(session, Message.create(RoleType.USER, text))
        before = {m.id for m in session_manager.list_messages(session)}

        lifecycle.on_reply(session)

        # 打印本轮新增消息
        for m in session_manager.list_messages(session):
            if m.id not in before:
                print(f"[{m.role.value}] {m.content}")


if __name__ == "__main__":
    main()
