import json
import os

from shared.context import Operation, OperationObjectType, OperationType
from shared.events import SessionEvent
from shared.models import RoleType

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认人设；manifest 的 config.system_prompt 可整体替换
DEFAULT_PERSONA = (
    "## Tram 助手\n"
    "你是 Tram，一个认真、诚实的助手。会话的系统说明里可能存在其他插件写入的段落"
    "（例如工具的调用方式），按其中的说明行事即可。\n"
    "如果一次调用发起后始终没有收到结果，就不要再重复发起，直接凭已有信息回答。\n"
)


def _load_config() -> dict:
    """读取自己的 manifest 中的 config（插件配置走插件，程序不消费该字段）"""
    with open(os.path.join(PLUGIN_DIR, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f).get("config", {}) or {}


class PromptPlugin:
    """系统提示词插件：只管自己的人设，不认识也不处理其他插件写入的段落"""

    def __init__(self) -> None:
        persona = str(_load_config().get("system_prompt") or "").strip()
        self._persona = persona if persona else DEFAULT_PERSONA

    def on_load(self, ctx):
        ctx.add_method(SessionEvent.ON_START, self.reply)

    def reply(self, ctx):
        result = ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.READ))
        messages = result.data if result.ok else None
        if messages is None:
            ctx.doFilter()
            return

        # 不假设位置：逐条扫描找第一条 SYSTEM 消息
        sys_msg = None
        for m in messages:
            if m.role == RoleType.SYSTEM:
                sys_msg = m
                break

        if sys_msg is None:
            # 会话还没有系统消息：自己补一条（不依赖任何插件先来过）
            ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.ADD,
                                 role="SYSTEM", content=self._persona))
        elif self._persona not in sys_msg.content:
            # 有系统消息但没有自己的人设：读原文 → 追加 → 写回（不覆盖别人的段落）
            ctx.submit(Operation(object_type=OperationObjectType.MESSAGE, type=OperationType.WRITE,
                                 object_id=sys_msg.id,
                                 content=sys_msg.content.rstrip() + "\n\n" + self._persona,
                                 options=sys_msg.options))
        # 已有自己的人设则什么都不做（避免不必要的操作）
        ctx.doFilter()


def create_plugin():
    return PromptPlugin()
