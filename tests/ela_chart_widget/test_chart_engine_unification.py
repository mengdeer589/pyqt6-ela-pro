"""统一绘制状态机：令牌颜色 / selection / hover 的一致性回归。"""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts._tokens import T
from pyqt6_ela_pro.charts._utils import parse_color


def _bar_chart(make, *, item_style=None, label=None, select=None):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    series = {
        "type": "bar",
        "name": "A",
        "data": [10, 8],
        "selectedMode": "multiple",
        "label": {"show": True, "position": "inside"},
    }
    if item_style is not None:
        series["itemStyle"] = item_style
    if label is not None:
        series["label"].update(label)
    if select is not None:
        series["select"] = select
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "series": [series],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def test_item_style_accepts_theme_token(make):
    old_mode = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    try:
        chart = _bar_chart(make, item_style={"color": "color.primary"})
        renderer = chart.seriesRenderers[0]
        expected = parse_color(T("color.primary", chart)).name()
        assert renderer.itemColor(0).name() == expected
        assert renderer.itemBorder(0)[0] is None
    finally:
        eTheme.setThemeMode(old_mode)


def test_label_color_accepts_theme_token(make):
    old_mode = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    try:
        chart = _bar_chart(make, label={"color": "color.text.primary"})
        renderer = chart.seriesRenderers[0]
        expected = parse_color(T("color.text.primary", chart)).name()
        assert renderer.labelColorFor(0).name() == expected
    finally:
        eTheme.setThemeMode(old_mode)


def test_selected_style_applies_color_opacity_border(make):
    chart = _bar_chart(
        make,
        select={
            "itemStyle": {
                "color": "#ff0000",
                "opacity": 0.5,
                "borderColor": "#00ff00",
                "borderWidth": 3,
            }
        },
    )
    chart.dispatchAction({"type": "select", "seriesName": "A", "dataIndex": 0})
    renderer = chart.seriesRenderers[0]
    color, alpha, border, width = renderer.stateStyle(
        0, None, QColor("#123456"), 1.0, None, 0.0
    )
    assert color.name() == "#ff0000"
    assert alpha == 0.5
    assert border.name() == "#00ff00"
    assert width == 3


def test_hover_state_applies_emphasis_then_blur(make):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "scatter",
                    "name": "S",
                    "data": [[1, 2], [2, 3]],
                    "emphasis": {
                        "focus": "self",
                        "itemStyle": {"color": "#00ff00", "opacity": 0.8},
                    },
                    "blur": {"itemStyle": {"opacity": 0.2}},
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    renderer = chart.seriesRenderers[0]
    color, alpha, _border, _width = renderer.stateStyle(0, 0, QColor("#123456"), 1.0)
    assert color.name() == "#00ff00"
    assert alpha == 0.8
    _color, alpha, _border, _width = renderer.stateStyle(1, 0, QColor("#123456"), 1.0)
    assert alpha == 0.2


def test_bar_visual_map_overrides_series_color(make):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "visualMap": {
                "min": 0,
                "max": 10,
                "inRange": {"colors": ["#000000", "#ffffff"]},
            },
            "series": [
                {
                    "type": "bar",
                    "name": "A",
                    "data": [0, 10],
                    "itemStyle": {"color": "#123456"},
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    renderer = chart.seriesRenderers[0]
    assert renderer.dataColor(0).name() == "#000000"
    assert renderer.dataColor(1).name() == "#ffffff"


def test_bar_polar_geometry_and_hit(make):
    chart = make(ElaChartWidget)
    chart.resize(500, 500)
    chart.setOption(
        {
            "animation": False,
            "polar": {"radius": "70%"},
            "angleAxis": {"type": "category", "data": ["a", "b", "c"]},
            "radiusAxis": {},
            "series": [
                {
                    "type": "bar",
                    "name": "P",
                    "data": [1, 2, 3],
                    "coordinateSystem": "polar",
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    renderer = chart.seriesRenderers[0]
    assert renderer._polar is True
    assert len(renderer._bars) == 3
    info = renderer.valueAtIndex(1)
    assert info is not None
    hit = renderer.hitTest(info["pos"])
    assert hit is not None and hit["dataIndex"] == 1
