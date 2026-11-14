"""运行轨迹：纯模型聚合 + 独立面板。"""

from __future__ import annotations

from _qthelpers import wait_until as _wait_until

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.chat import (
    ElaChatRoleType,
    ElaChatStats,
    ElaChatTraceOptions,
    ElaChatTracePanel,
    ElaChatView,
    buildTraceRows,
)
from pyqt6_ela_pro.chat._theme import base_color
from pyqt6_ela_pro.tooltips import ElaToolTip


def _build_view(make, *, child_ok=True):
    view = make(ElaChatView)
    view.resize(760, 560)
    mid = view.beginMessage(ElaChatRoleType.Assistant)
    created = view.message(mid).created_at
    view.beginStep(mid)
    view.appendText(mid, "开始")
    view.addToolCall(
        mid,
        "delegate_task",
        '{"task": "查资料"}',
        "p1",
        startedAt=created + 0.2,
        durationMs=1800,
    )
    view.addToolCall(
        mid,
        "read",
        '{"path": "a.py"}',
        "c1",
        parentId="p1",
        startedAt=created + 0.5,
        durationMs=700,
    )
    view.setToolCallResult(mid, "c1", "内容" if child_ok else "失败", ok=child_ok)
    view.setToolCallResult(mid, "p1", "结论", ok=True)
    view.addToolCall(
        mid,
        "read",
        '{"path": "ok.py"}',
        "ok1",
        startedAt=created + 2.2,
        durationMs=300,
    )
    view.setToolCallResult(mid, "ok1", "ok", ok=True)
    view.setStepStats(
        mid,
        ElaChatStats(
            total_tokens=120,
            cost_usd=0.01,
            duration_ms=1500.0,
        ),
    )
    view.endMessage(mid)
    view.setMessageDuration(mid, 2200)
    return view, mid


def _click_row(qapp, panel, visual) -> None:
    canvas = panel._canvas
    pos = QPointF(120.0, visual.y + visual.height / 2.0)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        QPointF(canvas.mapToGlobal(pos.toPoint())),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)
    qapp.processEvents()


def _move_to(qapp, panel, visual) -> None:
    canvas = panel._canvas
    pos = QPointF(200.0, visual.y + visual.height / 2.0)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        pos,
        QPointF(canvas.mapToGlobal(pos.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, event)
    qapp.processEvents()


def _contrast(a, b) -> float:
    def channel(value: int) -> float:
        value = value / 255.0
        if value <= 0.03928:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    def luminance(color) -> float:
        return (
            0.2126 * channel(color.red())
            + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue())
        )

    first = luminance(a)
    second = luminance(b)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


class TestTraceModel:
    def test_tree_and_totals(self, qapp, make):
        view, mid = _build_view(make)
        result = buildTraceRows(view.messages())
        assert not result.isEmpty()
        assert len(result.rows) == 1
        turn = result.rows[0]
        assert turn.kind == "turn"
        assert turn.message_id == mid
        assert turn.tokens == 120
        assert turn.cost_usd == 0.01
        assert turn.children[0].kind == "response"
        assert turn.children[0].children[0].kind == "step"
        flat = result.flatten()
        tools = [row for row in flat if row.kind == "tool"]
        assert len(tools) == 3
        assert result.tool_count == 3
        parent = next(row for row in tools if row.part_id == "p1")
        child = next(row for row in tools if row.part_id == "c1")
        assert child.depth == parent.depth + 1
        assert parent.duration_ms == 1800
        assert parent.span_ms > 0
        assert turn.span_ms >= parent.start_ms + parent.span_ms

    def test_error_count_and_subtree_flag(self, qapp, make):
        view, _ = _build_view(make, child_ok=False)
        result = buildTraceRows(view.messages())
        assert result.error_count == 1
        assert any(row.isError for row in result.flatten())
        turn = result.rows[0]
        assert turn.error_below is True
        assert turn.children[0].error_below is True

    def test_empty(self):
        result = buildTraceRows([])
        assert result.isEmpty()
        assert result.flatten() == ()

    def test_restored_session(self, qapp, make):
        view, _ = _build_view(make)
        bundle = view.exportSession()
        other = make(ElaChatView)
        other.importSession(bundle, clear=True)
        result = buildTraceRows(other.messages())
        assert result.tool_count == 3
        assert result.rows[0].tokens == 120

    def test_user_turn_groups_assistant_responses(self, qapp, make):
        view = make(ElaChatView)
        first_user = view.addMessage(ElaChatRoleType.User, "第一个问题")
        for _ in range(2):
            mid = view.beginMessage(ElaChatRoleType.Assistant)
            call = view.addToolCall(mid, "read", "{}", None, durationMs=100)
            view.setToolCallResult(mid, call, "ok", ok=True)
            view.endMessage(mid)
            view.setMessageDuration(mid, 100)
        second_user = view.addMessage(ElaChatRoleType.User, "第二个问题")
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        call = view.addToolCall(mid, "read", "{}", None, durationMs=100)
        view.setToolCallResult(mid, call, "ok", ok=True)
        view.endMessage(mid)
        view.setMessageDuration(mid, 100)

        result = buildTraceRows(view.messages())
        assert len(result.rows) == 2
        assert result.rows[0].message_id == first_user
        assert len(result.rows[0].children) == 2
        assert all(row.kind == "response" for row in result.rows[0].children)
        assert result.rows[1].message_id == second_user
        assert len(result.rows[1].children) == 1
        assert result.rows[0].children[0].children[0].kind == "step"

    def test_long_span_is_clipped(self, qapp, make):
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        created = view.message(mid).created_at
        view.addToolCall(
            mid,
            "slow",
            "{}",
            "slow-1",
            startedAt=created + 0.1,
            durationMs=9_000_000,
        )
        view.addToolCall(
            mid,
            "fast",
            "{}",
            "fast-1",
            startedAt=created + 0.2,
            durationMs=300,
        )
        view.endMessage(mid)
        result = buildTraceRows(view.messages())
        slow = next(row for row in result.flatten() if row.part_id == "slow-1")
        assert slow.clipped is True
        assert slow.duration_ms == 9_000_000
        assert slow.span_ms <= result.clip_ms + 0.01
        assert result.clipped_count >= 1


class TestTracePanel:
    def test_panel_rows_and_filter(self, qapp, make):
        view, _ = _build_view(make, child_ok=False)
        panel = make(ElaChatTracePanel)
        panel.setView(view)
        assert panel.rows()
        all_count = len(panel.rows())
        panel.setFilter("errors")
        assert 0 < len(panel.rows()) < all_count
        panel.setFilter("all")
        assert len(panel.rows()) == all_count

    def test_row_activation(self, qapp, make):
        view, mid = _build_view(make)
        panel = make(ElaChatTracePanel, view)
        panel.show()
        qapp.processEvents()
        hits = []
        panel.rowActivated.connect(hits.append)
        visual = next(
            item for item in panel._canvas.visualRows() if item.row.kind == "tool"
        )
        _click_row(qapp, panel, visual)
        assert hits == [mid]

    def test_empty_panel(self, qapp, make):
        view = make(ElaChatView)
        panel = make(ElaChatTracePanel, view)
        assert not panel.rows()
        assert not panel._scroll.isVisible()

    def test_options_toggle_live(self, qapp, make):
        view, _ = _build_view(make)
        panel = make(ElaChatTracePanel, view)
        panel.show()
        qapp.processEvents()
        panel.setOptions(ElaChatTraceOptions(effects=False, replay=False, tracks=False))
        assert panel.options().effects is False
        assert panel._trends.isVisibleTo(panel) is False
        assert panel._replay_button.isVisibleTo(panel) is False
        panel.setOption("view", "graph")
        assert panel._stack.currentWidget() is panel._graph_page
        assert panel._view_pivot.getCurrentIndex() == 1
        assert panel._graph_page._canvas is not None
        panel.setOption("view", "timeline")
        assert panel._stack.currentWidget() is panel._timeline_page
        assert panel._view_pivot.getCurrentIndex() == 0
        panel.setFilter("errors")
        assert panel._filter_pivot.getCurrentIndex() == 1
        panel.setFilter("all")
        assert panel._filter_pivot.getCurrentIndex() == 0

    def test_hover_uses_ela_tooltip(self, qapp, make):
        view, _ = _build_view(make)
        panel = make(ElaChatTracePanel, view)
        panel.show()
        qapp.processEvents()
        visual = next(
            item for item in panel._canvas.visualRows() if item.row.kind == "tool"
        )
        _move_to(qapp, panel, visual)
        tip = panel._canvas._hover_tooltip
        assert isinstance(tip, ElaToolTip)
        assert tip.isVisible() is True
        assert "耗时" in tip._label.text()
        panel._canvas.leaveEvent(QEvent(QEvent.Type.Leave))
        qapp.processEvents()
        assert tip.isVisible() is False

    def test_speed_menu_reaches_20(self, qapp, make):
        view, _ = _build_view(make)
        panel = make(ElaChatTracePanel, view)
        actions = panel._speed_menu.actions()
        values = [action.data() for action in actions]
        assert 20.0 in values
        action = next(action for action in actions if action.data() == 20.0)
        action.trigger()
        qapp.processEvents()
        assert panel.replaySpeed() == 20.0
        assert panel._speed_button.text() == "20×"

    def test_kind_palette_contrast(self, qapp, make):
        view, _ = _build_view(make)
        panel = make(ElaChatTracePanel, view)
        canvas = panel._canvas
        for mode in (ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark):
            canvas.applyTheme(mode)
            background = base_color(mode)
            for kind in (
                "tool",
                "response",
                "reasoning",
                "plan",
                "permission",
                "error",
            ):
                ratio = _contrast(canvas._colors[kind], background)
                assert ratio >= 3.0, (mode, kind, ratio)

    def test_replay_state(self, qapp, make):
        view, _ = _build_view(make)
        panel = make(ElaChatTracePanel, view)
        panel.show()
        qapp.processEvents()
        panel.startReplay()
        assert panel.isReplaying() is True
        qapp.processEvents()
        assert panel._canvas.playhead() is not None
        panel.stopReplay()
        assert panel.isReplaying() is False
        assert panel._canvas.playhead() is None

    def test_replay_speed_reaches_20(self, qapp, make):
        view, _ = _build_view(make)
        panel = make(ElaChatTracePanel, view)
        speeds = [panel.cycleReplaySpeed() for _ in range(8)]
        assert panel.replaySpeed() in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0)
        assert 20.0 in speeds

    def test_replay_continues_across_turns(self, qapp, make):
        view = make(ElaChatView)
        for index in range(2):
            view.addMessage(ElaChatRoleType.User, f"问题 {index}")
            mid = view.beginMessage(ElaChatRoleType.Assistant)
            created = view.message(mid).created_at
            call = view.addToolCall(
                mid,
                "read",
                "{}",
                None,
                startedAt=created + 0.01,
                durationMs=120,
            )
            view.setToolCallResult(mid, call, "ok", ok=True)
            view.setStepStats(mid, ElaChatStats(total_tokens=10, duration_ms=120))
            view.endMessage(mid)
            view.setMessageDuration(mid, 120)
        panel = make(ElaChatTracePanel, view)
        panel.show()
        qapp.processEvents()
        panel.setCurrentTurn(0)
        panel.startReplay()
        assert _wait_until(qapp, lambda: panel.currentTurn() == 1, timeout_ms=6000)
        assert _wait_until(qapp, lambda: not panel.isReplaying(), timeout_ms=6000)
        panel.stopReplay()

    def test_timeline_uses_canvas_not_per_row_widgets(self, qapp, make):
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        for index in range(80):
            view.addToolCall(mid, "read", '{"path": "a.py"}', f"t{index}")
        view.endMessage(mid)
        panel = make(ElaChatTracePanel, view)
        assert len(panel.rows()) >= 80
        assert len(panel.findChildren(QWidget)) < 40
