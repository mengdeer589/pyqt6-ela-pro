"""延迟分段物化 / 超长消息窗口化 / 懒进度环 / resize 冻结的回归测试。"""

from __future__ import annotations

import bisect

from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatMessage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
    ElaChatView,
)
from pyqt6_ela_pro.chat.blocks import ToolCallCard
from pyqt6_ela_pro.ela_shimmer import ElaShimmer


def _tool_part(message_id: int, step: int) -> ElaChatPart:
    call = ElaChatToolCall(
        id=f"call-{message_id}-{step}",
        name="shell",
        arguments='{"command":"echo hi"}',
        result="hi",
        status="done",
    )
    return ElaChatPart(
        id=call.id,
        kind=ElaChatPartKindType.Tool,
        tool_call=call,
        status=ElaChatStatusType.Done,
        step=step,
    )


def _assistant_dict(message_id: int, steps: int) -> dict:
    parts = tuple(_tool_part(message_id, step) for step in range(1, steps + 1))
    return (
        ElaChatMessage(id=message_id, role=ElaChatRoleType.Assistant)
        .withParts(parts)
        .toDict()
    )


def _bundle(count: int, steps: int = 2) -> dict:
    messages = [_assistant_dict(index, steps) for index in range(1, count + 1)]
    return {
        "schema": 1,
        "session": {"id": "virtual", "title": "virtual"},
        "messages": messages,
    }


class TestDeferredParts:
    def test_batch_restore_keeps_old_messages_as_data(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()

        assert view.importSession(_bundle(20)) == 20
        qapp.processEvents()

        first = view.bubble(1)
        assert first is not None
        assert first.partsDeferred() is True
        # 数据侧完整：messages() / 导出 / 工具读取都不能看到空 parts
        message = view.message(1)
        assert [part.kind for part in message.parts] == [
            ElaChatPartKindType.Tool,
            ElaChatPartKindType.Tool,
        ]
        assert [call.id for call in first.toolCalls()] == ["call-1-1", "call-1-2"]
        assert len(view.exportSession()["messages"][0]["parts"]) == 2

    def test_materialize_message_builds_widgets(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(20))
        qapp.processEvents()

        first = view.bubble(1)
        assert first.partsDeferred() is True
        assert view.materializeMessage(1) is True
        assert first.partsDeferred() is False
        assert first.isVisible() is True
        assert len(first.findChildren(ToolCallCard)) == 2
        assert len(first.toolPanels()) == 2

    def test_disable_virtual_parts_materializes_all(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(20))
        qapp.processEvents()
        assert any(
            view.bubble(message.id).partsDeferred()
            for message in view.messages()
            if view.bubble(message.id) is not None
        )
        view.setVirtualPartsEnabled(False)
        assert all(
            not view.bubble(message.id).partsDeferred()
            for message in view.messages()
            if view.bubble(message.id) is not None
        )

    def test_scroll_to_top_materializes_lazy_page(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(20))
        qapp.processEvents()
        assert view.bubble(1).partsDeferred() is True

        # offscreen 下首帧布局可能还没算出滚动范围：resize 一次逼布局落地
        view.resize(560, 480)
        qapp.processEvents()
        bar = view.scrollBar()
        assert bar.maximum() > 0
        # 先确保确实在底部，再滚到顶：首屏若本就在 0，setValue(0) 不发 valueChanged
        bar.setValue(bar.maximum())
        qapp.processEvents()
        target = view._lazy_ids[-1] if view._lazy_ids else None
        bar.setValue(0)
        qapp.processEvents()
        # 并行负载下滚动信号可能被合并 / 丢失，显式重放一次滚动处理
        view._on_scrolled(0)
        # 第一页懒加载取的是「离当前最近的那条旧消息」，不是最老的 1
        assert target is not None
        assert _wait_until(
            qapp,
            lambda: (
                (b := view.bubble(target)) is not None and b.partsDeferred() is False
            ),
        )
        assert view.bubble(1).partsDeferred() is True
        # 更早的消息可显式物化
        assert view.scrollToMessage(1) is True
        assert view.bubble(1).partsDeferred() is False
        assert len(view.bubble(1).findChildren(ToolCallCard)) == 2


class TestDeferredShells:
    def test_large_batch_keeps_old_messages_as_placeholders(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        assert view.importSession(_bundle(100, steps=1)) == 100
        qapp.processEvents()

        # 首屏之外的消息没有气泡，但数据 / 导出完整
        assert view.bubble(1) is None
        assert view.message(1) is not None
        assert len(view.message(1).parts) == 1
        assert len(view.exportSession()["messages"]) == 100
        assert len(view._shell_placeholders) > 0

    def test_placeholders_stay_childless(self, qapp, make):
        """历史虚拟化占位保持零子控件 —— 不能逐条换成 ElaShimmer 控件。"""
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(100, steps=1))
        qapp.processEvents()

        assert len(view._shell_placeholders) > 0
        assert view.findChildren(ElaShimmer) == []

    def test_materialize_shell_and_remove(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        # 关闭视口挂起：定时器在并行负载下可能抢在贴底前物化 id 1
        view.setViewportSuspension(False)
        view.importSession(_bundle(100, steps=1))
        qapp.processEvents()
        assert view.bubble(1) is None

        assert view.materializeMessage(1) is True
        bubble = view.bubble(1)
        assert bubble is not None
        assert len(bubble.parts()) == 1

        assert view.bubble(2) is None
        view.removeMessage(2)
        assert view.count() == 99
        assert view.message(2) is None

    def test_disable_shell_virtualization_materializes_all(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(100, steps=1))
        qapp.processEvents()
        assert view.bubble(1) is None
        view.setShellVirtualizationEnabled(False)
        assert all(view.bubble(message.id) is not None for message in view.messages())


class TestVirtualList:
    def test_spacer_mode_has_no_per_message_placeholders(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        assert view.importSession(_bundle(300, steps=1)) == 300
        qapp.processEvents()

        assert view._virtual_list_mode is True
        assert view._shell_placeholders == {}
        assert view.bubble(1) is None
        assert len(view._bubbles) < 40
        assert view.message(1) is not None
        assert len(view.exportSession()["messages"]) == 300

    def test_virtual_list_materialize_scroll_and_remove(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(300, steps=1))
        qapp.processEvents()

        view.materializeMessage(1)
        bubble = view.bubble(1)
        assert bubble is not None
        assert bubble.isVisible() is True
        assert bubble.partsDeferred() is False
        assert len(bubble.parts()) == 1
        assert view.scrollToMessage(150) is True
        assert view.bubble(150) is not None

        assert view.bubble(2) is None
        view.removeMessage(2)
        assert view.count() == 299
        assert view.message(2) is None

    def test_disable_virtual_list_materializes_all(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(220, steps=1))
        qapp.processEvents()
        assert view._virtual_list_mode is True
        view.setVirtualListEnabled(False)
        assert view._virtual_list_mode is False
        assert all(view.bubble(message.id) is not None for message in view.messages())

    def test_materialized_window_stays_contiguous(self, qapp, make):
        """物化分帧后窗口仍是**连续**切片：spacer 列表没有逐条占位，留洞会错位。"""
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(300, steps=1))
        qapp.processEvents()

        bar = view._scroll.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        qapp.processEvents()
        assert _wait_until(qapp, lambda: not view._virtual_window_timer.isActive())

        indices = [
            view._virtual_index[messageId] for messageId in view._virtual_bubble_ids
        ]
        assert indices, "可见区间内至少要物化一条消息"
        assert indices == list(range(min(indices), max(indices) + 1))

    def test_materialize_budget_fills_viewport_first(self, qapp, make):
        """视口区间优先铺满；预算用完的下一帧继续，最终覆盖整个视口。"""
        view = make(ElaChatView)
        view.resize(640, 400)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(300, steps=1))
        qapp.processEvents()

        bar = view._scroll.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        qapp.processEvents()
        assert _wait_until(qapp, lambda: not view._virtual_window_timer.isActive())

        prefix = view._virtual_prefix
        viewport = view._scroll.viewport().height()
        top = bar.value()
        core_first = max(0, bisect.bisect_right(prefix, top) - 1)
        core_last = min(
            len(view._virtual_order) - 1,
            bisect.bisect_right(prefix, top + viewport) - 1,
        )
        indices = sorted(
            view._virtual_index[messageId] for messageId in view._virtual_bubble_ids
        )
        assert indices[0] <= core_first
        assert indices[-1] >= core_last


class TestHugeMessageWindow:
    def test_materialize_keeps_tail_steps_and_expands(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.resize(640, 400)
        bubble.show()
        qapp.processEvents()
        parts = tuple(_tool_part(1, step) for step in range(1, 31))
        assert bubble.setPartsDeferred(parts) is True
        assert bubble.materializeParts() is True
        assert bubble.partsWindowed() is True
        # 数据完整，但只建了末尾窗口的卡片
        assert len(bubble.parts()) == 30
        assert len(bubble.toolCalls()) == 30
        assert len(bubble.findChildren(ToolCallCard)) == 12

        assert bubble.expandParts() is True
        assert bubble.partsWindowed() is False
        assert len(bubble.findChildren(ToolCallCard)) == 30


class TestLazyBusyRing:
    def test_progress_ring_created_on_demand(self, qapp, make):
        call = ElaChatToolCall(
            id="c1",
            name="shell",
            arguments="{}",
            status=ElaChatToolStatusType.Done,
        )
        card = make(ToolCallCard, tool_call=call)
        assert card._busy is None
        assert card.isBusy() is False

        card.setBusy(True)
        assert card._busy is not None
        assert card.isBusy() is True
        assert card._busy.getIsBusying() is True

        card.setBusy(False)
        assert card.isBusy() is False
        assert card._busy.getIsBusying() is False


class TestResizeFreeze:
    def test_width_is_frozen_before_release(self, qapp, make):
        view = make(ElaChatView)
        view.resize(700, 500)
        view.show()
        qapp.processEvents()
        view.addMessage(ElaChatRoleType.Assistant, "hello")
        view.setResizeReflowDeferred(True, minMessages=1, delayMs=10_000, minParts=1)

        view.resize(560, 500)
        qapp.processEvents()
        assert view._resize_frozen_width > 0
        view.setResizeReflowDeferred(False)
        assert view._resize_frozen_width == 0


class TestVirtualListNewMessage:
    def test_new_message_does_not_duplicate_bottom_spacer(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(300, steps=1))
        qapp.processEvents()
        view.materializeMessage(300)
        previous = view.bubble(300)
        assert previous is not None

        mid = view.addMessage(ElaChatRoleType.Assistant, "新回答 " * 40)
        qapp.processEvents()
        view._refresh_virtual_window(at_bottom=True)
        qapp.processEvents()

        bubble = view.bubble(mid)
        assert bubble is not None
        assert mid in view._virtual_bubble_ids
        # 新消息在末尾：bottom spacer 不应再算一遍它的高度
        assert view._virtual_bottom_spacer.height() == 0
        gap = bubble.y() - (previous.y() + previous.height())
        assert 0 <= gap <= 30


class TestShellRecycling:
    def test_far_bubbles_are_recycled_to_placeholders(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(120, steps=1))
        qapp.processEvents()
        assert view.bubble(120) is not None

        view._scroll.verticalScrollBar().setValue(0)
        assert _wait_until(qapp, lambda: len(view._bubbles) < 40, timeout_ms=5000)
        assert len(view._shell_placeholders) > 80
        assert view._shell_recycling is True

        # 滚回底部要能重新物化最新消息
        view.scrollToBottom()
        assert _wait_until(qapp, lambda: view.bubble(120) is not None, timeout_ms=5000)


class TestRecyclingFlushesParts:
    def test_dematerialize_flushes_unsynced_parts(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        view.show()
        qapp.processEvents()
        view.importSession(_bundle(120, steps=1))
        qapp.processEvents()

        bar = view._scroll.verticalScrollBar()
        assert _wait_until(qapp, lambda: bar.maximum() > 0, timeout_ms=5000)
        bar.setValue(0)
        assert _wait_until(qapp, lambda: view.bubble(1) is not None, timeout_ms=5000)
        view.addToolCall(1, "shell", '{"command": "ls"}')
        assert 1 in view._dirty_syncs

        view.scrollToBottom()
        assert _wait_until(qapp, lambda: view.bubble(1) is None, timeout_ms=5000)
        assert view.message(1).tool_calls
