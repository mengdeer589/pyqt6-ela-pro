"""折线 gap 插入（记录中断）、单调 x 快路径与包络保峰的回归契约。

背景：冲击 / 振动等物理试验数据是**等间隔时间戳 + 可能的记录中断**
（如 0.1、0.2、0.3… 中夹一段 7s 跳变）。抽稀后中断会被直线桥接 ——
两级规则修复（见 ``charts/_downsample.py::analyze_x`` 与
``LineSeriesRenderer._apply_gap_breaks``）：

1. 数据侧：相邻时间差 > 4.1 × 步长（正差中位数）处 = 中断，一次性预计算；
2. 屏幕侧：中断在当前窗口的像素宽度 ≥ 4px 才断开（亚像素空洞照常连线）。

同时钉住「单调 x 的 searchsorted 窗口与全量掩码逐值等价」与
「每桶 min/max 必在采样输出」（冲击尖峰不许丢）。
"""

from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import _downsample as ds

pytestmark = pytest.mark.skipif(
    ds.np is None or not ds.available(), reason="需要 numpy + tsdownsample"
)


def _two_col(t, y):
    return np.column_stack(
        [np.asarray(t, dtype=np.float64), np.asarray(y, dtype=np.float64)]
    )


def _option(t, y, **series):
    return {
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "A", "data": _two_col(t, y), **series}],
    }


def _render(chart):
    chart.anim.setProgress(1.0)
    chart.show()
    for _ in range(3):
        QApplication.processEvents()
    return chart.seriesRenderers[0]


def _zoom(chart, start_value, end_value):
    chart.dispatchAction(
        {"type": "dataZoom", "startValue": start_value, "endValue": end_value}
    )
    chart.grab()
    QApplication.processEvents()


def _gapped(n=100_000, step=0.1, at=None, gap=30.0):
    """等间隔时间基 + 一处记录中断（gap 秒）。"""
    if at is None:
        at = n // 2
    t = np.concatenate(
        [
            np.arange(at, dtype=np.float64) * step,
            (at * step + gap) + np.arange(n - at, dtype=np.float64) * step,
        ]
    )
    return t, np.sin(t * 0.1)


def _none_count(r):
    return sum(pt is None for pt in r._points)


# ---------------------------------------------------------------------------
# analyze_x：时间基一次性分析
# ---------------------------------------------------------------------------


class TestAnalyzeX:
    def test_uniform_grid(self):
        t = np.arange(200_000, dtype=np.float64) * 0.1
        mono, strict, step, pos, dur = ds.analyze_x(t)
        assert mono and strict
        assert step == pytest.approx(0.1, rel=1e-9)
        assert pos.size == 0 and dur.size == 0

    def test_gap_detected_with_position_and_duration(self):
        t = np.concatenate(
            [
                np.arange(50_000, dtype=np.float64) * 0.1,
                5_000.0 + 7.0 + np.arange(50_000, dtype=np.float64) * 0.1,
            ]
        )
        mono, strict, step, pos, dur = ds.analyze_x(t)
        assert mono and strict
        assert pos.tolist() == [49_999]
        assert dur[0] == pytest.approx(7.1, rel=1e-6)

    def test_small_jumps_are_not_gaps(self):
        """±几个采样间隔的抖动 / 缺样不算中断（4.1 × 步长内）。"""
        t = np.arange(100_000, dtype=np.float64) * 0.1
        t[50_000:] += 0.3  # 3 个间隔的缺口
        _, _, _, pos, _ = ds.analyze_x(t)
        assert pos.size == 0

    def test_unsorted_is_not_monotone(self):
        mono, strict, step, pos, dur = ds.analyze_x(np.array([0.0, 2.0, 1.0]))
        assert not mono and not strict
        assert pos.size == 0

    def test_duplicates_are_monotone_not_strict(self):
        mono, strict, step, pos, dur = ds.analyze_x(
            (np.arange(10_000, dtype=np.float64) // 2)
        )
        assert mono and not strict
        assert pos.size == 0

    def test_non_finite_is_rejected(self):
        x = np.arange(10_000, dtype=np.float64)
        x[10] = np.nan
        mono, strict, step, pos, dur = ds.analyze_x(x)
        assert not mono and not strict

    def test_short_series_skips_gap_scan(self):
        t = np.array([0.0, 1.0, 2.0, 3.0, 8.0, 9.0])
        mono, strict, step, pos, dur = ds.analyze_x(t)
        assert mono and strict
        assert pos.size == 0 and step == 0.0

    def test_float32_timestamps_no_false_gaps(self):
        t = (np.arange(200_000, dtype=np.float32) * np.float32(0.1)).astype(np.float64)
        _, strict, step, pos, _ = ds.analyze_x(t)
        assert strict
        assert step == pytest.approx(0.1, rel=0.05)
        assert pos.size == 0


# ---------------------------------------------------------------------------
# gap 插入（记录中断）的屏幕侧行为
# ---------------------------------------------------------------------------


class TestGapBreaks:
    def test_gap_detected_at_data_level(self, make):
        """数据侧：中断位置与时长一次性预计算。"""
        t, y = _gapped(gap=30.0)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y))
        r = _render(chart)
        assert r._np_gap_pos is not None
        assert r._np_gap_pos.tolist() == [49_999]
        assert r._np_gap_dur[0] == pytest.approx(30.1, rel=1e-6)

    def test_visible_gap_breaks_polyline(self, make):
        """300s 中断在全景里 ≈ 26px（≥4px）→ 必须断开。"""
        t, y = _gapped(gap=300.0)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y))
        r = _render(chart)
        assert _none_count(r) == 1, "可见的记录中断未断开"
        # 断点占位必须保持 _point_idx 升序（valueAtIndex 用二分查最近点）；
        # 占位是「重复前一下标 + 对应 None 点」。
        assert r._point_idx == sorted(r._point_idx), "断点占位破坏了 _point_idx 升序"
        gap = r._points.index(None)
        assert 0 < gap < len(r._point_idx)
        assert r._point_idx[gap] == r._point_idx[gap - 1]

    def test_subpixel_gap_kept_connected(self, make):
        """10s 中断在全景里 <1px → 数据侧检测到但屏幕侧不断开。"""
        t, y = _gapped(gap=10.0)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y))
        r = _render(chart)
        assert r._np_gap_pos.size == 1, "数据侧应检测到中断"
        assert _none_count(r) == 0, "亚像素空洞不应断开"

    def test_gap_becomes_visible_when_zoomed(self, make):
        """同一份数据：全景不断，缩放到中断处（30s / 200s 窗口）必须断。"""
        t, y = _gapped(gap=30.0)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y))
        r = _render(chart)
        assert _none_count(r) == 0, "全景下 30s 中断约 2.7px，不应断开"

        _zoom(chart, 4_900.0, 5_100.0)
        assert _none_count(r) == 1, "缩放到中断处后应断开"

    def test_connect_nulls_disables_gap_breaks(self, make):
        t, y = _gapped(gap=300.0)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y, connectNulls=True))
        r = _render(chart)
        assert _none_count(r) == 0, "connectNulls 应关闭 gap 断开"

    def test_add_gaps_false_disables(self, make):
        t, y = _gapped(gap=300.0)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y, addGaps=False))
        r = _render(chart)
        assert _none_count(r) == 0, "addGaps=False 应关闭 gap 断开"

    def test_uniform_no_false_gaps(self, make):
        n = 200_000
        t = np.arange(n, dtype=np.float64) * 0.1
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, np.sin(t * 0.3)))
        r = _render(chart)
        assert r._np_gap_pos.size == 0
        assert _none_count(r) == 0

    def test_float32_timestamps_no_false_breaks(self, make):
        """float32 时间戳的量化抖动不得触发假断点。"""
        n = 200_000
        t = (np.arange(n, dtype=np.float32) * np.float32(0.1)).astype(np.float64)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, np.sin(t * 0.3)))
        r = _render(chart)
        assert r._np_gap_pos.size == 0
        assert _none_count(r) == 0


# ---------------------------------------------------------------------------
# 单调 x 快路径（searchsorted 连续窗口）
# ---------------------------------------------------------------------------


class TestMonotoneWindow:
    def test_sorted_x_uses_contiguous_window_equal_to_mask(self, make):
        n = 20_000
        t = np.arange(n, dtype=np.float64) * 0.1
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, np.sin(t)))
        r = _render(chart)
        assert r._np_x_monotone and r._np_x_strict

        _zoom(chart, 500.0, 600.0)
        coord = chart.primaryCoord()
        win = r._window(coord)
        assert isinstance(win, tuple), "单调 x 必须走连续段（切片视图）"
        expected = np.flatnonzero((t >= coord.x_axis.vmin) & (t <= coord.x_axis.vmax))
        np.testing.assert_array_equal(np.arange(win[0], win[1]), expected)

    def test_unsorted_x_window_is_mask(self, make):
        n = 20_000
        t = (np.arange(n, dtype=np.float64) % 1000).astype(np.float64)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, np.sin(np.arange(n, dtype=np.float64))))
        r = _render(chart)
        assert not r._np_x_monotone

        _zoom(chart, 100.0, 300.0)
        coord = chart.primaryCoord()
        win = r._window(coord)
        assert isinstance(win, np.ndarray), "乱序 x 必须退回掩码下标"
        expected = np.flatnonzero((t >= coord.x_axis.vmin) & (t <= coord.x_axis.vmax))
        np.testing.assert_array_equal(win, expected)

    def test_x_analysis_runs_once_per_data_identity(self, make):
        """时间基分析（O(n)）必须按数据身份缓存，不得每次布局重跑。"""
        n = 100_000
        t = np.arange(n, dtype=np.float64) * 0.1
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, np.sin(t)))
        _render(chart)

        calls = []
        orig = ds.analyze_x

        def counted(x):
            calls.append(1)
            return orig(x)

        ds.analyze_x = counted
        try:
            chart.invalidateLayout()
            _render(chart)
        finally:
            ds.analyze_x = orig
        assert not calls, "同数据重复布局不应重跑 analyze_x"


# ---------------------------------------------------------------------------
# 摄入契约：2D [x, y] 数据必须转出 C 连续副本（否则 tsdownsample 静默降级）
# ---------------------------------------------------------------------------


class TestContiguousIntake:
    def test_two_column_data_is_contiguous_for_tsdownsample(self, make):
        """列视图会被 tsdownsample 的 Rust 侧静默拒绝 → 必须一次性转连续。

        退化代价实测：1M 点降采样 0.5ms → 12ms（numpy 兜底），且每次新窗口
        都要重付。这条守卫钉住「2D 输入不静默降级」。
        """
        t, y = _gapped(gap=30.0)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y))
        r = _render(chart)
        assert r._np_x.flags["C_CONTIGUOUS"], "x 列视图未转连续副本"
        assert r._np_y.flags["C_CONTIGUOUS"], "y 列视图未转连续副本"
        picked = ds.downsample_indices(r._np_x, r._np_y, 2600, "minmax")
        assert picked is not None, "连续副本缺失 —— tsdownsample 路径被静默降级"

    def test_contiguous_copy_keeps_values(self, make):
        t, y = _gapped(gap=30.0)
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y))
        r = _render(chart)
        np.testing.assert_array_equal(r._np_x, t)
        np.testing.assert_array_equal(r._np_y, y)


# ---------------------------------------------------------------------------
# 包络保峰（冲击 / 振动语义）
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_single_spike_survives_sampling(self, make):
        n = 500_000
        t = np.arange(n, dtype=np.float64) * 0.1
        y = np.sin(t * 0.2)
        y[123_456] = 7.5
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y))
        r = _render(chart)
        assert r._sampled
        assert 123_456 in set(r._point_idx), "单点尖峰被抽稀丢了"

    def test_window_extremes_preserved(self, make):
        """minmax 包络：窗口内的全局极值必须出现在采样输出里。"""
        n = 500_000
        t = np.arange(n, dtype=np.float64) * 0.1
        y = np.sin(t * 0.5)
        y[100_000] = 9.0
        y[400_000] = -9.0
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(_option(t, y))
        r = _render(chart)
        idx = {i for i in r._point_idx if i >= 0}
        assert 100_000 in idx and 400_000 in idx
        kept = np.array([y[i] for i in sorted(idx)])
        assert kept.max() == pytest.approx(9.0)
        assert kept.min() == pytest.approx(-9.0)
