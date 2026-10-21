"""ElaChartWidget 折线 / 散点性能基线（离屏，可复跑、可出 JSON）。

用法::

    uv run python tools/perf/bench_charts.py            # 表格
    uv run python tools/perf/bench_charts.py --json out.json

测什么（对齐 docs/performance.md 的「分阶段」口径）：

* ``ingest`` / ``layout`` / ``paint`` / ``frame``：库自带 ``benchmark()`` 的口径
  （帧 = 布局 + 纯光栅化，不含窗口合成）；
* ``hover``：合成 MouseMove → 命中 + 重绘（走完整事件路径）；
* ``zoom``：``dispatchAction(dataZoom)`` + ``grab()``（同窗口重复缩放，
  第二次起命中采样 LRU）；
* ``zoom新窗口``：8 个互不相同窗口逐个进入的中位数（真实重采样成本）；
* ``缩回全景``：先离开全景再缩回（全景缓存槽常驻，重复回访更便宜）。

基线（2026-10-18 重测，本机离屏 1400×800；改采样 / 绘制管线后请重跑并更新 docs）：

    场景                         frame      hover    zoom      zoom新窗口  缩回全景
    折线 value 1M（采样）         9.4ms      0.85ms   11.6ms    12.5ms      32.6ms
    折线 category 1M（采样）      9.4ms      0.85ms   14.1ms    19.6ms      45.0ms
    散点 1M（采样）               9.4ms      1.6ms    37.1ms    37.7ms      38.2ms
    冲击 5M 单通道（时间戳）       3.0ms      0.85ms   7.4ms     8.3ms       10.4ms
    冲击 3×2M 三通道              6.4ms      0.89ms   16.6ms    19.2ms      21.9ms

「更快但不重采样」= 曲线是错的（历史 bug），别拿旧数字当基线。

设计上的两条纪律（与 charts 的历史结论一致）：

1. **不建合成压测数据当真实场景**：这里的 100 万点是「长序列 + 周期波动」，
   不是随机噪声堆量；冲击场景（显式时间戳 + 记录中断 + 脉冲）对应
   物理试验数据的常态形状；
2. **时间单位一律 ms**，`benchmark()` 返回的就是 ms。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from PyQt6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from PyQt6ElaWidgetTools import eApp  # noqa: E402

from pyqt6_ela_pro import ElaChartWidget  # noqa: E402

W, H = 1400, 800


def build(
    series_type: str,
    n: int,
    *,
    axis: str = "value",
    sampling: bool = True,
    extra: dict | None = None,
    series_data: list | None = None,
) -> ElaChartWidget:
    chart = ElaChartWidget()
    chart.resize(W, H)
    xaxis = (
        {"type": "category", "data": [str(i) for i in range(n)]}
        if axis == "category"
        else {"type": "value"}
    )
    single = {
        "type": series_type,
        "name": "S",
        "data": (np.arange(n) % 997).astype(np.float64),
    }
    if not sampling:
        single["sampling"] = False
    single.update(extra or {})
    if series_data is None:
        series_list = [single]
    else:
        series_list = []
        for i, data in enumerate(series_data):
            series = dict(single)
            series["name"] = f"S{i + 1}"
            series["data"] = data
            series_list.append(series)
    chart.setOption(
        {
            "animation": False,
            "xAxis": xaxis,
            "yAxis": {"type": "value"},
            "series": series_list,
        }
    )
    chart.anim.setProgress(1.0)
    return chart


def shock_series(channels: int, n: int, *, step: float = 0.1, gap: float = 60.0):
    """冲击 / 振动形态：等间隔时间戳 + 一处记录中断，2D [t, v] 输入。

    数据形状是「物理试验」常态（显式浮点时间戳、几百万点、含记录中断），
    也顺带覆盖「2D 列视图 → 连续副本」与 gap 预计算这两条路径。
    """
    cut = n // 2
    t = np.concatenate(
        [
            np.arange(cut, dtype=np.float64) * step,
            (cut * step + gap) + np.arange(n - cut, dtype=np.float64) * step,
        ]
    )
    out = []
    for c in range(channels):
        rng = np.random.default_rng(c)
        v = 0.1 * np.sin(
            2 * np.pi * (50.0 + 10.0 * c) * t
        ) + 0.02 * rng.standard_normal(t.size)
        for k in range(8):
            i = int(t.size * (k + 0.5) / 8)
            seg = np.arange(0, 2000)
            v[i + seg] += (
                5.0 * np.exp(-seg / 300.0) * np.sin(2 * np.pi * 800 * seg / 51200.0)
            )
        out.append(np.column_stack([t, v]))
    return out


def _best(fn, repeat: int = 6) -> float:
    best = 1e9
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - t0) * 1000.0)
    return best


def measure(chart: ElaChartWidget, app: QApplication, frames: int = 5) -> dict:
    result = dict(chart.benchmark(frames=frames, perSeries=False))
    renderer = chart.seriesRenderers[0]
    points = [p for p in getattr(renderer, "_points", []) if p is not None]
    dots = getattr(renderer, "_dots", [])
    anchor = (
        points[len(points) // 2]
        if points
        else (dots[len(dots) // 2]["pt"] if dots else None)
    )
    if anchor is not None:

        def hover() -> None:
            event = QMouseEvent(
                QEvent.Type.MouseMove,
                anchor,
                QPointF(chart.mapToGlobal(anchor.toPoint())),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(chart, event)
            app.processEvents()

        result["hoverMs"] = _best(hover)

        def zoom() -> None:
            chart.dispatchAction({"type": "dataZoom", "start": 40, "end": 60})
            chart.grab()
            app.processEvents()

        result["zoomMs"] = _best(zoom, repeat=4)

        # 真实「新窗口」成本：8 个互不相同的窗口逐个进入（同窗口重复 dispatch
        # 会命中采样 LRU，``zoomMs`` 测到的是缓存命中路径）。
        def zoom_alt() -> None:
            times = []
            for i in range(8):
                t0 = time.perf_counter()
                chart.dispatchAction(
                    {"type": "dataZoom", "start": 40 + i, "end": 60 + i}
                )
                chart.grab()
                app.processEvents()
                times.append((time.perf_counter() - t0) * 1000.0)
            result["zoomAltMs"] = float(np.median(times))

        zoom_alt()

        # 缩回全景：先离开全景以保证这次是真实重算（全景槽常驻，回访走缓存）
        chart.dispatchAction({"type": "dataZoom", "start": 5, "end": 95})
        chart.grab()
        app.processEvents()
        t0 = time.perf_counter()
        chart.dispatchAction({"type": "dataZoom", "start": 0, "end": 100})
        chart.grab()
        app.processEvents()
        result["fullMs"] = (time.perf_counter() - t0) * 1000.0
    result["drawnPoints"] = len(
        getattr(renderer, "_points", []) or getattr(renderer, "_dots", [])
    )
    result["dataPoints"] = getattr(renderer, "_data_len", len(renderer.data()))
    return result


CASES: list[tuple[str, dict]] = [
    ("折线 value 100k（采样）", dict(series_type="line", n=100_000)),
    ("折线 value 1M（采样）", dict(series_type="line", n=1_000_000)),
    (
        "折线 category 1M（采样）",
        dict(series_type="line", n=1_000_000, axis="category"),
    ),
    ("折线 1M sampling=false", dict(series_type="line", n=1_000_000, sampling=False)),
    (
        "折线+点 1M（采样）",
        dict(series_type="line", n=1_000_000, extra={"symbol": "circle"}),
    ),
    ("面积 1M（采样）", dict(series_type="line", n=1_000_000, extra={"areaStyle": {}})),
    (
        "smooth 1M（采样）",
        dict(series_type="line", n=1_000_000, extra={"smooth": True}),
    ),
    (
        "step 1M（采样）",
        dict(series_type="line", n=1_000_000, extra={"step": "middle"}),
    ),
    (
        "散点 50k（采样）",
        dict(series_type="scatter", n=50_000, extra={"symbolSize": 4}),
    ),
    (
        "散点 1M（采样）",
        dict(series_type="scatter", n=1_000_000, extra={"symbolSize": 4}),
    ),
    # 冲击 / 振动形态：显式时间戳（2D [t, v]）+ 记录中断；单通道与三通道对比
    (
        "冲击 5M 单通道（时间戳）",
        dict(series_type="line", n=5_000_000, series_data=shock_series(1, 5_000_000)),
    ),
    (
        "冲击 3×2M 三通道",
        dict(series_type="line", n=2_000_000, series_data=shock_series(3, 2_000_000)),
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="")
    parser.add_argument("--frames", type=int, default=5)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    eApp.init()
    rows = []
    print(
        f"{'场景':30} {'ingest':>8} {'frame':>7} {'hover':>7} {'zoom':>7} "
        f"{'zoom新窗口':>10} {'缩回全景':>8} {'drawn':>8}"
    )
    for label, kwargs in CASES:
        chart = build(**kwargs)
        row = measure(chart, app, frames=args.frames)
        row["case"] = label
        rows.append(row)
        print(
            f"{label:30} {row['ingestMs']:8.1f} {row['frameMs']:7.1f} "
            f"{row.get('hoverMs', float('nan')):7.2f} {row.get('zoomMs', float('nan')):7.2f} "
            f"{row.get('zoomAltMs', float('nan')):10.1f} {row.get('fullMs', float('nan')):8.1f} "
            f"{row['drawnPoints']:8d}",
            flush=True,
        )
        chart.deleteLater()
        app.processEvents()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
        print("json:", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
