"""Plugin 基类：只挂生命周期 on_load / on_start / on_stop / on_unload。

每阶段收到 PluginContext（{ui, events, status, agent, store, config, log}）。
"""
import json


class Plugin:
    manifest = None  # manager 加载时注入（manifest.json 全文）

    def on_load(self, ctx):
        pass

    def on_start(self, ctx):
        pass

    def on_stop(self, ctx):
        pass

    def on_unload(self, ctx):
        pass


def read_manifest(plugin_dir):
    """读插件目录的 manifest.json（manager 与工具用）。"""
    path = plugin_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))
