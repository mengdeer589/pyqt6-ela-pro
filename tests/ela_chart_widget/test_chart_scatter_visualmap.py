"""散点 / 气泡图吃 ``visualMap``：按值上色（连续 / 分段 / dimension / 系列绑定）。"""

from __future__ import annotations

from pyqt6_ela_pro.charts import ElaChartWidget

_BASE = {
    "animation": False,
    "xAxis": {"type": "value", "min": 0, "max": 10},
    "yAxis": {"type": "value", "min": 0, "max": 10},
}


def _chart(make, series, **extra):
    chart = make(ElaChartWidget)
    chart.resize(420, 300)
    option = dict(_BASE)
    option["series"] = series
    option.update(extra)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _scatter(data, **extra):
    series = {"type": "scatter", "symbolSize": 20, "data": data}
    series.update(extra)
    return series


class TestContinuousVisualMap:
    def test_endpoints_map_to_band_colors(self, make):
        chart = _chart(
            make,
            [_scatter([[2, 2, 0], [8, 8, 100]])],
            visualMap={
                "min": 0,
                "max": 100,
                "inRange": {"colors": ["#ff0000", "#00ff00"]},
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.itemColor(0).name() == "#ff0000"
        assert renderer.itemColor(1).name() == "#00ff00"

    def test_rgba_band_is_parsed(self, make):
        chart = _chart(
            make,
            [_scatter([[2, 2, 0], [8, 8, 100]])],
            visualMap={
                "min": 0,
                "max": 100,
                "inRange": {"colors": ["rgba(1, 2, 3, 1)", "rgba(255, 0, 0, 1)"]},
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.itemColor(0).name() == "#010203"
        assert renderer.itemColor(1).name() == "#ff0000"

    def test_visual_map_disables_uniform_fast_path(self, make):
        chart = _chart(
            make,
            [_scatter([[2, 2, 0], [8, 8, 100]])],
            visualMap={"min": 0, "max": 100},
        )
        assert chart.seriesRenderers[0].uniformItemStyle() is None

    def test_without_visual_map_uses_series_color(self, make):
        chart = _chart(make, [_scatter([[2, 2, 0], [8, 8, 100]])])
        renderer = chart.seriesRenderers[0]
        assert renderer.visualColor(0) is None
        assert renderer.itemColor(0).name() == chart.colorForSeries(0).name()


class TestPiecewiseVisualMap:
    def test_pieces_color_points(self, make):
        chart = _chart(
            make,
            [_scatter([[2, 2, 10], [8, 8, 90]])],
            visualMap={
                "type": "piecewise",
                "pieces": [
                    {"max": 50, "color": "#0000ff"},
                    {"min": 50, "color": "#ff00ff"},
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.itemColor(0).name() == "#0000ff"
        assert renderer.itemColor(1).name() == "#ff00ff"


class TestVisualDimension:
    def test_default_dimension_is_last(self, make):
        # 第 3 维（value）决定颜色，而不是 x
        chart = _chart(
            make,
            [_scatter([[9, 9, 0], [1, 1, 100]])],
            visualMap={
                "min": 0,
                "max": 100,
                "inRange": {"colors": ["#ff0000", "#00ff00"]},
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.itemColor(0).name() == "#ff0000"
        assert renderer.itemColor(1).name() == "#00ff00"

    def test_explicit_dimension(self, make):
        chart = _chart(
            make,
            [_scatter([[0, 9, 9], [100, 1, 1]])],
            visualMap={
                "min": 0,
                "max": 100,
                "dimension": 0,
                "inRange": {"colors": ["#ff0000", "#00ff00"]},
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.itemColor(0).name() == "#ff0000"
        assert renderer.itemColor(1).name() == "#00ff00"

    def test_scalar_value(self, make):
        chart = _chart(
            make,
            [{"type": "scatter", "symbolSize": 20, "data": [0, 100]}],
            visualMap={
                "min": 0,
                "max": 100,
                "inRange": {"colors": ["#ff0000", "#00ff00"]},
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.itemColor(0).name() == "#ff0000"
        assert renderer.itemColor(1).name() == "#00ff00"

    def test_item_style_color_overrides_visual_map(self, make):
        chart = _chart(
            make,
            [
                _scatter(
                    [
                        {"value": [2, 2, 0], "itemStyle": {"color": "#123456"}},
                        [8, 8, 100],
                    ]
                )
            ],
            visualMap={
                "min": 0,
                "max": 100,
                "inRange": {"colors": ["#ff0000", "#00ff00"]},
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.itemColor(0).name() == "#123456"
        assert renderer.itemColor(1).name() == "#00ff00"


class TestSeriesBinding:
    def test_series_index_binds_only_target(self, make):
        chart = _chart(
            make,
            [
                _scatter([[2, 2, 0]], id="a"),
                _scatter([[8, 8, 100]], id="b"),
            ],
            visualMap={
                "min": 0,
                "max": 100,
                "seriesIndex": 1,
                "inRange": {"colors": ["#ff0000", "#00ff00"]},
            },
        )
        first, second = chart.seriesRenderers
        assert first.visualColor(0) is None
        assert first.itemColor(0).name() == chart.colorForSeries(first).name()
        assert second.itemColor(0).name() == "#00ff00"

    def test_generic_map_applies_to_all_series(self, make):
        chart = _chart(
            make,
            [
                _scatter([[2, 2, 0]], id="a"),
                _scatter([[8, 8, 100]], id="b"),
            ],
            visualMap={
                "min": 0,
                "max": 100,
                "inRange": {"colors": ["#ff0000", "#00ff00"]},
            },
        )
        first, second = chart.seriesRenderers
        assert first.itemColor(0).name() == "#ff0000"
        assert second.itemColor(0).name() == "#00ff00"
