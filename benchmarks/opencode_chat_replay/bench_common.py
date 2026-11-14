"""Shared helpers for the opencode replay benchmark."""

from __future__ import annotations

import ctypes
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyqt6_ela_pro import ElaMarkdownViewer  # noqa: E402
from pyqt6_ela_pro.chat.blocks import SubagentCard, ToolCallCard  # noqa: E402


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def rss_mb() -> float:
    try:
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        if not psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            ctypes.sizeof(counters),
        ):
            return 0.0
        return counters.WorkingSetSize / (1024 * 1024)
    except (AttributeError, OSError, ValueError):
        return 0.0


def load_bundle(path: Path, limit: int = 0) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        bundle = json.load(stream)
    if limit > 0:
        bundle = dict(bundle)
        bundle["messages"] = list(bundle.get("messages") or ())[:limit]
        extra = dict(bundle.get("extra") or {})
        extra["bench_limit"] = limit
        bundle["extra"] = extra
    return bundle


def apply_preset(view, name: str) -> None:
    if name == "default":
        return
    if name == "no-virtual":
        view.setVirtualPartsEnabled(False)
        view.setShellVirtualizationEnabled(False)
        view.setVirtualListEnabled(False)
        view.setViewportSuspension(False)
        view.setResizeReflowDeferred(False)
    elif name == "low-threshold":
        view.setVirtualPartsEnabled(True)
        view.setShellVirtualizationEnabled(True, 10)
        view.setVirtualListEnabled(True, 20)
        view.setViewportSuspension(True, 10)
        view.setResizeReflowDeferred(True, 10, 120, 20)
    elif name == "collapsed-tools":
        view.setToolDefaultOpen(_always_closed)
        view.setToolGrouping(True)
    elif name == "narrow":
        view.setContentMaxWidth(600)
    elif name == "no-stats":
        view.setStatsMode("none")
    elif name == "no-avatar":
        view.setAvatarVisible(False)
    else:
        raise ValueError(f"未知 preset：{name!r}")


def _always_closed(*_args, **_kwargs) -> bool:
    return False


def process_events(app, seconds: float = 0.05) -> None:
    deadline = time.perf_counter() + max(0.0, seconds)
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.003)


def drain_until(app, predicate, timeout: float = 120.0) -> bool:
    deadline = time.perf_counter() + max(0.1, timeout)
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    return False


def widget_counts(view) -> dict:
    return {
        "messages": view.count(),
        "markdown_viewers": len(view.findChildren(ElaMarkdownViewer)),
        "tool_cards": len(view.findChildren(ToolCallCard)),
        "subagent_cards": len(view.findChildren(SubagentCard)),
    }


__all__ = [
    "BASE",
    "ROOT",
    "apply_preset",
    "drain_until",
    "load_bundle",
    "process_events",
    "rss_mb",
    "widget_counts",
]
