"""TurnService＋引擎 echo stub：竖切全流程、互斥、失败、取消、trace。"""
import json

import pytest

from host.services.turns import TurnRunningError


def test_echo_turn_full_flow(app, recorder):
    s = app.sessions.create()
    app.messages.append(s["id"], "user", "你好Tram")

    turn = app.turns.start(s["id"])

    assert turn["status"] == "done"
    assert turn["trace_id"] and turn["trace_id"].startswith("trace_")
    msgs = app.messages.list(s["id"])
    assert [m["role"] for m in msgs] == ["user", "agent"]
    assert msgs[1]["content"] == "你好Tram"  # echo：原样回
    assert turn["input_msg_ids"] == [msgs[0]["id"]]
    assert turn["output_msg_ids"] == [msgs[1]["id"]]
    assert [e["type"] for e in recorder] == [
        "session.created", "message.appended", "turn.started", "message.appended", "turn.finished",
    ]
    # trace：jsonl 多一行，trace_id 与 Turn 对上
    lines = (app.data_dir / "traces" / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
    rec = json.loads(lines[-1])
    assert rec["content_out"] == "你好Tram"
    assert rec["trace_id"] == turn["trace_id"]
    assert rec["turn_id"] == turn["id"]


def test_one_running_turn_per_session(app, monkeypatch):
    s = app.sessions.create()
    app.messages.append(s["id"], "user", "hi")
    conflict = {}

    def fake_run(ctx, filters=(), turn_id=None):
        try:
            app.turns.start(s["id"])  # 链运行中同会话再拉一轮 → 必须被拒
            conflict["seen"] = False
        except TurnRunningError:
            conflict["seen"] = True
        return "ok", "trace_conflict"

    monkeypatch.setattr(app.engine, "run", fake_run)
    turn = app.turns.start(s["id"])
    assert conflict["seen"] is True
    assert turn["status"] == "done"


def test_failed_turn(app, recorder, monkeypatch):
    s = app.sessions.create()
    app.messages.append(s["id"], "user", "hi")

    def boom(ctx, filters=(), turn_id=None):
        raise RuntimeError("engine down")

    monkeypatch.setattr(app.engine, "run", boom)
    with pytest.raises(RuntimeError, match="engine down"):
        app.turns.start(s["id"])

    finished = [e for e in recorder if e["type"] == "turn.finished"]
    assert finished[-1]["payload"]["turn"]["status"] == "failed"
    assert [m["role"] for m in app.messages.list(s["id"])] == ["user"]  # 失败不落 agent 消息

    # running 已清理：下一轮可正常开
    monkeypatch.setattr(app.engine, "run", lambda ctx, filters=(), turn_id=None: ("ok", "trace_t"))
    assert app.turns.start(s["id"])["status"] == "done"


def test_cancel_during_run_discards_output(app, recorder, monkeypatch):
    s = app.sessions.create()
    app.messages.append(s["id"], "user", "hi")

    def fake_run(ctx, filters=(), turn_id=None):
        app.turns.cancel(s["id"])  # 链运行途中取消
        return "late", "trace_cancel"

    monkeypatch.setattr(app.engine, "run", fake_run)
    turn = app.turns.start(s["id"])

    assert turn["status"] == "cancelled"
    assert [m["role"] for m in app.messages.list(s["id"])] == ["user"]  # 结果作废不落库
    finished = [e for e in recorder if e["type"] == "turn.finished"]
    assert len(finished) == 1 and finished[0]["payload"]["turn"]["status"] == "cancelled"


def test_cancel_without_running_turn(app):
    s = app.sessions.create()
    from host.services.turns import TurnError
    with pytest.raises(TurnError):
        app.turns.cancel(s["id"])


def test_trigger_vocab(app):
    s = app.sessions.create()
    app.messages.append(s["id"], "user", "hi")
    with pytest.raises(ValueError, match="trigger"):
        app.turns.start(s["id"], trigger="cron")
