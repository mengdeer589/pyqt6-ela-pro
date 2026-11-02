"""图例悬停：饼 / 漏斗的数据项图例不能把整条系列压暗。"""

from __future__ import annotations

from PyQt6.QtGui import QImage, QPainter

from pyqt6_ela_pro.charts import ElaChartWidget


def _chart(make, series):
    chart = make(ElaChartWidget)
    chart.resize(480, 360)
    chart.setOption(
        {
            "animation": False,
            "legend": {"bottom": 0},
            "series": [series],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _paint_opacities(chart):
    renderer = chart.seriesRenderers[0]
    seen = []
    renderer.paint = lambda p, t: seen.append(p.opacity())
    image = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        chart._paint_series(painter, 1.0)
    finally:
        painter.end()
    return seen


class TestItemLegendHover:
    def test_pie_item_legend_hover_keeps_series_opaque(self, make):
        chart = _chart(
            make,
            {
                "type": "pie",
                "name": "访问",
                "data": [
                    {"name": "直接访问", "value": 60},
                    {"name": "搜索引擎", "value": 40},
                ],
            },
        )
        chart._legend_hover = "直接访问"
        assert _paint_opacities(chart) == [1.0]

    def test_funnel_item_legend_hover_keeps_series_opaque(self, make):
        chart = _chart(
            make,
            {
                "type": "funnel",
                "name": "转化",
                "data": [
                    {"name": "曝光", "value": 60},
                    {"name": "点击", "value": 40},
                ],
            },
        )
        chart._legend_hover = "曝光"
        assert _paint_opacities(chart) == [1.0]

    def test_series_legend_hover_still_dims_other_series(self, make):
        chart = make(ElaChartWidget)
        chart.resize(480, 360)
        chart.setOption(
            {
                "animation": False,
                "legend": {"bottom": 0},
                "xAxis": {"type": "category", "data": ["A"]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "bar", "name": "一", "data": [1]},
                    {"type": "bar", "name": "二", "data": [2]},
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        chart._legend_hover = "一"
        seen = []
        for renderer in chart.seriesRenderers:
            renderer.paint = lambda p, t: seen.append(p.opacity())
        image = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        try:
            chart._paint_series(painter, 1.0)
        finally:
            painter.end()
        assert seen == [1.0, 0.35]

    def test_pie_legend_click_marks_item_disabled(self, make):
        chart = _chart(
            make,
            {
                "type": "pie",
                "name": "访问",
                "data": [
                    {"name": "直接访问", "value": 60},
                    {"name": "搜索引擎", "value": 40},
                ],
            },
        )
        chart._legendSelectToggle("直接访问")
        assert chart._legendItemVisible("直接访问") is False
        assert chart._legendItemVisible("搜索引擎") is True

    def test_series_legend_click_marks_series_disabled(self, make):
        chart = make(ElaChartWidget)
        chart.resize(480, 360)
        chart.setOption(
            {
                "animation": False,
                "legend": {"bottom": 0},
                "xAxis": {"type": "category", "data": ["A"]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "bar", "name": "一", "data": [1]},
                    {"type": "bar", "name": "二", "data": [2]},
                ],
            }
        )
        chart._legendSelectToggle("一")
        assert chart._legendItemVisible("一") is False
        assert chart._legendItemVisible("二") is True
