"""统一绘制语义补完：分类图例 / 层级标签编辑 / 系列动画 / 组件令牌。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEasingCurve, Qt
from PyQt6.QtGui import QImage, QPainter

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts._tokens import T
from pyqt6_ela_pro.charts._utils import parse_color
from pyqt6_ela_pro.charts.interact.timeline import ChartTimeline
from pyqt6_ela_pro.charts.interact.visualmap import VisualMapComponent


def _chart(make, option):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _paint(renderer, width=600, height=400):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        renderer.paint(painter, 1.0)
    finally:
        painter.end()
    return image


def test_graph_uses_categories_for_legend_and_hiding(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "series": [
                {
                    "type": "graph",
                    "name": "G",
                    "layout": "circular",
                    "categories": [
                        {"name": "甲", "itemStyle": {"color": "#ff0000"}},
                        {"name": "乙", "itemStyle": {"color": "#00ff00"}},
                    ],
                    "data": [
                        {"name": "A", "value": 1, "category": 0},
                        {"name": "B", "value": 2, "category": 1},
                    ],
                    "links": [{"source": "A", "target": "B"}],
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    assert dict(renderer.legendItems()) == {
        "甲": parse_color("#ff0000"),
        "乙": parse_color("#00ff00"),
    }

    renderer.setHiddenItems(["甲"])
    _paint(renderer)
    assert all(index != 0 for index, _rect, _text in renderer._label_rects)
    assert renderer.hitTest(renderer._nodes[0]["pos"]) is None
    hit = renderer.hitTest(renderer._nodes[1]["pos"])
    assert hit is not None and hit["dataIndex"] == 1


_HIERARCHY_CASES = [
    (
        "graph",
        {
            "type": "graph",
            "layout": "circular",
            "data": [{"name": "A", "value": 1}, {"name": "B", "value": 2}],
            "links": [{"source": "A", "target": "B"}],
        },
    ),
    (
        "tree",
        {
            "type": "tree",
            "data": [
                {
                    "name": "根",
                    "children": [
                        {"name": "甲", "value": 2},
                        {"name": "乙", "value": 1},
                    ],
                }
            ],
        },
    ),
    (
        "treemap",
        {
            "type": "treemap",
            "data": [
                {
                    "name": "根",
                    "children": [
                        {"name": "甲", "value": 2},
                        {"name": "乙", "value": 1},
                    ],
                }
            ],
        },
    ),
    (
        "sunburst",
        {
            "type": "sunburst",
            "data": [
                {
                    "name": "根",
                    "children": [
                        {"name": "甲", "value": 2},
                        {"name": "乙", "value": 1},
                    ],
                }
            ],
        },
    ),
    (
        "sankey",
        {
            "type": "sankey",
            "data": [{"name": "甲"}, {"name": "乙"}],
            "links": [{"source": "甲", "target": "乙", "value": 1}],
        },
    ),
    (
        "map",
        {
            "type": "map",
            "data": [{"name": "华北", "value": 1}],
        },
    ),
]


@pytest.mark.parametrize(
    "kind, series", _HIERARCHY_CASES, ids=[c[0] for c in _HIERARCHY_CASES]
)
def test_hierarchy_label_can_be_edited(make, kind, series):
    chart = _chart(make, {"animation": False, "series": [series]})
    renderer = chart.seriesRenderers[0]
    _paint(renderer)
    assert renderer._label_rects, f"{kind} 没有产出标签命中框"

    index, rect, _text = renderer._label_rects[0]
    hit = renderer.labelHitTest(rect.center())
    assert hit is not None and hit[0] == index
    assert renderer.setLabelText(index, "Z")

    _paint(renderer)
    assert any(text == "Z" for _idx, _rect, text in renderer._label_rects)


def test_series_animation_duration_and_easing(make):
    chart = _chart(
        make,
        {
            "animation": True,
            "animationDuration": 1000,
            "animationEasing": "linear",
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "series": [
                {"type": "bar", "name": "A", "data": [1, 2], "animationDuration": 1000},
                {
                    "type": "bar",
                    "name": "B",
                    "data": [1, 2],
                    "animationDuration": 2000,
                    "animationEasing": "quadraticIn",
                },
            ],
        },
    )
    assert chart._max_series_animation_duration(False) == 2000
    chart.anim.stop()
    chart.anim.setDuration(2000)
    chart.anim.setEasing(QEasingCurve.Type.Linear)
    chart.anim.setProgress(0.25)

    fast, slow = chart.seriesRenderers
    assert fast.animProgress(chart.anim.t, chart.anim.raw) == pytest.approx(0.5)
    expected = QEasingCurve(QEasingCurve.Type.InQuad).valueForProgress(0.25)
    assert slow.animProgress(chart.anim.t, chart.anim.raw) == pytest.approx(expected)


def test_visual_map_resolves_theme_tokens(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "visualMap": {
                "min": 0,
                "max": 1,
                "inRange": {"colors": ["color.primary", "color.bg.base"]},
            },
            "series": [{"type": "bar", "data": [0, 1]}],
        },
    )
    component = next(c for c in chart.components if isinstance(c, VisualMapComponent))
    assert component.mapColor(0).name() == parse_color(T("color.primary", chart)).name()
    assert component.mapColor(1).name() == parse_color(T("color.bg.base", chart)).name()


def test_timeline_control_style_resolves_theme_tokens(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "timeline": {
                "data": ["a", "b"],
                "controlStyle": {"color": "color.primary"},
            },
            "series": [{"type": "bar", "data": [1, 2]}],
        },
    )
    timeline = next(c for c in chart.components if isinstance(c, ChartTimeline))
    image = QImage(600, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        timeline.paint(painter, 1.0)
    finally:
        painter.end()

    center = timeline._play_rect.center()
    pixel = image.pixelColor(int(center.x()) - 6, int(center.y()))
    if pixel.alpha() < 200:
        pytest.skip("当前 Qt 平台不渲染控件形状像素")
    assert pixel.name() == parse_color(T("color.primary", chart)).name()
