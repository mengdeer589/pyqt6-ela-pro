"""跨图 ``universalTransition``：同组图表交换旧几何 / 截图。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import connectCharts, disconnectCharts


def _option(values, *, universal=True, typ="bar"):
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
        "yAxis": {"type": "value"},
        "series": [{"type": typ, "name": "S", "data": values}],
    }
    if universal:
        option["universalTransition"] = {"enabled": True, "duration": 80}
    return option


def _ready(make, option):
    chart = make(ElaChartWidget)
    chart.resize(420, 300)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def test_cross_chart_universal_transition(make):
    source = _ready(make, _option([1, 2, 3]))
    target = _ready(make, _option([1, 2, 3]))
    source.setGroup("cross-universal")
    target.setGroup("cross-universal")
    connectCharts("cross-universal")
    try:
        source.setOption({"series": [{"type": "bar", "name": "S", "data": [3, 2, 1]}]})
        state = target._incoming_morph
        assert state is not None
        assert target._incoming_t == 0.0
        assert state["morph"][0][0] == "S"
        assert state["morph"][0][1]["kind"] == "bar"
        assert state["plot"].width() > 0

        target._layout_all(force=True)
        from PyQt6.QtGui import QColor, QImage, QPainter

        image = QImage(target.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        try:
            target._paint_content(painter)
        finally:
            painter.end()
        # 到点后状态必须清空，不能留下永久叠加层。
        target._incoming_started = 0.0
        target._incoming_duration = 1.0
        target._tick_universal()
        assert target._incoming_morph is None
    finally:
        disconnectCharts("cross-universal")


def test_cross_chart_ignores_other_group(make):
    source = _ready(make, _option([1, 2, 3]))
    other = _ready(make, _option([1, 2, 3]))
    source.setGroup("group-a")
    other.setGroup("group-b")
    try:
        source.setOption({"series": [{"type": "bar", "name": "S", "data": [3, 2, 1]}]})
        assert other._incoming_morph is None
    finally:
        disconnectCharts()


def test_cross_chart_requires_target_enabled(make):
    source = _ready(make, _option([1, 2, 3]))
    target = _ready(make, _option([1, 2, 3], universal=False))
    source.setGroup("cross-off")
    target.setGroup("cross-off")
    try:
        source.setOption({"series": [{"type": "bar", "name": "S", "data": [3, 2, 1]}]})
        assert target._incoming_morph is None
    finally:
        disconnectCharts("cross-off")
