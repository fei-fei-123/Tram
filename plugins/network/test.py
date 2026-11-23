import urllib.parse
import urllib.request
import re


def _fetch(url: str) -> tuple[bool, str]:
    """访问指定 URL，返回截断后的响应正文"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, f"非法 URL：{url}"

    ok, text = _http_get_text(url)
    if not ok:
        return False, text

    # 转义
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", "\"")
    text = text.replace("&apos;", "'")
    text = text.replace("&nbsp;", " ")
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    # 去除常见 HTML 标签（简单处理，足以让模型看到文本）
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    print(text)
    with open("test.html", "w", encoding="utf-8") as f:
        f.write(text)


    return True, text

def _http_get_text(url: str) -> tuple[bool, str]:
    """发起 HTTP GET，返回 (ok, 文本或错误说明)"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
    except Exception as e:
        return False, f"请求失败：{e}"

    try:
        text = raw.decode(charset, errors="replace")
    except Exception:
        text = raw.decode("utf-8", errors="replace")
    return True, text

_fetch("https://www.baidu.com")