"""仪表盘中心数值字号：默认随半径自适应，可显式覆盖。"""

from __future__ import annotations

from pyqt6_ela_pro.charts import ElaChartWidget


def _gauge(make, detail=None):
    chart = make(ElaChartWidget)
    chart.resize(480, 360)
    chart.setOption(
        {
            "animation": False,
            "series": [
                {
                    "type": "gauge",
                    "min": 0,
                    "max": 100,
                    "data": [{"name": "负载", "value": 62}],
                    "detail": detail or {},
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestGaugeDetailFont:
    def test_default_scales_with_radius(self, make):
        chart = _gauge(make)
        renderer = chart.seriesRenderers[0]
        expected = int(
            round(max(12.0, min(22.0, max(13.0, renderer._radius * 0.32))))
        )
        assert renderer._detail_font({}, renderer._radius).pixelSize() == expected

    def test_font_size_override(self, make):
        chart = _gauge(make, {"fontSize": 12})
        renderer = chart.seriesRenderers[0]
        assert renderer._detail_font(renderer.detailStyle(), renderer._radius).pixelSize() == 12

    def test_invalid_font_size_falls_back(self, make):
        chart = _gauge(make, {"fontSize": "not-a-number"})
        renderer = chart.seriesRenderers[0]
        expected = int(
            round(max(12.0, min(22.0, max(13.0, renderer._radius * 0.32))))
        )
        assert renderer._detail_font(renderer.detailStyle(), renderer._radius).pixelSize() == expected
