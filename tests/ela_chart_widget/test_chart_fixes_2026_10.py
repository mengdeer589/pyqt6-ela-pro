"""2026-10 图表缺陷修复的回归测试（轴范围 / 缓存 / 语义 / 导出 / 生命周期）。"""

from __future__ import annotations

import math

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QImage, QPainter, QWheelEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts.axes.calendar import CalendarCoord


def _render(widget) -> QImage:
    image = QImage(
        max(1, widget.width()),
        max(1, widget.height()),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    widget.render(image)
    return image


def _pixel_diff(a: QImage, b: QImage) -> int:
    count = 0
    for y in range(0, min(a.height(), b.height()), 2):
        for x in range(0, min(a.width(), b.width()), 2):
            if a.pixel(x, y) != b.pixel(x, y):
                count += 1
    return count


def _ready(make, option, width=640, height=420) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(width, height)
    chart.show()
    chart.setOption(option)
    QApplication.processEvents()
    return chart


class TestAxisExtentWithAutoZoom:
    """默认自动滚轮 dataZoom 不能把「未修正的轴范围」当全量。"""

    def test_stacked_bar_keeps_stack_sum(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "bar", "stack": "s", "data": [30, 40]},
                    {"type": "bar", "stack": "s", "data": [30, 40]},
                ],
            },
        )
        axis = chart.coords[0].y_axis
        assert axis.vmin == 0.0
        assert axis.vmax >= 80.0

    def test_horizontal_bar_uses_value_axis(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {"type": "category", "data": ["a", "b", "c"]},
                "series": [{"type": "bar", "data": [10, 20, 40]}],
            },
        )
        axis = chart.coords[0].x_axis
        assert axis.vmax >= 40.0
        rights = [bar["rect"].right() for bar in chart.seriesRenderers[0]._bars]
        assert rights[0] < rights[1] < rights[2], "横向柱长度必须按数值递增"

    def test_stacked_line_keeps_stack_sum(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "line", "stack": "t", "data": [3, 4, 5]},
                    {"type": "line", "stack": "t", "data": [2, 3, 4]},
                ],
            },
        )
        assert chart.coords[0].y_axis.vmax >= 9.0

    def test_stack_aligns_by_x_value(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "bar", "stack": "s", "data": [[10, 5], [20, 3]]},
                    {"type": "bar", "stack": "s", "data": [[20, 4], [30, 6]]},
                ],
            },
        )
        bases = chart.seriesRenderers[1]._stack_bases()[0]
        assert bases == {10: 5.0, 20: 3.0}

    def test_nice_ticks_subnormal_span(self):
        from pyqt6_ela_pro.charts.axes import niceTicks

        lo, hi, ticks = niceTicks(0.0, 2.5e-323, 5)
        assert hi >= lo
        assert ticks

    def test_candlestick_uses_high_low(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "candlestick", "data": [[20, 25, 5, 40], [22, 30, 10, 35]]}
                ],
            },
        )
        assert chart.coords[0].y_axis.vmax >= 40.0


class TestLazyUpdateCache:
    def test_lazy_update_paints_new_data(self, make):
        a = {
            "animation": False,
            "xAxis": {"data": ["a", "b", "c"]},
            "yAxis": {"max": 40},
            "series": [{"type": "bar", "data": [30, 10, 10]}],
        }
        b = {
            "animation": False,
            "xAxis": {"data": ["a", "b", "c"]},
            "yAxis": {"max": 40},
            "series": [{"type": "bar", "data": [10, 10, 30]}],
        }
        chart = _ready(make, a)
        img_a = _render(chart)
        chart.setOption(b, notMerge=True)
        QApplication.processEvents()
        img_b = _render(chart)
        chart.setOption(a, notMerge=True)
        QApplication.processEvents()
        _render(chart)
        chart.setOption(b, lazyUpdate=True)
        # 定时器触发前先画一帧：旧渲染器会把位图写进「新版本号」的缓存键。
        _render(chart)
        QApplication.processEvents()
        final = _render(chart)
        assert _pixel_diff(final, img_a) > 0
        assert _pixel_diff(final, img_b) == 0


class TestMergeAndState:
    def test_merge_reuses_old_series_objects(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"data": ["a"]},
                "yAxis": {},
                "series": [{"type": "bar", "data": [1]}],
            },
        )
        before = chart._option["series"][0]
        chart.setOption({"series": [{"data": [2]}]})
        assert chart._option["series"][0] is before, "合并不应深拷贝旧系列"

    def test_merge_accepts_null_series_item(self, make):
        chart = _ready(make, {"series": [None]})
        chart.setOption({"series": [{"type": "line", "name": "a", "data": [1]}]})
        assert [r.name for r in chart.seriesRenderers] == ["a"]

    def test_not_merge_resets_zoom(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"data": ["A", "B", "C", "D"]},
                "yAxis": {},
                "series": [{"type": "bar", "data": [1, 2, 3, 4]}],
            },
        )
        chart.dispatchAction({"type": "dataZoom", "start": 30, "end": 60})
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"data": ["A", "B"]},
                "yAxis": {},
                "series": [{"type": "bar", "data": [1, 2]}],
            },
            notMerge=True,
        )
        zoom = chart._component("dataZoom")
        assert (zoom.start, zoom.end) == (0.0, 100.0)

    def test_multi_legend_selection_survives_set_option(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "legend": [{"selected": {"a": True}}, {"selected": {"b": True}}],
                "xAxis": {"data": ["x"]},
                "yAxis": {},
                "series": [
                    {"type": "bar", "name": "a", "data": [1]},
                    {"type": "bar", "name": "b", "data": [2]},
                ],
            },
        )
        chart.dispatchAction({"type": "legendUnSelect", "name": "a"})
        chart.setOption({"series": [{"name": "a", "data": [3]}]})
        visible = {r.name: r.visible for r in chart.seriesRenderers}
        assert visible == {"a": False, "b": True}
        selected = chart.getOption()["legend"][0]["selected"]
        assert selected["a"] is False

    def test_timeline_frame_falls_back_to_base(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "baseOption": {
                    "title": {"text": "Base"},
                    "series": [{"type": "bar", "data": [1]}],
                },
                "timeline": {"data": ["t0", "t1"], "currentIndex": 0},
                "options": [{"title": {"text": "Frame0"}}, {}],
            },
        )
        chart.dispatchAction({"type": "timelineChange", "currentIndex": 1})
        assert chart._option["title"]["text"] == "Base"
        assert chart._option["timeline"]["currentIndex"] == 1

    def test_legend_hidden_without_option(self, make):
        chart = _ready(
            make,
            {"animation": False, "series": [{"type": "pie", "data": [{"name": "a", "value": 1}]}]},
        )
        assert chart.legend.shown is False

    def test_pie_legend_uses_data_items(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "legend": {},
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "a", "value": 1},
                            {"name": "b", "value": 2},
                            {"name": "c", "value": 3},
                        ],
                    }
                ],
            },
        )
        assert [name for name, _ in chart.legend._all_items] == ["a", "b", "c"]
        chart.dispatchAction({"type": "legendUnSelect", "name": "b"})
        QApplication.processEvents()
        assert [s["name"] for s in chart.seriesRenderers[0]._sectors] == ["a", "c"]
        assert chart.getOption()["legend"]["selected"] == {"a": True, "b": False, "c": True}
        # 普通 setOption 合并后仍保持隐藏
        chart.setOption(
            {
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "a", "value": 1},
                            {"name": "b", "value": 2},
                            {"name": "c", "value": 3},
                        ],
                    }
                ]
            }
        )
        QApplication.processEvents()
        assert [s["name"] for s in chart.seriesRenderers[0]._sectors] == ["a", "c"]

    def test_dispose_rejects_api(self, make):
        chart = _ready(make, {"series": []})
        chart.dispose()
        with pytest.raises(RuntimeError):
            chart.setOption({"series": []})


class TestAxisInteractions:
    def test_category_outside_window_maps_outside_plot(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c", "d", "e", "f"]},
                "yAxis": {},
                "dataZoom": [{"type": "inside", "start": 50, "end": 100}],
                "series": [{"type": "line", "data": [["a", 1], ["d", 4], ["f", 6]]}],
            },
        )
        coord = chart.coords[0]
        axis = coord.x_axis
        outside = axis.map("a", coord.plot.left(), coord.plot.right())
        inside = axis.map("d", coord.plot.left(), coord.plot.right())
        assert outside < coord.plot.left()
        assert outside != inside

    def test_start_value_roundtrip(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {},
                "dataZoom": [{"type": "inside", "start": 0, "end": 100}],
                "series": [{"type": "bar", "data": [1, 2, 3]}],
            },
        )
        chart.dispatchAction({"type": "dataZoom", "startValue": 1, "endValue": 2})
        assert chart.coords[0].x_axis.categories == ["b", "c"]

    def test_split_number_survives_auto_zoom(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value", "splitNumber": 10},
                "series": [{"type": "line", "data": [0, 1]}],
            },
        )
        assert len(chart.coords[0].y_axis.ticks()) >= 9

    def test_inverse_wheel_keeps_anchor(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value", "min": 0, "max": 10, "inverse": True},
                "series": [{"type": "line", "data": [0, 10]}],
            },
        )
        coord = chart.coords[0]
        pos = QPointF(coord.plot.center().x(), coord.plot.top() + coord.plot.height() * 0.1)
        before = chart.convertFromPixel({"seriesIndex": 0}, [pos.x(), pos.y()])
        event = QWheelEvent(
            pos,
            pos,
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(chart, event)
        QApplication.processEvents()
        after = chart.convertFromPixel({"seriesIndex": 0}, [pos.x(), pos.y()])
        assert abs(after[1] - before[1]) < 1e-6

    def test_value_axis_interval_uses_tick_index(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a"]},
                "yAxis": {"type": "value", "min": 1, "max": 5, "axisLabel": {"interval": 1}},
                "series": [{"type": "line", "data": [1]}],
            },
        )
        axis = chart.coords[0].y_axis
        shown = [axis.labelShownAt(i) for i in range(len(axis.ticks()))]
        assert shown == [True, False, True, False, True]


class TestSemantics:
    def test_calendar_month_range(self):
        start, end = CalendarCoord._resolve_range("2026-01")
        assert (start.year, start.month, start.day) == (2026, 1, 1)
        assert (end.year, end.month, end.day) == (2026, 1, 31)

    def test_calendar_year_list(self):
        start, end = CalendarCoord._resolve_range(["2031"])
        assert (start.year, end.year) == (2031, 2031)

    def test_radar_indicator_min(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "radar": {
                    "indicator": [
                        {"name": "a", "min": 50, "max": 100},
                        {"name": "b", "min": 0, "max": 100},
                    ]
                },
                "series": [{"type": "radar", "data": [{"name": "s", "value": [50, 100]}]}],
            },
        )
        renderer = chart.seriesRenderers[0]
        first = renderer._polys[0]["points"][0]
        assert abs(first.x() - renderer._center.x()) < 1e-6
        assert abs(first.y() - renderer._center.y()) < 1e-6

    def test_gauge_negative_value(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "series": [
                    {"type": "gauge", "min": -100, "max": 100, "data": [{"name": "v", "value": -30}]}
                ],
            },
        )
        assert chart.seriesRenderers[0]._value == -30.0

    def test_pie_negative_keeps_data_index(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "a", "value": -5},
                            {"name": "b", "value": 10, "itemStyle": {"color": "#ff0000"}},
                            {"name": "c", "value": 30},
                        ],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert [s["index"] for s in renderer._sectors] == [0, 1, 2]
        assert renderer.itemColor(1).name() == "#ff0000"

    def test_funnel_last_layer_trapezoid(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "funnel",
                        "data": [
                            {"name": "a", "value": 100},
                            {"name": "b", "value": 60},
                            {"name": "c", "value": 20},
                        ],
                    }
                ],
            },
        )
        poly = chart.seriesRenderers[0]._layers[-1]["poly"]
        top_w = abs(poly[1].x() - poly[0].x())
        bottom_w = abs(poly[2].x() - poly[3].x())
        assert bottom_w < top_w

    def test_gap_value_at_index_stays_sorted(self, make):
        xs = list(range(60)) + [3600 + i for i in range(60)]
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "data": [[x, 1.0] for x in xs]}],
            },
            width=900,
            height=500,
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._point_idx == sorted(renderer._point_idx)
        info = renderer.valueAtIndex(0)
        assert info is not None and info["pos"] is not None
        assert info["pos"].x() < chart.width() / 2

    def test_graph_node_value(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "series": [{"type": "graph", "data": [{"name": "a", "value": 42}], "links": []}],
            },
            width=400,
            height=300,
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._nodes[0]["value"] == 42
        assert renderer.hitTest(renderer._nodes[0]["pos"])["value"] == 42

    def test_heatmap_calendar_data_index(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "calendar": {"range": ["2025-01-01", "2025-12-31"]},
                "series": [
                    {
                        "type": "heatmap",
                        "coordinateSystem": "calendar",
                        "data": [["2025-01-20", 80]],
                    }
                ],
            },
            width=700,
            height=400,
        )
        cells = [c for c in chart.seriesRenderers[0]._cells if not c.get("empty")]
        assert [(c["label"], c["index"]) for c in cells] == [("2025-01-20", 0)]

    def test_sampling_stats_api(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {},
                "series": [{"type": "line", "data": [math.sin(i / 20) for i in range(20_000)]}],
            },
        )
        stats = chart.seriesRenderers[0].samplingStats()
        assert stats["dataLen"] == 20_000
        assert stats["drawn"] > 0
        assert isinstance(stats["sampled"], bool)


class TestPaintAndExport:
    def test_visual_map_drag_recolors_series(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value", "min": 0, "max": 4},
                "yAxis": {"type": "value", "min": 0, "max": 4},
                "visualMap": {"min": 0, "max": 100, "calculable": True, "dimension": 2},
                "series": [
                    {
                        "type": "scatter",
                        "symbolSize": 40,
                        "data": [[1, 1, 10], [2, 2, 50], [3, 3, 100]],
                    }
                ],
            },
            width=600,
            height=450,
        )
        before = _render(chart)
        chart._component("visualMap").max = 50.0
        chart.update()
        QApplication.processEvents()
        after = _render(chart)
        assert _pixel_diff(before, after) > 0

    def test_export_does_not_materialize_option(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {},
                "series": [{"type": "line", "data": [[i, i] for i in range(1000)]}],
            },
        )

        def boom():
            raise AssertionError("导出不应调用 getOption()")

        chart.getOption = boom  # type: ignore[method-assign]
        assert chart.getDataURL({"type": "png"})

    def test_save_image_jpeg(self, make, tmp_path):
        chart = _ready(
            make,
            {"animation": False, "series": [{"type": "pie", "data": [{"name": "a", "value": 1}]}]},
        )
        target = tmp_path / "chart.jpg"
        assert chart.saveImage(str(target))
        assert target.read_bytes()[:2] == b"\xff\xd8", "jpg 路径必须写 JPEG 字节"

    def test_lines_curveness_hit_test(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value", "min": 0, "max": 10},
                "yAxis": {"type": "value", "min": 0, "max": 10},
                "series": [
                    {
                        "type": "lines",
                        "lineStyle": {"curveness": 0.35},
                        "data": [{"coords": [[0, 0], [10, 10]]}],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        seg = renderer._segments[0]
        path = renderer._curve_path(seg["p0"], seg["p1"], 0.35)
        mid = path.pointAtPercent(0.5)
        assert renderer.hitTest(mid) is not None
        chord_mid = QPointF(
            (seg["p0"].x() + seg["p1"].x()) / 2, (seg["p0"].y() + seg["p1"].y()) / 2
        )
        assert renderer.hitTest(chord_mid) is None

    def test_parallel_uses_option_background(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "backgroundColor": "#ff0000",
                "parallelAxis": [{"dim": 0, "name": "a"}, {"dim": 1, "name": "b"}],
                "series": [{"type": "parallel", "data": [[1, 2], [2, 3]]}],
            },
        )
        image = _render(chart)
        color = image.pixelColor(10, 10)
        assert color.red() > 200 and color.green() < 100

    def test_hierarchy_label_string_font_size(self, make):
        chart = _ready(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "pie",
                        "label": {"show": True, "fontSize": "12.5"},
                        "data": [{"name": "a", "value": 1}, {"name": "b", "value": 2}],
                    }
                ],
            },
        )
        image = QImage(400, 300, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        try:
            chart.seriesRenderers[0].paint(painter, 1.0)
        finally:
            painter.end()


class TestAnimationHitTest:
    @pytest.mark.parametrize(
        "option",
        [
            {"series": [{"type": "funnel", "data": [{"name": "a", "value": 1}]}]},
            {
                "xAxis": {"type": "category", "data": ["a"]},
                "yAxis": {},
                "series": [{"type": "boxplot", "data": [[1, 2, 3, 4, 5]]}],
            },
            {
                "xAxis": {"type": "category", "data": ["a"]},
                "yAxis": {},
                "series": [{"type": "candlestick", "data": [[1, 2, 0, 3]]}],
            },
        ],
        ids=["funnel", "boxplot", "candlestick"],
    )
    def test_hit_test_disabled_during_animation(self, make, option):
        chart = _ready(make, {"animation": False, **option})
        renderer = chart.seriesRenderers[0]
        renderer._anim_t = 0.2
        assert renderer.hitTest(QPointF(chart.width() / 2, chart.height() / 2)) is None
