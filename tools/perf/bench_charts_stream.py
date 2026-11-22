"""流式图表基准：``pushData`` / ``setDataWindow`` / 绘制。

    uv run python tools/perf/bench_charts_stream.py --points 100000 --window 10000

输出 p50 / p95 / max 与（可选）进程峰值内存；``--json`` 写机器可读结果。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time


def _percentile(values: list, fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def _summary(values: list) -> dict:
    if not values:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "count": len(values),
        "p50": round(statistics.median(values), 3),
        "p95": round(_percentile(values, 0.95), 3),
        "max": round(max(values), 3),
        "mean": round(statistics.fmean(values), 3),
    }


def _peak_rss_mb():
    try:
        import psutil
    except Exception:
        psutil = None
    if psutil is not None:
        try:
            return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        except Exception:
            pass
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        handle = kernel32.GetCurrentProcess()
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        return round(counters.PeakWorkingSetSize / (1024 * 1024), 1)
    except Exception:
        return None


def run(args) -> dict:
    from PyQt6.QtGui import QColor, QImage, QPainter
    from PyQt6.QtWidgets import QApplication

    from pyqt6_ela_pro import ElaChartWidget

    app = QApplication.instance() or QApplication([])

    def point(index: int):
        return [index, round(math.sin(index / 40.0) * 100.0, 4)]

    initial = [point(i) for i in range(args.points)]
    chart = ElaChartWidget()
    chart.resize(900, 520)
    started = time.perf_counter()
    chart.setOption(
        {
            "animation": False,
            "sampling": "lttb",
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "name": "stream", "data": initial}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    initial_ms = (time.perf_counter() - started) * 1000.0

    image = QImage(chart.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))

    def paint_once() -> float:
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        begin = time.perf_counter()
        try:
            chart._paint_content(painter)
        finally:
            painter.end()
        return (time.perf_counter() - begin) * 1000.0

    first_paint_ms = paint_once()

    cursor = args.points
    batch_points = [
        [cursor + offset, point(cursor + offset)[1]] for offset in range(args.batch)
    ]
    push_times = []
    for _ in range(args.calls):
        begin = time.perf_counter()
        chart.pushData("stream", batch_points, maxPoints=args.window)
        push_times.append((time.perf_counter() - begin) * 1000.0)
        cursor += args.batch
        batch_points = [
            [cursor + offset, point(cursor + offset)[1]] for offset in range(args.batch)
        ]

    window_data = [point(i) for i in range(args.points)]
    begin = time.perf_counter()
    chart.setDataWindow("stream", window_data, maxPoints=args.window)
    set_window_ms = (time.perf_counter() - begin) * 1000.0

    paint_times = [paint_once() for _ in range(args.frames)]

    app.processEvents()
    result = {
        "points": args.points,
        "window": args.window,
        "batch": args.batch,
        "calls": args.calls,
        "initial_set_option_ms": round(initial_ms, 3),
        "first_paint_ms": round(first_paint_ms, 3),
        "push_ms": _summary(push_times),
        "set_data_window_ms": round(set_window_ms, 3),
        "paint_ms": _summary(paint_times),
        "peak_rss_mb": _peak_rss_mb(),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=100_000)
    parser.add_argument("--window", type=int, default=10_000)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--calls", type=int, default=500)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    result = run(args)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
