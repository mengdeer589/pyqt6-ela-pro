"""ECharts 选项键保真测试：轴键 / 系列键 / emphasis / calendar / timeline。"""

from __future__ import annotations

from PyQt6.QtCore import QRectF
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts.axes import AxisModel, CalendarCoord, GridCoord


def _make(option, size=(600, 400)):
    chart = ElaChartWidget()
    chart.resize(*size)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


class TestAxisKeys:
    def test_axis_label_interval_and_rotate(self):
        model = AxisModel(
            {
                "type": "category",
                "data": ["a", "b", "c", "d", "e"],
                "axisLabel": {"interval": 1, "rotate": 30, "color": "#123456"},
            }
        )
        assert model.labelShownAt(0, "a") is True
        assert model.labelShownAt(1, "b") is False
        assert model.labelShownAt(2, "c") is True
        assert model.labelColor().name() == "#123456"

    def test_axis_label_formatter(self):
        model = AxisModel({"type": "value", "axisLabel": {"formatter": "{value} 元"}})
        model.setExtent(0, 10)
        assert model.formatTickLabel(2.0) == "2 元"
        model2 = AxisModel(
            {"type": "value", "axisLabel": {"formatter": lambda v: f"<{v}>"}}
        )
        assert model2.formatTickLabel(3.0) == "<3>"

    def test_boundary_gap_false_maps_edges(self):
        coord = GridCoord(
            option={
                "xAxis": {
                    "type": "category",
                    "data": ["a", "b", "c"],
                    "boundaryGap": False,
                },
                "yAxis": {},
            }
        )
        coord.layout(QRectF(0, 0, 300, 200))
        left = coord.x_axis.map(0, coord.plot.left(), coord.plot.right(), local=True)
        right = coord.x_axis.map(2, coord.plot.left(), coord.plot.right(), local=True)
        assert abs(left - coord.plot.left()) < 1e-6
        assert abs(right - coord.plot.right()) < 1e-6

    def test_inverse_reverses_axis(self):
        normal = AxisModel({"type": "value"})
        normal.setExtent(0, 10)
        inverted = AxisModel({"type": "value", "inverse": True})
        inverted.setExtent(0, 10)
        p1 = normal.map(10, 0, 100)
        p2 = inverted.map(10, 0, 100)
        assert p1 == 100 and p2 == 0

    def test_min_max_interval(self):
        model = AxisModel({"type": "value", "minInterval": 5})
        model.setExtent(0, 10, segments=10)
        ticks = model.ticks()
        assert len(ticks) >= 2
        assert ticks[1] - ticks[0] >= 5 - 1e-9

    def test_scale_skips_zero_baseline(self):
        model = AxisModel({"type": "value", "scale": True})
        model.setExtent(100, 200)
        assert model.vmin > 0
        model2 = AxisModel({"type": "value"})
        model2.setExtent(100, 200)
        assert model2.vmin == 0.0

    def test_split_number(self):
        model = AxisModel({"type": "value", "splitNumber": 10})
        model.setExtent(0, 100)
        assert len(model.ticks()) >= 6

    def test_axis_style_keys_render(self):
        chart = _make(
            {
                "xAxis": {
                    "type": "category",
                    "data": ["一", "二", "三"],
                    "name": "月份",
                    "nameLocation": "middle",
                    "axisTick": {"show": True, "inside": True, "length": 8},
                    "axisLine": {"lineStyle": {"color": "#ff0000", "width": 2}},
                },
                "yAxis": {
                    "type": "value",
                    "name": "销量",
                    "nameLocation": "middle",
                    "splitLine": {"show": False},
                    "splitArea": {"show": True},
                },
                "grid": {"show": True, "borderColor": "#00ff00", "borderWidth": 1},
                "series": [{"type": "bar", "name": "A", "data": [1, 2, 3]}],
            }
        )
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()

    def test_grid_contain_label(self):
        option = {
            "xAxis": {"type": "category", "data": ["长标签一", "长标签二"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "name": "A", "data": [100000, 200000]}],
        }
        plain = _make(option)
        contained = _make({**option, "grid": {"containLabel": True}})
        assert contained.coords[0].m_left >= plain.coords[0].m_left
        assert contained.coords[0].m_bottom >= plain.coords[0].m_bottom
        plain.deleteLater()
        contained.deleteLater()


class TestSeriesKeys:
    def test_series_silent_skips_hit(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [
                    {"type": "bar", "name": "A", "silent": True, "data": [1, 2]}
                ],
            }
        )
        renderer = chart.seriesRenderers[0]
        pos = renderer._bars[0]["rect"].center()
        assert renderer.hitTest(pos) is not None  # 渲染器本身可命中
        assert chart.hitItem(pos) is None  # chart 层跳过 silent 系列
        chart.deleteLater()

    def test_series_animation_false_renders_final(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [
                    {"type": "bar", "name": "A", "animation": False, "data": [1, 2]}
                ],
            }
        )
        assert chart.seriesRenderers[0].animProgress(0.0) == 1.0
        chart.deleteLater()

    def test_emphasis_and_blur_styles(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "bar",
                        "name": "A",
                        "data": [1, 2],
                        "emphasis": {"itemStyle": {"color": "#ff0000"}},
                        "blur": {"itemStyle": {"opacity": 0.2}},
                    }
                ],
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.emphasisColor(0).name() == "#ff0000"
        assert abs(renderer.blurOpacity() - 0.2) < 1e-6
        chart._hover = (renderer, {"dataIndex": 0})
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()

    def test_candlestick_echarts_color_keys(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "candlestick",
                        "name": "K",
                        "data": [[20, 34, 10, 38], [40, 35, 30, 50]],
                        "itemStyle": {"color": "#ff0000", "color0": "#00ff00"},
                    }
                ],
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._up_color().name() == "#ff0000"
        assert renderer._down_color().name() == "#00ff00"
        chart.deleteLater()

    def test_line_sampling_string(self):
        chart = _make(
            {
                "xAxis": {"type": "value"},
                "yAxis": {},
                "series": [
                    {
                        "type": "line",
                        "name": "A",
                        "data": [[i, i % 7] for i in range(5000)],
                        "sampling": "lttb",
                    }
                ],
            }
        )
        enabled, _threshold, _ppb, algo = chart.seriesRenderers[0]._sampling_params()
        assert enabled is True and algo == "lttb"
        chart.deleteLater()

    def test_line_sampling_false_string(self):
        chart = _make(
            {
                "xAxis": {"type": "value"},
                "yAxis": {},
                "series": [
                    {"type": "line", "name": "A", "data": [1, 2, 3], "sampling": "none"}
                ],
            }
        )
        enabled, *_ = chart.seriesRenderers[0]._sampling_params()
        assert enabled is False
        chart.deleteLater()

    def test_funnel_label_positions(self):
        option = {
            "series": [
                {
                    "type": "funnel",
                    "name": "F",
                    "data": [
                        {"name": "展现", "value": 100},
                        {"name": "点击", "value": 60},
                    ],
                }
            ]
        }
        for pos in (
            "inside",
            "insideLeft",
            "insideRight",
            "left",
            "right",
            "top",
            "bottom",
        ):
            chart = _make(
                {
                    "series": [
                        {
                            **option["series"][0],
                            "label": {"show": True, "position": pos},
                        }
                    ]
                }
            )
            image = chart.grab().toImage()
            assert image.width() == chart.width()
            chart.deleteLater()

    def test_tree_edge_shape(self):
        option = {
            "series": [
                {
                    "type": "tree",
                    "name": "T",
                    "data": [
                        {
                            "name": "root",
                            "children": [{"name": "a", "value": 1}],
                        }
                    ],
                }
            ]
        }
        for shape in ("polyline", "curve"):
            chart = _make(
                {
                    "series": [
                        {
                            **option["series"][0],
                            "edgeShape": shape,
                        }
                    ]
                }
            )
            image = chart.grab().toImage()
            assert image.width() == chart.width()
            chart.deleteLater()

    def test_lines_effect_alias_removed(self):
        chart = _make(
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "lines",
                        "name": "L",
                        "data": [{"coords": [[0, 0], [10, 10]]}],
                        "effect": {"show": True, "period": 4},
                    }
                ],
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._timer is not None
        chart.deleteLater()

    def test_heatmap_item_tooltip_formatter(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "category", "data": ["a", "b"]},
                "series": [
                    {
                        "type": "heatmap",
                        "name": "H",
                        "data": [
                            {
                                "value": [0, 0, 1],
                                "tooltip": {"formatter": "自定义文案"},
                            },
                            [1, 1, 9],
                        ],
                    }
                ],
            }
        )
        renderer = chart.seriesRenderers[0]
        hit = renderer.hitTest(renderer._cells[0]["rect"].center())
        assert hit["tooltipFormatter"] == "自定义文案"
        lines = chart.tooltip.buildLines(hit, renderer.color(), renderer.name)
        assert any("自定义文案" in line[2] for line in lines)
        chart.deleteLater()


class TestCalendarKeys:
    def test_calendar_range_year_and_orient(self):
        coord = CalendarCoord(option={"calendar": {"range": "2026"}})
        coord.layout(QRectF(0, 0, 900, 200))
        assert coord.start.year == 2026 and coord.end.year == 2026
        vertical = CalendarCoord(
            option={"calendar": {"range": 2026, "orient": "vertical"}}
        )
        vertical.layout(QRectF(0, 0, 900, 400))
        assert vertical._vertical is True

    def test_calendar_split_line_and_item_style(self):
        chart = _make(
            {
                "calendar": {
                    "range": 2026,
                    "splitLine": {"show": True},
                    "itemStyle": {"color": "#eeeeee"},
                },
                "series": [
                    {
                        "type": "heatmap",
                        "coordinateSystem": "calendar",
                        "name": "H",
                        "data": [["2026-01-01", 5]],
                    }
                ],
            }
        )
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        empty = next(c for c in chart.seriesRenderers[0]._cells if c["empty"])
        assert empty["color"].name() == "#eeeeee"
        chart.deleteLater()


class TestTimelineKeys:
    def test_timeline_base_option_and_current_index(self):
        chart = _make(
            {
                "baseOption": {
                    "title": {"text": "基线标题"},
                    "xAxis": {"type": "category", "data": ["一", "二"]},
                    "yAxis": {},
                    "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
                },
                "timeline": {"data": ["2024", "2025", "2026"], "currentIndex": 1},
                "options": [
                    {"series": [{"name": "A", "data": [1, 2]}]},
                    {"series": [{"name": "A", "data": [3, 4]}]},
                    {"series": [{"name": "A", "data": [5, 6]}]},
                ],
            }
        )
        assert chart.title.text == "基线标题"
        assert chart.seriesRenderers[0].data() == [3, 4]  # currentIndex=1 的帧
        assert chart._timeline_index == 1
        # getOption 保留 options 帧结构（供后续切换）
        option = chart.getOption()
        assert len(option["options"]) == 3
        assert option["series"][0]["data"] == [3, 4]
        chart.deleteLater()

    def test_timeline_frame_switch_keeps_animation(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "timeline": {"data": ["2024", "2025"]},
                "options": [
                    {"series": [{"type": "bar", "name": "A", "data": [1, 2]}]},
                    {"series": [{"type": "bar", "name": "A", "data": [7, 8]}]},
                ],
            }
        )
        timeline = next(c for c in chart.components if c.optionKey == "timeline")
        timeline.goto(1)
        renderer = chart.seriesRenderers[0]
        assert renderer.data() == [7, 8]
        assert renderer.prev_data == [1, 2]  # 过渡动画的旧数据
        chart.deleteLater()

    def test_timeline_plain_set_option_keeps_frame(self):
        """普通 setOption 合并帧数据时不应把当前帧回退到 options[0]。"""
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "timeline": {"data": ["2024", "2025", "2026"], "currentIndex": 2},
                "options": [
                    {"series": [{"type": "bar", "name": "A", "data": [1, 2]}]},
                    {"series": [{"type": "bar", "name": "A", "data": [3, 4]}]},
                    {"series": [{"type": "bar", "name": "A", "data": [5, 6]}]},
                ],
            }
        )
        assert chart.seriesRenderers[0].data() == [5, 6]
        chart.setOption({"title": {"text": "叠加标题"}})
        assert chart.seriesRenderers[0].data() == [5, 6]
        assert chart.title.text == "叠加标题"
        chart.deleteLater()


class TestTooltipKeys:
    def test_axis_pointer_types(self):
        for kind in ("line", "shadow", "cross", "none"):
            chart = _make(
                {
                    "tooltip": {"trigger": "axis", "axisPointer": {"type": kind}},
                    "xAxis": {"type": "category", "data": ["一", "二"]},
                    "yAxis": {},
                    "series": [{"type": "line", "name": "A", "data": [1, 2]}],
                }
            )
            assert chart.tooltip.axisPointerType() == kind
            image = chart.grab().toImage()
            assert image.width() == chart.width()
            chart.deleteLater()

    def test_tooltip_style_keys_render(self):
        chart = _make(
            {
                "tooltip": {
                    "trigger": "item",
                    "backgroundColor": "#ffffff",
                    "borderColor": "#000000",
                    "borderWidth": 2,
                    "textStyle": {"color": "#333333", "fontSize": 12},
                },
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
            }
        )
        renderer = chart.seriesRenderers[0]
        pos = renderer._bars[0]["rect"].center()
        chart._hover = (renderer, {"dataIndex": 0})
        chart.tooltip.showAt(
            pos,
            chart.tooltip.buildLines({"name": "一", "value": 1}, renderer.color(), "A"),
        )
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()


class TestTitleAndBackground:
    def test_title_bottom_and_styles(self):
        chart = _make(
            {
                "title": {
                    "text": "主标题",
                    "subtext": "副标题",
                    "bottom": 4,
                    "left": "center",
                    "textStyle": {"color": "#ff0000", "fontSize": 20},
                    "subtextStyle": {"color": "#00ff00"},
                },
                "xAxis": {"type": "category", "data": ["一"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1]}],
            }
        )
        assert chart.title.atBottom is True
        band = chart.title.bandRect(chart.width(), chart.height())
        assert band.bottom() <= chart.height()
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()

    def test_background_color(self):
        chart = _make(
            {
                "backgroundColor": "#112233",
                "series": [{"type": "pie", "data": [1, 2]}],
            }
        )
        image = chart.grab().toImage()
        assert image.pixelColor(2, 2).name() == "#112233"
        chart.deleteLater()

    def test_legend_data_and_item_size(self):
        chart = _make(
            {
                "legend": {"data": ["B"], "itemWidth": 16, "itemHeight": 12},
                "xAxis": {"type": "category", "data": ["一"]},
                "yAxis": {},
                "series": [
                    {"type": "bar", "name": "A", "data": [1]},
                    {"type": "line", "name": "B", "data": [2]},
                ],
            }
        )
        names = [name for name, _ in chart.legend._items]
        assert names == ["B"]
        assert chart.legend.itemWidth() == 16.0
        assert chart.legend.itemHeight() == 12.0
        chart.deleteLater()
