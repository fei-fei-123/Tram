from shared.context import Operation, OperationObjectType, OperationType
from shared.events import SessionEvent


class HelloPlugin:

    def on_load(self, ctx):
        ctx.add_method(SessionEvent.ON_REPLY, self.turn)

    def turn(self, ctx):
        # 模拟LLM出一条Hello
        ctx.doFilter()
        ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.ADD, role="AI", content="Byebye!"))
        


def create_plugin():
    return HelloPlugin()
