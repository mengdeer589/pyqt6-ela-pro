"""跨图联动：connectCharts 同步 dataZoom / legend / axis tooltip。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import connectCharts, disconnectCharts


def _chart(make):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(
        {
            "animation": False,
            "tooltip": {"trigger": "axis"},
            "legend": {"show": True},
            "xAxis": {"type": "category", "data": [str(i) for i in range(12)]},
            "yAxis": {"type": "value"},
            "dataZoom": [{"type": "inside", "start": 0, "end": 100}],
            "series": [
                {"type": "line", "name": "A", "data": list(range(12))},
                {"type": "line", "name": "B", "data": list(range(12, 24))},
            ],
        }
    )
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _move(chart, pos):
    chart.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pos),
            QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


class TestConnectCharts:
    def _pair(self, make):
        first = _chart(make)
        second = _chart(make)
        first.setGroup("g")
        second.setGroup("g")
        connectCharts("g")
        return first, second

    def test_data_zoom_syncs(self, qapp, make):
        first, second = self._pair(make)
        first.dispatchAction({"type": "dataZoom", "start": 20, "end": 60})
        zoom = second._component("dataZoom")
        assert (zoom.start, zoom.end) == (20.0, 60.0)
        disconnectCharts("g")

    def test_legend_syncs(self, qapp, make):
        first, second = self._pair(make)
        first.dispatchAction({"type": "legendUnSelect", "name": "A"})
        assert second._seriesVisible("A") is False
        disconnectCharts("g")

    def test_axis_tooltip_syncs(self, qapp, make):
        first, second = self._pair(make)
        coord = first.primaryCoord()
        pos = QPointF(
            coord.plot.left() + coord.plot.width() * 0.25, coord.plot.center().y()
        )
        _move(first, pos)
        assert first.tooltip.active is True
        assert second.tooltip.active is True
        assert [name for _c, name, _v in second.tooltip._lines if name] == ["A", "B"]
        disconnectCharts("g")

    def test_disconnect_stops_sync(self, qapp, make):
        first, second = self._pair(make)
        disconnectCharts("g")
        first.dispatchAction({"type": "dataZoom", "start": 30, "end": 70})
        zoom = second._component("dataZoom")
        assert (zoom.start, zoom.end) == (0.0, 100.0)
