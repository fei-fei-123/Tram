from host.operation import OperationManager
from shared.events import SessionEvent


class ChainManager:
    """执行链管理器，即插件拿到的ctx"""

    def __init__(self, op_manager: OperationManager) -> None:
        self.op_manager = op_manager
        self.plugin_id = ""
        self.chains: dict[SessionEvent, list[tuple[str, object]]] = {}
        self._do_filter = None

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
    def add_method(self, event: SessionEvent, method):
        """添加方法到执行链"""
        self.chains.setdefault(event, []).append((self.plugin_id, method))

    def submit(self, operation):
        """插件提交操作"""
        return self.op_manager.submit(self.plugin_id, operation)

    def doFilter(self):
        """执行过滤器"""
        self._do_filter() if self._do_filter is not None else None


    # ====================== 私有方法 ====================== #
    def _dispatch(self, methods: list, index: int, call_back = None):
        """调进第index个方法"""
        if index >= len(methods):
            if call_back is not None:
                call_back()
            return
        plugin_id, method = methods[index]
        self.set_current(plugin_id)
        handed = [False]

        def do_filter():
            handed[0] = True
            self._dispatch(methods, index + 1, call_back)

        self._do_filter = do_filter
        try:
            method(self)
        except Exception as e:
            if handed[0]:
                # 后半段报错：视为已执行完毕，回程继续
                print(f"chain 后半段异常: {e}")
                self.op_manager.submit_error(plugin_id, str(e))
            else:
                # 前半段报错：中断本次链
                print(f"chain 前半段异常: {e}")
                self.op_manager.submit_error(plugin_id, str(e))
                raise
