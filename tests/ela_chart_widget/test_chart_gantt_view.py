"""甘特 preferredHeight / 纵向滚动容器 / 自定义类目顺序。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import ElaGanttView
from pyqt6_ela_pro.charts.axes import _dt_to_ms

TASKS = [
    {"name": "需求", "start": "2026-11-02", "end": "2026-11-05", "progress": 1.0},
    {"name": "设计", "start": "2026-11-05", "end": "2026-11-09", "progress": 0.8},
    {"name": "接口", "start": "2026-11-09", "end": "2026-11-15", "progress": 0.5},
    {"name": "界面", "start": "2026-11-09", "end": "2026-11-16", "progress": 0.4},
    {"name": "测试", "start": "2026-11-16", "end": "2026-11-22", "progress": 0.0},
]


def _chart(make, tasks=None, **extra):
    chart = make(ElaChartWidget)
    chart.resize(900, 520)
    series = {"type": "gantt", "name": "计划", "data": tasks or TASKS}
    series.update(extra)
    chart.setOption(
        {
            "animation": False,
            "tooltip": {"trigger": "item"},
            "grid": {"left": 100},
            "xAxis": {"type": "time"},
            "yAxis": {"type": "category", "inverse": True},
            "series": [series],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _mouse(etype, pos, chart, button=Qt.MouseButton.LeftButton, buttons=None):
    return QMouseEvent(
        etype,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        button,
        buttons if buttons is not None else button,
        Qt.KeyboardModifier.NoModifier,
    )


def _tasks(count=40):
    base = date(2026, 11, 2)
    out = []
    for i in range(count):
        start = base + timedelta(days=i * 2)
        end = start + timedelta(days=3 + (i % 5))
        out.append(
            {
                "name": f"任务 {i + 1:02d}",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "progress": (i % 10) / 10,
            }
        )
    return out


def _view(make, tasks=None):
    view = make(ElaGanttView)
    view.resize(900, 500)
    view.setOption(
        {
            "animation": False,
            "tooltip": {"trigger": "item"},
            "grid": {"left": 110},
            "xAxis": {"type": "time"},
            "yAxis": {"type": "category", "inverse": True},
            "series": [
                {
                    "type": "gantt",
                    "name": "计划",
                    "data": tasks or _tasks(),
                    "editable": True,
                    "snap": "day",
                }
            ],
        }
    )
    view.show()
    QApplication.processEvents()
    view._refresh(view.topRow())
    return view


class TestRows:
    def test_explicit_category_order_still_wins(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(900, 520)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "time"},
                "yAxis": {"type": "category", "data": ["B", "A"]},
                "series": [
                    {
                        "type": "gantt",
                        "name": "计划",
                        "data": [
                            {"name": "A", "start": "2026-11-02", "end": "2026-11-04"},
                            {"name": "B", "start": "2026-11-05", "end": "2026-11-08"},
                        ],
                    }
                ],
            }
        )
        chart._layout_all(force=True)
        rows = {
            item["name"]: item["row_local"] for item in chart.seriesRenderers[0]._items
        }
        assert rows == {"A": 1, "B": 0}


class TestPreferredHeight:
    def test_plain_rows(self, qapp, make):
        chart = _chart(make)
        assert chart.preferredHeight() == 5 * 26 + 88
        assert chart.preferredHeight(rowHeight=30, padding=50) == 5 * 30 + 50


class TestGanttView:
    def test_scroll_window_and_scrollbar(self, qapp, make):
        view = _view(make)
        coord = view.chart().primaryCoord()
        full = getattr(coord.y_axis, "_all_categories", None) or coord.y_axis.categories
        assert len(full) == 40
        visible = view.visibleRows()
        assert 10 <= visible < len(full)
        assert view.chart()._component("dataZoom") is not None
        assert len(coord.y_axis.categories) == visible
        assert view._bar.maximum() == len(full) - visible

    def test_scroll_to_row(self, qapp, make):
        view = _view(make)
        full = (
            getattr(view.chart().primaryCoord().y_axis, "_all_categories", None)
            or view.chart().primaryCoord().y_axis.categories
        )
        view.scrollToRow(10)
        assert view.topRow() == 10
        assert view.chart().primaryCoord().y_axis.categories[0] == full[10]

    def test_wheel_scrolls_rows(self, qapp, make):
        view = _view(make)
        view.scrollToRow(10)
        before = view.topRow()
        plot = view.chart().primaryCoord().plot
        event = QWheelEvent(
            QPointF(plot.center()),
            QPointF(view.chart().mapToGlobal(plot.center().toPoint())),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(view.chart(), event)
        assert view.topRow() > before

    def test_row_height_changes_visible_rows(self, qapp, make):
        view = _view(make)
        before = view.visibleRows()
        view.setRowHeight(40)
        assert view.visibleRows() < before

    def test_task_changed_signal_is_forwarded(self, qapp, make):
        view = _view(make)
        chart = view.chart()
        events = []
        view.ganttTaskChanged.connect(events.append)
        item = chart.seriesRenderers[0]._items[1]  # 任务 02
        pos = item["rect"].center()
        chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos, chart))
        chart.mouseMoveEvent(
            _mouse(
                QEvent.Type.MouseMove,
                pos + QPointF(40, 0),
                chart,
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
            )
        )
        chart.mouseReleaseEvent(
            _mouse(QEvent.Type.MouseButtonRelease, pos + QPointF(40, 0), chart)
        )
        assert events and events[0]["name"] == "任务 02"


class TestViewToolbar:
    def test_toolbar_hidden_by_default(self, qapp, make):
        view = _view(make)
        assert view.toolbarVisible() is False
        view.setToolbarVisible(True)
        assert view.toolbarVisible() is True

    def test_scale_sets_time_window(self, qapp, make):
        view = _view(make)
        view.setScale("day")
        axis = view.chart().primaryCoord().x_axis
        span = float(axis.vmax) - float(axis.vmin)
        assert view.scale() == "day"
        assert 13.0 * 86400000 <= span <= 15.0 * 86400000
        assert view._scale_pivot.getCurrentIndex() == 1

    def test_scale_pivot_click(self, qapp, make):
        view = _view(make)
        view.setToolbarVisible(True)
        QApplication.processEvents()
        view._scale_pivot.pivotClicked.emit(2)
        assert view.scale() == "week"
        axis = view.chart().primaryCoord().x_axis
        assert float(axis.vmax) - float(axis.vmin) >= 50.0 * 86400000
        assert view._scale_pivot.getCurrentIndex() == 2

    def test_scale_pivot_full_range(self, qapp, make):
        view = _view(make)
        view.setToolbarVisible(True)
        view.setScale("day")
        view._scale_pivot.pivotClicked.emit(0)
        assert view.scale() == ""
        assert view._scale_pivot.getCurrentIndex() == 0

    def test_go_to_today_keeps_span(self, qapp, make):
        view = _view(make)
        view.setScale("day")
        axis = view.chart().primaryCoord().x_axis
        comp = view.chart()._component("dataZoom")
        before_pct = float(comp.end) - float(comp.start)
        view.goToToday()
        now = _dt_to_ms(datetime.now())
        assert float(axis.vmin) <= now <= float(axis.vmax)
        assert float(comp.end) - float(comp.start) == pytest.approx(
            before_pct, rel=0.02
        )

    def test_fit_rows_uses_available_height(self, qapp, make):
        view = _view(make, tasks=_tasks(8))
        view.fitRows()
        assert view.rowHeight() > 26.0
        assert view.visibleRows() == 8

    def test_scroll_preserves_x_window(self, qapp, make):
        view = _view(make)
        view.setScale("day")
        axis = view.chart().primaryCoord().x_axis
        before = (float(axis.vmin), float(axis.vmax))
        view._apply_window(5, view._total_rows)
        after = (float(axis.vmin), float(axis.vmax))
        assert after[0] == pytest.approx(before[0], rel=1e-3)
        assert after[1] == pytest.approx(before[1], rel=1e-3)

    def test_show_full_range(self, qapp, make):
        view = _view(make)
        view.setScale("month")
        view.showFullRange()
        assert view.scale() == ""
        axis = view.chart().primaryCoord().x_axis
        extent = axis._data_extent
        assert float(axis.vmin) <= extent[0] + 86400000
        assert float(axis.vmax) >= extent[1] - 86400000
