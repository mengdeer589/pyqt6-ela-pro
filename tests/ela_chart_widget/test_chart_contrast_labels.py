"""填充色上的标签对比色：显式 label.color 优先，否则按填充色选黑 / 白。"""

from __future__ import annotations

from PyQt6.QtGui import QColor

from pyqt6_ela_pro import ElaChartWidget


def _bar_chart(make, item=None):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "data": [item or 10],
                    "label": {"show": True, "position": "inside"},
                    "itemStyle": {"color": "#000000"},
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestContrastLabelColor:
    def test_dark_fill_uses_white(self, qapp, make):
        renderer = _bar_chart(make).seriesRenderers[0]
        assert renderer.contrastLabelColor(QColor("#000000"), 0).name() == "#ffffff"

    def test_light_fill_uses_black(self, qapp, make):
        renderer = _bar_chart(make).seriesRenderers[0]
        assert renderer.contrastLabelColor(QColor("#ffffff"), 0).name() == "#000000"

    def test_explicit_series_color_wins(self, qapp, make):
        chart = _bar_chart(make)
        chart.updateSeries(
            {"label": {"show": True, "position": "inside", "color": "#ff0000"}},
            seriesIndex=0,
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.contrastLabelColor(QColor("#000000"), 0).name() == "#ff0000"

    def test_explicit_item_color_wins(self, qapp, make):
        chart = _bar_chart(
            make,
            {"value": 10, "label": {"color": "#00ff00"}},
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.contrastLabelColor(QColor("#000000"), 0).name() == "#00ff00"
