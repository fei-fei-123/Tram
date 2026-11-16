from enum import Enum


class SessionEvent(str, Enum):
    """会话级生命周期"""
    ON_START = "onStart"
    ON_PAUSE = "onPause"
    ON_RECOVER = "onRecover"
    ON_REPLY = "onReply"
    ON_TURN = "onTurn"
    ON_ARCHIVE = "onArchive"
    ON_DELETE = "onDelete"


class PluginEvent(str, Enum):
    """插件级生命周期"""
    ON_LOAD = "onLoad"
    ON_ENABLE = "onEnable"
    ON_DISABLE = "onDisable"
    ON_UNLOAD = "onUnload"