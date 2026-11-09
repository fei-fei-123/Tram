"""trace 写入（机制白名单 4）：jsonl 逐行，全程可查可重放。"""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Tracer:
    def __init__(self, path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, entry, trace_id=None):
        """补齐 trace_id/ts 后追加一行，返回 trace_id；同轮各行共用同一 trace_id。"""
        entry.setdefault("trace_id", trace_id or f"trace_{uuid.uuid4().hex}")
        entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return entry["trace_id"]
