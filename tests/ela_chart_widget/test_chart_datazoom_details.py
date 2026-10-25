"""dataZoom 细节：minValueSpan 别名 / slider 标签 / 滚轮修饰键。"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": [str(i) for i in range(100)]},
        "yAxis": {"type": "value"},
        "dataZoom": [{"type": "inside", "start": 0, "end": 100}],
        "series": [{"type": "line", "name": "A", "data": list(range(100))}],
    }
    option.update(patch)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _wheel(chart, modifiers=Qt.KeyboardModifier.NoModifier):
    plot = chart.primaryCoord().plot
    event = QWheelEvent(
        QPointF(plot.center()),
        QPointF(chart.mapToGlobal(plot.center().toPoint())),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    chart.wheelEvent(event)


class TestZoomSpan:
    def test_min_value_span_alias_clamps(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "inside", "minValueSpan": 40}])
        chart.dispatchAction({"type": "dataZoom", "start": 0, "end": 10})
        zoom = chart._component("dataZoom")
        assert zoom.end - zoom.start >= 40.0


class TestSliderLabels:
    def test_default_percent_label(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "slider", "start": 25, "end": 75}])
        zoom = chart._component("dataZoom")
        assert zoom._slider_label(25) == "25%"

    def test_label_formatter_callable(self, qapp, make):
        chart = _chart(
            make,
            dataZoom=[
                {
                    "type": "slider",
                    "labelFormatter": lambda value: f"{value:.1f} pct",
                }
            ],
        )
        zoom = chart._component("dataZoom")
        assert zoom._slider_label(12.5) == "12.5 pct"

    def test_show_detail_false_still_paints(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "slider", "showDetail": False}])
        assert chart.grab().width() == chart.width()


class TestWheelModifier:
    def test_shift_required(self, qapp, make):
        chart = _chart(
            make,
            dataZoom=[{"type": "inside", "zoomOnMouseWheel": "shift", "start": 0, "end": 100}],
        )
        zoom = chart._component("dataZoom")
        _wheel(chart)
        assert (zoom.start, zoom.end) == (0.0, 100.0)
        _wheel(chart, Qt.KeyboardModifier.ShiftModifier)
        assert zoom.end - zoom.start < 100.0
