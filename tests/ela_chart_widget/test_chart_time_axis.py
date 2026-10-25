"""time 轴：日期字符串 / 时间戳、时间刻度与标签、tooltip、min/max。"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts.axes import AxisModel


def _chart(make, **patch):
    chart = make(ElaChartWidget)
    chart.resize(800, 400)
    option = {
        "animation": False,
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "line",
                "name": "A",
                "data": [
                    ["2026-01-01", 3],
                    ["2026-02-01", 7],
                    ["2026-03-01", 5],
                    ["2026-04-01", 9],
                ],
            }
        ],
    }
    option.update(patch)
    chart.setOption(option)
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


class TestTimeNumber:
    def test_iso_string_and_datetime(self):
        expected = datetime(2026, 1, 1).timestamp() * 1000.0
        assert AxisModel.toNumber("2026-01-01") == expected
        assert AxisModel.toNumber(datetime(2026, 1, 1)) == expected
        assert AxisModel.toNumber((2026, 1, 1)) == expected

    def test_numeric_is_milliseconds(self):
        assert AxisModel.toNumber(1767225600000) == 1767225600000.0

    def test_invalid_returns_none(self):
        assert AxisModel.toNumber("not-a-date") is None
        assert AxisModel.toNumber(None) is None


class TestTimeAxis:
    def test_time_axis_uses_value_geometry(self, qapp, make):
        chart = _chart(make)
        axis = chart.primaryCoord().x_axis
        assert axis.is_time is True
        assert axis.type == "value"

    def test_ticks_are_time_labelled(self, qapp, make):
        chart = _chart(make)
        axis = chart.primaryCoord().x_axis
        labels = [axis.formatTickLabel(tick) for tick in axis.ticks()]
        assert labels
        assert all("-" in label or len(label) == 4 for label in labels)
        assert any("2026" in label for label in labels)

    def test_min_max_accept_date_strings(self, qapp, make):
        chart = _chart(
            make,
            xAxis={
                "type": "time",
                "min": "2026-01-15",
                "max": "2026-03-15",
            },
        )
        axis = chart.primaryCoord().x_axis
        assert axis.vmin >= AxisModel.toNumber("2026-01-01")
        assert axis.vmax <= AxisModel.toNumber("2026-04-15")

    def test_axis_tooltip_uses_date_title(self, qapp, make):
        chart = _chart(make)
        coord = chart.primaryCoord()
        x = coord.x_axis.map(
            AxisModel.toNumber("2026-02-01"),
            coord.plot.left(),
            coord.plot.right(),
        )
        _move(chart, QPointF(x, coord.plot.center().y()))
        assert chart.tooltip.active is True
        assert chart.tooltip._axis_label.startswith("2026-02")
        rows = [(name, value) for _c, name, value in chart.tooltip._lines if name]
        assert rows == [("A", "7")]
