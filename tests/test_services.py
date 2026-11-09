"""SessionService / MessageService：词表校验、落库、事件广播。"""
import pytest


# ---- Session ----

def test_session_create_rename_archive(app, recorder):
    s = app.sessions.create()
    assert s["id"].startswith("sess_") and s["status"] == "active"
    assert recorder[-1]["type"] == "session.created"

    app.sessions.rename(s["id"], "测试会话")
    assert app.sessions.get(s["id"])["title"] == "测试会话"
    assert recorder[-1]["type"] == "session.updated"
    assert recorder[-1]["payload"]["changed"] == ["title"]

    app.sessions.archive(s["id"])
    assert app.sessions.get(s["id"])["status"] == "archived"
    assert [e["type"] for e in recorder].count("session.updated") == 2


def test_session_missing_raises(app):
    with pytest.raises(KeyError):
        app.sessions.rename("sess_nope", "x")


def test_session_list_filters_by_status(app):
    a = app.sessions.create("a")
    b = app.sessions.create("b")
    app.sessions.archive(a["id"])
    assert [s["id"] for s in app.sessions.list()] == [a["id"], b["id"]]
    assert [s["id"] for s in app.sessions.list(status="active")] == [b["id"]]


# ---- Message ----

def test_message_append_role_vocab(app):
    s = app.sessions.create()
    for role in ("user", "agent", "plugin"):
        msg = app.messages.append(s["id"], role, "hi")
        assert msg["role"] == role and msg["id"].startswith("msg_")
    with pytest.raises(ValueError, match="role"):
        app.messages.append(s["id"], "system", "hi")  # 一期词表无 system
    with pytest.raises(ValueError, match="session"):
        app.messages.append("sess_nope", "user", "hi")


def test_message_edit_marks_edited_and_broadcasts(app, recorder):
    s = app.sessions.create()
    msg = app.messages.append(s["id"], "user", "原文")
    updated = app.messages.edit(msg["id"], "改后")
    assert updated["content"] == "改后" and updated["edited"] is True
    assert app.messages.get(msg["id"])["edited"] is True
    assert recorder[-1]["type"] == "message.edited"


def test_message_delete_broadcasts(app, recorder):
    s = app.sessions.create()
    msg = app.messages.append(s["id"], "user", "将删")
    app.messages.delete(msg["id"])
    assert app.messages.get(msg["id"]) is None
    last = recorder[-1]
    assert last["type"] == "message.deleted"
    assert last["payload"] == {"message_id": msg["id"], "session_id": s["id"]}


def test_list_recent_returns_tail_in_order(app):
    s = app.sessions.create()
    for i in range(5):
        app.messages.append(s["id"], "user", f"m{i}")
    recent = app.messages.list_recent(s["id"], 3)
    assert [m["content"] for m in recent] == ["m2", "m3", "m4"]
    assert app.messages.list_recent(s["id"], 99) == app.messages.list(s["id"])
