"""折线 / 散点的**绘制量上界**（LOD）与坐标轴标签抽稀。

为什么钉几何而不是耗时：墙钟受机器与 CI 负载影响（本仓库的既定纪律），
而 LOD 的契约是「绘制量与像素尺寸挂钩、与数据量解耦」——那个可以用
结构断言精确钉住。

覆盖：
1. 折线（value / category 轴）：抽稀后点数 ≤ 2×绘图宽 × pointsPerPixel；
2. `sampling: false` 时**不抽稀**（用户显式要求全量）；
3. 散点：窗口 + 像素密度抽稀；
4. 符号（点）：数量 ≤ 每 10px 一个；
5. 坐标轴标签 / 刻度：步长按标签宽度算（不重叠），1M 个类别的轴不会画 1M 个标签。
"""

from __future__ import annotations

import numpy as np
import pytest

from pyqt6_ela_pro import ElaChartWidget

N_SMALL = 5_000
N_LARGE = 200_000


def _line(chart: ElaChartWidget, n: int, **series) -> None:
    opt = {
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "line",
                "name": "A",
                "data": (np.arange(n) % 997).astype(np.float64),
                **series,
            }
        ],
    }
    chart.setOption(opt)


def _category_line(chart: ElaChartWidget, n: int, **series) -> None:
    opt = {
        "xAxis": {"type": "category", "data": [str(i) for i in range(n)]},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "line",
                "name": "A",
                "data": (np.arange(n) % 997).astype(np.float64),
                **series,
            }
        ],
    }
    chart.setOption(opt)


class TestLineLOD:
    def test_value_axis_draws_pixel_bounded(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        _line(chart, N_LARGE)
        chart.anim.setProgress(1.0)
        renderer = chart.seriesRenderers[0]
        assert renderer._sampled is True
        # 1000px × 2 点/px（默认 pointsPerPixel）+ 桶边界余量
        assert len(renderer._points) <= 1000 * 2 + 64

    def test_category_axis_draws_pixel_bounded(self, qapp, make):
        """**category 轴此前完全不抽稀**：1M 类别要画 1M 段。"""

        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        _category_line(chart, N_LARGE)
        chart.anim.setProgress(1.0)
        renderer = chart.seriesRenderers[0]
        assert renderer._sampled is True
        assert len(renderer._points) <= 1000 * 2 + 64

    def test_sampling_false_keeps_full_data(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        _line(chart, N_SMALL, sampling=False)
        chart.anim.setProgress(1.0)
        renderer = chart.seriesRenderers[0]
        assert renderer._sampled is False
        assert len(renderer._points) == N_SMALL

    def test_small_data_untouched(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        _line(chart, 200)
        chart.anim.setProgress(1.0)
        renderer = chart.seriesRenderers[0]
        assert renderer._sampled is False
        assert len(renderer._points) == 200

    def test_unsorted_x_still_decimated(self, qapp, make):
        """x 不单调（tsdownsample 要求有序）时必须仍能抽稀 —— 走 numpy 按桶兜底。"""

        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        n = 50_000
        xs = (np.arange(n) % 1000).astype(np.float64)  # 非单调
        opt = {
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "A",
                    "data": np.column_stack([xs, (np.arange(n) % 97).astype(float)]),
                }
            ],
        }
        chart.setOption(opt)
        chart.anim.setProgress(1.0)
        renderer = chart.seriesRenderers[0]
        assert renderer._sampled is True
        assert len(renderer._points) <= 1000 * 2 + 64

    def test_symbols_pixel_bounded(self, qapp, make):
        """符号数量按像素密度（约每 10px 一个），与数据量无关。"""

        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        _line(chart, N_LARGE, symbol="circle", showSymbol=True)
        chart.anim.setProgress(1.0)
        renderer = chart.seriesRenderers[0]
        assert 0 < len(renderer._symbol_items) <= 1000 / 10 + 8


class TestScatterLOD:
    def _scatter(self, chart, n: int, **series) -> None:
        opt = {
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "scatter",
                    "name": "S",
                    "data": (np.arange(n) % 997).astype(np.float64),
                    "symbolSize": 4,
                    **series,
                }
            ],
        }
        chart.setOption(opt)

    def test_large_scatter_is_decimated(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        self._scatter(chart, N_LARGE)
        chart.anim.setProgress(1.0)
        renderer = chart.seriesRenderers[0]
        assert 0 < len(renderer._dots) <= 1000 * 4 + 64

    def test_small_scatter_untouched(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        self._scatter(chart, 500)
        chart.anim.setProgress(1.0)
        assert len(chart.seriesRenderers[0]._dots) == 500


class TestAxisIntervalLOD:
    """坐标轴标签 / 刻度的抽稀（``interval: 'auto'``）。"""

    def test_huge_category_axis_does_not_draw_every_label(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        _category_line(chart, N_LARGE)
        coord = chart.primaryCoord()
        step = coord._interval_step(coord.x_axis, False, "axisLabel")
        assert step > 1, "1M 个类别的轴必须抽稀标签"
        drawn = len(coord._axis_positions(coord.x_axis, False, step))
        # 标签不重叠：每个标签至少占「标签宽度」的像素
        assert drawn * 20 <= 1000 + 8

    def test_explicit_interval_respected(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        chart.setOption(
            {
                "xAxis": {"type": "category", "data": [str(i) for i in range(100)]},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "data": list(range(100))}],
            }
        )
        coord = chart.primaryCoord()
        coord.x_axis.opt.setdefault("axisLabel", {})["interval"] = 9  # 每 10 个一个
        assert coord._interval_step(coord.x_axis, False, "axisLabel") == 10

    def test_ticks_never_denser_than_labels(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(1000, 600)
        _category_line(chart, N_LARGE)
        coord = chart.primaryCoord()
        label_step = coord._interval_step(coord.x_axis, False, "axisLabel")
        tick_step = coord._interval_step(coord.x_axis, False, "axisTick")
        assert tick_step >= label_step


class TestSamplingFallbacks:
    def test_bucket_minmax_is_monotonic_and_bounded(self):
        from pyqt6_ela_pro.charts import _downsample as ds

        if ds.np is None:  # pragma: no cover - numpy 是 charts 的可选依赖
            pytest.skip("缺 numpy")
        y = ds.np.sin(ds.np.arange(10_000)) * 100
        picked = ds.bucket_minmax_indices(y, 500)
        assert picked is not None
        assert len(picked) <= 500 + 8
        assert list(picked) == sorted(picked.tolist())
        # 包络保形：抽稀后的极值必须覆盖原始极值（min/max 是保形算法）
        assert y[int(picked[0]) :].min() >= y.min() - 1e-9
        assert y.max() <= y[list(picked)].max() + 1e-9

    def test_bucket_minmax_skips_all_nan_bucket(self):
        from pyqt6_ela_pro.charts import _downsample as ds

        if ds.np is None:  # pragma: no cover
            pytest.skip("缺 numpy")
        y = ds.np.full(1000, ds.np.nan)
        y[400:410] = 1.0
        picked = ds.bucket_minmax_indices(y, 100)
        assert picked is not None
        assert all(400 <= int(i) < 410 for i in picked)
