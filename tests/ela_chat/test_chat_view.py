"""ElaChatView 消息列表测试：增删改、流式、快照、贴底与空态。"""

from __future__ import annotations

from _qthelpers import wait_until as _wait_until
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QPalette, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QTextEdit
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.chat import (
    ElaChatReasoningStyleType,
    DISCLAIMER_TEXT,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatView,
    ElaChatWidget,
)


def _long_view(qapp, make, messages: int = 8) -> ElaChatView:
    view = make(ElaChatView)
    view.resize(420, 220)
    view.show()
    qapp.processEvents()
    for index in range(messages):
        view.addMessage(ElaChatRoleType.User, f"消息 {index} " + "内容" * 20)
    bar = view._scroll.verticalScrollBar()
    _wait_until(qapp, lambda: bar.maximum() > 0)
    return view


class TestMessages:
    def test_add_and_snapshot(self, qapp, make):
        view = make(ElaChatView)
        first = view.addMessage(ElaChatRoleType.User, "你好")
        second = view.addMessage(ElaChatRoleType.System, "提示")
        assert (first, second) == (1, 2)
        assert view.count() == 2
        snapshot = view.messages()
        assert [m.text for m in snapshot] == ["你好", "提示"]
        assert [m.role for m in snapshot] == [ElaChatRoleType.User, ElaChatRoleType.System]
        assert view.message(second).text == "提示"
        assert view.message(99) is None
        assert view.lastMessage().id == second

    def test_begin_append_end(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        assert view.message(messageId).status == ElaChatStatusType.Streaming
        view.appendText(messageId, "部分")
        view.appendText(messageId, "内容")
        # 快照 text 是落定值；实时全文走气泡
        assert view.message(messageId).text == ""
        assert view.bubble(messageId).text() == "部分内容"
        finished = []
        view.messageStreamFinished.connect(
            lambda mid, status: finished.append((mid, status))
        )
        view.endMessage(messageId, ElaChatStatusType.Stopped)
        assert finished == [(messageId, ElaChatStatusType.Stopped)]
        assert view.message(messageId).status == ElaChatStatusType.Stopped
        assert view.message(messageId).text == "部分内容"

    def test_update_remove_clear(self, qapp, make):
        view = make(ElaChatView)
        first = view.addMessage(ElaChatRoleType.User, "a")
        second = view.addMessage(ElaChatRoleType.Assistant, "b")
        removed = []
        view.messageRemoved.connect(removed.append)

        view.updateMessage(second, "b2")
        assert view.message(second).text == "b2"

        view.removeMessage(first)
        assert removed == [first]
        assert view.count() == 1
        assert view.bubble(first) is None

        view.clear()
        assert view.messages() == []
        assert view.bubble(second) is None

    def test_signals_order(self, qapp, make):
        view = make(ElaChatView)
        events = []
        view.messageAdded.connect(lambda mid, role: events.append(("added", mid, role)))
        view.messageUpdated.connect(lambda mid: events.append(("updated", mid)))
        view.messageStreamFinished.connect(
            lambda mid, status: events.append(("finished", mid, status))
        )
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(messageId, "x")
        view.endMessage(messageId)
        assert events[0] == ("added", messageId, ElaChatRoleType.Assistant)
        assert ("updated", messageId) in events
        assert events[-1] == ("finished", messageId, ElaChatStatusType.Done)

    def test_append_unknown_id_ignored(self, qapp, make):
        view = make(ElaChatView)
        view.appendText(99, "x")
        view.endMessage(99)
        assert view.messages() == []


class TestEmptyState:
    def test_visibility_toggles(self, qapp, make):
        view = make(ElaChatView)
        view.show()
        qapp.processEvents()
        assert view._empty.isVisible()
        messageId = view.addMessage(ElaChatRoleType.User, "hi")
        qapp.processEvents()
        assert not view._empty.isVisible()
        view.removeMessage(messageId)
        qapp.processEvents()
        assert view._empty.isVisible()

    def test_suggestions_and_titles(self, qapp, make):
        view = make(ElaChatView)
        view.setEmptyTitle("标题")
        view.setEmptySubtitle("副标题")
        view.setSuggestions(["A", "B", ""])
        assert view.emptyTitle() == "标题"
        assert view.emptySubtitle() == "副标题"
        assert view.suggestions() == ["A", "B"]
        clicked = []
        view.suggestionClicked.connect(clicked.append)
        buttons = view._empty.findChildren(
            type(view._empty._suggestions_box.itemAt(0).widget())
        )
        assert len(buttons) == 2
        buttons[1].click()
        assert clicked == ["B"]


class TestStickToBottom:
    def test_follows_bottom_and_jump_button(self, qapp, make):
        view = _long_view(qapp, make)
        bar = view._scroll.verticalScrollBar()
        assert bar.maximum() > 0
        assert _wait_until(qapp, lambda: bar.value() >= bar.maximum() - 6)
        assert view.stickToBottom()

        bar.setValue(0)
        assert _wait_until(qapp, lambda: not view.stickToBottom())
        assert view._jump_button.isVisible()

        view._jump_button.click()
        assert _wait_until(qapp, lambda: bar.value() >= bar.maximum() - 6)
        assert view.stickToBottom()
        assert not view._jump_button.isVisible()

    def test_stick_disabled_does_not_follow(self, qapp, make):
        view = _long_view(qapp, make, messages=4)
        bar = view._scroll.verticalScrollBar()
        bar.setValue(0)
        qapp.processEvents()
        view.setStickToBottom(False)
        bar.setValue(0)
        view.addMessage(ElaChatRoleType.User, "新消息 " + "内容" * 20)
        # 关掉贴底后不得再跟随：等 follow 定时器确定没被武装，视口应停在原处
        assert _wait_until(qapp, lambda: not view._follow_timer.isActive())
        assert bar.value() < bar.maximum() - 6


class TestAppearancePropagation:
    def test_content_background_follows_theme(self, qapp, make):
        view = make(ElaChatView)
        content = view.contentWidget()
        content._onThemeChanged(ElaThemeType.ThemeMode.Light)
        assert content.palette().color(QPalette.ColorRole.Window).name() == "#f7f7f7"
        content._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert content.palette().color(QPalette.ColorRole.Window).name() == "#3a3a3a"

    def test_avatar_and_ratio_applied(self, qapp, make):
        view = make(ElaChatView)
        view.setAvatarVisible(False)
        view.setUserBubbleMaxWidth(0.5)
        messageId = view.addMessage(ElaChatRoleType.User, "hi")
        bubble = view.bubble(messageId)
        assert bubble.avatarVisible() is False
        assert bubble.maxWidthRatio() == 0.5

        view.setAvatarVisible(True)
        view.setUserBubbleMaxWidth(0.8)
        assert bubble.avatarVisible() is True
        assert bubble.maxWidthRatio() == 0.8


class TestReasoningLayer:
    def test_reasoning_stream(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginReasoning(messageId)
        assert view.bubble(messageId).reasoningBlock().isOpened()
        view.appendReasoning(messageId, "先想")
        view.appendReasoning(messageId, "再算")
        # 快照 reasoning 是落定值；实时全文走气泡
        assert view.message(messageId).reasoning == ""
        assert view.bubble(messageId).reasoning() == "先想再算"
        view.endReasoning(messageId, 800)
        assert view.message(messageId).reasoning_ms == 800.0
        assert view.message(messageId).reasoning == "先想再算"
        assert not view.bubble(messageId).reasoningBlock().isOpened()

    def test_set_reasoning_replaces(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "回答")
        view.setReasoning(messageId, "整体推理", 1200.0)
        snapshot = view.message(messageId)
        assert snapshot.reasoning == "整体推理"
        assert snapshot.reasoning_ms == 1200.0

    def test_update_message_replaces_all_text_parts(self, qapp, make):
        """多段正文（多步骤）时 ``updateMessage`` 是**整段替换**，不是追加。"""
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(messageId)
        view.appendText(messageId, "A")
        view.endText(messageId)
        view.beginStep(messageId)
        view.beginText(messageId)
        view.appendText(messageId, "B")
        view.endText(messageId)

        view.updateMessage(messageId, "C")

        assert view.bubble(messageId).text() == "C"
        assert view.message(messageId).text == "C"

    def test_unknown_id_ignored(self, qapp, make):
        view = make(ElaChatView)
        view.beginReasoning(99)
        view.appendReasoning(99, "x")
        view.endReasoning(99, 1.0)
        assert view.messages() == []


class TestToolLayer:
    def test_tool_call_flow(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        callId = view.addToolCall(messageId, "read_file", '{"path": "a"}')
        assert callId
        calls = view.toolCalls(messageId)
        assert len(calls) == 1
        assert calls[0].name == "read_file"
        assert calls[0].isRunning

        view.setToolCallResult(messageId, callId, "文件内容", ok=True)
        snapshot = view.message(messageId).tool_calls[0]
        assert snapshot.isDone
        assert snapshot.result == "文件内容"

        view.clearToolCalls(messageId)
        assert view.message(messageId).tool_calls == ()
        assert view.toolCalls(messageId) == []

    def test_unknown_id_ignored(self, qapp, make):
        view = make(ElaChatView)
        assert view.addToolCall(99, "tool") is None
        view.setToolCallResult(99, "x", "y")
        assert view.messages() == []


class TestStatsErrorAttachments:
    def test_stats_and_error(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        stats = ElaChatStats(
            prompt_tokens=1, completion_tokens=2, total_tokens=3, tps=9.0
        )
        view.setStepStats(messageId, stats)
        assert view.message(messageId).stats is stats

        view.setMessageError(messageId, "接口超时")
        snapshot = view.message(messageId)
        assert snapshot.error == "接口超时"
        assert snapshot.status == ElaChatStatusType.Error

    def test_message_attachments(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.User, "看这个")
        view.setMessageAttachments(
            messageId, [{"name": "a.png", "path": "C:/tmp/a.png", "size": 1024}]
        )
        assert len(view.message(messageId).attachments) == 1
        view.addMessageAttachment(messageId, "b.txt", "C:/tmp/b.txt", 2)
        assert len(view.message(messageId).attachments) == 2

    def test_title_and_timestamp(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        view.setMessageTitle(messageId, "deepseek")
        view.setMessageTimestamp(messageId, "12:34:56")
        snapshot = view.message(messageId)
        assert snapshot.title == "deepseek"
        assert snapshot.timestamp == "12:34:56"
        assert view.bubble(messageId).title() == "deepseek"


class TestMessageActions:
    def test_action_signals_carry_message_id(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.User, "hi")
        events = []
        copies = []
        view.messageActionTriggered.connect(lambda mid, key: events.append((mid, key)))
        view.copyRequested.connect(copies.append)
        view.bubble(messageId).actions().toolButton("copy").click()
        assert events == [(messageId, "copy")]
        assert copies == [messageId]

    def test_regenerate_hidden_until_turn_finishes(self, qapp, make):
        """底部行整行（含「重新生成」）在回合结束前不出现（与气泡层同一判定）。"""
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        bubble = view.bubble(messageId)
        assert bubble.footer().isHidden() is True
        view.appendText(messageId, "写一半")
        assert bubble.footer().isHidden() is True

        view.endMessage(messageId)
        assert bubble.footer().isHidden() is False
        assert bubble.actions().toolButton("regenerate").isVisibleTo(bubble) is True

    def test_disclaimer_applies_to_existing_and_new_messages(self, qapp, make):
        """「AI 生成」提示：view 改一次覆盖已有 + 之后新增的助手消息。"""
        view = make(ElaChatView)
        first = view.bubble(view.addMessage(ElaChatRoleType.Assistant, "一"))
        second_id = view.addMessage(ElaChatRoleType.Assistant, "二")
        assert view.disclaimer() == DISCLAIMER_TEXT
        assert view.disclaimerVisible() is True

        view.setDisclaimer("统一提示：内容由 AI 生成")
        assert first.disclaimer() == "统一提示：内容由 AI 生成"
        assert view.bubble(second_id).disclaimer() == "统一提示：内容由 AI 生成"

        view.setDisclaimerVisible(False)
        assert view.disclaimerVisible() is False
        assert first.disclaimerVisible() is False
        new_id = view.addMessage(ElaChatRoleType.Assistant, "三")  # 新消息也继承
        assert view.bubble(new_id).disclaimerVisible() is False
        qapp.processEvents()

    def test_custom_action_passthrough(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        events = []
        view.messageActionTriggered.connect(lambda mid, key: events.append((mid, key)))
        bubble = view.bubble(messageId)
        bubble.actions().addCustomAction("favorite", tooltip="收藏")
        bubble.actions().toolButton("favorite").click()
        assert events == [(messageId, "favorite")]

    def test_attachment_clicked_carries_message_id(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.User, "看附件")
        view.setMessageAttachments(messageId, [{"name": "a.txt", "path": "C:/a.txt"}])
        clicked = []
        view.attachmentClicked.connect(lambda mid, path: clicked.append((mid, path)))
        strip = view.bubble(messageId).attachmentStrip()
        strip.attachmentClicked.emit("C:/a.txt")
        assert clicked == [(messageId, "C:/a.txt")]


class TestCopyNotificationToggle:
    def test_default_enabled(self, qapp, make):
        view = make(ElaChatView)
        assert view.copyNotificationEnabled() is True

    def test_applies_to_existing_and_new_messages(self, qapp, make):
        """与其它展示形态 setter 一致：view 改一次，已有 + 之后新增全部生效。"""
        view = make(ElaChatView)
        first = view.bubble(view.addMessage(ElaChatRoleType.User, "一"))

        view.setCopyNotificationEnabled(False)
        second_id = view.addMessage(ElaChatRoleType.User, "二")
        assert first.copyNotificationEnabled() is False
        assert view.bubble(second_id).copyNotificationEnabled() is False

        view.setCopyNotificationEnabled(True)
        assert first.copyNotificationEnabled() is True
        assert view.bubble(second_id).copyNotificationEnabled() is True


class TestViewPassthroughs:
    def test_duration_title_timestamp_emit_updates(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        events = []
        view.messageUpdated.connect(events.append)

        view.setMessageDuration(messageId, 1500)
        view.setMessageTitle(messageId, "模型")
        view.setMessageTimestamp(messageId, "12:00:00")

        assert events == [messageId, messageId, messageId]
        assert view.message(messageId).duration_ms == 1500.0

    def test_style_and_grouping_applied(self, qapp, make):
        view = make(ElaChatView)
        view.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        view.setToolGrouping(False)
        assert view.reasoningStyle() == ElaChatReasoningStyleType.Inline
        assert view.toolGrouping() is False
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        bubble = view.bubble(messageId)
        assert bubble.reasoningStyle() == ElaChatReasoningStyleType.Inline
        assert bubble.toolGrouping() is False

    def test_message_duration(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        view.setMessageDuration(messageId, 1500)
        assert view.message(messageId).duration_ms == 1500.0
        assert view.bubble(messageId).duration() == 1500.0


class TestBatchRemoveAndSync:
    def test_remove_messages_from(self, qapp, make):
        view = make(ElaChatView)
        first = view.addMessage(ElaChatRoleType.User, "a")
        second = view.addMessage(ElaChatRoleType.Assistant, "b")
        third = view.addMessage(ElaChatRoleType.User, "c")
        removed = []
        view.messageRemoved.connect(removed.append)

        assert view.removeMessagesFrom(second) == [second, third]
        assert removed == [second, third]
        assert [m.id for m in view.messages()] == [first]
        assert view.removeMessagesFrom(999) == []

    def test_snapshot_stays_synchronous_for_readers(self, qapp, make):
        """未跑事件循环也能读到一致快照 —— 且与读取时机无关。

        完整反转后快照只含**已落定**内容，所以流式期间是空串；一致性
        （不跑事件循环也能立刻读到、与读几次无关）仍然成立，这正是
        落定语义的前提。
        """
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        updates = []
        view.messageUpdated.connect(updates.append)

        for chunk in ("a", "b", "c"):
            view.appendText(messageId, chunk)

        # 未跑事件循环也能立刻读到，且读多少次都一样
        assert view.message(messageId).text == ""
        assert view.message(messageId).text == ""
        assert view.message(messageId).text == ""
        assert updates == [messageId, messageId, messageId]

        view.endMessage(messageId)
        assert view.message(messageId).text == "abc"

    def test_guard_installed_for_streamed_viewer_and_pruned(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(messageId, "hello")
        assert view.bubble(messageId).markdownViewer() is not None

        guards = view._guards_by_message.get(messageId, [])
        assert len(guards) == 1
        assert guards[0] in view._scroll_guards

        view.removeMessage(messageId)

        assert messageId not in view._guards_by_message
        assert guards[0] not in view._scroll_guards


class TestScrollBehavior:
    def test_jump_threshold(self, qapp, make):
        view = _long_view(qapp, make, messages=8)
        bar = view._scroll.verticalScrollBar()
        bar.setValue(0)
        qapp.processEvents()
        view.setJumpThreshold(0)
        assert view._jump_button.isVisible()
        view.setJumpThreshold(10**9)
        assert not view._jump_button.isVisible()
        view.setJumpThreshold(None)
        assert view.jumpThreshold() is None

    def test_nested_scroll_guard_installed(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        viewer = view.bubble(messageId).markdownViewer()
        assert viewer is not None
        assert view.guardNestedScroll(viewer) is not None
        assert len(view._scroll_guards) >= 1

    def test_follow_timer_does_not_loop(self, qapp, make):
        view = _long_view(qapp, make)
        view._scroll_to_bottom_if_sticky()
        assert _wait_until(qapp, lambda: not view._follow_timer.isActive())

    def test_tool_toggle_keeps_viewport(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 260)
        view.show()
        qapp.processEvents()
        for index in range(6):
            view.addMessage(ElaChatRoleType.User, f"消息 {index} " + "内容" * 30)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "回答 " + "内容" * 20)
        callId = view.addToolCall(messageId, "read", '{"path": "a.py"}')
        view.setToolCallResult(messageId, callId, "结果 " * 20)
        bar = view._scroll.verticalScrollBar()
        _wait_until(qapp, lambda: bar.maximum() > 0)
        # 等异步渲染（Markdown）出内容后再测展开行为
        viewer = view.bubble(messageId).markdownViewer()
        assert _wait_until(
            qapp, lambda: viewer is not None and not viewer.document().isEmpty()
        )

        # 1) 展开外层面板：内容增长但视口保持不动
        view.scrollToBottom()
        qapp.processEvents()
        before_value = bar.value()
        panel = view.bubble(messageId).toolPanel()
        panel.setOpened(True)
        assert _wait_until(qapp, lambda: bar.maximum() > before_value)
        assert bar.value() == before_value

        # 2) 暂停窗口结束后展开内层卡片，同样不带动视口
        assert _wait_until(qapp, lambda: view.followHeld() is False)
        view.scrollToBottom()
        qapp.processEvents()
        before_value = bar.value()
        card = view.bubble(messageId)._tool_cards[callId]
        card.setOpened(True)
        assert _wait_until(qapp, lambda: bar.maximum() > before_value)
        assert bar.value() == before_value
        # 暂停窗口结束后也不会补一次滚动
        assert _wait_until(qapp, lambda: view.followHeld() is False)
        assert bar.value() == before_value

    def test_nested_scroll_guard_blocks_at_boundary(self, qapp, make):

        view = make(ElaChatView)
        inner = QTextEdit()
        inner.setPlainText("\n".join(f"行 {i}" for i in range(200)))
        inner.resize(120, 60)
        inner.show()
        qapp.processEvents()
        guard = view.guardNestedScroll(inner)
        assert guard is not None

        bar = inner.verticalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(bar.maximum())
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        assert guard.eventFilter(inner.viewport(), event) is True

        bar.setValue(0)
        up_event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        assert guard.eventFilter(inner.viewport(), up_event) is True
        inner.deleteLater()


class TestScrollBar:
    """垂直滚动条必须**看得见、拖得动**。

    回归背景：``ElaScrollArea`` 构造时装了 ``ElaScrollBar`` 之后又强制
    ``ScrollBarAlwaysOff``（ElaScrollArea.cpp:16-19），滚动条永远不显示 ——
    滚轮能滚但没有把手。这几个用例守住 ``__init__`` 里那次
    ``setVerticalScrollBarPolicy(AsNeeded)`` 不被回退。
    """

    def test_default_policy_is_as_needed(self, qapp, make):

        view = make(ElaChatView)
        assert view.scrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        assert view.scrollBar() is view._scroll.verticalScrollBar()

    def test_visible_when_overflowing_hidden_when_fits(self, qapp, make):
        view = _long_view(qapp, make, messages=8)
        bar = view.scrollBar()
        assert bar.maximum() > 0
        assert bar.isVisible()
        # 内容不足一屏时 AsNeeded 语义：自动隐藏
        for messageId in [m.id for m in view.messages()]:
            view.removeMessage(messageId)
        assert _wait_until(qapp, lambda: bar.maximum() == 0)
        assert not bar.isVisible()

    def test_set_policy_toggles_visibility(self, qapp, make):

        view = _long_view(qapp, make, messages=8)
        bar = view.scrollBar()
        view.setScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        qapp.processEvents()
        assert view.scrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert not bar.isVisible()
        view.setScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        assert _wait_until(qapp, bar.isVisible)
        assert view.scrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded

    def test_reflow_release_resyncs_width_after_viewport_shrink(self, qapp, make):
        """冻结期间滚动条出现会窄化视口，解冻后必须把内容拉回视口宽度。

        否则内容比视口宽、水平方向又 AlwaysOff → 右侧被裁掉一个滚动条的宽度。
        """

        view = make(ElaChatView)
        view.resize(420, 260)
        view.show()
        qapp.processEvents()
        view.addMessage(ElaChatRoleType.Assistant, "短")
        qapp.processEvents()
        view.setResizeReflowDeferred(True, minMessages=0, delayMs=20)
        view.resize(460, 260)  # 冻结内容宽度
        # 冻结期间灌满内容 → 滚动条出现，视口窄 10px
        for index in range(6):
            view.addMessage(ElaChatRoleType.Assistant, f"消息 {index} " + "内容" * 20)
        assert _wait_until(qapp, lambda: view.scrollBar().maximum() > 0)
        assert view.scrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        assert _wait_until(qapp, lambda: view._resize_frozen_width == 0)
        assert view._content.width() == view._scroll.viewport().width()

    def test_drag_handle_scrolls_and_stops_following(self, qapp, make):

        view = _long_view(qapp, make, messages=8)
        bar = view.scrollBar()
        bar.setValue(0)
        qapp.processEvents()
        assert view.stickToBottom() is False

        # QTest.mouseMove 不带 buttons 位，拖动段要直发带 LeftButton 的事件
        QTest.mousePress(
            bar,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(5, 10),
        )
        for y in (40, 80, 120):
            bar.setValue(0)
            qapp.sendEvent(
                bar,
                QMouseEvent(
                    QMouseEvent.Type.MouseMove,
                    QPointF(5, y),
                    Qt.MouseButton.NoButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            qapp.processEvents()
            assert bar.value() > 0
        QTest.mouseRelease(
            bar,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(5, 120),
        )
        # 停在中间：既滚动了，又没回到底部
        assert 0 < bar.value() < bar.maximum()
        assert view._content.y() == -bar.value()
        # 手动拖动后不再贴底跟随
        assert view.stickToBottom() is False


class TestContentMaxWidth:
    """阅读宽度默认不限；宿主显式收紧时只作用于助手内容列。"""

    def test_default_unlimited(self, qapp, make):
        view = make(ElaChatView)
        assert view.contentMaxWidth() == 0
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        assert view.bubble(messageId).contentMaxWidth() == 0
        assert view.bubble(messageId)._column.maximumWidth() == 16777215

    def test_user_message_unaffected(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.User, "hi")
        assert view.bubble(messageId).contentMaxWidth() == 0
        assert view.bubble(messageId)._column.maximumWidth() == 16777215

    def test_setter_applies_to_existing_and_disable(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        view.setContentMaxWidth(500)
        # 限的是整列（正文 + 附件条 + 底部行），不是只限正文 ——
        # 否则宽窗口下 footer 比正文列宽，往右伸出去
        bubble = view.bubble(messageId)
        assert bubble._column.maximumWidth() == 500
        view.setContentMaxWidth(0)
        assert bubble._column.maximumWidth() == 16777215
        assert view.contentMaxWidth() == 0

    def test_column_wraps_content_and_footer(self, qapp, make):
        """内容列必须同时装下正文、附件条与底部行（否则限宽时 footer 伸出列外）。"""
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "hi")
        bubble = view.bubble(messageId)
        assert bubble._content.parentWidget() is bubble._column
        assert bubble._footer.parentWidget() is bubble._column
        assert bubble._attachments_host.parentWidget() is bubble._column

    def test_widget_passthrough(self, qapp, make):

        chat = make(ElaChatWidget)
        assert chat.chatView().contentMaxWidth() == 0
        chat.chatView().setContentMaxWidth(640)
        assert chat.chatView().contentMaxWidth() == 640


class TestResizeReflowDeferred:
    """交互 resize 延迟重排：拖动期间冻结内容宽度，停手统一 reflow。"""

    def _view_with_messages(self, qapp, make, count: int = 4) -> ElaChatView:
        view = make(ElaChatView)
        view.resize(420, 260)
        view.show()
        qapp.processEvents()
        for index in range(count):
            view.addMessage(ElaChatRoleType.Assistant, f"消息 {index} " + "内容" * 10)
        qapp.processEvents()
        return view

    def test_freeze_then_release(self, qapp, make):
        view = self._view_with_messages(qapp, make)
        view.setResizeReflowDeferred(True, minMessages=2, delayMs=30)
        view.resize(460, 260)
        frozen = view._content.width()
        assert view._content.minimumWidth() == frozen
        assert view._content.maximumWidth() == frozen

        assert _wait_until(qapp, lambda: view._resize_frozen_width == 0)
        assert view._content.maximumWidth() == 16777215
        assert view._content.width() == view._scroll.viewport().width()

    def test_continuous_resize_freezes_once(self, qapp, make):
        view = self._view_with_messages(qapp, make)
        view.setResizeReflowDeferred(True, minMessages=2, delayMs=40)
        view.resize(460, 260)
        frozen = view._content.minimumWidth()
        for width in (470, 480, 490):
            view.resize(width, 260)
            qapp.processEvents()
            assert view._content.minimumWidth() == frozen  # 拖动期间保持首帧宽度
        assert view._resize_frozen_width > 0
        assert _wait_until(qapp, lambda: view._resize_frozen_width == 0)

    def test_below_threshold_not_frozen(self, qapp, make):
        view = self._view_with_messages(qapp, make)
        view.setResizeReflowDeferred(True, minMessages=50, delayMs=30)
        view.resize(460, 260)
        assert view._resize_frozen_width == 0
        assert view._content.maximumWidth() == 16777215

    def test_disabled_not_frozen(self, qapp, make):
        view = self._view_with_messages(qapp, make)
        view.setResizeReflowDeferred(False, minMessages=2)
        assert view.resizeReflowDeferred() is False
        view.resize(460, 260)
        assert view._resize_frozen_width == 0

    def test_release_returns_to_bottom(self, qapp, make):
        view = make(ElaChatView)
        view.resize(420, 200)
        view.show()
        qapp.processEvents()
        for index in range(6):
            view.addMessage(ElaChatRoleType.Assistant, f"消息 {index} " + "内容" * 20)
        view.setResizeReflowDeferred(True, minMessages=2, delayMs=20)
        view.scrollToBottom()
        qapp.processEvents()
        view.resize(380, 200)
        assert _wait_until(qapp, lambda: view._resize_frozen_width == 0)
        assert _wait_until(qapp, lambda: view._atBottom())
