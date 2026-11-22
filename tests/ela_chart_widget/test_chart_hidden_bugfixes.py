"""隐藏缺陷回归：下标契约 / 堆叠 / 缓存 / 坐标轴 / 组件显隐。"""

from __future__ import annotations

from datetime import datetime

import pytest

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, option, w=640, h=420):
    chart = make(ElaChartWidget)
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _grid(x_type="category", y_type="value", **patch):
    option = {
        "animation": False,
        "xAxis": {"type": x_type},
        "yAxis": {"type": y_type},
    }
    option.update(patch)
    return option


class TestIndexContract:
    def test_value_at_index_is_absolute(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                dataZoom=[{"type": "inside", "start": 40, "end": 60}],
                xAxis={"type": "category", "data": [str(i) for i in range(100)]},
                series=[{"type": "line", "data": list(range(100))}],
            ),
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.valueAtIndex(50)["value"] == 50
        assert renderer.valueAtIndex(0)["value"] == 0

    def test_pie_hit_keeps_original_index_after_hidden_item(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "legend": {},
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "A", "value": 10},
                            {"name": "B", "value": 20},
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        chart._setDataItemVisible("A", False)
        chart._layout_all(force=True)
        assert [s["index"] for s in renderer._sectors] == [1]
        sector = renderer._sectors[0]
        mid = (sector["a0"] + sector["a1"]) / 2.0
        pt = renderer._pt(mid, (sector["r0"] + sector["r1"]) / 2.0)
        hit = renderer.hitTest(pt)
        assert hit is not None and hit["dataIndex"] == 1

    def test_heatmap_skipped_item_keeps_original_index(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                xAxis={"type": "category", "data": ["a", "b"]},
                yAxis={"type": "category", "data": ["x", "y"]},
                series=[
                    {
                        "type": "heatmap",
                        "data": [[0, 0, 1], [0, 1, None], [1, 0, 5]],
                    }
                ],
            ),
        )
        cells = chart.seriesRenderers[0]._cells
        assert [c["index"] for c in cells] == [0, 2]


class TestStackAndCache:
    def test_bar_stack_strategy_all(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                xAxis={"type": "category", "data": ["a"]},
                series=[
                    {
                        "type": "bar",
                        "name": "A",
                        "stack": "s",
                        "stackStrategy": "all",
                        "data": [5],
                    },
                    {
                        "type": "bar",
                        "name": "B",
                        "stack": "s",
                        "stackStrategy": "all",
                        "data": [-5],
                    },
                ],
            ),
        )
        bars = chart.seriesRenderers[1]._bars
        assert bars[0]["v0"] == 5.0
        assert bars[0]["v0"] + bars[0]["y"] == 0.0

    def test_stacked_area_keeps_bases_without_sampling(self, qapp, make):
        n = 3000
        values = [float(i % 20 + 1) for i in range(n)]
        chart = _chart(
            make,
            _grid(
                xAxis={"type": "category", "data": [str(i) for i in range(n)]},
                series=[
                    {
                        "type": "line",
                        "name": "A",
                        "stack": "s",
                        "sampling": False,
                        "areaStyle": {},
                        "data": values,
                    },
                    {
                        "type": "line",
                        "name": "B",
                        "stack": "s",
                        "sampling": False,
                        "areaStyle": {},
                        "data": values,
                    },
                ],
            ),
        )
        renderer = chart.seriesRenderers[1]
        captured = []
        original = renderer._area_fill_path

        def wrapper(seg_bases, base_y, curve, geom_pts, coord):
            captured.append(list(seg_bases))
            return original(seg_bases, base_y, curve, geom_pts, coord)

        renderer._area_fill_path = wrapper
        chart._render_to_painter()
        assert captured
        assert any(any(b is not None for b in bases) for bases in captured)

    def test_stack_patch_invalidates_extent_cache(self, qapp, make):
        values = [float(i % 50 + 1) for i in range(300)]
        chart = _chart(
            make,
            _grid(
                xAxis={"type": "category", "data": [str(i) for i in range(300)]},
                series=[
                    {"type": "bar", "name": "A", "stack": "s", "data": values},
                    {"type": "bar", "name": "B", "data": values},
                ],
            ),
        )
        before = chart.primaryCoord().y_axis.vmax
        chart.updateSeries({"stack": "s"}, seriesIndex=1)
        chart._layout_all(force=True)
        after = chart.primaryCoord().y_axis.vmax
        assert after > before


class TestTimelineMerge:
    def test_partial_frame_keeps_other_series(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "timeline": {"data": ["t0", "t1"]},
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "bar", "name": "A", "data": [1, 2]},
                    {"type": "line", "name": "B", "data": [3, 4]},
                ],
                "options": [{"series": [{"name": "A", "data": [5, 6]}]}],
            },
        )
        chart.dispatchAction({"type": "timelineChange", "currentIndex": 0})
        assert [r.name for r in chart.seriesRenderers] == ["A", "B"]
        assert chart.seriesRenderers[0].opt["type"] == "bar"


class TestAxesAndComponents:
    def test_grid_width_does_not_raise(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                xAxis={"type": "category", "data": ["a", "b"]},
                grid={"width": 300},
                series=[{"type": "line", "data": [1, 2]}],
            ),
        )
        assert chart.primaryCoord().plot.width() <= 300.0

    def test_boundary_gap_false_array(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                xAxis={
                    "type": "category",
                    "data": ["a", "b", "c"],
                    "boundaryGap": [False, False],
                },
                series=[{"type": "line", "data": [1, 2, 3]}],
            ),
        )
        coord = chart.primaryCoord()
        first = coord.mapPoint(0, 1)
        assert abs(first.x() - coord.plot.left()) < 1.0

    def test_log_base_near_one_is_clamped(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                yAxis={"type": "log", "logBase": 1.0000001},
                series=[{"type": "line", "data": [1, 10]}],
            ),
        )
        assert chart.primaryCoord().y_axis.log_base == 10.0

    def test_calendar_datetime_range(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "calendar": {"range": [datetime(2026, 1, 1), datetime(2026, 12, 31)]},
                "series": [{"type": "heatmap", "data": []}],
            },
        )
        coord = next(c for c in chart.coords if c.kind == "calendar")
        assert coord.weeks() >= 52

    def test_toolbox_empty_feature_dict_enables_only_that(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                series=[{"type": "line", "data": [1, 2]}],
                toolbox={"feature": {"saveAsImage": {}}},
            ),
        )
        comp = chart._component("toolbox")
        assert comp.features == ["saveAsImage"]

    def test_show_false_hides_bands(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                title={"show": False, "text": "hidden"},
                visualMap={"show": False, "min": 0, "max": 10},
                series=[{"type": "line", "data": [1, 2]}],
            ),
        )
        assert chart.title.height() == 0.0
        comp = chart._component("visualMap")
        assert comp.reserveRight() == 0.0 and comp.reserveBottom() == 0.0

    def test_gantt_unnamed_tasks_use_data_order(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "time"},
                "yAxis": {"type": "category", "data": ["A", "B"]},
                "series": [
                    {
                        "type": "gantt",
                        "data": [
                            ["2026-11-02", "2026-11-03"],
                            ["2026-11-04", "2026-11-05"],
                        ],
                    }
                ],
            },
        )
        assert len(chart.seriesRenderers[0]._items) == 2


class TestDataAndSeries:
    def test_image_flips_with_inverse_axis(self, qapp, make):
        np = pytest.importorskip("numpy")
        chart = _chart(
            make,
            _grid(
                xAxis={"type": "value", "inverse": True},
                yAxis={"type": "value"},
                series=[{"type": "image", "data": np.arange(9.0).reshape(3, 3)}],
            ),
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._flip_x is True
        assert renderer._flip_y is False

    def test_sunburst_scalar_radius(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "sunburst",
                        "radius": "80%",
                        "data": [
                            {
                                "name": "root",
                                "children": [
                                    {"name": "a", "value": 1},
                                    {"name": "b", "value": 2},
                                ],
                            }
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._r1 > 50.0

    def test_append_data_keeps_short_raw_array(self, qapp, make):
        np = pytest.importorskip("numpy")
        chart = _chart(
            make,
            _grid(series=[{"type": "line", "data": np.arange(10.0)}]),
        )
        assert chart.appendData({"seriesIndex": 0, "data": [10.0]})
        assert len(chart.seriesRenderers[0].data()) == 11
        assert chart.seriesRenderers[0].data()[0] == 0.0

    def test_buffer_to_list_handles_2d_int(self, qapp, make):
        np = pytest.importorskip("numpy")
        from pyqt6_ela_pro.charts.data import toBuffer

        buf = toBuffer(np.zeros((300, 2), dtype=np.int64))
        assert buf is not None
        assert buf.toList()[0] == [0.0, 0.0]

    def test_markpoint_horizontal_category_axis(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {"type": "category", "data": ["a", "b", "c"]},
                "series": [
                    {
                        "type": "bar",
                        "data": [10, 20, 40],
                        "markPoint": {"data": [{"type": "max"}]},
                    }
                ],
            },
        )
        coord = chart.primaryCoord()
        comp = chart._component("markPoint")
        pos = comp._marks[0]["pos"]
        assert coord.plot.contains(pos)
        assert pos.x() > coord.plot.center().x()

    def test_hierarchy_hit_carries_data_item(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "treemap",
                        "data": [
                            {
                                "name": "root",
                                "children": [
                                    {"name": "a", "value": 1},
                                    {"name": "b", "value": 3},
                                ],
                            }
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        child = renderer._nodes[-1]
        hit = renderer.hitTest(child.rect.center())
        assert hit is not None
        assert hit["data"] is child.item


class TestInteract:
    def test_brush_selects_horizontal_bar(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {"type": "category", "data": ["a", "b", "c"]},
                "brush": {"type": "rect"},
                "series": [{"type": "bar", "data": [10, 20, 40]}],
            },
        )
        brush = chart.brushComponent()
        brush._coord = chart.primaryCoord()
        brush._rect = chart.primaryCoord().plot
        brush._collect()
        assert len(brush.selected_items) == 3

    def test_datazoom_single_sided_value_keeps_other_edge(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                xAxis={"type": "category", "data": [str(i) for i in range(100)]},
                dataZoom=[{"type": "inside", "start": 60, "end": 90}],
                series=[{"type": "line", "data": list(range(100))}],
            ),
        )
        chart.dispatchAction({"type": "dataZoom", "startValue": 70})
        zoom = chart._component("dataZoom")
        assert zoom.start > 65.0
        assert zoom.end == pytest.approx(90.0, abs=0.5)

    def test_visualmap_series_index_list(self, qapp, make):
        chart = _chart(
            make,
            _grid(
                xAxis={"type": "value"},
                yAxis={"type": "value"},
                visualMap={
                    "type": "continuous",
                    "seriesIndex": [1],
                    "min": 0,
                    "max": 10,
                },
                series=[
                    {"type": "scatter", "data": [[1, 1]]},
                    {"type": "scatter", "data": [[2, 2]]},
                ],
            ),
        )
        comp = chart._component("visualMap")
        assert comp.bindsTo(1, "") is True
        assert comp.bindsTo(0, "") is False
        assert comp.isGeneric is False

    def test_map_name_property_falls_back_to_name(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "map",
                        "nameProperty": "region",
                        "data": [{"name": "华北", "value": 10}],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._index_map()["华北"] == 0
        assert renderer._value_map()["华北"] == 10

    def test_funnel_legend_color_matches_layer(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "legend": {},
                "series": [
                    {
                        "type": "funnel",
                        "sort": "descending",
                        "data": [
                            {"name": "A", "value": 10},
                            {"name": "B", "value": 30},
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        legend = dict(renderer.legendItems())
        layers = {layer["name"]: layer["color"] for layer in renderer._layers}
        assert layers["A"].name() == legend["A"].name()
        assert layers["B"].name() == legend["B"].name()

    def test_reset_view_resets_graph_roam(self, qapp, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "graph",
                        "roam": True,
                        "data": [{"name": "A"}, {"name": "B"}],
                        "links": [{"source": "A", "target": "B"}],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        renderer._zoom = 2.5
        chart.resetView()
        assert renderer._zoom == 1.0
