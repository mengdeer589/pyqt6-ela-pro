"""甘特图：时间范围 / 自动类目 / 进度 / 依赖 / 命中 / 拖动改期。"""

from __future__ import annotations

from datetime import datetime

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QContextMenuEvent, QMouseEvent

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts._tokens import T
from pyqt6_ela_pro.charts._utils import parse_color
from pyqt6_ela_pro.charts.axes import AxisModel, _ms_to_dt, _to_timestamp

TASKS = [
    {
        "name": "需求梳理",
        "start": "2026-11-02",
        "end": "2026-11-06",
        "progress": 1.0,
    },
    {
        "name": "方案设计",
        "start": "2026-11-06",
        "end": "2026-11-10",
        "progress": 0.8,
        "dependencies": ["需求梳理"],
    },
    {
        "name": "开发",
        "start": "2026-11-10",
        "end": "2026-11-20",
        "progress": 0.4,
        "dependencies": ["方案设计"],
        "itemStyle": {"color": "#e67700"},
    },
    {
        "name": "评审",
        "start": "2026-11-24",
        "milestone": True,
        "dependencies": ["开发"],
    },
]


def _chart(make, tasks=None, series_extra=None, **option) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(960, 460)
    series = {
        "type": "gantt",
        "name": "计划",
        "data": [
            dict(item) if isinstance(item, dict) else list(item)
            for item in (tasks or TASKS)
        ],
        "editable": True,
        "snap": "day",
        "todayLine": {"show": True, "date": "2026-11-18"},
    }
    series.update(series_extra or {})
    opt = {
        "animation": False,
        "tooltip": {"trigger": "item"},
        "xAxis": {"type": "time"},
        "yAxis": {"type": "category", "inverse": True},
        "series": [series],
    }
    opt.update(option)
    chart.setOption(opt)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _renderer(chart):
    return chart.seriesRenderers[0]


def _mouse(etype, pos, chart, button=Qt.MouseButton.LeftButton, buttons=None):
    return QMouseEvent(
        etype,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        button,
        buttons if buttons is not None else button,
        Qt.KeyboardModifier.NoModifier,
    )


def _press(chart, pos) -> None:
    chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos, chart))


def _move(chart, pos, buttons=Qt.MouseButton.LeftButton) -> None:
    chart.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, pos, chart, Qt.MouseButton.NoButton, buttons)
    )


def _release(chart, pos) -> None:
    chart.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pos, chart))


def _drag(chart, start, end) -> None:
    _press(chart, start)
    _move(chart, end)
    _release(chart, end)


class TestLayout:
    def test_time_axis_covers_start_and_end(self, qapp, make):
        chart = _chart(make)
        axis = chart.primaryCoord().x_axis
        assert axis.is_time is True
        assert axis.vmin <= AxisModel.toNumber("2026-11-02")
        assert axis.vmax >= AxisModel.toNumber("2026-11-24")

    def test_auto_categories_from_names(self, qapp, make):
        chart = _chart(make)
        assert chart.primaryCoord().y_axis.categories == [
            "需求梳理",
            "方案设计",
            "开发",
            "评审",
        ]

    def test_explicit_category_order_wins(self, qapp, make):
        chart = _chart(
            make,
            yAxis={
                "type": "category",
                "data": ["开发", "需求梳理", "方案设计", "评审"],
            },
        )
        renderer = _renderer(chart)
        rows = {item["name"]: item["row_local"] for item in renderer._items}
        assert rows["开发"] == 0
        assert rows["需求梳理"] == 1

    def test_y_labels_follow_top_down_category_order(self, qapp, make):
        chart = _chart(make)
        coord = chart.primaryCoord()
        positions = coord._axis_positions(coord.y_axis, True)
        assert [label for _x, _y, label, _i in positions] == [
            "需求梳理",
            "方案设计",
            "开发",
            "评审",
        ]
        ys = [y for _x, y, _label, _i in positions]
        assert ys == sorted(ys)
        renderer = _renderer(chart)
        assert [item["y"] for item in renderer._items] == pytest.approx(ys)

    def test_progress_rect_ratio(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        first = renderer._items[0]
        third = renderer._items[2]
        assert first["progress_rect"].width() == pytest.approx(first["rect"].width())
        assert third["progress_rect"].width() == pytest.approx(
            third["rect"].width() * 0.4
        )

    def test_milestone_uses_diamond_geometry(self, qapp, make):
        chart = _chart(make)
        item = _renderer(chart)._items[3]
        assert item["milestone"] is True
        assert item["milestone_pt"] is not None
        assert item["rect"].width() == pytest.approx(item["rect"].height())

    def test_zero_duration_is_milestone(self, qapp, make):
        chart = _chart(
            make,
            tasks=[{"name": "A", "start": "2026-11-02", "end": "2026-11-02"}],
        )
        assert _renderer(chart)._items[0]["milestone"] is True

    def test_dependencies_resolve(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        assert renderer._items[1]["deps"] == ["需求梳理"]
        assert renderer._find_dep("需求梳理") is renderer._items[0]

    def test_invalid_items_are_skipped(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                {"name": "坏数据", "start": "not-a-date", "end": "also-bad"},
                {"name": "正常", "start": "2026-11-02", "end": "2026-11-03"},
            ],
        )
        assert len(_renderer(chart)._items) == 1

    def test_iso_values_keep_string_shape(self, qapp, make):
        chart = _chart(make)
        data = chart.getOption()["series"][0]["data"]
        assert isinstance(data[0]["start"], str)
        assert isinstance(data[0]["end"], str)

    def test_list_and_value_shorthand_progress(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                ["2026-11-02", "2026-11-06", 0.5],
                {"name": "B", "value": ["2026-11-07", "2026-11-09", 0.25]},
            ],
            yAxis={"type": "category", "data": ["A", "B"]},
        )
        renderer = _renderer(chart)
        assert renderer._items[0]["progress"] == pytest.approx(0.5)
        assert renderer._items[1]["progress"] == pytest.approx(0.25)
        assert renderer._items[0]["progress_rect"].width() == pytest.approx(
            renderer._items[0]["rect"].width() * 0.5
        )

    def test_cross_series_dependency_by_name(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(900, 420)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "time"},
                "yAxis": {"type": "category", "data": ["A", "B"]},
                "series": [
                    {
                        "type": "gantt",
                        "name": "左",
                        "data": [
                            {"name": "A", "start": "2026-11-02", "end": "2026-11-05"}
                        ],
                    },
                    {
                        "type": "gantt",
                        "name": "右",
                        "data": [
                            {
                                "name": "B",
                                "start": "2026-11-06",
                                "end": "2026-11-09",
                                "dependencies": ["A"],
                            }
                        ],
                    },
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        right = chart.seriesRenderers[1]
        left = chart.seriesRenderers[0]
        assert right._find_dep("A") is left._items[0]


class TestProgressLabel:
    def test_background_follows_visible_region(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                {
                    "name": "满进度",
                    "start": "2026-11-02",
                    "end": "2026-11-05",
                    "progress": 1.0,
                },
                {
                    "name": "零进度",
                    "start": "2026-11-02",
                    "end": "2026-11-05",
                    "progress": 0.0,
                },
            ],
        )
        renderer = _renderer(chart)
        items = {item["name"]: item for item in renderer._items}
        full = items["满进度"]
        fill, dx = renderer._label_background(
            full, full["rect"], parse_color(full["color"]), 1.0, 24.0
        )
        assert fill.alpha() == 255
        assert dx == 0.0
        empty = items["零进度"]
        base, _dx = renderer._label_background(
            empty, empty["rect"], parse_color(empty["color"]), 1.0, 24.0
        )
        # 0% 时进度填充不可见，标签实际落在低透明度底轨上
        assert base.alpha() < 255


class TestThemeColors:
    def test_status_color_alpha_scales_with_progress(self, qapp, make):
        """令牌自带 alpha 必须与 item/progress alpha 相乘，不能被压满。"""
        chart = _chart(
            make,
            tasks=[
                {
                    "name": "半透明",
                    "status": "todo",
                    "start": "2026-11-02",
                    "end": "2026-11-12",
                    "progress": 0.5,
                }
            ],
            series_extra={
                "statusColors": {"todo": "rgba(0, 0, 0, 0.5)"},
                "progress": {"show": True},
            },
        )
        renderer = _renderer(chart)
        item = renderer._items[0]
        image = chart.grab().toImage()
        dpr = image.devicePixelRatio()
        rect = item["rect"]
        y = round(rect.center().y() * dpr)
        fill = image.pixelColor(round((rect.left() + rect.width() * 0.25) * dpr), y)
        base = image.pixelColor(round((rect.left() + rect.width() * 0.75) * dpr), y)
        bg = parse_color(T("color.bg.base", chart))
        expected_base = round(bg.red() * (1.0 - 0.5 * 0.35))
        expected_fill = round(expected_base * (1.0 - 0.5))
        assert abs(fill.red() - expected_fill) <= 8, (
            f"进度填充 alpha 被压平: {fill.name()} != {expected_fill}"
        )
        assert abs(base.red() - expected_base) <= 8, (
            f"底轨 alpha 未乘令牌 alpha: {base.name()} != {expected_base}"
        )

    def test_status_colors_follow_chart_theme(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                {
                    "name": "完成",
                    "status": "done",
                    "start": "2026-11-02",
                    "end": "2026-11-04",
                },
                {
                    "name": "进行中",
                    "status": "doing",
                    "start": "2026-11-04",
                    "end": "2026-11-07",
                },
                {
                    "name": "自定义",
                    "status": "done",
                    "start": "2026-11-07",
                    "end": "2026-11-09",
                    "itemStyle": {"color": "#ff0000"},
                },
            ],
            series_extra={
                "statusColors": {
                    "done": "color.primary",
                    "doing": "color.warning",
                }
            },
        )
        chart.setChartTheme("matlab")
        chart._layout_all(force=True)
        renderer = _renderer(chart)
        assert (
            renderer._items[0]["color"].name()
            == parse_color(T("color.primary", chart)).name()
        )
        assert (
            renderer._items[1]["color"].name()
            == parse_color(T("color.warning", chart)).name()
        )
        assert renderer._items[2]["color"].name() == "#ff0000"
        before = [item["color"].name() for item in renderer._items[:2]]

        chart.setChartTheme("ggplot2")
        chart._layout_all(force=True)
        renderer = _renderer(chart)
        after = [item["color"].name() for item in renderer._items[:2]]
        assert after != before
        assert renderer._items[2]["color"].name() == "#ff0000"


class TestHitAndTooltip:
    def test_hit_returns_task_color_and_rows(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        item = renderer._items[2]
        hit = renderer.hitTest(item["rect"].center())
        assert hit is not None
        assert hit["name"] == "开发"
        assert hit["dataIndex"] == 2
        assert hit["color"].isValid()
        labels = [row[0] for row in hit["rows"]]
        assert labels == ["开始", "结束", "工期", "进度"]

    def test_hit_outside_plot_returns_none(self, qapp, make):
        chart = _chart(make)
        assert _renderer(chart).hitTest(QPointF(2, 2)) is None

    def test_milestone_hit(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        item = renderer._items[3]
        hit = renderer.hitTest(item["milestone_pt"])
        assert hit is not None
        assert hit["name"] == "评审"

    def test_value_at_index_has_axis_text(self, qapp, make):
        chart = _chart(make)
        info = _renderer(chart).valueAtIndex(0)
        assert info is not None
        assert "→" in info["axisText"]

    def test_axis_tooltip_uses_axis_text(self, qapp, make):
        chart = _chart(make, tooltip={"trigger": "axis"})
        item = _renderer(chart)._items[0]
        _move(chart, item["rect"].center(), Qt.MouseButton.NoButton)
        rows = [(name, text) for _color, name, text in chart.tooltip._lines if name]
        assert ("计划", "2026-11-02 → 2026-11-06") in rows

    def test_row_window_offset_maps_value_at_index(self, qapp, make):
        chart = _chart(make)
        axis = chart.primaryCoord().y_axis
        axis.categories = ["开发", "评审"]
        axis.setWindowOffset(2)
        # valueAtIndex 收全量下标（与 hitTest / click params 一致）
        info = _renderer(chart).valueAtIndex(2)
        assert info is not None
        assert info["name"] == "开发"


class TestDrag:
    def test_drag_moves_task_and_emits(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        item = renderer._items[0]
        before_start = item["start"]
        before_end = item["end"]
        events = []
        chart.ganttTaskChanged.connect(events.append)
        zoom = chart._component("dataZoom")
        window = (zoom.start, zoom.end) if zoom is not None else None

        _drag(chart, item["rect"].center(), item["rect"].center() + QPointF(40, 0))

        chart._layout_all(force=True)
        after = renderer._items[0]
        assert after["start"] > before_start
        assert after["end"] > before_end
        assert after["end"] - after["start"] == before_end - before_start
        assert len(events) == 1
        assert events[0]["mode"] == "move"
        assert events[0]["name"] == "需求梳理"
        if zoom is not None:
            assert (zoom.start, zoom.end) == window

    def test_drag_on_empty_plot_still_pans(self, qapp, make):
        chart = _chart(make)
        zoom = chart._component("dataZoom")
        assert zoom is not None
        before = (zoom.start, zoom.end)
        plot = chart.primaryCoord().plot
        start = QPointF(plot.right() - 4, plot.bottom() - 4)
        _drag(chart, start, start + QPointF(-60, 0))
        assert (zoom.start, zoom.end) != before

    def test_resize_right_edge_only_changes_end(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        item = renderer._items[2]
        before_start, before_end = item["start"], item["end"]
        edge = QPointF(item["rect"].right() - 2, item["rect"].center().y())
        events = []
        chart.ganttTaskChanged.connect(events.append)
        _drag(chart, edge, edge + QPointF(-50, 0))
        chart._layout_all(force=True)
        after = renderer._items[2]
        assert after["start"] == before_start
        assert after["end"] < before_end
        assert events and events[0]["mode"] == "resize-end"

    def test_resize_start_only_changes_start(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        item = renderer._items[2]
        before_start, before_end = item["start"], item["end"]
        edge = QPointF(item["rect"].left() + 2, item["rect"].center().y())
        _drag(chart, edge, edge + QPointF(40, 0))
        chart._layout_all(force=True)
        after = renderer._items[2]
        assert after["start"] > before_start
        assert after["end"] == before_end

    def test_snap_day_lands_on_midnight(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        item = renderer._items[0]
        _drag(chart, item["rect"].center(), item["rect"].center() + QPointF(40, 0))
        chart._layout_all(force=True)
        after = renderer._items[0]
        dt = _ms_to_dt(after["start"])
        assert (dt.hour, dt.minute, dt.second) == (0, 0, 0)

    def test_drag_is_clamped_to_axis_range(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        item = renderer._items[0]
        plot = chart.primaryCoord().plot
        _drag(
            chart,
            item["rect"].center(),
            QPointF(plot.right() + 400, item["rect"].center().y()),
        )
        chart._layout_all(force=True)
        after = renderer._items[0]
        assert after["end"] <= chart.primaryCoord().x_axis.vmax + 1e-6

    def test_click_without_drag_still_clicks(self, qapp, make):
        chart = _chart(make)
        item = _renderer(chart)._items[0]
        clicks = []
        changes = []
        chart.itemClicked.connect(clicks.append)
        chart.ganttTaskChanged.connect(changes.append)
        _press(chart, item["rect"].center())
        _release(chart, item["rect"].center())
        assert len(clicks) == 1
        assert changes == []

    def test_editable_false_does_not_change_data(self, qapp, make):
        chart = _chart(make, series_extra={"editable": False})
        item = _renderer(chart)._items[0]
        before = item["start"]
        _drag(chart, item["rect"].center(), item["rect"].center() + QPointF(50, 0))
        chart._layout_all(force=True)
        assert _renderer(chart)._items[0]["start"] == before

    def test_interaction_toggle_disables_drag(self, qapp, make):
        chart = _chart(make)
        chart.setInteractionEnabled("gantt", False)
        item = _renderer(chart)._items[0]
        before = item["start"]
        _drag(chart, item["rect"].center(), item["rect"].center() + QPointF(50, 0))
        chart._layout_all(force=True)
        assert _renderer(chart)._items[0]["start"] == before

    def test_cursor_shapes(self, qapp, make):
        chart = _chart(make)
        item = _renderer(chart)._items[2]
        _move(chart, item["rect"].center(), Qt.MouseButton.NoButton)
        assert chart.cursor().shape() == Qt.CursorShape.OpenHandCursor
        _move(
            chart,
            QPointF(item["rect"].right() - 2, item["rect"].center().y()),
            Qt.MouseButton.NoButton,
        )
        assert chart.cursor().shape() == Qt.CursorShape.SizeHorCursor
        _press(chart, item["rect"].center())
        _move(chart, item["rect"].center() + QPointF(10, 0))
        assert chart.cursor().shape() == Qt.CursorShape.ClosedHandCursor
        _release(chart, item["rect"].center() + QPointF(10, 0))

    def test_annotation_wins_over_gantt(self, qapp, make):
        chart = _chart(
            make,
            annotations=[
                {
                    "id": "note",
                    "x": "2026-11-10",
                    "y": "开发",
                    "text": "备注",
                    "ax": 20,
                    "ay": -20,
                }
            ],
        )
        item = _renderer(chart)._items[2]
        before = item["start"]
        comp = [c for c in chart._components if c.optionKey == "annotations"][0]
        _drag(chart, comp.box().center(), comp.box().center() + QPointF(30, 10))
        chart._layout_all(force=True)
        assert _renderer(chart)._items[2]["start"] == before

    def test_drag_long_task_keeps_duration(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                {"name": "长任务", "start": "2026-11-02", "end": "2026-12-12"},
                {"name": "短任务", "start": "2026-11-10", "end": "2026-11-12"},
            ],
        )
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 40})
        chart._layout_all(force=True)
        renderer = _renderer(chart)
        item = renderer._items[0]
        before_duration = item["end"] - item["start"]
        plot = chart.primaryCoord().plot
        pos = QPointF(plot.center().x(), item["rect"].center().y())
        _drag(chart, pos, pos + QPointF(30, 0))
        assert item["end"] - item["start"] == pytest.approx(before_duration)

    def test_milestone_moves_with_start_and_end(self, qapp, make):
        chart = _chart(make)
        renderer = _renderer(chart)
        item = renderer._items[3]
        before = item["start"]
        pt = item["milestone_pt"]
        _drag(chart, pt, pt + QPointF(50, 0))
        chart._layout_all(force=True)
        after = renderer._items[3]
        assert after["start"] > before
        assert after["end"] == after["start"]
        assert after["milestone"] is True

    def test_release_keeps_viewport(self, qapp, make):
        chart = _chart(make)
        item = _renderer(chart)._items[0]
        axis = chart.primaryCoord().x_axis
        before = (axis.vmin, axis.vmax)
        _drag(chart, item["rect"].center(), item["rect"].center() + QPointF(40, 0))
        assert (axis.vmin, axis.vmax) == before

    def test_datetime_input_keeps_datetime(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                {
                    "name": "A",
                    "start": datetime(2026, 11, 2),
                    "end": datetime(2026, 11, 6),
                },
                {"name": "B", "start": "2026-11-10", "end": "2026-11-12"},
            ],
        )
        item = _renderer(chart)._items[0]
        _drag(chart, item["rect"].center(), item["rect"].center() + QPointF(30, 0))
        data = chart.getOption()["series"][0]["data"]
        assert isinstance(data[0]["start"], datetime)


class TestProgressEditing:
    def test_drag_updates_progress_and_emits(self, qapp, make):
        chart = _chart(
            make,
            series_extra={"progress": {"show": True, "editable": True}},
        )
        item = _renderer(chart)._items[2]
        assert item["progress_handle"] is not None
        events = []
        chart.ganttProgressChanged.connect(events.append)
        start = item["progress_handle"].center()
        target = QPointF(
            item["rect"].left() + item["rect"].width() * 0.8,
            start.y(),
        )
        _press(chart, start)
        _move(chart, target)
        _release(chart, target)
        assert item["progress"] == pytest.approx(0.8, abs=0.02)
        data = chart.getOption()["series"][0]["data"]
        assert data[2]["progress"] == pytest.approx(0.8, abs=0.02)
        assert events
        assert events[0]["name"] == "开发"
        assert events[0]["progress"] == pytest.approx(0.8, abs=0.02)
        assert events[0]["prevProgress"] == pytest.approx(0.4)

    def test_handle_above_bar_keeps_edge_resize(self, qapp, make):
        chart = _chart(
            make,
            series_extra={"progress": {"show": True, "editable": True}},
        )
        renderer = _renderer(chart)
        item = renderer._items[2]
        assert item["progress_handle"].center().y() < item["rect"].top()
        assert renderer._drag_mode(item, item["rect"].topLeft()) == "resize-start"

    def test_progress_editable_without_task_drag(self, qapp, make):
        chart = _chart(
            make,
            series_extra={
                "editable": False,
                "progress": {"show": True, "editable": True},
            },
        )
        item = _renderer(chart)._items[2]
        start = item["progress_handle"].center()
        target = QPointF(
            item["rect"].left() + item["rect"].width() * 0.7,
            start.y(),
        )
        _press(chart, start)
        _move(chart, target)
        _release(chart, target)
        assert item["progress"] == pytest.approx(0.7, abs=0.02)


class TestTaskSignals:
    def test_click_double_and_context_menu(self, qapp, make):
        chart = _chart(make)
        item = _renderer(chart)._items[0]
        clicked, doubled, menu = [], [], []
        chart.ganttTaskClicked.connect(clicked.append)
        chart.ganttTaskDoubleClicked.connect(doubled.append)
        chart.ganttTaskContextMenuRequested.connect(menu.append)
        center = item["rect"].center()
        _press(chart, center)
        _release(chart, center)
        assert clicked and clicked[0]["name"] == "需求梳理"
        chart.mouseDoubleClickEvent(
            _mouse(QEvent.Type.MouseButtonDblClick, center, chart)
        )
        assert doubled and doubled[0]["dataIndex"] == 0
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            center.toPoint(),
            chart.mapToGlobal(center.toPoint()),
        )
        chart.contextMenuEvent(event)
        assert menu and menu[0]["name"] == "需求梳理"
        assert "globalPos" in menu[0]


class TestBaselineDeadline:
    def test_x_extent_and_item_geometry(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                {
                    "name": "A",
                    "start": "2026-11-02",
                    "end": "2026-11-06",
                    "progress": 0.5,
                    "baseline": {"start": "2026-10-30", "end": "2026-11-05"},
                    "deadline": "2026-11-20",
                },
                {
                    "name": "B",
                    "start": "2026-11-02",
                    "end": "2026-11-06",
                    "progress": 0.5,
                    "deadline": "2026-11-04",
                },
            ],
        )
        axis = chart.primaryCoord().x_axis
        assert axis.vmin <= _to_timestamp("2026-10-30")
        assert axis.vmax >= _to_timestamp("2026-11-20")
        items = {item["name"]: item for item in _renderer(chart)._items}
        item = items["A"]
        assert item["baseline_rect"] is not None
        assert item["baseline_overrun"] is not None
        assert item["deadline_x"] is not None
        assert item["overdue"] is False
        overdue = items["B"]
        assert overdue["overdue"] is True
        assert overdue["overdue_days"] == pytest.approx(2.0)

    def test_completed_task_is_not_overdue(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                {
                    "name": "A",
                    "start": "2026-11-02",
                    "end": "2026-11-06",
                    "progress": 1.0,
                    "deadline": "2026-11-04",
                }
            ],
        )
        item = _renderer(chart)._items[0]
        assert item["overdue"] is False

    def test_tooltip_rows_include_baseline_and_deadline(self, qapp, make):
        chart = _chart(
            make,
            tasks=[
                {
                    "name": "A",
                    "start": "2026-11-02",
                    "end": "2026-11-06",
                    "progress": 0.5,
                    "baseline": ["2026-11-01", "2026-11-05"],
                    "deadline": "2026-11-04",
                }
            ],
        )
        item = _renderer(chart)._items[0]
        hit = _renderer(chart).hitTest(item["rect"].center())
        labels = [row[0] for row in hit["rows"]]
        assert "基线" in labels
        assert "偏差" in labels
        assert "截止" in labels
        assert "逾期" in labels


class TestCriticalPath:
    def test_chain_marks_critical_and_slack(self, qapp, make):
        tasks = [
            {"name": "A", "start": "2026-11-01", "end": "2026-11-03"},
            {
                "name": "B",
                "start": "2026-11-03",
                "end": "2026-11-06",
                "dependencies": ["A"],
            },
            {
                "name": "C",
                "start": "2026-11-06",
                "end": "2026-11-09",
                "dependencies": ["B"],
            },
            {
                "name": "D",
                "start": "2026-11-02",
                "end": "2026-11-04",
                "dependencies": ["A"],
            },
        ]
        chart = _chart(make, tasks=tasks, series_extra={"criticalPath": {"show": True}})
        items = {item["name"]: item for item in _renderer(chart)._items}
        assert items["A"]["critical"] is True
        assert items["B"]["critical"] is True
        assert items["C"]["critical"] is True
        assert items["D"]["critical"] is False
        assert items["D"]["slack"] > 86400000.0

    def test_cycle_skips_critical_path(self, qapp, make):
        tasks = [
            {
                "name": "A",
                "start": "2026-11-01",
                "end": "2026-11-03",
                "dependencies": ["B"],
            },
            {
                "name": "B",
                "start": "2026-11-03",
                "end": "2026-11-06",
                "dependencies": ["A"],
            },
        ]
        chart = _chart(make, tasks=tasks, series_extra={"criticalPath": {"show": True}})
        assert all(not item["critical"] for item in _renderer(chart)._items)

class TestAxisPolish:
    """非工作日 / 月首线 / 今天列 / 月首标签 / y 轴省略。"""

    def test_weekend_dates_add_nonwork_days(self, qapp, make):
        chart = _chart(
            make,
            series_extra={
                "weekend": {"show": True, "dates": ["2026-11-18", "2026-11-16"]}
            },
        )
        renderer = _renderer(chart)
        assert renderer._is_nonwork(datetime(2026, 11, 18)) is True
        assert renderer._is_nonwork(datetime(2026, 11, 16)) is True
        assert renderer._is_nonwork(datetime(2026, 11, 17)) is False
        assert renderer._is_nonwork(datetime(2026, 11, 21)) is True  # 周六

    def test_weekend_dates_reject_garbage(self, qapp, make):
        chart = _chart(
            make,
            series_extra={"weekend": {"show": True, "dates": ["not-a-date", None, 1]}},
        )
        assert _renderer(chart)._nonwork_dates == frozenset()

    def test_month_lines_at_month_edges(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "time", "min": "2026-10-20", "max": "2026-12-20"},
        )
        coord = chart.coords[0]
        positions = _renderer(chart)._month_line_positions(coord)
        assert len(positions) == 2  # 11-01 / 12-01
        assert positions[0] < positions[1]
        assert coord.plot.left() <= positions[0] <= coord.plot.right()

    def test_month_lines_skip_short_span(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "time", "min": "2026-11-01", "max": "2026-11-20"},
        )
        assert _renderer(chart)._month_line_positions(chart.coords[0]) == []

    def test_month_line_can_be_disabled(self, qapp, make):
        chart = _chart(
            make,
            series_extra={"monthLine": {"show": False}},
            xAxis={"type": "time", "min": "2026-10-20", "max": "2026-12-20"},
        )
        assert _renderer(chart)._month_cfg["show"] is False

    def test_today_band_covers_one_day(self, qapp, make):
        chart = _chart(make)
        coord = chart.coords[0]
        rect = _renderer(chart)._today_band(coord)
        assert rect is not None
        x_axis = coord.x_axis
        one_day = x_axis.map(_to_timestamp("2026-11-19"), coord.plot.left(), coord.plot.right()) - x_axis.map(
            _to_timestamp("2026-11-18"), coord.plot.left(), coord.plot.right()
        )
        assert abs(rect.width() - one_day) <= 1.5

    def test_today_band_can_be_disabled(self, qapp, make):
        chart = _chart(
            make, series_extra={"todayLine": {"show": True, "date": "2026-11-18", "band": False}}
        )
        assert _renderer(chart)._today_band(chart.coords[0]) is None

    def test_month_first_axis_label(self, qapp, make):
        chart = _chart(
            make,
            xAxis={
                "type": "time",
                "min": "2026-10-20",
                "max": "2026-12-20",
                "splitNumber": 6,
                "axisLabel": {"formatter": "{MM}-{dd}", "monthFirst": True},
            },
        )
        axis = chart.coords[0].x_axis
        ticks = axis.ticks()
        labels = [axis.formatTickLabel(value, i) for i, value in enumerate(ticks)]
        assert any(text.endswith("月") for text in labels)
        first = next(text for text in labels if text.endswith("月"))
        assert first in ("11月", "12月")
