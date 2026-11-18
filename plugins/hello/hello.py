from shared.context import Operation, OperationObjectType, OperationType
from shared.events import SessionEvent


class HelloPlugin:

    def on_load(self, ctx):
        ctx.add_method(SessionEvent.ON_TURN, self.turn)

    def turn(self, ctx):
        # 模拟LLM出一条Hello
        ctx.submit(Operation(object_type=OperationObjectType.SESSION, type=OperationType.ADD, role="AI", content="Hello!"))
        ctx.submit(Operation(object_type=OperationObjectType.REPLY, type=OperationType.NEW_TURN))
        ctx.doFilter()


def create_plugin():
    return HelloPlugin()
