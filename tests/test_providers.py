"""OpenAI 兼容 provider：请求组装与响应抽取；网络口子打桩隔离。"""
from engine.providers import OpenAICompatProvider, _extract_content


def test_extract_content_normal():
    assert _extract_content({"choices": [{"message": {"content": "hi"}}]}) == "hi"


def test_extract_content_tolerates_missing():
    assert _extract_content({}) == ""
    assert _extract_content({"choices": []}) == ""
    assert _extract_content({"choices": [{"message": {"content": None}}]}) == ""


def test_chat_posts_openai_shape(monkeypatch):
    captured = {}

    def fake_post(url, body, headers=None, timeout=60):
        captured["url"] = url
        captured["body"] = body
        captured["headers"] = headers
        return {"choices": [{"message": {"content": "回"}}]}

    monkeypatch.setattr("engine.providers._http_post_json", fake_post)
    p = OpenAICompatProvider("http://x:8000/v1/", "test-model", api_key="sk-x")
    resp = p.chat([{"role": "user", "content": "q"}])

    assert resp == {"content": "回"}
    assert captured["url"] == "http://x:8000/v1/chat/completions"  # 尾斜杠收掉
    assert captured["body"] == {"model": "test-model",
                                "messages": [{"role": "user", "content": "q"}]}
    assert captured["headers"]["Authorization"] == "Bearer sk-x"


def test_chat_without_key_no_auth_header(monkeypatch):
    captured = {}

    def fake_post(url, body, headers=None, timeout=60):
        captured["headers"] = headers
        return {"choices": [{"message": {"content": ""}}]}

    monkeypatch.setattr("engine.providers._http_post_json", fake_post)
    OpenAICompatProvider("http://x", "m").chat([])
    assert captured["headers"] == {}
