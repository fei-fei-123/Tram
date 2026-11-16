from host.operation import OperationManager
from shared.events import SessionEvent


class ChainManager:
    """执行链管理器，即插件拿到的ctx"""

    def __init__(self, op_manager: OperationManager, plugin_id: str = "") -> None:
        self.op_manager = op_manager
        self.plugin_id = plugin_id    # 当前说话的插件，派发方盖章
        self.data: dict = {}
        self.chains: dict[SessionEvent, list[tuple[str, object]]] = {}
        self._do_filter = None

    def set_current(self, plugin_id: str):
        """派发方调进插件方法前盖章"""
        self.plugin_id = plugin_id

    def add_method(self, event: SessionEvent, method):
        """添加方法到执行链，归属自动带上"""
        self.chains.setdefault(event, []).append((self.plugin_id, method))

    def get_chain(self, event: SessionEvent) -> list[tuple[str, object]]:
        """获取执行链"""
        return list(self.chains.get(event, []))

    def submit(self, operation):
        """插件提交操作，归属当前插件"""
        return self.op_manager.submit(self.plugin_id, operation)

    def doFilter(self):
        """交棒：调下游插件，下游跑完回到下一行"""
        self._do_filter()

    def run_chain(self, event: SessionEvent, data: dict):
        """运行执行链：洋葱模型"""
        methods = self.get_chain(event)
        self.data = data    # 本轮数据挂ctx上，串行安全
        self._dispatch(methods, 0)

    def _dispatch(self, methods: list, index: int):
        """调进第index个方法"""
        if index >= len(methods):
            return
        plugin_id, method = methods[index]
        self.set_current(plugin_id)
        handed = [False]

        def do_filter():
            handed[0] = True
            self._dispatch(methods, index + 1)

        self._do_filter = do_filter
        try:
            method(self)
        except Exception as e:
            if handed[0]:
                # 后半段报错：视为已执行完毕，回程继续
                print(f"chain 后半段异常: {e}")
            else:
                # 前半段报错：中断本次链
                raise
