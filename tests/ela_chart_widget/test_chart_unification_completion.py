"""统一语义补完：索引域 / 状态链 / 标签 / 视觉映射 / 交互动画。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QImage, QPainter

from pyqt6_ela_pro import ElaChartWidget


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


def _colors(image):
    return {
        image.pixelColor(x, y).name()
        for y in range(0, image.height(), 2)
        for x in range(0, image.width(), 2)
        if image.pixelColor(x, y).alpha() > 180
    }


@pytest.mark.parametrize("kind", ["tree", "treemap", "sunburst"])
def test_hierarchy_index_domain_and_selection(make, kind):
    chart = _chart(
        make,
        {
            "animation": False,
            "series": [
                {
                    "type": kind,
                    "name": "H",
                    "data": [
                        {
                            "name": "root",
                            "children": [
                                {"name": "a", "value": 1, "selected": True},
                                {"name": "b", "value": 2},
                            ],
                        }
                    ],
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    assert renderer.itemCount() == 3
    assert [renderer.nameAtIndex(i) for i in range(3)] == ["root", "a", "b"]
    info = renderer.valueAtIndex(1)
    assert info is not None and info["name"] == "a"
    assert chart.selectedIndices(renderer) == {1}

    assert chart.dispatchAction({"type": "select", "seriesName": "H", "dataIndex": 2})
    assert chart.selectedIndices(renderer) == {1, 2}


def test_pictorial_bar_state_labels_and_visual_map(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "visualMap": {
                "min": 0,
                "max": 10,
                "show": False,
                "inRange": {"colors": ["#000000", "#ffffff"]},
            },
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "pictorialBar",
                    "name": "P",
                    "data": [0, 10],
                    "selectedMode": "multiple",
                    "select": {"itemStyle": {"color": "#ff0000"}},
                    "label": {"show": True},
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    assert renderer.dataColor(0).name() == "#000000"
    assert renderer.dataColor(1).name() == "#ffffff"

    before = _colors(_paint(renderer))
    chart.dispatchAction({"type": "select", "seriesName": "P", "dataIndex": 1})
    after = _colors(_paint(renderer))
    assert before != after
    assert len(renderer._label_rects) >= 1


def test_theme_river_hit_metadata_label_edit_and_hover(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "series": [
                {
                    "type": "themeRiver",
                    "name": "R",
                    "data": [
                        ["2026-01-01", 10, "a"],
                        ["2026-01-02", 20, "a"],
                        ["2026-01-01", 20, "b"],
                        ["2026-01-02", 15, "b"],
                    ],
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    _paint(renderer)
    stream = renderer._streams[0]
    hit = renderer.hitTest(stream["top"][-1])
    assert hit is not None and hit["dataIndex"] == 1
    assert renderer._label_rects

    assert renderer.setLabelText(1, "Z")
    _paint(renderer)
    assert any(text == "Z" for _idx, _rect, text in renderer._label_rects)


def test_gauge_hit_index_and_hover_color(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "series": [
                {
                    "type": "gauge",
                    "name": "G",
                    "data": [{"value": 50, "name": "x"}],
                    "progress": {"show": True},
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    hit = renderer.hitTest(renderer._center)
    assert hit is not None and hit["dataIndex"] == 0
    before = _colors(_paint(renderer))
    chart.dispatchAction({"type": "highlight", "seriesName": "G", "dataIndex": 0})
    after = _colors(_paint(renderer))
    assert before != after


def test_radar_labels_and_edit(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "radar": {"indicator": [{"name": "a"}, {"name": "b"}]},
            "series": [
                {
                    "type": "radar",
                    "name": "S",
                    "data": [{"name": "x", "value": [1, 2]}],
                    "label": {"show": True},
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    _paint(renderer)
    assert len(renderer._label_rects) == 2
    assert renderer.setLabelText(0, "Z")
    _paint(renderer)
    assert any(text == "Z" for _idx, _rect, text in renderer._label_rects)


@pytest.mark.parametrize(
    "kind,data",
    [
        ("boxplot", [[1, 2, 3, 4, 5], [2, 3, 4, 5, 6]]),
        ("candlestick", [[1, 2, 3, 4], [2, 4, 1, 5]]),
    ],
)
def test_boxplot_and_candlestick_labels(make, kind, data):
    chart = _chart(
        make,
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": kind,
                    "name": "S",
                    "data": data,
                    "label": {"show": True},
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    _paint(renderer)
    assert len(renderer._label_rects) == 2
    assert renderer.setLabelText(0, "Z")
    _paint(renderer)
    assert any(text == "Z" for _idx, _rect, text in renderer._label_rects)


def test_graph_line_style_symbol_and_legend_hover(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "series": [
                {
                    "type": "graph",
                    "name": "G",
                    "layout": "circular",
                    "categories": [{"name": "c1"}, {"name": "c2"}],
                    "lineStyle": {
                        "color": "color.primary",
                        "width": 3,
                        "curveness": 0.2,
                    },
                    "data": [
                        {"name": "a", "category": 0, "symbol": "rect"},
                        {"name": "b", "category": 1, "symbol": "diamond"},
                    ],
                    "links": [{"source": "a", "target": "b"}],
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    assert renderer._nodes[0]["symbol"] == "rect"
    assert renderer._nodes[1]["symbol"] == "diamond"
    assert renderer._edge_styles == {}

    before = _colors(_paint(renderer))
    chart._legend_hover = "c1"
    after = _colors(_paint(renderer))
    chart._legend_hover = None
    assert before != after


def test_image_value_at_index_matches_hit(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "image",
                    "name": "I",
                    "data": [[0, 1], [1, 0]],
                    "extent": [0, 1, 0, 1],
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    hit = renderer.hitTest(renderer._image_rect.center())
    assert hit is not None
    info = renderer.valueAtIndex(hit["dataIndex"])
    assert info is not None
    assert info["value"] == hit["value"]
    assert info["color"].name() == hit["color"].name()


def test_mark_line_polar_and_single_axis(make):
    polar = _chart(
        make,
        {
            "animation": False,
            "polar": {"radius": "70%"},
            "angleAxis": {"type": "category", "data": ["a", "b", "c"]},
            "radiusAxis": {},
            "series": [
                {
                    "type": "bar",
                    "name": "P",
                    "coordinateSystem": "polar",
                    "data": [1, 2, 3],
                    "markLine": {
                        "data": [
                            {"type": "average"},
                            {"coord": [[0, 0], [2, 3]]},
                        ]
                    },
                }
            ],
        },
    )
    mark_line = next(
        c for c in polar.components if getattr(c, "optionKey", "") == "markLine"
    )
    assert len(mark_line._lines) == 2
    _paint(polar.seriesRenderers[0])

    single = _chart(
        make,
        {
            "animation": False,
            "singleAxis": {"type": "value"},
            "series": [
                {
                    "type": "scatter",
                    "name": "S",
                    "coordinateSystem": "singleAxis",
                    "data": [[1, 10], [2, 30]],
                    "markLine": {"data": [{"xAxis": 20}]},
                }
            ],
        },
    )
    mark_line = next(
        c for c in single.components if getattr(c, "optionKey", "") == "markLine"
    )
    assert len(mark_line._lines) == 1
    _paint(single.seriesRenderers[0])


def test_selected_mode_series(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "name": "B",
                    "data": [1, 2, 3],
                    "selectedMode": "series",
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    chart._handle_select_click(renderer, {"dataIndex": 0})
    assert chart.selectedIndices(renderer) == {0, 1, 2}
    chart._handle_select_click(renderer, {"dataIndex": 0})
    assert chart.selectedIndices(renderer) == set()


def test_animation_delay_and_threshold(make):
    chart = _chart(
        make,
        {
            "animation": True,
            "animationDuration": 1000,
            "animationDelay": 500,
            "animationEasing": "linear",
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "series": [
                {"type": "bar", "name": "A", "data": [1, 2]},
                {
                    "type": "bar",
                    "name": "B",
                    "data": [1, 2],
                    "animationDelay": 0,
                    "animationDuration": 1000,
                },
            ],
        },
    )
    assert chart.anim.requested == 1500
    chart.anim.stop()
    chart.anim.setDuration(1500)
    chart.anim.setEasing(chart.anim.easing)
    chart.anim.setProgress(0.25)
    delayed, immediate = chart.seriesRenderers
    assert delayed.animProgress(chart.anim.t, chart.anim.raw) == 0.0
    assert immediate.animProgress(chart.anim.t, chart.anim.raw) == pytest.approx(0.375)

    threshold = _chart(
        make,
        {
            "animation": True,
            "animationThreshold": 2,
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "name": "C", "data": [1, 2, 3]}],
        },
    )
    assert threshold.seriesRenderers[0].animProgress(0.5, 0.5) == 1.0


def test_tree_roam_expand_and_node_click_false(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "series": [
                {
                    "type": "tree",
                    "name": "T",
                    "roam": True,
                    "initialTreeDepth": 1,
                    "data": [
                        {
                            "name": "r",
                            "children": [
                                {
                                    "name": "a",
                                    "children": [{"name": "aa", "value": 1}],
                                },
                                {"name": "b", "value": 2},
                            ],
                        }
                    ],
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    assert [name for name, _pt in renderer._nodes] and "aa" not in [
        node.name for node, _pt in renderer._nodes
    ]
    node = next(n for n, _pt in renderer._nodes if n.name == "a")
    assert renderer.onMousePress(renderer._transform(node_point(renderer, node)))
    chart._layout_all(force=True)
    assert "aa" in [node.name for node, _pt in renderer._nodes]

    treemap = _chart(
        make,
        {
            "animation": False,
            "series": [
                {
                    "type": "treemap",
                    "name": "M",
                    "nodeClick": False,
                    "data": [
                        {
                            "name": "r",
                            "children": [{"name": "a", "value": 1}],
                        }
                    ],
                }
            ],
        },
    )
    tm = treemap.seriesRenderers[0]
    tm_node = next(n for n in tm._nodes if n.children)
    assert tm.onMousePress(tm_node.rect.center()) is False


def node_point(renderer, node):
    for n, pt in renderer._nodes:
        if n is node:
            return pt
    return QPointF()


def test_sankey_draggable_and_node_align(make):
    chart = _chart(
        make,
        {
            "animation": False,
            "series": [
                {
                    "type": "sankey",
                    "name": "S",
                    "nodeAlign": "left",
                    "draggable": True,
                    "data": [{"name": "a"}, {"name": "b"}],
                    "links": [{"source": "a", "target": "b", "value": 1}],
                }
            ],
        },
    )
    renderer = chart.seriesRenderers[0]
    assert len({round(nd["rect"].x(), 3) for nd in renderer._nodes}) == 1
    node = renderer._nodes[0]
    assert renderer.onMousePress(node["rect"].center())
    target_y = node["rect"].top() + 80
    renderer.onMouseMove(QPointF(node["rect"].center().x(), target_y))
    renderer.onMouseRelease(QPointF())
    assert renderer._fixed_y
    chart._layout_all(force=True)
    assert renderer._fixed_y


def test_treemap_sunburst_node_click_false(make):
    for kind in ("treemap", "sunburst"):
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": kind,
                        "name": "M",
                        "nodeClick": False,
                        "data": [
                            {
                                "name": "r",
                                "children": [{"name": "a", "value": 1}],
                            }
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        if kind == "treemap":
            node = next(n for n in renderer._nodes if n.children)
            assert renderer.onMousePress(node.rect.center()) is False
        else:
            assert renderer.onMousePress(renderer._center) is False


def test_visual_map_reaches_value_based_series(make):
    for kind, option in (
        (
            "line",
            {
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "name": "L", "data": [0, 10]}],
            },
        ),
        (
            "radar",
            {
                "radar": {"indicator": [{"name": "a"}, {"name": "b"}]},
                "series": [
                    {
                        "type": "radar",
                        "name": "R",
                        "data": [{"name": "x", "value": [10, 0]}],
                    }
                ],
            },
        ),
        (
            "gauge",
            {"series": [{"type": "gauge", "name": "G", "data": [{"value": 0}]}]},
        ),
    ):
        option = {
            "animation": False,
            "visualMap": {
                "min": 0,
                "max": 10,
                "show": False,
                "inRange": {"colors": ["#000000", "#ffffff"]},
            },
            **option,
        }
        chart = _chart(make, option)
        renderer = chart.seriesRenderers[0]
        color = renderer.dataColor(0)
        assert color.name() == "#000000", kind
