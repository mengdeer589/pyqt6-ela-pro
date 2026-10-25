"""光标反馈：命中数据 / 图例 / 缩放 / 平移 / slider / 离开。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "line", "name": "A", "mode": "lines+markers", "data": [1, 2, 3]}
        ],
    }
    option.update(patch)
    chart.setOption(option)
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


class TestCursor:
    def test_pointer_over_data(self, qapp, make):
        chart = _chart(make)
        _move(chart, chart.seriesRenderers[0]._points[1])
        assert chart.cursor().shape() == Qt.CursorShape.PointingHandCursor

    def test_cross_cursor_in_zoom_mode(self, qapp, make):
        chart = _chart(make)
        chart.setDragMode("zoom")
        coord = chart.primaryCoord()
        _move(chart, QPointF(coord.plot.right() - 4, coord.plot.top() + 4))
        assert chart.cursor().shape() == Qt.CursorShape.CrossCursor

    def test_open_hand_in_pan_mode(self, qapp, make):
        chart = _chart(make)
        chart.setDragMode("pan")
        coord = chart.primaryCoord()
        _move(chart, QPointF(coord.plot.right() - 4, coord.plot.top() + 4))
        assert chart.cursor().shape() == Qt.CursorShape.OpenHandCursor

    def test_arrow_outside_plot(self, qapp, make):
        chart = _chart(make)
        _move(chart, QPointF(2, 2))
        assert chart.cursor().shape() == Qt.CursorShape.ArrowCursor

    def test_leave_resets_arrow(self, qapp, make):
        chart = _chart(make)
        _move(chart, chart.seriesRenderers[0]._points[1])
        chart.leaveEvent(QEvent(QEvent.Type.Leave))
        assert chart.cursor().shape() == Qt.CursorShape.ArrowCursor

    def test_slider_handle_cursor(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "slider", "start": 0, "end": 100}])
        zoom = chart._component("dataZoom")
        _move(chart, zoom._h_start.center())
        assert chart.cursor().shape() == Qt.CursorShape.SizeHorCursor
