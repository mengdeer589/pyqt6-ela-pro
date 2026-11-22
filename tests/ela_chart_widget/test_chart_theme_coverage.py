"""主题响应矩阵：内置主题 / 明暗档覆盖所有系列与颜色令牌入口。"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import (
    chartThemes,
    chartThemeSpec,
    chartToken,
)
from pyqt6_ela_pro._colors import contrastRatio
from pyqt6_ela_pro.charts._tokens import theme_ramp
from pyqt6_ela_pro.charts._utils import parse_color
from pyqt6_ela_pro.charts.axes._shared import _line_pen
from pyqt6_ela_pro.charts.exporter import ChartExporter


def _option(series: dict) -> dict:
    return {"animation": False, "series": [series]}


SERIES_SAMPLES = {
    "bar": _option({"type": "bar", "name": "S", "data": [1, 2, 3]}),
    "pictorialBar": _option({"type": "pictorialBar", "name": "S", "data": [1, 2, 3]}),
    "line": _option({"type": "line", "name": "S", "data": [1, 2, 3]}),
    "scatter": _option({"type": "scatter", "name": "S", "data": [[1, 1], [2, 2]]}),
    "effectScatter": _option(
        {"type": "effectScatter", "name": "S", "data": [[1, 1], [2, 2]]}
    ),
    "boxplot": _option({"type": "boxplot", "name": "S", "data": [[1, 2, 3, 4, 5]]}),
    "candlestick": _option(
        {"type": "candlestick", "name": "S", "data": [[1, 2, 3, 4], [2, 3, 1, 5]]}
    ),
    "pie": _option(
        {
            "type": "pie",
            "name": "S",
            "data": [{"name": "a", "value": 1}, {"name": "b", "value": 2}],
        }
    ),
    "funnel": _option(
        {
            "type": "funnel",
            "name": "S",
            "data": [{"name": "a", "value": 2}, {"name": "b", "value": 1}],
        }
    ),
    "gauge": _option(
        {"type": "gauge", "name": "S", "data": [{"value": 50, "name": "x"}]}
    ),
    "radar": {
        "animation": False,
        "radar": {"indicator": [{"name": "a"}, {"name": "b"}]},
        "series": [
            {"type": "radar", "name": "S", "data": [{"name": "x", "value": [1, 2]}]}
        ],
    },
    "graph": _option(
        {
            "type": "graph",
            "name": "S",
            "layout": "circular",
            "categories": [{"name": "c1"}],
            "data": [
                {"name": "a", "value": 1, "category": 0},
                {"name": "b", "value": 2, "category": 0},
            ],
            "links": [{"source": "a", "target": "b"}],
        }
    ),
    "tree": _option(
        {
            "type": "tree",
            "name": "S",
            "data": [{"name": "a", "children": [{"name": "b", "value": 1}]}],
        }
    ),
    "treemap": _option(
        {
            "type": "treemap",
            "name": "S",
            "data": [{"name": "a", "children": [{"name": "b", "value": 1}]}],
        }
    ),
    "sunburst": _option(
        {
            "type": "sunburst",
            "name": "S",
            "data": [{"name": "a", "children": [{"name": "b", "value": 1}]}],
        }
    ),
    "sankey": _option(
        {
            "type": "sankey",
            "name": "S",
            "data": [{"name": "a"}, {"name": "b"}],
            "links": [{"source": "a", "target": "b", "value": 1}],
        }
    ),
    "themeRiver": _option(
        {
            "type": "themeRiver",
            "name": "S",
            "data": [
                ["2026-01-01", 1, "a"],
                ["2026-01-02", 2, "a"],
                ["2026-01-01", 2, "b"],
                ["2026-01-02", 1, "b"],
            ],
        }
    ),
    "parallel": {
        "animation": False,
        "parallelAxis": [{"dim": 0, "name": "a"}, {"dim": 1, "name": "b"}],
        "series": [{"type": "parallel", "name": "S", "data": [[1, 2], [2, 1]]}],
    },
    "lines": _option(
        {
            "type": "lines",
            "name": "S",
            "data": [{"coords": [[0, 0], [1, 1]]}],
        }
    ),
    "map": _option(
        {
            "type": "map",
            "name": "S",
            "data": [{"name": "华北", "value": 1}, {"name": "华东", "value": 2}],
        }
    ),
    "heatmap": _option(
        {
            "type": "heatmap",
            "name": "S",
            "data": [[0, 0, 1], [1, 1, 2]],
        }
    ),
    "image": _option(
        {
            "type": "image",
            "name": "S",
            "data": [[0, 1], [1, 0]],
            "extent": [0, 1, 0, 1],
        }
    ),
    "gantt": _option(
        {
            "type": "gantt",
            "name": "S",
            "data": [
                {
                    "name": "a",
                    "start": "2026-11-02",
                    "end": "2026-11-06",
                    "progress": 0.5,
                }
            ],
        }
    ),
}


def _axes_for(kind: str) -> dict:
    if kind in {"bar", "pictorialBar", "line"}:
        return {
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {"type": "value"},
        }
    if kind in {"scatter", "effectScatter", "lines", "image"}:
        return {"xAxis": {"type": "value"}, "yAxis": {"type": "value"}}
    if kind in {"boxplot", "candlestick"}:
        return {
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
        }
    if kind == "heatmap":
        return {
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "category", "data": ["x", "y"]},
        }
    if kind == "gantt":
        return {
            "xAxis": {"type": "time"},
            "yAxis": {"type": "category", "inverse": True},
        }
    return {}


def _chart(make, theme: str, kind: str) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setChartTheme(theme)
    option = dict(_axes_for(kind))
    option.update(SERIES_SAMPLES[kind])
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


@pytest.mark.parametrize("kind", list(SERIES_SAMPLES))
def test_every_series_uses_theme_palette(make, kind):
    """23 种系列的默认主色都必须来自当前主题 palette[0]。"""
    for theme in chartThemes():
        chart = _chart(make, theme, kind)
        renderer = chart.seriesRenderers[0]
        assert renderer.color().name() == chart.palette()[0].name(), (kind, theme)


@pytest.mark.parametrize("kind", list(SERIES_SAMPLES))
def test_every_series_palette_changes_in_dark(make, kind):
    """23 种系列都必须取到暗色档 palette[0]。"""
    previous = eTheme.getThemeMode()
    try:
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
        light = _chart(make, "matlab", kind).seriesRenderers[0].color().name()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        dark = _chart(make, "matlab", kind).seriesRenderers[0].color().name()
        assert light != dark, kind
    finally:
        eTheme.setThemeMode(previous)


def test_builtin_themes_have_dark_palette_and_ramp():
    for theme in chartThemes():
        spec = chartThemeSpec(theme)
        assert spec.get("palette_dark"), theme
        assert spec["palette"] != spec["palette_dark"], theme
        if theme == "ela":
            continue
        dark = spec["dark"]
        assert dark.get("color.ramp"), theme
        assert spec["light"]["color.ramp"] != dark["color.ramp"], theme
        bg = parse_color(dark["color.bg.base"])
        for value in spec["palette_dark"]:
            assert contrastRatio(parse_color(value), bg) >= 3.0, (theme, value)
        for value in dark["color.ramp"]:
            assert contrastRatio(parse_color(value), bg) >= 1.8, (theme, value)


def test_light_and_dark_switch_changes_palette_and_ramp(make):
    previous = eTheme.getThemeMode()
    try:
        for theme in chartThemes():
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
            light = _chart(make, theme, "bar")
            light_palette = [c.name() for c in light.palette()]
            light_ramp = [c.name() for c in theme_ramp(light)]
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            dark_palette = [c.name() for c in light.palette()]
            dark_ramp = [c.name() for c in theme_ramp(light)]
            assert light_palette != dark_palette, theme
            assert light_ramp != dark_ramp, theme
    finally:
        eTheme.setThemeMode(previous)


def test_pie_and_funnel_follow_dark_palette(make):
    previous = eTheme.getThemeMode()
    try:
        for theme in ("matlab", "tableau"):
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
            pie_light = _chart(make, theme, "pie")
            funnel_light = _chart(make, theme, "funnel")
            light = [c.name() for c in pie_light.palette()]
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            pie_dark = _chart(make, theme, "pie")
            funnel_dark = _chart(make, theme, "funnel")
            dark = [c.name() for c in pie_dark.palette()]
            pie_light_sectors = [
                s["color"].name() for s in pie_light.seriesRenderers[0]._sectors
            ]
            pie_dark_sectors = [
                s["color"].name() for s in pie_dark.seriesRenderers[0]._sectors
            ]
            funnel_light_layers = [
                layer["color"].name()
                for layer in funnel_light.seriesRenderers[0]._layers
            ]
            funnel_dark_layers = [
                layer["color"].name()
                for layer in funnel_dark.seriesRenderers[0]._layers
            ]
            assert pie_light_sectors == light[: len(pie_light_sectors)]
            assert pie_dark_sectors == dark[: len(pie_dark_sectors)]
            assert funnel_light_layers == light[: len(funnel_light_layers)]
            assert funnel_dark_layers == dark[: len(funnel_dark_layers)]
    finally:
        eTheme.setThemeMode(previous)


def test_heatmap_and_image_follow_dark_ramp(make):
    previous = eTheme.getThemeMode()
    try:
        for theme in ("matlab", "plotly"):
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
            light_chart = _chart(make, theme, "heatmap")
            light_cells = [
                cell["color"].name()
                for cell in light_chart.seriesRenderers[0]._cells
                if not cell["empty"]
            ]
            light_image = [
                c.name()
                for c in _chart(make, theme, "image").seriesRenderers[0]._colors()
            ]
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            dark_chart = _chart(make, theme, "heatmap")
            dark_cells = [
                cell["color"].name()
                for cell in dark_chart.seriesRenderers[0]._cells
                if not cell["empty"]
            ]
            dark_image = [
                c.name()
                for c in _chart(make, theme, "image").seriesRenderers[0]._colors()
            ]
            assert light_cells != dark_cells, theme
            assert light_image != dark_image, theme
    finally:
        eTheme.setThemeMode(previous)


def test_candlestick_uses_dark_semantic_colors(make):
    previous = eTheme.getThemeMode()
    try:
        for theme in ("matlab", "plotly"):
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
            light = _chart(make, theme, "candlestick").seriesRenderers[0]
            light_up = light._up_color().name()
            light_down = light._down_color().name()
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            dark = _chart(make, theme, "candlestick").seriesRenderers[0]
            assert light_up != dark._up_color().name(), theme
            assert light_down != dark._down_color().name(), theme
    finally:
        eTheme.setThemeMode(previous)


def test_series_color_option_color_and_background_tokens(make):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setChartTheme("echarts")
    primary = chartToken("color.primary", chart)
    danger = chartToken("color.danger", chart)
    chart.setOption(
        {
            "animation": False,
            "color": ["color.primary", "color.danger"],
            "backgroundColor": "color.primary",
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "name": "A",
                    "data": [1, 2],
                    "color": "color.primary",
                }
            ],
        }
    )
    renderer = chart.seriesRenderers[0]
    assert renderer.color().name() == primary.name()
    assert [c.name() for c in chart.palette()] == [primary.name(), danger.name()]
    assert chart._background_color().name() == primary.name()

    pen = _line_pen(
        {"lineStyle": {"color": "color.primary"}},
        QColor("#000000"),
        chart=chart,
    )
    assert pen.color().name() == primary.name()
    assert ChartExporter(chart)._option_color("color.primary").name() == primary.name()
    assert chart.setAxisLabelStyle("x", color="color.primary") is True
