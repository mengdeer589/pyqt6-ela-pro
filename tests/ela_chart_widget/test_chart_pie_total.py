"""环形饼中心总计 `totalLabel` 的字号：默认随内半径自适应，可显式覆盖。"""

from __future__ import annotations

from PyQt6.QtGui import QImage, QPainter

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts.axes import chartFont


def _donut(make, total_label):
    chart = make(ElaChartWidget)
    chart.resize(640, 420)
    chart.setOption(
        {
            "animation": False,
            "series": [
                {
                    "type": "pie",
                    "radius": ["42%", "68%"],
                    "totalLabel": total_label,
                    "data": [
                        {"name": "A", "value": 60},
                        {"name": "B", "value": 40},
                    ],
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _paint_font(chart):
    renderer = chart.seriesRenderers[0]
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        renderer._paint_center_total(painter, chartFont(11))
        return painter.font().pixelSize()
    finally:
        painter.end()


class TestPieCenterTotal:
    def test_default_scales_with_inner_radius(self, make):
        chart = _donut(make, {"show": True})
        renderer = chart.seriesRenderers[0]
        expected = int(
            round(max(12.0, min(22.0, max(13.0, renderer._r_in * 0.32))))
        )
        assert _paint_font(chart) == expected

    def test_font_size_override(self, make):
        chart = _donut(make, {"show": True, "fontSize": 12})
        assert _paint_font(chart) == 12

    def test_invalid_font_size_falls_back(self, make):
        chart = _donut(make, {"show": True, "fontSize": "not-a-number"})
        renderer = chart.seriesRenderers[0]
        expected = int(
            round(max(12.0, min(22.0, max(13.0, renderer._r_in * 0.32))))
        )
        assert _paint_font(chart) == expected
