import json
import os
import re

from shared.context import Operation, OperationObjectType, OperationType
from shared.events import SessionEvent
from shared.models import RoleType

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# 仓库根（plugins/fs/fs.py 向上三级），用于解析 config.root 的相对路径
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CALL_BLOCK = re.compile(r"```call\s*(.*?)```", re.DOTALL)
RESULT_ID = re.compile(r"\[result id=(\S+?)\s")

# 自识别标记：仅用于定位自己的声明段落，不是跨插件约定
MARKER = "## 文件系统工具（fs 插件）"

DECLARATION = """## 文件系统工具（fs 插件）
你可以操作工作区文件（路径相对于工作区根，不允许绝对路径与 .. 越界）。可用工具：
- fs.read_file —— 读取文本文件。args: {"path": "a.txt"}
- fs.write_file —— 写入文本文件（整文件覆盖）。args: {"path": "a.txt", "content": "内容"}
- fs.list_dir —— 列出目录内容。args: {"path": "."}
调用方式：在回复末尾输出一个或多个 ```call 代码块，每个块内是一行 JSON：
{"tool": "fs.read_file", "id": "自定义唯一id", "args": {"path": "a.txt"}}
输出调用块后立即停止，等待以 [result id=… ok=…] 开头的消息送达后再继续。"""

READ_LIMIT = 32768  # 单文件读取上限（字符），超出截断


def _load_config() -> dict:
    """读取自己的 manifest 中的 config（插件配置走插件，程序不消费该字段）"""
    with open(os.path.join(PLUGIN_DIR, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f).get("config", {}) or {}


class FsPlugin:
    """文件系统工具插件：onReply 声明调用方式，onTurn 执行属于自己的调用"""

    def __init__(self) -> None:
        root = str(_load_config().get("root") or "data/workspace")
        self._root = os.path.normpath(os.path.join(REPO_ROOT, root))
        os.makedirs(self._root, exist_ok=True)

    def on_load(self, ctx):
        ctx.add_method(SessionEvent.ON_START, self.reply)
        ctx.add_method(SessionEvent.ON_TURN, self.turn)

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
            if not tool.startswith("fs."):
                continue
            cid = str(call.get("id") or "") or f"fs-auto-{seq}"
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
            if tool == "fs.read_file":
                rel = self._arg(args, "path")
                path = self._resolve(rel)
                if not os.path.isfile(path):
                    return False, f"文件不存在：{rel}"
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if len(text) > READ_LIMIT:
                    text = text[:READ_LIMIT] + f"\n…（已截断，共 {len(text)} 字符）"
                return True, text
            if tool == "fs.write_file":
                rel = self._arg(args, "path")
                content = self._arg(args, "content")
                path = self._resolve(rel)
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return True, f"已写入 {len(content)} 字符 → {rel}"
            if tool == "fs.list_dir":
                rel = args.get("path") or "."
                path = self._resolve(rel)
                if not os.path.isdir(path):
                    return False, f"目录不存在：{rel}"
                lines = []
                for name in sorted(os.listdir(path)):
                    full = os.path.join(path, name)
                    if os.path.isdir(full):
                        lines.append(f"{name}/")
                    else:
                        lines.append(f"{name}（{os.path.getsize(full)} B）")
                return True, "\n".join(lines) if lines else "（空目录）"
            return False, f"未知工具：{tool}"
        except Exception as e:
            return False, f"执行失败：{e}"

    @staticmethod
    def _arg(args: dict, key: str) -> str:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"缺少或非法的参数 {key}")
        return value

    def _resolve(self, rel: str) -> str:
        """相对路径 → 工作区内的绝对路径，越界即拒"""
        root = os.path.realpath(self._root)
        path = os.path.realpath(os.path.join(root, rel))
        if path != root and not path.startswith(root + os.sep):
            raise ValueError(f"路径越界：{rel}")
        return path


def create_plugin():
    return FsPlugin()
