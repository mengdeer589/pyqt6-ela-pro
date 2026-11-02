"""tooltip / 事件 params 的数据项颜色：各类系列命中必须返回真实颜色。

回归：``hitTest`` 漏 ``color`` 时 tooltip 圆点 / click params 只能回退系列色，
逐项 itemStyle、visualMap、饼 / 漏斗 / 树图 / 地图等会显示错误颜色。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF, Qt

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
        node = next(
            n for n in renderer._nodes if not n.children and n.rect.width() > 4
        )
        expected = renderer.itemColor(node.style_index, default=node.color).name()
        assert chart.hitItem(node.rect.center())["color"] == expected

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
