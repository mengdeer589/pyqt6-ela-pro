"""运行轨迹：纯模型聚合 + 独立面板。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatRoleType,
    ElaChatStats,
    ElaChatTracePanel,
    ElaChatView,
    buildTraceRows,
)


def _build_view(make, *, child_ok=True):
    view = make(ElaChatView)
    view.resize(760, 560)
    mid = view.beginMessage(ElaChatRoleType.Assistant)
    view.beginStep(mid)
    view.appendText(mid, "开始")
    view.addToolCall(mid, "delegate_task", '{"task": "查资料"}', "p1")
    view.addToolCall(mid, "read", '{"path": "a.py"}', "c1", parentId="p1")
    view.setToolCallResult(mid, "c1", "内容" if child_ok else "失败", ok=child_ok)
    view.setToolCallResult(mid, "p1", "结论", ok=True)
    view.setStepStats(
        mid,
        ElaChatStats(
            total_tokens=120,
            cost_usd=0.01,
            duration_ms=1500.0,
        ),
    )
    view.endMessage(mid)
    return view, mid


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
        assert turn.children[0].kind == "step"
        flat = result.flatten()
        tools = [row for row in flat if row.kind == "tool"]
        assert len(tools) == 2
        assert result.tool_count == 2
        parent = next(row for row in tools if row.part_id == "p1")
        child = next(row for row in tools if row.part_id == "c1")
        assert child.depth == parent.depth + 1
        assert parent.duration_ms >= 0

    def test_error_count(self, qapp, make):
        view, _ = _build_view(make, child_ok=False)
        result = buildTraceRows(view.messages())
        assert result.error_count == 1
        assert any(row.isError for row in result.flatten())

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
        assert result.tool_count == 2
        assert result.rows[0].tokens == 120


class TestTracePanel:
    def test_panel_rows_and_filter(self, qapp, make):
        view, _ = _build_view(make, child_ok=False)
        panel = make(ElaChatTracePanel)
        panel.setView(view)
        assert panel.rows()
        all_count = len(panel.rows())
        panel.setFilter("errors")
        assert 0 < len(panel.rows()) <= all_count
        panel.setFilter("all")
        assert len(panel.rows()) == all_count

    def test_row_activation(self, qapp, make):
        view, mid = _build_view(make)
        panel = make(ElaChatTracePanel, view)
        hits = []
        panel.rowActivated.connect(hits.append)
        widget = panel.rows()[0]
        widget.activated.emit(mid, "p1")
        assert hits == [mid]

    def test_empty_panel(self, qapp, make):
        view = make(ElaChatView)
        panel = make(ElaChatTracePanel, view)
        assert not panel.rows()
        assert not panel._scroll.isVisible()
