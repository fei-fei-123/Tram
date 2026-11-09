"""provider 外置：引擎不内置模型客户端，chat 进 content 出。

OpenAI 兼容适配器走 /chat/completions；网络收口在 _http_post_json，测试打桩替换。
"""
import json
import urllib.request


def _http_post_json(url, body, headers=None, timeout=60):
    # 组包
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    # 发起请求
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_content(data):
    # 取 choices[0].message.content，缺了就空串
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


class Provider:
    """provider 适配器根：chat(messages) -> {"content": str}，失败抛异常。"""

    def chat(self, messages):
        raise NotImplementedError


class OpenAICompatProvider(Provider):
    """OpenAI 兼容接口适配器：base_url ＋ model，key 可空（本地网关常免钥）。"""

    def __init__(self, base_url, model, api_key=None, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(self, messages):
        # 组请求体
        body = {"model": self.model, "messages": messages}
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # 发起请求、抽 content
        data = _http_post_json(f"{self.base_url}/chat/completions", body, headers, self.timeout)
        return {"content": _extract_content(data)}
