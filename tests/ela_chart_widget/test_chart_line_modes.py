"""折线 / 散点的 Plotly 三模式：lines / markers / lines+markers。"""

from __future__ import annotations

from pyqt6_ela_pro.charts import ElaChartWidget


def _chart(make, series: dict):
    chart = make(ElaChartWidget)
    chart.resize(640, 400)
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {"type": "value"},
        "series": [series],
    }
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    return chart


class TestLineModes:
    def test_line_defaults_to_lines_without_markers(self, qapp, make):
        chart = _chart(make, {"type": "line", "name": "L", "data": [1, 2, 3]})
        renderer = chart.seriesRenderers[0]
        assert renderer.plotMode() == "lines"
        assert renderer.showLine()
        assert not renderer.showMarkers()
        assert renderer._symbol_items == []

    def test_line_mode_markers_only(self, qapp, make):
        chart = _chart(
            make,
            {"type": "line", "name": "L", "mode": "markers", "data": [1, 2, 3]},
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.plotMode() == "markers"
        assert not renderer.showLine()
        assert renderer.showMarkers()
        assert renderer._symbol_items

    def test_line_mode_lines_plus_markers(self, qapp, make):
        chart = _chart(
            make,
            {
                "type": "line",
                "name": "L",
                "mode": "lines+markers",
                "data": [1, 2, 3],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.plotMode() == "lines+markers"
        assert renderer.showLine()
        assert renderer.showMarkers()
        assert renderer._symbol_items

    def test_legacy_show_symbol_enables_markers(self, qapp, make):
        chart = _chart(
            make,
            {"type": "line", "name": "L", "showSymbol": True, "data": [1, 2, 3]},
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.plotMode() == "lines+markers"
        assert renderer._symbol_items

    def test_explicit_mode_wins_over_show_symbol(self, qapp, make):
        chart = _chart(
            make,
            {
                "type": "line",
                "name": "L",
                "mode": "lines",
                "showSymbol": True,
                "data": [1, 2, 3],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.plotMode() == "lines"
        assert renderer._symbol_items == []


class TestScatterModes:
    def test_scatter_defaults_to_markers(self, qapp, make):
        chart = _chart(make, {"type": "scatter", "name": "S", "data": [[0, 1], [1, 2]]})
        renderer = chart.seriesRenderers[0]
        assert renderer.plotMode() == "markers"
        assert not renderer.showLine()
        assert renderer.showMarkers()

    def test_scatter_lines_plus_markers(self, qapp, make):
        chart = _chart(
            make,
            {
                "type": "scatter",
                "name": "S",
                "mode": "lines+markers",
                "data": [[0, 1], [1, 2], [2, 3]],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.plotMode() == "lines+markers"
        assert renderer.showLine()
        assert renderer.showMarkers()

    def test_scatter_lines_only(self, qapp, make):
        chart = _chart(
            make,
            {
                "type": "scatter",
                "name": "S",
                "mode": "lines",
                "data": [[0, 1], [1, 2], [2, 3]],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.plotMode() == "lines"
        assert renderer.showLine()
        assert not renderer.showMarkers()
