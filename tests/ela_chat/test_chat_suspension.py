"""视口外查看器挂起测试（大消息量下的内存与 reflow 优化）。"""

from __future__ import annotations


from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import (
    ElaChatReasoningStyleType,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatView,
    ElaChatWidget,
)

MD = (
    "## 标题\n\n这是**回答**，包含 `代码` 与列表：\n\n- 项目一\n- 项目二\n\n"
    + "补充内容。" * 20
)


def _build(qapp, make, count: int = 6, reasoning: bool = False):
    view = make(ElaChatView)
    view.resize(360, 160)
    view.show()
    qapp.processEvents()
    view.setViewportSuspension(True, minMessages=2)
    ids = []
    for index in range(count):
        messageId = view.addMessage(ElaChatRoleType.Assistant, MD + f"\n\n第 {index} 段")
        if reasoning:
            view.setReasoning(messageId, f"## 步骤 {index}\n推理内容", 300.0)
        ids.append(messageId)
    qapp.processEvents()
    return view, ids


class TestViewportSuspension:
    def test_offscreen_suspended_and_restored(self, qapp, make):
        view, ids = _build(qapp, make)
        bar = view._scroll.verticalScrollBar()
        assert _wait_until(qapp, lambda: bar.maximum() > 0)
        bar.setValue(0)
        last = ids[-1]
        assert _wait_until(qapp, lambda: view.bubble(last).viewersSuspended())

        bubble = view.bubble(last)
        assert bubble.markdownViewer() is None
        assert view.message(last).text.startswith("## 标题")
        assert last in view._suspended_ids
        # 快照与分段数据不受影响
        parts = view.message(last).parts
        assert parts and parts[0].kind == ElaChatPartKindType.Text
        assert view.bubble(ids[0]).viewersSuspended() is False

        height = bubble.height()
        bar.setValue(bar.maximum())
        assert _wait_until(qapp, lambda: not view.bubble(last).viewersSuspended())
        assert "标题" in view.bubble(last).markdownViewer().markdown()
        assert abs(view.bubble(last).height() - height) <= 2

    def test_streaming_message_never_suspended(self, qapp, make):
        view, _ids = _build(qapp, make)
        bar = view._scroll.verticalScrollBar()
        assert _wait_until(qapp, lambda: bar.maximum() > 0)
        streaming_id = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(streaming_id, "流式内容")
        bar.setValue(0)
        qapp.processEvents()
        # 触发一次挂起判定
        view._update_suspension()
        assert view.bubble(streaming_id).viewersSuspended() is False
        assert streaming_id not in view._suspended_ids

    def test_toggle_off_restores_all(self, qapp, make):
        view, ids = _build(qapp, make)
        bar = view._scroll.verticalScrollBar()
        assert _wait_until(qapp, lambda: bar.maximum() > 0)
        bar.setValue(0)
        assert _wait_until(qapp, lambda: view.bubble(ids[-1]).viewersSuspended())

        view.setViewportSuspension(False)
        assert view.viewportSuspension() is False
        assert all(not view.bubble(mid).viewersSuspended() for mid in ids)
        assert view._suspended_ids == set()

    def test_below_threshold_not_suspended(self, qapp, make):
        view, ids = _build(qapp, make)
        view.setViewportSuspension(True, minMessages=50)
        bar = view._scroll.verticalScrollBar()
        assert _wait_until(qapp, lambda: bar.maximum() > 0)
        bar.setValue(0)
        view._update_suspension()
        assert all(not view.bubble(mid).viewersSuspended() for mid in ids)

    def test_guards_dropped_and_reinstalled(self, qapp, make):
        view, ids = _build(qapp, make)
        bar = view._scroll.verticalScrollBar()
        assert _wait_until(qapp, lambda: bar.maximum() > 0)
        bar.setValue(0)
        last = ids[-1]
        assert _wait_until(qapp, lambda: view.bubble(last).viewersSuspended())
        assert view._guards_by_message.get(last, []) == []

        bar.setValue(bar.maximum())
        assert _wait_until(qapp, lambda: not view.bubble(last).viewersSuspended())
        assert view._guards_by_message.get(last, [])

    def test_style_switch_while_suspended(self, qapp, make):
        view, ids = _build(qapp, make, reasoning=True)
        bar = view._scroll.verticalScrollBar()
        assert _wait_until(qapp, lambda: bar.maximum() > 0)
        bar.setValue(0)
        last = ids[-1]
        assert _wait_until(qapp, lambda: view.bubble(last).viewersSuspended())

        view.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        assert view.bubble(last).viewersSuspended() is True
        bar.setValue(bar.maximum())
        assert _wait_until(qapp, lambda: not view.bubble(last).viewersSuspended())
        assert "推理内容" in view.bubble(last).reasoning()

    def test_widget_passthrough(self, qapp, make):
        chat = make(ElaChatWidget)
        assert chat.chatView().viewportSuspension() is True
        chat.chatView().setViewportSuspension(False)
        assert chat.chatView().viewportSuspension() is False
