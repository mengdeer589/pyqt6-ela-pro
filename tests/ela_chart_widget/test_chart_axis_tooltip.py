"""axis tooltip：数值 x 轴按最近点聚合、每系列 marker、item 模式不画指示线。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, **option) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    opt = {"animation": False}
    opt.update(option)
    chart.setOption(opt)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _move(chart, pos):
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    chart.mouseMoveEvent(event)


class TestAxisTooltipValueAxis:
    def test_collects_every_series_at_nearest_x(self, qapp, make):
        chart = _chart(
            make,
            tooltip={"trigger": "axis"},
            xAxis={"type": "value"},
            yAxis={"type": "value"},
            series=[
                {"type": "line", "name": "A", "data": [[1000, 5], [2000, 9], [3000, 4]]},
                {"type": "line", "name": "B", "data": [[1000, 7], [2000, 3], [3000, 8]]},
            ],
        )
        coord = chart.primaryCoord()
        px = coord.x_axis.map(2000, coord.plot.left(), coord.plot.right())
        _move(chart, QPointF(px, coord.plot.center().y()))
        rows = [(name, value) for _color, name, value in chart.tooltip._lines if name]
        assert rows == [("A", "9"), ("B", "3")]
        assert chart.tooltip._axis_pointer is True
        assert len(chart.tooltip._markers) == 2
        assert [(r.name, hit.get("dataIndex")) for r, hit in chart._axis_hover] == [
            ("A", 1),
            ("B", 1),
        ]

    def test_nearest_between_points_picks_closest(self, qapp, make):
        chart = _chart(
            make,
            tooltip={"trigger": "axis"},
            xAxis={"type": "value"},
            yAxis={"type": "value"},
            series=[
                {
                    "type": "line",
                    "name": "A",
                    "data": [[0, 1], [100, 2], [200, 3]],
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.nearestIndexAt(140) == 1
        assert renderer.nearestIndexAt(151) == 2
        assert renderer.nearestIndexAt(-50) == 0

    def test_axis_tooltip_uses_snapped_marker_x(self, qapp, make):
        chart = _chart(
            make,
            tooltip={"trigger": "axis"},
            xAxis={"type": "value"},
            yAxis={"type": "value"},
            series=[{"type": "line", "name": "A", "data": [[0, 1], [100, 5]]}],
        )
        coord = chart.primaryCoord()
        px = coord.x_axis.map(55, coord.plot.left(), coord.plot.right())
        _move(chart, QPointF(px, coord.plot.center().y()))
        # value 轴 snap=auto（false）：指示线跟随光标；marker 落在最近的数据点
        assert chart.tooltip._axis_label == "55"
        assert chart.tooltip._marker_pos is not None
        assert abs(chart.tooltip._marker_pos.x() - px) < 1.0
        snapped = coord.x_axis.map(100, coord.plot.left(), coord.plot.right())
        assert abs(chart.tooltip._markers[0][0].x() - snapped) < 1.0


class TestAxisTooltipCategory:
    def test_category_keeps_category_title(self, qapp, make):
        chart = _chart(
            make,
            tooltip={"trigger": "axis"},
            xAxis={"type": "category", "data": ["一月", "二月", "三月"]},
            yAxis={"type": "value"},
            series=[
                {"type": "line", "name": "A", "data": [1, 2, 3]},
                {"type": "line", "name": "B", "data": [3, 2, 1]},
            ],
        )
        coord = chart.primaryCoord()
        px = coord.x_axis.map(1, coord.plot.left(), coord.plot.right(), local=True)
        _move(chart, QPointF(px, coord.plot.center().y()))
        assert chart.tooltip._lines[0] == (None, "", "二月")
        rows = [(name, value) for _c, name, value in chart.tooltip._lines if name]
        assert rows == [("A", "2"), ("B", "2")]


class TestAxisPointerSemantics:
    def test_default_pointer_is_line(self, qapp, make):
        chart = _chart(make, series=[])
        assert chart.tooltip.axisPointerType() == "line"

    def test_item_tooltip_does_not_draw_pointer(self, qapp, make):
        chart = _chart(
            make,
            tooltip={"trigger": "item"},
            xAxis={"type": "category", "data": ["a", "b"]},
            yAxis={"type": "value"},
            series=[{"type": "line", "mode": "lines+markers", "data": [1, 2]}],
        )
        renderer = chart.seriesRenderers[0]
        _move(chart, QPointF(renderer._points[0]))
        assert chart.tooltip.active is True
        assert chart.tooltip._axis_pointer is False
