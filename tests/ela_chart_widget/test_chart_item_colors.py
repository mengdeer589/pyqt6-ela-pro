"""tooltip / 事件 params 的数据项颜色：各类系列命中必须返回真实颜色。

回归：``hitTest`` 漏 ``color`` 时 tooltip 圆点 / click params 只能回退系列色，
逐项 itemStyle、visualMap、饼 / 漏斗 / 树图 / 地图等会显示错误颜色。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF, Qt

from _pixels import opaque_colors, skip_if_no_pixels
from pyqt6_ela_pro.charts import ElaChartWidget


def _chart(make, option):
    chart = make(ElaChartWidget)
    chart.resize(640, 420)
    chart.setOption({"animation": False, **option})
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _bar(make, data, **series):
    return _chart(
        make,
        {
            "xAxis": {"type": "category", "data": ["A"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": data, **series}],
        },
    )


class TestItemColors:
    def test_bar_item_style_color(self, make):
        chart = _bar(
            make,
            [{"value": 1.0, "itemStyle": {"color": "#ff0000"}}],
        )
        renderer = chart.seriesRenderers[0]
        pos = renderer._bars[0]["rect"].center()
        assert chart.hitItem(pos)["color"] == "#ff0000"

    def test_scatter_visual_map_color(self, make):
        np = pytest.importorskip("numpy")
        chart = _chart(
            make,
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "visualMap": {"min": 0, "max": 10},
                "series": [
                    {
                        "type": "scatter",
                        "data": np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 10.0]]),
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        colors = [renderer.itemColor(i).name() for i in range(2)]
        assert colors[0] != colors[1]
        for dot, expected in zip(renderer._dots, colors):
            assert chart.hitItem(dot["pt"])["color"] == expected

    def test_heatmap_cell_color(self, make):
        chart = _chart(
            make,
            {
                "xAxis": {"type": "category", "data": ["A"]},
                "yAxis": {"type": "category", "data": ["X"]},
                "visualMap": {"min": 0, "max": 10},
                "series": [{"type": "heatmap", "data": [[0, 0, 10]]}],
            },
        )
        renderer = chart.seriesRenderers[0]
        cell = renderer._cells[0]
        assert chart.hitItem(cell["rect"].center())["color"] == cell["color"].name()

    def test_funnel_layer_color(self, make):
        chart = _chart(
            make,
            {
                "series": [
                    {
                        "type": "funnel",
                        "data": [
                            {"name": "A", "value": 10},
                            {"name": "B", "value": 5},
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        layer = renderer._layers[0]
        assert (
            chart.hitItem(layer["poly"].boundingRect().center())["color"]
            == layer["color"].name()
        )

    def test_candlestick_up_down_colors(self, make):
        chart = _chart(
            make,
            {
                "xAxis": {"type": "category", "data": ["A", "B"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "candlestick",
                        "data": [
                            [10.0, 12.0, 9.0, 13.0],
                            [12.0, 8.0, 7.0, 13.0],
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.coords[0]
        hits = []
        for item in renderer._items:
            y = coord.y_axis.map(
                (item["open"] + item["close"]) / 2,
                coord.plot.bottom(),
                coord.plot.top(),
            )
            hits.append(chart.hitItem(QPointF(item["cx"], y)))
        assert hits[0]["color"] == renderer._up_color().name()
        assert hits[1]["color"] == renderer._down_color().name()

    def test_treemap_node_color(self, make):
        chart = _chart(
            make,
            {
                "series": [
                    {
                        "type": "treemap",
                        "data": [
                            {
                                "name": "A",
                                "value": 10,
                                "children": [{"name": "A1", "value": 10}],
                            }
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        node = next(n for n in renderer._nodes if not n.children and n.rect.width() > 4)
        assert chart.hitItem(node.rect.center())["color"] == node.color.name()

    @pytest.mark.parametrize("kind", ["treemap", "sunburst", "tree"])
    def test_single_root_hierarchy_colors_each_branch(self, make, kind):
        """单根包装（根 → A/B）时按分支取色，不能整图只有调色板第一种颜色。"""
        chart = _chart(
            make,
            {
                "series": [
                    {
                        "type": kind,
                        "data": [
                            {
                                "name": "根",
                                "children": [
                                    {
                                        "name": "A",
                                        "value": 50,
                                        "children": [{"name": "A1", "value": 20}],
                                    },
                                    {
                                        "name": "B",
                                        "value": 50,
                                        "children": [{"name": "B1", "value": 30}],
                                    },
                                ],
                            }
                        ],
                    }
                ]
            },
        )
        renderer = chart.seriesRenderers[0]
        nodes = [
            item[0] if isinstance(item, tuple) else item
            for item in getattr(renderer, "_nodes", [])
        ]
        colors = {n.name: n.color.name() for n in nodes if n.color is not None}
        assert colors["A"] != colors["B"]
        assert colors["A1"] != colors["A"]
        assert colors["B1"] != colors["B"]

    @pytest.mark.parametrize("kind", ["treemap", "sunburst", "tree"])
    def test_hierarchy_node_item_style_color(self, make, kind):
        """嵌套节点的 ``itemStyle.color`` 覆盖分支色（描绘与命中同一真源）。"""
        chart = _chart(
            make,
            {
                "series": [
                    {
                        "type": kind,
                        "data": [
                            {
                                "name": "根",
                                "children": [
                                    {
                                        "name": "A",
                                        "value": 50,
                                        "itemStyle": {"color": "#ff0000"},
                                    },
                                    {"name": "B", "value": 50},
                                ],
                            }
                        ],
                    }
                ]
            },
        )
        renderer = chart.seriesRenderers[0]
        nodes = [
            item if isinstance(item, tuple) else (item, None)
            for item in getattr(renderer, "_nodes", [])
        ]
        node, pt = next((n, p) for n, p in nodes if n.name == "A")
        if pt is None:
            if kind == "treemap":
                pt = node.rect.center()
            else:  # sunburst
                r0, r1 = renderer._ring(node.level)
                pt = renderer._pt((node.a0 + node.a1) / 2, (r0 + r1) / 2)
        hit = renderer.hitTest(pt)
        assert hit is not None
        assert hit["color"].name() == "#ff0000"

    def test_candlestick_item_style_color(self, make):
        chart = _chart(
            make,
            {
                "xAxis": {"type": "category", "data": ["A", "B"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "candlestick",
                        "data": [
                            [10, 20, 8, 22],
                            {
                                "value": [10, 25, 8, 28],
                                "itemStyle": {"color": "#ff0000"},
                            },
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        item = renderer._items[1]
        coord = chart.primaryCoord()
        y = coord.y_axis.map(
            (item["open"] + item["close"]) / 2, coord.plot.bottom(), coord.plot.top()
        )
        assert chart.hitItem(QPointF(item["cx"], y))["color"] == "#ff0000"

    def test_lines_item_line_style_color(self, make):
        chart = _chart(
            make,
            {
                "xAxis": {"type": "value", "min": 0, "max": 10},
                "yAxis": {"type": "value", "min": 0, "max": 10},
                "series": [
                    {
                        "type": "lines",
                        "coordinateSystem": "cartesian2d",
                        "data": [
                            {
                                "coords": [[1, 1], [4, 7]],
                                "lineStyle": {"color": "#ff0000"},
                            }
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        seg = renderer._segments[0]
        mid = QPointF(
            (seg["p0"].x() + seg["p1"].x()) / 2, (seg["p0"].y() + seg["p1"].y()) / 2
        )
        assert renderer.hitTest(mid)["color"].name() == "#ff0000"

    def test_parallel_rows_use_palette_colors(self, make):
        """平行坐标每行取一种调色板色（命中 / 绘制同一真源）。"""
        chart = _chart(
            make,
            {
                "parallelAxis": [{"name": "A"}, {"name": "B"}],
                "series": [
                    {
                        "type": "parallel",
                        "name": "样本",
                        "data": [[1, 2], [3, 4], [5, 6]],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        colors = [row["color"].name() for row in renderer._rows]
        assert len(set(colors)) == 3
        for row in renderer._rows:
            hit = renderer.hitTest(row["pts"][0])
            assert hit is not None
            assert hit["color"].name() == row["color"].name()

    def test_pictorial_bar_item_style_color_paints(self, make):
        chart = _chart(
            make,
            {
                "xAxis": {"type": "category", "data": ["A", "B"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "pictorialBar",
                        "symbol": "rect",
                        "symbolRepeat": True,
                        "symbolSize": 8,
                        "data": [
                            {"value": 10, "itemStyle": {"color": "#ff0000"}},
                            5,
                        ],
                    }
                ],
            },
        )
        skip_if_no_pixels(opaque_colors(chart))
        image = chart.grab().toImage()
        rect = chart.seriesRenderers[0]._bars[0]["rect"]
        assert any(
            image.pixelColor(x, y).red() - image.pixelColor(x, y).blue() > 40
            for y in range(int(rect.top()) + 4, int(rect.bottom()) - 4, 4)
            for x in range(int(rect.left()) + 4, int(rect.right()) - 4, 4)
        )

    def test_boxplot_item_style_color_paints(self, make):
        chart = _chart(
            make,
            {
                "xAxis": {"type": "category", "data": ["A", "B"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "boxplot",
                        "data": [
                            {
                                "value": [1, 2, 3, 4, 5],
                                "itemStyle": {"color": "#ff0000"},
                            },
                            [2, 3, 4, 5, 6],
                        ],
                    }
                ],
            },
        )
        skip_if_no_pixels(opaque_colors(chart))
        image = chart.grab().toImage()
        renderer = chart.seriesRenderers[0]
        item = renderer._items[0]
        coord = chart.primaryCoord()
        y_q1 = coord.y_axis.map(item["vals"][1], coord.plot.bottom(), coord.plot.top())
        y_med = coord.y_axis.map(item["vals"][2], coord.plot.bottom(), coord.plot.top())
        c = image.pixelColor(int(item["cx"]), int((y_q1 + y_med) / 2))
        assert c.red() - c.blue() > 20

    def test_map_region_color(self, make):
        chart = _chart(
            make,
            {
                "series": [
                    {
                        "type": "map",
                        "data": [{"name": "华北", "value": 10}],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        chart.grab()  # 触发 paint，填充 _region_colors
        for name, poly, _index in renderer._polys:
            center = poly.boundingRect().center()
            if poly.containsPoint(center, Qt.FillRule.OddEvenFill):
                hit = renderer.hitTest(center)
                if hit is not None:
                    assert hit["color"] == renderer._region_colors[hit["name"]]
                    return
        pytest.skip("demo map 没有可命中的中心点")
