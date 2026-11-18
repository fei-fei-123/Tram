from typing import Callable

from host.operation import OperationManager
from shared.events import SessionEvent


class ChainManager:
    """执行链管理器，即插件拿到的ctx"""

    def __init__(self, op_manager: OperationManager) -> None:
        self.op_manager = op_manager
        self.plugin_id = ""
        self.chains: dict[SessionEvent, list[tuple[str, object]]] = {}
        self._do_filter = None
        # 装配钩子
        self.is_open: Callable[[str], bool] | None = None
        self.on_register: Callable[[str, SessionEvent, object], None] | None = None

    # ====================== 插件链管理 ====================== #

    def set_current(self, plugin_id: str):
        """设置当前插件"""
        self.plugin_id = plugin_id

    def get_chain(self, event: SessionEvent) -> list[tuple[str, object]]:
        """获取执行链"""
        return list(self.chains.get(event, []))

    def run_chain(self, event: SessionEvent, call_back = None):
        """运行执行链"""
        methods = self.get_chain(event)
        self._dispatch(methods, 0, call_back)


    # ====================== 插件链操作 ====================== #
    def set_chains(self, chains: dict[SessionEvent, list[tuple[str, object]]]):
        """整体替换执行链（重装配专用），不触发注册上报"""
        self.chains = chains

    def add_method(self, event: SessionEvent, method):
        """添加方法到执行链"""
        self.chains.setdefault(event, []).append((self.plugin_id, method))
        if self.on_register is not None:
            self.on_register(self.plugin_id, event, method)

    def submit(self, operation):
        """插件提交操作"""
        return self.op_manager.submit(self.plugin_id, operation)

    def get_interrupt(self) -> dict | None:
        """查询当前回复的中断原因；None 表示正常结束"""
        return self.op_manager.get_interrupt()

    def doFilter(self):
        """执行过滤器"""
        f, self._do_filter = self._do_filter, None
        if f is not None:
            f()


    # ====================== 私有方法 ====================== #
    def _dispatch(self, methods: list, index: int, call_back = None):
        """调进第index个方法"""
        if index >= len(methods):
            if call_back is not None:
                call_back()
            return
        plugin_id, method = methods[index]
        # 启停门控
        if self.is_open is not None and not self.is_open(plugin_id):
            self._dispatch(methods, index + 1, call_back)
            return
        self.set_current(plugin_id)
        handed = [False]

        def do_filter():
            handed[0] = True
            self._dispatch(methods, index + 1, call_back)
            self.plugin_id = plugin_id

        self._do_filter = do_filter
        try:
            method(self)
        except Exception as e:
            if handed[0]:
                # 后半段报错：视为已执行完毕，回程继续
                print(f"chain 后半段异常: {e}")
            else:
                # 前半段报错：中断本次链（下游不执行）
                print(f"chain 前半段异常: {e}")
            self.op_manager.submit_error(plugin_id, str(e))
            if not handed[0]:
                # 中断原因落到回复级（先到先得），收尾段经 get_interrupt 查询
                self.op_manager.mark_interrupted(plugin_id, str(e))
        except BaseException as e:
            # 非常规异常（用户取消/SystemExit等）：
            if not getattr(e, "_tram_logged", False):
                print(f"chain 非常规中断: {type(e).__name__}: {e}")
                self.op_manager.submit_error(plugin_id, f"中断: {type(e).__name__}")
                self.op_manager.mark_interrupted(plugin_id, f"中断: {type(e).__name__}")
                setattr(e, "_tram_logged", True)
            raise
        finally:
            # 未消费的doFilter闭包作废，防止回程/链外重复触发下游
            self._do_filter = None
