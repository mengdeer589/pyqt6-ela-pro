"""组件数组写法 / 雷达顶层组件 / 地图 label / 各组件外观键的守卫。

覆盖的是一类**静默失效**：ECharts 写法能传、不报错，但结果要么整块丢弃
（``grid: [{...}]`` 让坐标系消失），要么根本不看（``map.label.show``）。

不需要 numpy：所有这些断言都在布局 / 解析层，不依赖渲染。
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QWheelEvent

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts._tokens import T
from pyqt6_ela_pro.charts.axes import (
    CalendarCoord,
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
)


def _chart(make, option=None, w=520, h=380) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(w, h)
    chart.setOption(
        option
        or {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A", "B"]},
            "yAxis": {"type": "value"},
            "series": [
                {"type": "line", "name": "alpha", "data": [1, 2]},
                {"type": "line", "name": "beta", "data": [2, 1]},
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _base(extra: dict) -> dict:
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": ["A", "B"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "alpha", "data": [1, 2]}],
    }
    option.update(extra)
    return option


class TestComponentArrays:
    """ECharts 组件数组：单实例取第一个 dict，不能让组件消失。"""

    def test_grid_array_keeps_coord(self, make):
        chart = _chart(make, _base({"grid": [{"left": 80}]}))
        assert any(isinstance(c, GridCoord) for c in chart.coords)
        assert chart.coords[0].m_left == 80.0

    def test_grid_single_element_array(self, make):
        chart = _chart(make, _base({"grid": [{"left": 11}]}))
        assert chart.coords[0].m_left == 11.0
        assert len([c for c in chart.coords if isinstance(c, GridCoord)]) == 1

    def test_polar_array_keeps_coord(self, make):
        chart = _chart(make, _base({"polar": [{"radius": "70%"}]}))
        assert any(isinstance(c, PolarCoord) for c in chart.coords)

    def test_calendar_array_keeps_coord(self, make):
        chart = _chart(make, _base({"calendar": [{"range": "2026"}]}))
        assert any(isinstance(c, CalendarCoord) for c in chart.coords)

    def test_single_axis_array_keeps_coord(self, make):
        chart = _chart(make, _base({"singleAxis": [{"type": "value"}]}))
        assert any(isinstance(c, SingleAxisCoord) for c in chart.coords)

    def test_title_array(self, make):
        chart = _chart(make, _base({"title": [{"text": "数组标题"}]}))
        assert chart.title.text == "数组标题"

    def test_legend_array(self, make):
        option = _base(
            {
                "legend": [{"data": ["beta"]}],
                "series": [
                    {"type": "line", "name": "alpha", "data": [1, 2]},
                    {"type": "line", "name": "beta", "data": [2, 1]},
                ],
            }
        )
        chart = _chart(make, option)
        assert [name for name, _ in chart.legend._items] == ["beta"]

    def test_tooltip_array(self, make):
        chart = _chart(make, _base({"tooltip": [{"trigger": "axis"}]}))
        assert chart.tooltip.opt.get("trigger") == "axis"

    def test_brush_array(self, make):
        chart = _chart(make, _base({"brush": [{"type": "lasso"}]}))
        # 组件建起来了（数组不再让构造函数 ValueError）。
        # 注意：``type`` 会被 dragMode（显式配 brush 默认 select）覆写成 rect。
        assert chart._component("brush") is not None
        assert chart.dragMode() == "select"

    def test_toolbox_array(self, make):
        chart = _chart(
            make, _base({"toolbox": [{"feature": {"saveAsImage": {}}}]})
        )
        assert chart._component("toolbox") is not None


class TestRadarComponent:
    def _radar(self, make, extra: dict):
        option = {
            "animation": False,
            "radar": extra,
            "series": [{"type": "radar", "name": "R", "data": [{"value": [50, 60]}]}],
        }
        chart = _chart(make, option)
        return chart, chart.seriesRenderers[0]

    def test_top_level_indicator(self, make):
        _chart_obj, renderer = self._radar(
            make,
            {"indicator": [{"name": "销售", "max": 100}, {"name": "技术", "max": 100}]},
        )
        assert [d["name"] for d in renderer._indicators] == ["销售", "技术"]

    def test_series_indicator_wins(self, make):
        chart = make(ElaChartWidget)
        chart.resize(480, 360)
        chart.setOption(
            {
                "animation": False,
                "radar": {"indicator": [{"name": "顶层", "max": 100}]},
                "series": [
                    {
                        "type": "radar",
                        "indicator": [{"name": "系列", "max": 100}],
                        "data": [{"value": [10]}],
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        assert [d["name"] for d in chart.seriesRenderers[0]._indicators] == ["系列"]

    def test_center_and_radius(self, make):
        chart, renderer = self._radar(
            make,
            {
                "indicator": [{"name": "a", "max": 100}, {"name": "b", "max": 100}],
                "center": ["30%", "40%"],
                "radius": "50%",
            },
        )
        # 30% / 40% 都落在中心左上方（不依赖内容区具体内缩多少）
        assert renderer._center.x() < chart.width() / 2
        assert renderer._center.y() < chart.height() / 2
        assert renderer._radius > 10.0

        _chart_obj, small = self._radar(
            make,
            {
                "indicator": [{"name": "a", "max": 100}, {"name": "b", "max": 100}],
                "radius": "25%",
            },
        )
        assert renderer._radius > small._radius


class TestMapLabel:
    def _map(self, make, label=None):
        series = {"type": "map", "name": "M", "data": []}
        if label is not None:
            series["label"] = label
        chart = _chart(make, {"animation": False, "series": [series]})
        return chart.seriesRenderers[0]

    def test_default_shown(self, make):
        assert self._map(make).labelShown() is True

    def test_show_false_hides(self, make):
        assert self._map(make, {"show": False}).labelShown() is False

    def test_style(self, make):
        renderer = self._map(
            make, {"fontSize": 15, "fontWeight": 700, "color": "#112233"}
        )
        style = renderer.labelStyle()
        assert style["fontSize"] == 15
        assert style["fontWeight"] == 700
        assert style["color"] == "#112233"

    def test_global_fallback(self, make):
        chart = make(ElaChartWidget)
        chart.resize(480, 360)
        chart.setOption(
            {
                "animation": False,
                "textStyle": {"fontSize": 16, "color": "#445566"},
                "series": [{"type": "map", "name": "M", "data": []}],
            }
        )
        style = chart.seriesRenderers[0].labelStyle()
        assert style["fontSize"] == 16
        assert style["color"] == "#445566"


class TestDataZoomStyle:
    def test_text_style(self, make):
        chart = _chart(
            make,
            _base(
                {
                    "dataZoom": [
                        {"type": "slider", "textStyle": {"fontSize": 17, "color": "#102030"}}
                    ]
                }
            ),
        )
        zoom = chart._component("dataZoom")
        assert zoom.detailStyle()["fontSize"] == 17
        assert zoom.detailStyle()["color"] == "#102030"

    def test_global_fallback(self, make):
        chart = _chart(
            make,
            _base(
                {
                    "textStyle": {"fontSize": 14},
                    "dataZoom": [{"type": "slider"}],
                }
            ),
        )
        assert chart._component("dataZoom").detailStyle()["fontSize"] == 14


class TestVisualMapText:
    def test_text_pair(self, make):
        chart = _chart(
            make,
            _base(
                {
                    "visualMap": {
                        "min": 0,
                        "max": 100,
                        "text": ["高", "低"],
                    }
                }
            ),
        )
        vm = chart._component("visualMap")
        assert vm.textPair() == ("高", "低")

    def test_text_pair_default_is_value(self, make):
        chart = _chart(make, _base({"visualMap": {"min": 3, "max": 9}}))
        assert chart._component("visualMap").textPair() == ("9", "3")

    def test_text_style_global(self, make):
        chart = _chart(
            make,
            _base(
                {
                    "textStyle": {"fontSize": 13, "color": "#aabbcc"},
                    "visualMap": {"min": 0, "max": 1},
                }
            ),
        )
        style = chart._component("visualMap").textStyle()
        assert style["fontSize"] == 13
        assert style["color"] == "#aabbcc"


class TestTimelineStyle:
    def _timeline(self, make, extra: dict):
        option = {
            "animation": False,
            "timeline": {"data": ["2024", "2025"], **extra},
            "xAxis": {"type": "category", "data": ["A"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "data": [1]}],
        }
        chart = _chart(make, option)
        return chart._component("timeline")

    def test_flat_label_style(self, make):
        timeline = self._timeline(make, {"label": {"fontSize": 15, "color": "#123"}})
        assert timeline.labelStyle()["fontSize"] == 15
        assert timeline.labelStyle()["color"] == "#123"

    def test_nested_label_text_style(self, make):
        timeline = self._timeline(
            make, {"label": {"textStyle": {"fontSize": 16, "fontWeight": 600}}}
        )
        assert timeline.labelStyle()["fontSize"] == 16
        assert timeline.labelStyle()["fontWeight"] == 600

    def test_line_style_merge(self, make):
        timeline = self._timeline(make, {"lineStyle": {"color": "#ff0000", "width": 3}})
        style = timeline._style("lineStyle", {"color": "#000", "width": 1})
        assert style["color"] == "#ff0000"
        assert style["width"] == 3


class TestCalendarLabelStyle:
    def _calendar(self, make, day: dict):
        option = {
            "animation": False,
            "calendar": {"range": "2026", "dayLabel": day},
            "series": [{"type": "heatmap", "data": [["2026-01-01", 1]]}],
        }
        chart = _chart(make, option)
        coord = next(c for c in chart.coords if isinstance(c, CalendarCoord))
        return coord

    def test_day_label_style(self, make):
        coord = self._calendar(
            make, {"color": "#123456", "fontSize": 15, "fontWeight": 700}
        )
        style = coord._label_style("day")
        assert style["color"] == "#123456"
        assert coord._label_font(style).pixelSize() == 15
        assert coord._label_font(style).weight() == 700

    def test_global_fallback(self, make):
        chart = make(ElaChartWidget)
        chart.resize(480, 360)
        chart.setOption(
            {
                "animation": False,
                "textStyle": {"fontSize": 16},
                "calendar": {"range": "2026"},
                "series": [{"type": "heatmap", "data": []}],
            }
        )
        coord = next(c for c in chart.coords if isinstance(c, CalendarCoord))
        assert coord._label_style("month")["fontSize"] == 16


class TestMarkLabelStyle:
    def _mark_chart(self, make, mark_point: dict):
        option = _base(
            {
                "series": [
                    {
                        "type": "line",
                        "name": "alpha",
                        "data": [1, 5, 2],
                        "markPoint": mark_point,
                    }
                ]
            }
        )
        chart = _chart(make, option)
        comp = next(c for c in chart.components if c.optionKey == "markPoint")
        return comp

    def test_item_overrides_series(self, make):
        comp = self._mark_chart(
            make,
            {
                "label": {"fontSize": 12, "color": "#111111"},
                "data": [
                    {"type": "max", "label": {"fontSize": 18, "color": "#222222"}}
                ],
            },
        )
        style = comp._label_style(comp.opt["data"][0])
        assert style["fontSize"] == 18
        assert style["color"] == "#222222"

    def test_position_bottom(self, make):
        comp = self._mark_chart(
            make, {"data": [{"type": "max", "label": {"position": "bottom"}}]}
        )
        mark = comp._marks[0]
        assert mark["rect"].top() >= mark["pos"].y()

    def test_show_false(self, make):
        comp = self._mark_chart(
            make, {"data": [{"type": "max", "label": {"show": False}}]}
        )
        assert comp._marks[0]["text"] == ""
        assert comp._marks[0]["rect"] is None

    def test_markline_style(self, make):
        option = _base(
            {
                "series": [
                    {
                        "type": "line",
                        "name": "alpha",
                        "data": [1, 5, 2],
                        "markLine": {
                            "label": {"fontSize": 15, "position": "start"},
                            "data": [{"type": "max"}],
                        },
                    }
                ]
            }
        )
        chart = _chart(make, option)
        comp = next(c for c in chart.components if c.optionKey == "markLine")
        line = comp._lines[0]
        assert line["font"].pixelSize() == 15
        assert line["text"].startswith("最大值")


class TestGaugeStyle:
    def _gauge(self, make, extra: dict):
        option = {
            "animation": False,
            "series": [
                {
                    "type": "gauge",
                    "name": "G",
                    "data": [{"name": "负载", "value": 66}],
                    **extra,
                }
            ],
        }
        chart = _chart(make, option)
        return chart.seriesRenderers[0]

    def test_detail_and_title_style(self, make):
        renderer = self._gauge(
            make,
            {
                "detail": {"color": "#ff0000", "fontSize": 20, "fontWeight": 700},
                "title": {"color": "#00ff00", "fontSize": 14},
            },
        )
        assert renderer.detailStyle()["color"] == "#ff0000"
        assert renderer.detailStyle()["fontWeight"] == 700
        assert renderer.titleStyle()["color"] == "#00ff00"

    def test_detail_formatter(self, make):
        renderer = self._gauge(make, {"detail": {"formatter": "{value}%"}})
        assert renderer._detail_text(66) == "66%"

    def test_detail_formatter_callable(self, make):
        renderer = self._gauge(
            make, {"detail": {"formatter": lambda v: f"<{v}>"}}
        )
        assert renderer._detail_text(66) == "<66>"


class TestParallelAxisStyle:
    def test_name_and_label_styles(self, make):
        option = {
            "animation": False,
            "parallelAxis": [
                {
                    "name": "销量",
                    "nameTextStyle": {"color": "#112233", "fontSize": 15},
                    "axisLabel": {"color": "#445566", "fontSize": 9},
                },
                {"name": "成本"},
            ],
            "series": [{"type": "parallel", "data": [[1, 2], [3, 4]]}],
        }
        chart = _chart(make, option)
        renderer = chart.seriesRenderers[0]
        first = renderer._axes[0]
        assert first["nameStyle"]["color"] == "#112233"
        assert first["labelStyle"]["fontSize"] == 9

    def test_axis_label_show_false(self, make):
        option = {
            "animation": False,
            "parallelAxis": [
                {"name": "a", "axisLabel": {"show": False}},
                {"name": "b"},
            ],
            "series": [{"type": "parallel", "data": [[1, 2], [3, 4]]}],
        }
        chart = _chart(make, option)
        renderer = chart.seriesRenderers[0]
        assert renderer._axis_label_shown(renderer._axes[0]) is False
        assert renderer._axis_label_shown(renderer._axes[1]) is True


class TestHierarchyLabelColor:
    def test_label_color_override(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "tree",
                        "label": {"color": "#123123"},
                        "data": [{"name": "root", "children": [{"name": "c"}]}],
                    }
                ],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.labelColor(QColor("#ffffff")).name() == "#123123"

    def test_default_when_unset(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [{"type": "tree", "data": [{"name": "root"}]}],
            },
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.labelColor(QColor("#ffffff")).name() == "#ffffff"


class TestAxisNameStyle:
    def test_name_style_and_gap(self, make):
        chart = _chart(
            make,
            _base(
                {
                    "yAxis": {
                        "type": "value",
                        "name": "销量",
                        "nameGap": 24,
                        "nameTextStyle": {
                            "color": "#123456",
                            "fontSize": 15,
                            "fontWeight": 700,
                        },
                    }
                }
            ),
        )
        axis = chart.coords[0].y_axes[0]
        assert axis.name_gap == 24.0
        assert axis.nameTextStyle()["color"] == "#123456"
        assert axis.nameFont().pixelSize() == 15
        assert axis.nameFont().weight() == 700


class TestCalendarNameMap:
    def _calendar(self, make, day=None, month=None):
        cal = {"range": "2026"}
        if day is not None:
            cal["dayLabel"] = day
        if month is not None:
            cal["monthLabel"] = month
        chart = _chart(
            make,
            {
                "animation": False,
                "calendar": cal,
                "series": [{"type": "heatmap", "data": []}],
            },
        )
        return next(c for c in chart.coords if isinstance(c, CalendarCoord))

    def test_default(self, make):
        coord = self._calendar(make)
        assert coord._weekday_label_rows()[0] == "周一"

    def test_day_name_map_array_is_sunday_first(self, make):
        names = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
        coord = self._calendar(make, day={"nameMap": names})
        rows = coord._weekday_label_rows()
        assert rows[0] == "MON"
        assert rows[2] == "WED"
        assert rows[4] == "FRI"

    def test_day_name_map_dict(self, make):
        coord = self._calendar(make, day={"nameMap": {1: "M", 3: "W", 5: "F"}})
        rows = coord._weekday_label_rows()
        assert rows[0] == "M"
        assert rows[2] == "W"
        assert rows[4] == "F"

    def test_month_name_map(self, make):
        names = [f"M{i}" for i in range(1, 13)]
        coord = self._calendar(make, month={"nameMap": names})
        assert coord._month_name(1) == "M1"
        assert coord._month_name(12) == "M12"

    def test_month_name_map_dict(self, make):
        coord = self._calendar(make, month={"nameMap": {2: "Feb"}})
        assert coord._month_name(2) == "Feb"
        assert coord._month_name(3) == "3月"


class TestLabelRotateAlign:
    def _ready(self, make, series: dict):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A", "B", "C"]},
                "yAxis": {"type": "value"},
                "series": [series],
            },
        )
        chart._render_to_painter()
        return chart.seriesRenderers[0]

    def _line(self, label: dict) -> dict:
        return {
            "type": "line",
            "name": "a",
            "mode": "lines+markers",
            "data": [1, 2, 3],
            "label": {"show": True, **label},
        }

    def test_default_label_bounds(self, make):
        renderer = self._ready(make, self._line({}))
        assert renderer._label_rects
        _index, rect, text = renderer._label_rects[0]
        assert text == "1"
        assert rect.height() > 0

    def test_rotate_expands_bounds(self, make):
        flat = self._ready(make, self._line({}))
        flat_rect = flat._label_rects[0][1]
        rotated = self._ready(make, self._line({"rotate": 60}))
        rotated_rect = rotated._label_rects[0][1]
        assert rotated_rect.width() > flat_rect.width() * 1.5

    def test_align_left_shifts_right(self, make):
        center = self._ready(make, self._line({}))
        left = self._ready(make, self._line({"align": "left"}))
        assert left._label_rects[0][1].center().x() > (
            center._label_rects[0][1].center().x()
        )

    def test_bar_rotate_bounds(self, make):
        flat = self._ready(
            make,
            {"type": "bar", "name": "b", "data": [1, 2, 3], "label": {"show": True}},
        )
        rotated = self._ready(
            make,
            {
                "type": "bar",
                "name": "b",
                "data": [1, 2, 3],
                "label": {"show": True, "rotate": 90},
            },
        )
        assert rotated._label_rects[0][1].width() > flat._label_rects[0][1].width()

    def test_heatmap_rotate_smoke(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A", "B"]},
                "yAxis": {"type": "category", "data": ["a", "b"]},
                "series": [
                    {
                        "type": "heatmap",
                        "name": "h",
                        "data": [["A", "a", 1], ["B", "b", 2]],
                        "label": {"show": True, "rotate": 45},
                    }
                ],
            },
        )
        chart._render_to_painter()  # 不抛即通过
        assert chart.seriesRenderers[0].labelShown() is True


class TestVisualMapCalculable:
    def _vm(self, make, calculable=True):
        chart = _chart(
            make,
            _base(
                {
                    "visualMap": {
                        "min": 0,
                        "max": 100,
                        "calculable": calculable,
                        "orient": "vertical",
                    }
                }
            ),
        )
        return chart, chart._component("visualMap")

    def test_flag(self, make):
        _chart_obj, vm = self._vm(make, True)
        assert vm.calculable is True
        _chart_obj, vm = self._vm(make, False)
        assert vm.calculable is False

    def test_handles_inside_bar(self, make):
        _chart_obj, vm = self._vm(make)
        lo, hi = vm._handle_points()
        assert vm._bar.contains(lo)
        assert vm._bar.contains(hi)
        assert hi.y() < lo.y()  # 竖直：max 在上

    def test_drag_narrows_range(self, make):
        _chart_obj, vm = self._vm(make)
        lo, _hi = vm._handle_points()
        assert vm.onMousePress(lo) is True
        assert vm._drag == "min"
        # 往上拖 → min 增大
        vm.onMouseMove(QPointF(lo.x(), lo.y() - 20))
        assert vm.min > 0
        assert vm.onMouseRelease(lo) is True
        assert vm._drag is None

    def test_disabled_when_not_calculable(self, make):
        _chart_obj, vm = self._vm(make, False)
        lo, _hi = vm._handle_points()
        assert vm.onMousePress(lo) is False

    def test_press_far_away_ignored(self, make):
        _chart_obj, vm = self._vm(make)
        assert vm.onMousePress(QPointF(vm._bar.center().x(), vm._bar.center().y())) is False


class TestDataZoomLockAndFilterMode:
    def _zoom(self, make, extra: dict):
        chart = _chart(
            make,
            _base({"dataZoom": [{"type": "inside", **extra}]}),
        )
        return chart._component("dataZoom")

    def test_zoom_lock(self, make):
        zoom = self._zoom(make, {"zoomLock": True})
        assert zoom.zoom_lock is True
        # 锁定后滚轮不缩放（早退，不读事件）
        assert zoom.onWheel(object()) is False

    def test_zoom_lock_default_off(self, make):
        assert self._zoom(make, {}).zoom_lock is False

    def test_filter_mode_default_and_none(self, make):
        assert self._zoom(make, {}).filter_mode == "filter"
        # "none" 未实现 → 留告警并按 filter 处理（这里只钉解析结果与告警路径）
        assert self._zoom(make, {"filterMode": "none"}).filter_mode == "none"
        # 非法值回退 filter
        assert self._zoom(make, {"filterMode": "weird"}).filter_mode == "filter"


class TestMultiInstance:
    """``title`` / ``legend`` / ``grid`` 的数组写法（多实例）。"""

    @staticmethod
    def _two_series():
        return [
            {"type": "line", "name": "alpha", "data": [1, 2]},
            {"type": "line", "name": "beta", "data": [2, 1]},
        ]

    def test_titles(self, make):
        chart = _chart(
            make,
            _base(
                {
                    "title": [{"text": "顶部"}, {"text": "底部", "bottom": 0}],
                }
            ),
        )
        assert [t.text for t in chart.titles] == ["顶部", "底部"]
        assert chart.title is chart.titles[0]
        content = chart._content_rect()
        assert content.top() > 0
        assert content.bottom() < chart.height()
        chart._render_to_painter()  # 两个标题都画，不抛

    def test_legends(self, make):
        chart = _chart(
            make,
            _base(
                {
                    "legend": [
                        {"data": ["alpha"], "top": 0},
                        {"data": ["beta"], "bottom": 0},
                    ],
                    "series": self._two_series(),
                }
            ),
        )
        assert [[n for n, _ in lg._items] for lg in chart.legends] == [
            ["alpha"],
            ["beta"],
        ]
        assert chart.legend is chart.legends[0]
        chart._layout_all(force=True)
        for legend in chart.legends:
            assert chart.legendAt(legend.rect.center()) is legend
        chart._render_to_painter()

    def test_two_grids(self, make):
        option = {
            "animation": False,
            "grid": [
                {"left": 50, "right": "52%", "top": 30, "bottom": 40},
                {"left": "55%", "right": 20, "top": 30, "bottom": 40},
            ],
            "xAxis": [
                {"type": "category", "data": ["A", "B"], "gridIndex": 0},
                {"type": "category", "data": ["C", "D"], "gridIndex": 1},
            ],
            "yAxis": [
                {"type": "value", "gridIndex": 0},
                {"type": "value", "gridIndex": 1, "position": "right"},
            ],
            "series": [
                {"type": "line", "name": "g0", "data": [1, 2], "gridIndex": 0},
                {
                    "type": "bar",
                    "name": "g1",
                    "data": [100, 200],
                    "xAxisIndex": 1,
                    "yAxisIndex": 1,
                },
            ],
        }
        chart = _chart(make, option)
        grids = [c for c in chart.coords if isinstance(c, GridCoord)]
        assert len(grids) == 2
        assert not grids[0].plot.intersects(grids[1].plot)
        assert [a.grid_index for a, _h, _p in grids[0]._axis_sides()] == [0, 0]
        assert [a.grid_index for a, _h, _p in grids[1]._axis_sides()] == [1, 1]

        view0 = chart.coordFor({"xAxisIndex": 0})
        view1 = chart.coordFor({"xAxisIndex": 1, "yAxisIndex": 1})
        assert view0.x_axis.grid_index == 0
        assert view1.x_axis.grid_index == 1
        assert view1.plot == grids[1].plot
        # 数值轴范围按网格过滤（g1 的 200 不能算到 g0 头上）
        assert grids[1].y_axis.vmax >= 200
        assert grids[0].y_axis.vmax < 100
        # 柱几何落在自己的网格里
        bar = chart.seriesRenderers[1]
        assert all(grids[1].plot.adjusted(-1, -1, 1, 1).contains(b["rect"]) for b in bar._bars)
        chart._render_to_painter()

    def test_single_grid_default(self, make):
        chart = _chart(make)
        assert len([c for c in chart.coords if isinstance(c, GridCoord)]) == 1


class TestMultiGridInteractions:
    """图表级交互在多网格下的归属（tooltip / dataZoom / brush）。"""

    @staticmethod
    def _option(extra=None):
        option = {
            "animation": False,
            "tooltip": {"trigger": "axis"},
            "grid": [
                {"left": 50, "right": "52%", "top": 40, "bottom": 50},
                {"left": "55%", "right": 30, "top": 40, "bottom": 50},
            ],
            "xAxis": [
                {"type": "category", "data": ["A", "B"], "gridIndex": 0},
                {"type": "category", "data": ["C", "D"], "gridIndex": 1},
            ],
            "yAxis": [
                {"type": "value", "gridIndex": 0},
                {"type": "value", "gridIndex": 1, "position": "right"},
            ],
            "series": [
                {
                    "type": "line",
                    "name": "左",
                    "data": [1, 2],
                    "xAxisIndex": 0,
                    "yAxisIndex": 0,
                },
                {
                    "type": "bar",
                    "name": "右",
                    "data": [5, 2],
                    "xAxisIndex": 1,
                    "yAxisIndex": 1,
                },
            ],
        }
        option.update(extra or {})
        return option

    @staticmethod
    def _grids(chart):
        return [c for c in chart.coords if isinstance(c, GridCoord)]

    def test_axis_tooltip_targets_hovered_grid(self, make):
        chart = _chart(make, self._option())
        grids = self._grids(chart)
        chart._update_tooltip(grids[1].plot.center())
        assert chart.tooltip.active is True
        assert chart.tooltip._coord is grids[1]
        names = [row[1] for row in chart.tooltip._lines if row[1]]
        assert "右" in names
        assert "左" not in names
        assert [r.name for r, _hit in chart._axis_hover] == ["右"]
        assert chart.tooltip._axis_label in ("C", "D")

    def test_filter_mode_none_keeps_series_data(self, make):
        chart = _chart(
            make,
            self._option(
                {
                    "dataZoom": [
                        {
                            "type": "inside",
                            "start": 0,
                            "end": 50,
                            "filterMode": "none",
                        }
                    ]
                }
            ),
        )
        grids = self._grids(chart)
        zoom = chart._component("dataZoom")
        assert zoom.filter_mode == "none"
        # 不物理删除数据：类目轴窗口化，系列 data 仍是全量
        assert len(chart.seriesRenderers[0].data()) == 2
        assert grids[0].x_axis.categories == ["A"]

    def test_long_labels_reserve_margin_on_second_grid(self, make):
        option = self._option(
            {
                "grid": [
                    {"left": 30, "right": "55%", "top": 30, "bottom": 40},
                    {"left": 10, "right": 90, "top": 30, "bottom": 40},
                ],
                "xAxis": [
                    {"type": "category", "data": ["A", "B"], "gridIndex": 0},
                    {"type": "category", "data": ["C", "D"], "gridIndex": 1},
                ],
                "yAxis": [
                    {"type": "value", "gridIndex": 0},
                    {"type": "value", "gridIndex": 1, "position": "left"},
                ],
                "series": [
                    {"type": "line", "name": "左", "data": [1, 2]},
                    {
                        "type": "bar",
                        "name": "右",
                        "data": [1234567, 7654321],
                        "xAxisIndex": 1,
                        "yAxisIndex": 1,
                    },
                ],
            }
        )
        chart = _chart(make, option)
        grids = self._grids(chart)
        need = grids[1]._axis_label_extent(grids[1].y_axis, True)
        assert need > 40.0  # 长数值标签确实需要更多空间
        assert grids[1].m_left >= need - 1.0

    def test_datazoom_window_applies_to_all_grids(self, make):
        chart = _chart(
            make,
            self._option({"dataZoom": [{"type": "inside", "start": 0, "end": 50}]}),
        )
        grids = self._grids(chart)
        assert len(grids[0].x_axis.categories) == 1
        assert len(grids[1].x_axis.categories) == 1
        assert grids[0].x_axis.categories == ["A"]
        assert grids[1].x_axis.categories == ["C"]

    def test_brush_selects_on_second_grid(self, make):
        chart = _chart(make, self._option({"brush": {"type": "rect"}}))
        grids = self._grids(chart)
        brush = chart._component("brush")
        plot = grids[1].plot
        start = QPointF(plot.left() + 2, plot.top() + 2)
        end = QPointF(plot.right() - 2, plot.bottom() - 2)
        assert brush.onMousePress(start) is True
        assert brush._coord is grids[1]
        brush.onMouseMove(end)
        assert brush.onMouseRelease(end) is True
        assert {item["series"] for item in brush.selected_items} == {"右"}
        assert brush._rect is not None  # select 模式保留选框

    @staticmethod
    def _wheel(pos):
        point = QPointF(pos)
        return QWheelEvent(
            point,
            point,
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

    def test_wheel_zoom_on_second_grid(self, make):
        chart = _chart(
            make,
            self._option({"dataZoom": [{"type": "inside"}]}),
        )
        grids = self._grids(chart)
        zoom = chart._component("dataZoom")
        assert zoom.onWheel(self._wheel(grids[1].plot.center())) is True
        assert zoom.start > 0.0 or zoom.end < 100.0

    def test_pan_uses_started_grid_plot(self, make):
        chart = _chart(
            make,
            self._option({"dataZoom": [{"type": "inside"}], "tooltip": {}}),
        )
        grids = self._grids(chart)
        chart.setDragMode("pan")  # 默认 zoom 模式会把拖拽让给框选
        zoom = chart._component("dataZoom")
        start = QPointF(grids[1].plot.center())
        assert zoom.onMousePress(start) is True
        assert zoom._pan_plot == grids[1].plot
        zoom.onMouseMove(QPointF(start.x() + 20, start.y()))
        assert zoom.onMouseRelease(start) is True
        assert zoom._pan_plot is None

    def test_brush_outside_plot_does_not_select(self, make):
        chart = _chart(make, self._option({"brush": {"type": "rect"}}))
        grids = self._grids(chart)
        brush = chart._component("brush")
        # 两网格之间的空白处：不接管、不产生选区
        gap = QPointF(
            (grids[0].plot.right() + grids[1].plot.left()) / 2,
            grids[0].plot.center().y(),
        )
        assert brush.onMousePress(gap) is False


class TestVisualMapPiecewise:
    def _vm(self, make, extra=None):
        option = _base(
            {
                "visualMap": {
                    "type": "piecewise",
                    "pieces": [
                        {"min": 0, "max": 50, "label": "低", "color": "#aaaaaa"},
                        {"min": 50, "max": 80, "label": "中", "color": "#bbbbbb"},
                        {"min": 80, "max": 100, "label": "高", "color": "#cccccc"},
                    ],
                    **(extra or {}),
                }
            }
        )
        chart = _chart(make, option)
        return chart, chart._component("visualMap")

    def test_flag_and_pieces(self, make):
        _chart_obj, vm = self._vm(make)
        assert vm.piecewise is True
        assert len(vm.pieces()) == 3
        assert len(vm._piece_rects) == 3
        assert vm.reserveRight() == 90.0

    def test_piece_predicates(self, make):
        _chart_obj, vm = self._vm(
            make,
            {
                "pieces": [
                    {"lt": 20, "color": "#111111"},
                    {"gte": 20, "lt": 60, "color": "#222222"},
                    {"gte": 60, "color": "#333333"},
                ]
            },
        )
        assert vm.mapColor(10).name() == "#111111"
        assert vm.mapColor(20).name() == "#222222"
        assert vm.mapColor(59.9).name() == "#222222"
        assert vm.mapColor(60).name() == "#333333"

    def test_out_of_range_color(self, make):
        _chart_obj, vm = self._vm(
            make,
            {"pieces": [{"min": 0, "max": 50, "color": "#aaaaaa"}],
             "outOfRange": {"color": "#123123"}},
        )
        assert vm.mapColor(10).name() == "#aaaaaa"
        assert vm.mapColor(90).name() == "#123123"

    def test_map_color_by_piece(self, make):
        _chart_obj, vm = self._vm(make)
        assert vm.mapColor(30).name() == "#aaaaaa"
        assert vm.mapColor(60).name() == "#bbbbbb"
        assert vm.mapColor(90).name() == "#cccccc"
        # 不在任何分段 → 中性色
        assert vm.mapColor(120).name() == QColor(T("color.bg.muted")).name()

    def test_horizontal_layout(self, make):
        _chart_obj, vm = self._vm(make, {"orient": "horizontal"})
        assert vm.reserveBottom() == 36.0
        assert len(vm._piece_rects) == 3
        # 同一行：y 相同、x 递增
        ys = {round(box[0].y(), 2) for box in vm._piece_rects}
        xs = [box[0].x() for box in vm._piece_rects]
        assert len(ys) == 1
        assert xs == sorted(xs)

    def test_paint_smoke(self, make):
        chart, _vm = self._vm(make)
        chart._render_to_painter()


class TestAxisPointerStyle:
    def _tooltip(self, make, extra: dict):
        chart = _chart(make, _base({"tooltip": {"axisPointer": extra}}))
        chart.tooltip._axis_label = "2026-10"
        return chart.tooltip

    def test_label_formatter_template(self, make):
        tooltip = self._tooltip(make, {"label": {"formatter": "{value} 月"}})
        assert tooltip.axisLabelText() == "2026-10 月"

    def test_label_formatter_callable(self, make):
        tooltip = self._tooltip(
            make, {"label": {"formatter": lambda v: f"[{v}]"}}
        )
        assert tooltip.axisLabelText() == "[2026-10]"

    def test_label_hidden(self, make):
        tooltip = self._tooltip(make, {"label": {"show": False}})
        assert tooltip.axisLabelText() == ""

    def test_line_style_parsed(self, make):
        tooltip = self._tooltip(make, {"lineStyle": {"color": "#ff0000", "width": 2}})
        assert tooltip.axisPointerLineStyle()["color"] == "#ff0000"
