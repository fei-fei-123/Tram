"""链可视化调试：临时目录装配一台宿主，把"列表即拓扑"打出来看。

链 ＝ 贡献段（插件 add_filter 只追加，注册序即运行序）
   ＋核心段（engine_config filters，缺省空，echo 不自动进链）。
另看 provider 单槽（插件 add_provider 上交）与 trace 文件位置。

用法：python scripts\\print_chain.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from host.app import build_app


def main():
    data_dir = Path(tempfile.mkdtemp(prefix="tram_chain_"))
    app = build_app(data_dir)  # 缺省扫插件仓
    try:
        app.start()

        print("链装配（列表即拓扑：贡献段在前，核心段在后）")
        print()

        # 贡献段：来源插件 id＋滤器名，注册序
        specs = app.plugins.chain_filter_specs()
        print(f"贡献段（插件滤器，{len(specs)} 项，注册序）：")
        for i, (pid, name) in enumerate(specs, 1):
            print(f"  {i}. [{pid}] {name}")

        print()

        # 核心段：engine_config filters，缺省空——如实打印
        core = app.engine.core_filters()
        print(f"核心段（engine_config filters，{len(core)} 项）：")
        for i, fn in enumerate(core, 1):
            print(f"  {i}. {getattr(fn, '__name__', repr(fn))}")
        if not core:
            print("  （当前缺省为空）")

        print()

        # provider 单槽
        provider = app.plugins.provider()
        if provider is None:
            print("provider 槽位：否")
        else:
            print(f"provider 槽位：是（{type(provider).__name__}）")

        # 最近 trace 文件
        trace = app.data_dir / "traces" / "trace.jsonl"
        if trace.exists():
            print(f"最近 trace 文件：{trace}")
        else:
            print(f"最近 trace 文件：{trace}（本次未跑轮，暂无记录）")
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
