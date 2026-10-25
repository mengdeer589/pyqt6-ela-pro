"""折线专项：smoothMonotone / step 数组 / areaStyle.origin / endLabel / 符号。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts.series_cartesian import _monotone_path


def _chart(make, series, **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": [str(i) for i in range(len(series[0]["data"]))]},
        "yAxis": {"type": "value"},
        "series": series,
    }
    option.update(patch)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    chart.grab()
    return chart


class TestSmoothMonotone:
    def test_monotone_path_does_not_overshoot(self):
        points = [QPointF(0, 0), QPointF(1, 10), QPointF(2, 10), QPointF(3, 10)]
        path = _monotone_path(points)
        bounds = path.boundingRect()
        assert bounds.top() >= -0.01
        assert bounds.bottom() <= 10.01

    def test_series_uses_monotone_path(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [0, 10, 10, 10],
                    "smooth": True,
                    "smoothMonotone": True,
                }
            ],
        )
        path, _pts = chart.seriesRenderers[0]._line_path(
            [QPointF(0, 100), QPointF(10, 50), QPointF(20, 50)]
        )
        assert path is not None
        assert path.boundingRect().top() >= 49.9


class TestStepAndOrigin:
    def test_step_array_start(self, qapp, make):
        chart = _chart(
            make,
            [{"type": "line", "name": "A", "data": [1, 2], "step": [True, False]}],
        )
        _path, pts = chart.seriesRenderers[0]._line_path(
            [QPointF(0, 100), QPointF(10, 50)]
        )
        assert len(pts) == 3
        assert pts[1] == QPointF(0, 50)

    def test_area_origin_start_uses_axis_min(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [100, 200, 150],
                    "areaStyle": {"origin": "start"},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        baseline = renderer._baseline_y(coord, {"origin": "start"})
        assert abs(baseline - coord.plot.bottom()) < 1.0

    def test_area_origin_number(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [100, 200, 150],
                    "areaStyle": {"origin": 150},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        baseline = renderer._baseline_y(coord, {"origin": 150})
        expected = coord.y_axis.map(150, coord.plot.bottom(), coord.plot.top())
        assert abs(baseline - expected) < 1.0


class TestLineSymbolsAndEndLabel:
    def test_show_all_symbol(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "mode": "lines+markers",
                    "showAllSymbol": True,
                    "data": list(range(100)),
                }
            ],
        )
        assert len(chart.seriesRenderers[0]._symbol_items) == 100

    def test_symbol_rotate_renders(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "mode": "lines+markers",
                    "symbol": "triangle",
                    "symbolRotate": 90,
                    "data": [1, 2, 3],
                }
            ],
        )
        assert chart.seriesRenderers[0]._symbol_items
        assert chart.grab().width() == chart.width()

    def test_end_label(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 5, 9],
                    "endLabel": {"show": True, "formatter": "末值 {c}"},
                }
            ],
        )
        end = chart.seriesRenderers[0]._end_label
        assert end is not None
        assert end[0] == "末值 9"

    def test_line_style_opacity_and_cap(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 2, 3],
                    "lineStyle": {"opacity": 0.5, "cap": "butt", "join": "bevel"},
                }
            ],
        )
        assert chart.grab().width() == chart.width()
