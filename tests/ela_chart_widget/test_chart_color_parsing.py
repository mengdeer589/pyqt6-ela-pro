"""ECharts 颜色字符串（``rgb()`` / ``rgba()``）解析。

``QColor`` 不认 CSS ``rgba(...)``：折线面积渐变如果直接喂给 ``QColor`` 会得到
无效色，绘制出来就是**纯黑填充**（示例概览图曾整片发黑）。``parse_color`` 是
唯一解析入口，``with_alpha`` / 系列颜色 / 渐变 stop 都走它。
"""

from __future__ import annotations

import pytest

from PyQt6.QtGui import QColor, QImage, QPainter

from pyqt6_ela_pro._colors import parse_color
from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts._utils import with_alpha


class TestParseColor:
    def test_rgba(self):
        color = parse_color("rgba(84, 112, 198, 0.38)")
        assert color.isValid()
        assert color.name() == "#5470c6"
        assert color.alpha() == round(0.38 * 255)

    def test_rgb(self):
        color = parse_color("rgb(1, 2, 3)")
        assert color.name() == "#010203"
        assert color.alpha() == 255

    def test_hex_and_named(self):
        assert parse_color("#5470c6").name() == "#5470c6"
        assert parse_color("red").name() == "#ff0000"

    def test_invalid(self):
        assert not parse_color("not-a-color").isValid()
        assert not parse_color(None).isValid()
        assert not parse_color(42).isValid()

    def test_with_alpha_accepts_rgba(self):
        color = with_alpha("rgba(84,112,198,0.38)", 128)
        assert color.alpha() == 128
        assert color.name() == "#5470c6"


class TestAreaGradientPaint:
    def test_rgba_stops_render_colored_not_black(self, make):
        chart = make(ElaChartWidget)
        chart.resize(520, 360)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A", "B", "C", "D"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "line",
                        "name": "营收",
                        "data": [10, 40, 25, 45],
                        "smooth": True,
                        "areaStyle": {
                            "color": {
                                "type": "linear",
                                "x": 0,
                                "y": 0,
                                "x2": 0,
                                "y2": 1,
                                "colorStops": [
                                    {"offset": 0, "color": "rgba(84,112,198,0.9)"},
                                    {"offset": 1, "color": "rgba(84,112,198,0.02)"},
                                ],
                            }
                        },
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        coord = chart.primaryCoord()
        img = QImage(
            chart.width(),
            chart.height(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        try:
            chart._paint_content(painter)
        finally:
            painter.end()
        # 取面积填充内部的一点（曲线下方、基线之上）
        x = int(coord.plot.center().x())
        y = int(coord.plot.top() + coord.plot.height() * 0.55)
        color = img.pixelColor(x, y)
        assert color.blue() > color.red(), f"面积渐变仍是黑色/无效色：{color.name()}"


def _calendar_chart(make, **option):
    chart = make(ElaChartWidget)
    chart.resize(720, 240)
    base = {
        "calendar": {"range": 2026, "cellSize": "auto"},
        "visualMap": {"min": 0, "max": 3},
        "series": [
            {
                "type": "heatmap",
                "coordinateSystem": "calendar",
                "name": "Token",
                "data": [
                    {"value": ["2026-01-01", 0]},
                    {"value": ["2026-01-02", 3]},
                ],
            }
        ],
    }
    base.update(option)
    chart.setOption(base)
    chart.anim.setProgress(1.0)
    return chart


class TestCalendarPalette:
    """日历热力的色带走 ``_ramp_color``（visualMap.inRange.colors 的直接消费者）。"""

    def test_rgba_palette_is_not_black(self, make):
        chart = _calendar_chart(
            make,
            visualMap={
                "min": 0,
                "max": 3,
                "inRange": {"colors": ["rgba(235,237,240,1)", "rgba(33,110,57,1)"]},
            },
        )
        cells = {
            cell["value"]: cell["color"]
            for cell in chart._series[0]._cells
            if not cell["empty"]
        }
        assert cells[0.0].name() == "#ebedf0"
        assert cells[3.0].name() == "#216e39"

    def test_calendar_item_style_accepts_rgba(self, make):
        chart = _calendar_chart(
            make,
            calendar={
                "range": 2026,
                "cellSize": "auto",
                "itemStyle": {"color": "rgba(200, 0, 0, 0.5)"},
            },
        )
        empty = next(cell for cell in chart._series[0]._cells if cell["empty"])
        assert empty["color"].name() == "#c80000"
        assert empty["color"].alpha() == 128


_RGBA = "rgba(1, 2, 3, 1)"

#: 各类系列的 data + 需要的坐标系（rgba 颜色只走公共解析链，形状不重要）
_SERIES_CASES = {
    "line": ({"data": [1, 2, 3]}, True),
    "bar": ({"data": [1, 2, 3]}, True),
    "scatter": ({"data": [1, 2, 3]}, True),
    "candlestick": ({"data": [[1, 2, 0, 3]]}, True),
    "pie": ({"data": [{"name": "a", "value": 1}]}, False),
    "funnel": ({"data": [{"name": "a", "value": 1}]}, False),
    "gauge": ({"data": [{"name": "a", "value": 1}]}, False),
    "radar": ({"data": [{"name": "a", "value": [1, 2, 3]}]}, False),
}


class TestOptionColorsAcrossRenderers:
    """option 里的 ``rgba()`` 必须落到 palette / 系列色 / 数据项色。

    改之前这些位置用 ``QColor(str)``（不认 rgb 函数式）→ 无效色 → 画成黑色。
    """

    @pytest.mark.parametrize("kind", list(_SERIES_CASES), ids=list(_SERIES_CASES))
    def test_series_rgba(self, make, kind):
        data, cartesian = _SERIES_CASES[kind]
        chart = make(ElaChartWidget)
        chart.resize(460, 320)
        option = {
            "animation": False,
            "color": [_RGBA],
            "series": [{"type": kind, "color": _RGBA, **data}],
        }
        if cartesian:
            option["xAxis"] = {"type": "category", "data": ["a", "b", "c"]}
            option["yAxis"] = {"type": "value"}
        if kind == "radar":
            option["radar"] = {"indicator": [{"name": "x", "max": 9}] * 3}
        chart.setOption(option)
        chart.anim.setProgress(1.0)

        assert chart.palette()[0].name() == "#010203"
        assert chart.colorForSeries(0).name() == "#010203"
        assert chart._series[0].itemColor(0).name() == "#010203"

    def test_visual_map_rgba_palette(self, make):
        chart = make(ElaChartWidget)
        chart.resize(460, 320)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value"},
                "visualMap": {
                    "min": 0,
                    "max": 10,
                    "inRange": {"colors": ["rgba(1, 2, 3, 1)", "rgba(255, 0, 0, 1)"]},
                },
                "series": [{"type": "bar", "data": [0, 10]}],
            }
        )
        comp = next(item for item in chart.components if item.optionKey == "visualMap")
        assert comp.mapColor(0).name() == "#010203"
        assert comp.mapColor(10).name() == "#ff0000"
