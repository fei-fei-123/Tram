import json
import os
import re
import subprocess

from shared.context import Operation, OperationObjectType, OperationType
from shared.events import SessionEvent
from shared.models import RoleType

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# 仓库根（plugins/shell/shell.py 向上三级），用于解析 config.cwd 的相对路径
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CALL_BLOCK = re.compile(r"```call\s*(.*?)```", re.DOTALL)
RESULT_ID = re.compile(r"\[result id=(\S+?)\s")

# 自识别标记：仅用于定位自己的声明段落，不是跨插件约定
MARKER = "## 命令执行工具（shell 插件）"

DECLARATION = """## 命令执行工具（shell 插件）
你可以在本机执行 shell 命令（工作目录为工作区根）。可用工具：
- shell.run_command —— 执行命令并返回输出。args: {"command": "命令文本"}
调用方式：在回复末尾输出一个或多个 ```call 代码块，每个块内是一行 JSON：
{"tool": "shell.run_command", "id": "自定义唯一id", "args": {"command": "dir"}}
输出调用块后立即停止，等待以 [result id=… ok=…] 开头的消息送达后再继续。
注意：命令有超时限制，长时间运行的命令会被终止。"""

DEFAULT_TIMEOUT = 30      # 单命令超时（秒）
DEFAULT_MAX_OUTPUT = 8192  # 输出截断上限（字符）


def _load_config() -> dict:
    """读取自己的 manifest 中的 config（插件配置走插件，程序不消费该字段）"""
    with open(os.path.join(PLUGIN_DIR, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f).get("config", {}) or {}


class ShellPlugin:
    """命令执行工具插件：onReply 声明调用方式，onTurn 执行属于自己的调用。

    高危插件：模型可以执行任意本机命令，不需要时请在插件管理里停用。
    """

    def __init__(self) -> None:
        cfg = _load_config()
        cwd = str(cfg.get("cwd") or "data/workspace")
        self._cwd = os.path.normpath(os.path.join(REPO_ROOT, cwd))
        os.makedirs(self._cwd, exist_ok=True)
        try:
            self._timeout = float(cfg.get("timeout") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            self._timeout = float(DEFAULT_TIMEOUT)
        try:
            self._max_output = int(cfg.get("max_output") or DEFAULT_MAX_OUTPUT)
        except (TypeError, ValueError):
            self._max_output = DEFAULT_MAX_OUTPUT

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
            if tool != "shell.run_command":
                continue
            cid = str(call.get("id") or "") or f"shell-auto-{seq}"
            if cid in answered:
                continue
            mine.append((cid, call.get("args") or {}))

        if not mine:
            ctx.doFilter()
            return

        for cid, args in mine:
            ok, text = self._exec(args)
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

    def _exec(self, args: dict) -> tuple[bool, str]:
        """执行单条命令；一切失败以 (False, 说明) 返回，让模型看见原因"""
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return False, "缺少或非法的参数 command"
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self._cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"命令超时（{self._timeout:g}s）被终止"
        except Exception as e:
            return False, f"执行失败：{e}"

        output = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if stderr:
            output = (output + "\n[stderr]\n" + stderr).strip()
        if len(output) > self._max_output:
            output = output[:self._max_output] + f"\n…（已截断，退出码 {proc.returncode}）"
        head = f"退出码 {proc.returncode}"
        return proc.returncode == 0, (head + "\n" + output if output else head)


def create_plugin():
    return ShellPlugin()
