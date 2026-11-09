"""EventBus：订阅序即派发序；dispose 幂等；wildcard 全收。"""


def test_publish_subscribe_in_order(app):
    seen = []
    h1 = app.bus.subscribe("x.a", lambda e: seen.append(("a1", e["payload"]["n"])))
    h2 = app.bus.subscribe("x.a", lambda e: seen.append(("a2", e["payload"]["n"])))

    ev = app.bus.publish("x.a", {"n": 1})

    assert seen == [("a1", 1), ("a2", 1)]
    assert ev["type"] == "x.a" and "ts" in ev
    h1.dispose()
    app.bus.publish("x.a", {"n": 2})
    assert seen == [("a1", 1), ("a2", 1), ("a2", 2)]


def test_wildcard_receives_everything(app):
    seen = []
    handle = app.bus.subscribe("*", lambda e: seen.append(e["type"]))
    app.bus.publish("a.b", {})
    app.bus.publish("c.d", {})
    handle.dispose()
    app.bus.publish("e.f", {})
    assert seen == ["a.b", "c.d"]


def test_dispose_is_idempotent(app):
    seen = []
    handle = app.bus.subscribe("x", lambda e: seen.append(1))
    handle.dispose()
    handle.dispose()
    app.bus.publish("x", {})
    assert seen == []


def test_payload_defaults_to_empty_dict(app):
    handle = app.bus.subscribe("x", lambda e: seen.append(e["payload"]))
    seen = []
    app.bus.publish("x")
    assert seen == [{}]
    handle.dispose()
