"""log 轴：刻度 / 映射 / 非正值过滤 / dataZoom / 柱基线。"""

from __future__ import annotations

import math

import pytest

from pyqt6_ela_pro.charts import AxisModel, ElaChartWidget, GridCoord


def _chart(make, **overrides):
    chart = make(ElaChartWidget)
    chart.resize(640, 400)
    option = {
        "animation": False,
        "xAxis": {"type": "value"},
        "yAxis": {"type": "log"},
        "series": [{"type": "line", "data": [[1, 1], [10, 10], [100, 100]]}],
    }
    option.update(overrides)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    return chart


class TestLogAxisModel:
    def test_ticks_and_mapping_are_logarithmic(self):
        axis = AxisModel({"type": "log"}, "value")
        axis.setExtent(1, 1000)
        assert axis.ticks() == pytest.approx([1.0, 10.0, 100.0, 1000.0])
        assert axis.map(10, 0, 100) == pytest.approx(100.0 / 3.0)
        assert axis.map(100, 0, 100) == pytest.approx(200.0 / 3.0)
        assert axis.invert(50, 0, 100) == pytest.approx(math.sqrt(10.0) * 10.0)

    def test_extreme_labels_use_scientific_notation(self):
        axis = AxisModel({"type": "log"}, "value")
        axis.setExtent(1e-9, 1e-3)
        labels = [axis.formatTickLabel(v) for v in axis.ticks()]
        assert "1e-9" in labels
        assert all(label != "0" for label in labels)

    def test_non_positive_values_are_ignored(self, qapp, make):
        chart = _chart(
            make,
            series=[{"type": "line", "data": [[1, -1], [2, 0], [3, 1], [4, 10]]}],
        )
        axis = chart.primaryCoord().y_axis
        assert axis.vmin == pytest.approx(1.0)
        assert axis.vmax == pytest.approx(10.0)

    def test_all_non_positive_falls_back_to_default_range(self, qapp, make):
        chart = _chart(
            make,
            series=[{"type": "line", "data": [[1, -1], [2, 0], [3, -5]]}],
        )
        axis = chart.primaryCoord().y_axis
        assert axis.vmin > 0.0
        assert axis.vmax > axis.vmin
        chart.grab()


class TestLogAxisChart:
    def test_non_positive_points_do_not_break_paint(self, qapp, make):
        chart = _chart(
            make,
            series=[{"type": "line", "data": [[1, -1], [2, 0], [3, 1], [4, 10]]}],
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        renderer.layout(coord.plot)
        assert any(point is None for point in renderer._points)
        chart.grab()

    def test_map_arrays_returns_nan_for_non_positive(self, qapp, make):
        np = pytest.importorskip("numpy")
        chart = _chart(make)
        coord = chart.primaryCoord()
        px, py = coord.mapArrays(
            np.array([1.0, 10.0, 100.0]),
            np.array([1.0, 10.0, 100.0]),
        )
        assert math.isfinite(py[0])
        _, py_bad = coord.mapArrays(
            np.array([1.0, 10.0, 100.0]),
            np.array([0.0, -1.0, 10.0]),
        )
        assert math.isnan(py_bad[0])
        assert math.isnan(py_bad[1])
        assert math.isfinite(py_bad[2])

    def test_datazoom_uses_log_space(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "log"},
            yAxis={"type": "log"},
            series=[
                {
                    "type": "line",
                    "data": [[1, 1], [10, 10], [100, 100], [1000, 1000]],
                }
            ],
        )
        axis = chart.primaryCoord().x_axis
        assert axis.vmin == pytest.approx(1.0)
        assert axis.vmax == pytest.approx(1000.0)
        chart.dispatchAction({"type": "dataZoom", "start": 50, "end": 100})
        assert axis.vmin == pytest.approx(math.sqrt(1000.0))
        assert axis.vmax == pytest.approx(1000.0)

    def test_bar_baseline_sits_on_axis_min(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "category", "data": ["a", "b", "c"]},
            yAxis={"type": "log"},
            series=[{"type": "bar", "data": [10, 100, 1000]}],
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        renderer.layout(coord.plot)
        assert renderer._bars
        axis_min = coord.y_axis.vmin
        for bar in renderer._bars:
            assert bar["v0"] == pytest.approx(axis_min)
            assert math.isfinite(bar["rect"].top())

    def test_log_axis_on_secondary_y(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "category", "data": ["a", "b", "c"]},
            yAxis=[{"type": "value"}, {"type": "log", "position": "right"}],
            series=[
                {"type": "line", "name": "a", "data": [1, 2, 3]},
                {
                    "type": "line",
                    "name": "b",
                    "yAxisIndex": 1,
                    "data": [10, 100, 1000],
                },
            ],
        )
        coord = chart.primaryCoord()
        assert isinstance(coord, GridCoord)
        assert coord.y_axes[0].vmax == pytest.approx(3.0)
        assert coord.y_axes[1].vmin == pytest.approx(10.0)
        assert coord.y_axes[1].vmax == pytest.approx(1000.0)
