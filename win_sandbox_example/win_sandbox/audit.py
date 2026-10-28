"""结构化审计事件（JSONL）。

借 OpenShell / OCSF 的「事件分类 + 严重级」思想，不抄完整 schema：
``event`` / ``severity`` / 时间戳 + 业务字段，一行一条，便于 grep / 回放。

不要在审计里记录完整命令或密钥：``command_digest`` 给 hash，
``command_preview`` 只留前 80 字符。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


class AuditSink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


AuditLike = AuditSink | Callable[[dict[str, Any]], None]


def command_digest(command: str) -> str:
    """命令的稳定短摘要，用于关联「开始 / 结束」而不泄露内容。"""
    return hashlib.sha256(command.encode("utf-8", "replace")).hexdigest()[:16]


def command_preview(command: str, limit: int = 80) -> str:
    """单行预览；超长截断，换行压成空格。"""
    text = " ".join(command.split())
    return text[:limit] + ("…" if len(text) > limit else "")


class JsonlAudit:
    """线程安全的 JSONL 审计写入器。"""

    def __init__(self, path: str | Path, *, ensure_ascii: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_ascii = ensure_ascii
        self._lock = threading.Lock()

    def emit(self, event: dict[str, Any]) -> None:
        record = {"ts": time.time(), **event}
        line = json.dumps(record, ensure_ascii=self.ensure_ascii, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


def read_events(path: str | Path) -> list[dict[str, Any]]:
    """读取 JSONL；坏行跳过（截断的日志不应该让诊断整体失败）。"""
    events: list[dict[str, Any]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def call_sink(sink: AuditLike | None, event: dict[str, Any]) -> None:
    """统一调用回调 / sink；审计失败绝不打断沙箱。"""
    if sink is None:
        return
    try:
        emit = getattr(sink, "emit", None)
        if callable(emit):
            emit(event)
        elif callable(sink):
            sink(event)
    except Exception:
        pass
