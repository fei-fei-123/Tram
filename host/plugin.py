from dataclasses import dataclass, field
import importlib.util
import json
import os

from host.operation import OperationManager
from shared.events import PluginEvent


@dataclass
class PluginMethod:
    """插件方法"""
    lifecycle: PluginEvent = PluginEvent.ON_LOAD
    name: str = ""
    args: list[dict] = field(default_factory=list) # 放到二期
    method: dict = field(default_factory=dict)


@dataclass
class Plugin:
    """插件实体"""
    id: str = ""
    name: str = ""
    description: str = ""
    version: str = ""
    path: str = ""
    instance: object = None
    methods: dict[PluginEvent, object] = field(default_factory=dict)

class PluginDB:
    """插件链数据库"""
    # TODO 先不实现，等什么时候需要持久化插件开启关闭再说
    pass

class PluginManager:
    """插件链管理器"""
    
    def __init__(self, db: PluginDB, path: str, opm: OperationManager):
        self.db = db
        self.path = path
        self.plugins: list[Plugin] = []
        self.opm = opm

    def create_plugin(self, data: dict, full_path: str) -> Plugin | None:
        """创建插件实体"""
        try:
            instance = self.create_instance(data, full_path)
            if instance is None:
                return None
            
            methods = self.create_methods(instance, data)
            plugin = Plugin(
                id=data["id"],
                name=data["name"],
                description=data["description"],
                version=data["version"],
                path=data["entry"]["file"],
                instance=instance,
                methods=methods,
            )
            return plugin
        except Exception as e:
            print(e)
            return None

    def create_instance(self, data: dict, full_path: str) -> object | None:
        """创建插件实例，插件文件按所在目录解析"""
        try:
            file = data["entry"]["file"]
            # 按路径加载插件文件
            spec = importlib.util.spec_from_file_location(data["id"], os.path.join(full_path, file))
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # 工厂造实例
            instance = getattr(module, data["entry"]["factory"])()
            return instance
        except Exception as e:
            print(e)
            return None

    def create_methods(self, instance: object, data: dict) -> dict[PluginEvent, object]:
        """创建插件方法"""
        methods: list = data["methods"]
        result: dict[PluginEvent, object] = {}
        for method in methods:
            if method["lifecycle"] in PluginEvent:
                result[method["lifecycle"]] = getattr(instance, method["method"])
        return result


    def load_plugin(self):
        """加载插件链"""
        dirs = os.listdir(self.path)
        for dir in dirs:
            full_path = self.path + "/" + dir
            if not os.path.isdir(full_path):
                continue
            
            manifast_path = os.path.join(full_path, "manifest.json")
            if not os.path.exists(manifast_path) or not os.path.isfile(manifast_path):
                continue
            # 读取插件清单
            with open(manifast_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            # 解析插件清单
            plugin = self.create_plugin(manifest, full_path)
            self.plugins.append(plugin) if plugin is not None else None
            


               
