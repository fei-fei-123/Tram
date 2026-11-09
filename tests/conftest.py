import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from engine.filters.echo import echo
from host.app import build_app


@pytest.fixture
def app(tmp_path):
    # 测试仓只装 hello；llm 真插件（含真网关配置）不进测试
    plugins_root = tmp_path / "plugins"
    shutil.copytree(ROOT / "plugins" / "hello", plugins_root / "hello")
    # 核心段注入 echo 兜底：无智能环也能回话（机制基线）
    application = build_app(tmp_path, plugins_root=plugins_root,
                            engine_config={"filters": [echo]})
    yield application
    application.shutdown()


@pytest.fixture
def recorder(app):
    """全量事件录音（wildcard 订阅）。"""
    events = []
    handle = app.bus.subscribe("*", lambda e: events.append(e))
    yield events
    handle.dispose()
