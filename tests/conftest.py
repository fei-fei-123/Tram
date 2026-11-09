import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from host.app import build_app


@pytest.fixture
def app(tmp_path):
    application = build_app(tmp_path, plugins_root=ROOT / "plugins", engine_config={})
    yield application
    application.shutdown()


@pytest.fixture
def recorder(app):
    """全量事件录音（wildcard 订阅）。"""
    events = []
    handle = app.bus.subscribe("*", lambda e: events.append(e))
    yield events
    handle.dispose()
