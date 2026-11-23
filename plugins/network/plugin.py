import json
import os
import re
import urllib.parse
import urllib.request

import requests

from shared.context import Operation, OperationObjectType, OperationType
from shared.events import SessionEvent
from shared.models import RoleType

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

CALL_BLOCK = re.compile(r"```call\s*(.*?)```", re.DOTALL)
RESULT_ID = re.compile(r"\[result id=(\S+?)\s")

# 自识别标记
MARKER = "## 网络工具（network 插件）"

DECLARATION = """## 网络工具（network 插件）
你可以执行网络搜索或访问指定 URL。可用工具：
- network.search —— 使用百度搜索关键词。args: {"key": "关键词"}
- network.fetch —— 访问指定 URL，返回响应内容。args: {"key": "https://www.baidu.com"}
调用方式：在回复末尾输出一个或多个 ```call 代码块，每个块内是一行 JSON：
{"tool": "network.search", "id": "自定义唯一id", "args": {"key": "关键词"}}
{"tool": "network.fetch", "id": "自定义唯一id", "args": {"key": "https://www.baidu.com"}}
输出调用块后立即停止，等待以 [result id=… ok=…] 开头的消息送达后再继续。
注意：请求有超时限制，响应过大将被截断。"""

DEFAULT_TIMEOUT = 30       # 单请求超时（秒）
DEFAULT_MAX_OUTPUT = 8192   # 输出截断上限（字符）


def _load_config() -> dict:
    """读取自己的 manifest 中的 config（插件配置走插件，程序不消费该字段）"""
    manifest = os.path.join(PLUGIN_DIR, "manifest.json")
    if not os.path.isfile(manifest):
        return {}
    with open(manifest, "r", encoding="utf-8") as f:
        return json.load(f).get("config", {}) or {}


class NetworkPlugin:
    """网络工具插件：onReply 声明调用方式，onTurn 执行属于自己的调用。"""

    def __init__(self) -> None:
        cfg = _load_config()
        try:
            self._timeout = float(cfg.get("timeout") or DEFAULT_TIMEOUT)
            self._max_output = int(cfg.get("max_output") or DEFAULT_MAX_OUTPUT)
            self.auth = cfg.get("auth") or ""
        except (TypeError, ValueError):
            self._max_output = DEFAULT_MAX_OUTPUT
            self._timeout = DEFAULT_TIMEOUT
            self.auth = ""

    def on_load(self, ctx):
        ctx.add_method(SessionEvent.ON_START, self.reply)
        ctx.add_method(SessionEvent.ON_TURN, self.turn)

    def reply(self, ctx):
        result = ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.READ))
        messages = result.data if result.ok else None
        if messages is None:
            ctx.doFilter()
            return

        # 逐条扫描找第一条 SYSTEM 消息
        sys_msg = None
        for m in messages:
            if m.role == RoleType.SYSTEM:
                sys_msg = m
                break

        if sys_msg is None:
            # 会话还没有系统消息：自己补一条
            ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.ADD,
                                 role="SYSTEM", content=DECLARATION))
        elif MARKER not in sys_msg.content:
            # 有系统消息但没有自己的声明：读原文 → 追加 → 写回（不覆盖别人的段落）
            ctx.submit(Operation(object_type=OperationObjectType.MESSAGE, type=OperationType.WRITE,
                                 object_id=sys_msg.id,
                                 content=sys_msg.content.rstrip() + "\n\n" + DECLARATION,
                                 options=sys_msg.options))
        # 已有自己的声明则什么都不做（避免不必要的操作）
        ctx.doFilter()

    def turn(self, ctx):
        result = ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.READ))
        messages = result.data if result.ok else None
        if not messages:
            ctx.doFilter()
            return

        # 找最后一条含调用块的 AI 消息
        last_ai = None
        for m in reversed(messages):
            if m.role == RoleType.AI and CALL_BLOCK.search(m.content):
                last_ai = m
                break
        if last_ai is None:
            ctx.doFilter()
            return

        # 其后已回答的调用 id
        answered = set()
        seen_tail = False
        for m in messages:
            if m is last_ai:
                seen_tail = True
                continue
            if seen_tail and m.role == RoleType.PLUGIN:
                for mm in RESULT_ID.finditer(m.content):
                    answered.add(mm.group(1))

        # 只处理：JSON 合法、工具名属于自己、未被回答的调用
        mine = []
        for seq, call in enumerate(self._parse_calls(last_ai.content)):
            tool = str(call.get("tool") or "")
            if not tool.startswith("network."):
                continue
            cid = str(call.get("id") or "") or f"network-auto-{seq}"
            if cid in answered:
                continue
            mine.append((cid, tool, call.get("args") or {}))

        if not mine:
            ctx.doFilter()
            return

        for cid, tool, args in mine:
            ok, text = self._exec(tool, args)
            ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.ADD,
                                 role="PLUGIN",
                                 content=f"[result id={cid} ok={'true' if ok else 'false'}] {text}"))
        # 出了结果才申请续轮（续轮不变式）
        ctx.submit(Operation(object_type=OperationObjectType.REPLY, type=OperationType.NEW_TURN))
        ctx.doFilter()

    # ====================== 私有方法 ====================== #

    @staticmethod
    def _parse_calls(text: str) -> list[dict]:
        """解析调用块；坏 JSON 的块丢弃（无法判断归属，不代答）"""
        calls = []
        for m in CALL_BLOCK.finditer(text):
            try:
                call = json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                continue
            if isinstance(call, dict):
                calls.append(call)
        return calls

    def _exec(self, tool: str, args: dict) -> tuple[bool, str]:
        """执行单个调用；一切失败以 (False, 说明) 返回，让模型看见原因"""
        try:
            if tool == "network.search":
                keyword = self._arg(args, "key")
                return self._search(keyword)
            if tool == "network.fetch":
                url = self._arg(args, "key")
                return self._fetch(url)
            return False, f"未知工具：{tool}"
        except Exception as e:
            return False, f"执行失败：{e}"

    @staticmethod
    def _arg(args: dict, key: str) -> str:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"缺少或非法的参数 {key}")
        return value

    def _search(self, keyword: str) -> tuple[bool, str]:
        """使用百度搜索关键词，返回解析后的简要结果"""
        url = "https://qianfan.baidubce.com/v2/ai_search/web_search"
        if not self.auth:
            return False, "未配置 API 密钥"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {self.auth}"
        }

        payload = json.dumps({
            "messages": [
                {
                    "role": "user",
                    "content": keyword
                }
            ],
            "edition": "standard",
            "search_source": "baidu_search_v2",
            "search_recency_filter": "week"
        }, ensure_ascii=False)

        response = requests.request("POST", url, headers=headers, data=payload.encode("utf-8"))
        response.encoding = "utf-8"

        return True, f"关键词：{keyword}\n" + response.text

    def _fetch(self, url: str) -> tuple[bool, str]:
        """访问指定 URL，返回截断后的响应正文"""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False, f"非法 URL：{url}"

        ok, text = self._http_get_text(url)
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

        return True, text

    def _http_get_text(self, url: str) -> tuple[bool, str]:
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
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
        except Exception as e:
            return False, f"请求失败：{e}"

        try:
            text = raw.decode(charset, errors="replace")
        except Exception:
            text = raw.decode("utf-8", errors="replace")
        return True, text

    def _truncate(self, text: str) -> str:
        if len(text) > self._max_output:
            return text[:self._max_output] + f"\n…（已截断，原长度 {len(text)} 字符）"
        return text


def create_plugin():
    return NetworkPlugin()
