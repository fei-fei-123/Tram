"""hello 插件：A 阶段示范。

一个滤器方法两段（完整洋葱）：下沉段改输入 → chain.doFilter 交棒下游 →
上浮段处理 content（加时间戳）。另演示「轮后改记录」（订阅 turn.finished 经
MessageService.edit）与「主动发言」（append role=plugin）两条宿主路径。
滤器注册只追加（add_filter(fn)），位置需求将来走实例配置列表。
"""
from datetime import datetime, timezone

from host.plugins.base import Plugin


def create_plugin():
    return HelloPlugin()


class HelloPlugin(Plugin):

    def on_start(self, ctx):
        inject = ctx.config.get("inject_suffix", "")
        stamp_tag = ctx.config.get("stamp_tag", "hello-onion")

        def hello_onion(c, chain):
            # 下沉段：改输入——模型看到的与页面显示的不同
            for m in reversed(c.get("messages") or []):
                if m.get("role") == "user":
                    m["content"] = f"{m['content']}{inject}"
                    break
            chain.doFilter(c)  # 交棒下游：echo（B 期 LLM）产出 content
            # 上浮段：处理 content——返回路径加时间戳
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            c["content"] = f"{c['content']} [{stamp_tag} {ts}]"
            return c["content"]

        ctx.agent.add_filter(hello_onion)

        # UI 贡献：声明式卡片，dispose 即撤销
        ctx.ui.add_card("Hello", "示范插件：洋葱滤器 / turn.finished 订阅 / 主动发言",
                        placement="panel")

    def on_turn_finished(self, ctx, event):
        turn = event["payload"]["turn"]
        if turn["status"] != "done":
            return
        seen = ctx.store.get("turns_seen", 0) + 1
        ctx.store.set("turns_seen", seen)

        # 轮后改记录——必经 MessageService.edit（改完必广播）
        review = ctx.config.get("review_suffix", "")
        for mid in turn["output_msg_ids"]:
            target = ctx.agent.get_message(mid)
            if target is not None:
                ctx.agent.edit_message(mid, f"{target['content']}{review}")

        # 主动发言——落库为 role=plugin 的 Message
        if ctx.config.get("greet", True):
            ctx.agent.speak(turn["session_id"],
                            f"{ctx.config.get('greet_text', 'hello')}（第 {seen} 次）")
