import json
import os
import re

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from shared.context import Operation, OperationObjectType, OperationType
from shared.events import SessionEvent
from shared.models import Message, RoleType

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# AI 消息中的工具调用块：```call … ```（见 spec/tool-protocol.md）
CALL_BLOCK = re.compile(r"```call\s*(.*?)```", re.DOTALL)
# PLUGIN 结果消息里的调用标识：[result id=… ok=…]
RESULT_ID = re.compile(r"\[result id=(\S+?)\s")

RETRY_NOTE = (
    "注意：你上一次发起的工具调用没有得到任何响应（对应的插件可能已停用）。"
    "请不要再发起调用，直接根据已有信息回答用户。"
)


def _load_config() -> dict:
    """读取自己的 manifest 中的 config（插件配置走插件，程序不消费该字段）"""
    with open(os.path.join(PLUGIN_DIR, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f).get("config", {}) or {}


def _parse_calls(text: str) -> list[dict]:
    """解析文本里的全部调用块，坏 JSON 的块直接丢弃（无法判断归属，不代答）"""
    calls = []
    for m in CALL_BLOCK.finditer(text):
        try:
            call = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(call, dict):
            calls.append(call)
    return calls


class LlmPlugin:
    """OpenAI 协议大模型插件：只搬运文本，不理解工具语义。

    SYSTEM → system（全部前置收拢）；USER → user；AI → assistant（原样，含调用块）；
    PLUGIN → user（原样，内容自带结果框架）。即使没有任何工具插件，它也是完整的聊天插件。
    """

    def __init__(self) -> None:
        cfg = _load_config()
        self._base_url = str(cfg.get("base_url") or "").strip() or None
        self._model = str(cfg.get("model") or "").strip() or "gpt-4o-mini"
        self._api_key = str(cfg.get("api_key") or "").strip()
        try:
            self._timeout = float(cfg.get("timeout") or 120)
        except (TypeError, ValueError):
            self._timeout = 120.0

    def on_load(self, ctx):
        ctx.add_method(SessionEvent.ON_TURN, self.turn)

    def turn(self, ctx):
        result = ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.READ))
        messages = result.data if result.ok else None
        if not messages:
            ctx.doFilter()
            return

        try:
            answer = self._chat(self._build_request(messages))
        except Exception as e:
            # 失败也要让用户看见，而不是只留在日志里；不申请续轮
            ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.ADD,
                                 role="PLUGIN", content=f"LLM 调用失败：{e}"))
            ctx.doFilter()
            return

        if not answer.strip():
            answer = "（模型返回了空回复）"
        ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.ADD,
                             role="AI", content=answer))
        if CALL_BLOCK.search(answer):
            # 输出了调用块才申请续轮（续轮不变式：有新消息才有申请）
            ctx.submit(Operation(object_type=OperationObjectType.REPLY, type=OperationType.NEW_TURN))
        ctx.doFilter()

    # ====================== 私有方法 ====================== #

    def _build_request(self, messages: list[Message]) -> list[ChatCompletionMessageParam]:
        """上下文消息 → OpenAI 请求消息"""
        request: list[ChatCompletionMessageParam] = []
        # SYSTEM 全部前置收拢（上下文里系统消息未必在开头）
        system_parts = [m.content for m in messages if m.role == RoleType.SYSTEM]
        if system_parts:
            request.append({"role": "system", "content": "\n\n".join(system_parts)})
        for m in messages:
            if m.role == RoleType.SYSTEM:
                continue
            if m.role == RoleType.AI:
                request.append({"role": "assistant", "content": m.content})
            else:
                request.append({"role": "user", "content": m.content})
        note = self._unanswered_note(messages)
        if note:
            request.append({"role": "user", "content": note})
        return request

    def _unanswered_note(self, messages: list) -> str | None:
        """重试护栏：最后一条含调用块的 AI 消息至今没有结果 → 注入放弃提示"""
        last_ai = None
        for m in reversed(messages):
            if m.role == RoleType.AI and CALL_BLOCK.search(m.content):
                last_ai = m
                break
        if last_ai is None:
            return None
        answered = set()
        seen_tail = False
        for m in messages:
            if m is last_ai:
                seen_tail = True
                continue
            if seen_tail and m.role == RoleType.PLUGIN:
                for mm in RESULT_ID.finditer(m.content):
                    answered.add(mm.group(1))
        for call in _parse_calls(last_ai.content):
            cid = str(call.get("id") or "")
            if not cid:
                # 模型没给 id：工具插件会合成 id 并在结果里回显，无法对账，不误报
                continue
            if cid not in answered:
                return RETRY_NOTE
        return None

    def _chat(self, request: list[ChatCompletionMessageParam]) -> str:
        # manifest 优先，环境变量兜底（OPENAI_BASE_URL / OPENAI_API_KEY）
        api_key = self._api_key or os.environ.get("OPENAI_API_KEY") or "EMPTY"
        base_url = self._base_url or os.environ.get("OPENAI_BASE_URL") or None
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=self._timeout)
        resp = client.chat.completions.create(model=self._model, messages=request)
        return resp.choices[0].message.content or ""


def create_plugin():
    return LlmPlugin()
