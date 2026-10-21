"""本轮审查修复的回归测试：收尾信号恰好一次 / 恢复结算 / 问答卡提交路径 / 审批补位等。

对应 `AGENTS.md` chat 小节新增的不变式。断言可见性用 ``isHidden()`` 而不是
``isVisible()``：控件挂在没 ``show()`` 的父链上时后者恒 False。
"""

from __future__ import annotations

import json

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent, Qt, QPointF
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatMockBackend,
    ElaChatOption,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatQuestion,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatStreamBinder,
    ElaChatToolBar,
    ElaChatView,
    ElaChatWidget,
    ReasoningBlock,
)
from pyqt6_ela_pro.chat.blocks import (
    CompactionSeparator,
    PermissionCard,
    PermissionRecord,
    ToolCallCard,
)
from pyqt6_ela_pro.chat.message import ElaChatToolCall, ElaChatToolStatusType


def _turn(chat) -> int:
    chat.sendUserMessage("hi")
    return chat.beginAssistantMessage()


def _question(key="q0", **kwargs) -> ElaChatQuestion:
    kwargs.setdefault("options", (ElaChatOption("A", "选 A"),))
    kwargs.setdefault("custom", True)
    return ElaChatQuestion(key=key, question="?", **kwargs)


class TestRestoreSettlesStreamingStatus:
    def test_midstream_export_import_lands_stopped(self, qapp, make):
        view = make(ElaChatView)
        mid = view.beginMessage()
        view.beginText(mid)
        view.appendText(mid, "半截回答")
        view.endText(mid)
        bundle = view.exportSession()
        assert bundle["messages"][0]["status"] == ElaChatStatusType.Streaming

        restored = make(ElaChatView)
        restored.importSession(bundle)
        assert restored.message(mid).status == ElaChatStatusType.Stopped
        assert restored.bubble(mid).isStreaming() is False
        # 批量恢复默认延迟物化：底部行在物化后才出现
        restored.materializeMessage(mid)
        assert restored.bubble(mid)._footer.isHidden() is False

    def test_settled_statuses_roundtrip_unchanged(self, qapp, make):
        view = make(ElaChatView)
        mid = view.beginMessage()
        view.appendText(mid, "x")
        view.endMessage(mid, ElaChatStatusType.Stopped)
        bundle = view.exportSession()
        assert bundle["messages"][0]["status"] == ElaChatStatusType.Stopped
        restored = make(ElaChatView)
        restored.importSession(bundle)
        assert restored.message(mid).status == ElaChatStatusType.Stopped
        assert restored.bubble(mid).isStreaming() is False

    def test_add_message_from_dict_settles_streaming(self, qapp, make):
        source = make(ElaChatView)
        mid = source.beginMessage()
        source.appendText(mid, "x")
        row = source.message(mid).toDict()
        assert row["status"] == ElaChatStatusType.Streaming

        target = make(ElaChatView)
        target.addMessageFromDict(row)
        assert target.message(mid).status == ElaChatStatusType.Stopped


class TestAddMessageIdConflicts:
    def test_duplicate_id_raises_and_keeps_single_bubble(self, qapp, make):
        view = make(ElaChatView)
        mid = view.addMessage(ElaChatRoleType.User, "first")
        with pytest.raises(ValueError):
            view.addMessage(ElaChatRoleType.User, "second", messageId=mid)
        assert view.count() == 1
        assert view.bubble(mid).text() == "first"
        assert len(view.contentWidget().findChildren(ElaChatBubble)) == 1

    @pytest.mark.parametrize("bad", ["1", 1.0, True], ids=["str", "float", "bool"])
    def test_non_int_id_raises_type_error(self, qapp, make, bad):
        view = make(ElaChatView)
        with pytest.raises(TypeError):
            view.addMessage(ElaChatRoleType.User, "x", messageId=bad)


class TestSingleGenerationFinish:
    def _wired(self, make):
        chat = make(ElaChatWidget)
        mock = make.track(ElaChatMockBackend(tickMs=0))
        binder = ElaChatStreamBinder(chat, worker=mock)
        mock.turnFinished.connect(binder.finish)
        return chat, mock, binder

    def test_stop_with_late_finish_emits_once_each(self, qapp, make):
        chat, mock, binder = self._wired(make)
        gen, msf = [], []
        chat.generationFinished.connect(lambda mid, st: gen.append((mid, st)))
        chat.chatView().messageStreamFinished.connect(
            lambda mid, st: msf.append((mid, st))
        )
        chat.stopRequested.connect(lambda: (binder.cancel(), mock.cancel()))
        binder.startTurn("hi")
        mid = chat.streamingMessageId()
        chat.stopGeneration()
        qapp.processEvents()
        assert gen == [(mid, ElaChatStatusType.Stopped)]
        assert msf == [(mid, ElaChatStatusType.Stopped)]

    def test_normal_finish_emits_once(self, qapp, make):
        chat, _mock, binder = self._wired(make)
        gen = []
        chat.generationFinished.connect(lambda mid, st: gen.append(st))
        turn = binder.startTurn("hi")
        binder.finish(turn)
        assert gen == [ElaChatStatusType.Done]

    def test_late_finish_after_error_reports_error(self, qapp, make):
        chat, _mock, binder = self._wired(make)
        gen = []
        chat.generationFinished.connect(lambda mid, st: gen.append(st))
        turn = binder.startTurn("hi")
        chat.setMessageError("boom", errorType="ServerError")
        binder.finish(turn)  # 迟到的正常收尾不得把错误回合报成 done
        assert gen == [ElaChatStatusType.Error]


class TestClearResetsSteer:
    def test_clear_drops_pending_steer(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.steerMessage("别动那个文件")
        assert chat.steerCount() == 1
        chat.clear()
        assert chat.steerCount() == 0


class TestRetrySettlesErrorStatus:
    def test_retry_clears_error_and_marks_stopped(self, qapp, make):
        chat = make(ElaChatWidget)
        view = chat.chatView()
        chat.sendUserMessage("q")
        mid = chat.beginAssistantMessage()
        view.beginText(mid)
        view.appendText(mid, "半截")
        view.endText(mid)
        view.setMessageError(mid, "boom", "ServerError")
        chat.setGenerating(False)

        assert chat.retryMessage(mid) is not None
        message = view.message(mid)
        assert (message.error, message.error_type) == ("", "")
        assert message.status == ElaChatStatusType.Stopped

    def test_retry_keeps_other_active_stream(self, qapp, make):
        chat = make(ElaChatWidget)
        view = chat.chatView()
        chat.addMessage(ElaChatRoleType.User, "q1")
        failed = chat.beginAssistantMessage()
        chat.endAssistantMessage(failed)
        view.setMessageError(failed, "boom")

        other = chat.beginAssistantMessage()
        assert chat.isGenerating() is True
        chat.retryMessage(failed)
        assert chat.isGenerating() is True
        assert chat.streamingMessageId() == other


class TestPermissionDockPromotion:
    @staticmethod
    def _pending(chat, mid, request_id):
        chat.chatView().beginPermission(
            mid, ElaChatPermission(request_id=request_id, action="edit")
        )

    def test_promote_after_clear_dock_and_settle(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        self._pending(chat, mid, "r1")
        self._pending(chat, mid, "r2")
        chat.clearPermissionDock()
        assert chat.permissionDock().card() is None

        assert chat.chatView().resolvePermission(mid, "r1", "allowed") is True
        card = chat.permissionDock().card()
        assert card is not None
        assert card.permission().request_id == "r2"

    def test_external_set_card_none_rearms(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        self._pending(chat, mid, "r1")
        chat.permissionDock().setCard(None)
        self._pending(chat, mid, "r2")
        card = chat.permissionDock().card()
        assert card is not None
        assert card.permission().request_id == "r2"

    def test_settling_queued_request_does_not_yank_current(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        self._pending(chat, mid, "r1")
        self._pending(chat, mid, "r2")
        current = chat.permissionDock().card()
        assert chat.chatView().resolvePermission(mid, "r2", "allowed") is True
        assert chat.permissionDock().card() is current

    def test_settle_after_card_deleted_is_safe(self, qapp, make):
        """宿主 dock 提前销毁交互卡后，落定不得碰已释放对象。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        part_id = bubble.beginPermission(
            ElaChatPermission(request_id="r1", action="edit")
        )
        card = bubble.interactivePermissionCard(part_id)
        assert card is not None
        sip.delete(card)

        assert bubble.resolvePermission("r1", "allowed") is True
        assert bubble.permissionCard("r1") is not None


class TestBubbleRestoreAndLayout:
    def test_suspended_reasoning_survives_style_switch(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        bubble.beginStream()
        bubble.beginReasoning()
        bubble.appendReasoning("推理正文")
        bubble.endReasoning(900)
        part_id = bubble.parts()[0].id

        bubble.setViewersSuspended(True)
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Collapse)
        bubble.setViewersSuspended(False)

        block = bubble._part_widgets[part_id]
        assert isinstance(block, ReasoningBlock)
        assert block.text() == "推理正文"

    def test_thinking_row_stays_before_streaming_viewer(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        bubble.beginStream()
        bubble.beginReasoning()
        bubble.appendReasoning("第一段")
        bubble.beginReasoning()  # 复用同一段（第二轮入口）
        layout = bubble._parts_layout
        viewer = bubble._part_widgets[bubble._current_reasoning_id]
        assert layout.indexOf(bubble.thinkingRow()) < layout.indexOf(viewer)

    @staticmethod
    def _docked(bubble) -> list:
        return [
            bubble._part_widgets[part.id].parentWidget() is bubble._stats_host
            for part in bubble.parts()
            if part.kind == ElaChatPartKindType.Stats
        ]

    def test_steps_mode_replay_matches_live(self, qapp, make):
        live = make(ElaChatBubble, ElaChatRoleType.Assistant)
        live.setStatsMode("steps")
        live.beginStream()
        live.setStepStats(ElaChatStats(prompt_tokens=1, completion_tokens=2))
        live.beginStep()
        live.setStepStats(ElaChatStats(prompt_tokens=3, completion_tokens=4))
        live.endStream()

        replay = make(ElaChatBubble, ElaChatRoleType.Assistant)
        replay.setStatsMode("steps")
        replay.setParts(tuple(live.parts()))

        assert self._docked(live) == [False, True]
        assert self._docked(replay) == self._docked(live)

    def test_permission_record_stays_before_later_text(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setToolGrouping(True)
        bubble.beginStream()
        # 两个上下文工具共用一张分组卡：按 part 计数会重复统计
        bubble.addToolCall("read", '{"path": "a"}', toolCallId="t1")
        bubble.addToolCall("read", '{"path": "b"}', toolCallId="t2")
        part_id = bubble.beginPermission(
            ElaChatPermission(request_id="r1", action="edit")
        )
        bubble.beginText()
        bubble.appendText("审批后的正文")
        bubble.endText()

        layout = bubble._parts_layout
        text_part = next(
            part for part in bubble.parts() if part.kind == ElaChatPartKindType.Text
        )
        bubble.resolvePermission("r1", "allowed")

        record = bubble._permission_cards[part_id]
        assert layout.indexOf(record) < layout.indexOf(
            bubble._part_widgets[text_part.id]
        )


class TestCompactionWidgets:
    def test_restored_compaction_accepts_more_summary(self, qapp, make):
        source = make(ElaChatBubble, ElaChatRoleType.Assistant)
        source.beginStream()
        part_id = source.beginCompaction()
        source.endCompaction(part_id)

        restored = make(ElaChatBubble, ElaChatRoleType.Assistant)
        restored.setParts(tuple(source.parts()))
        restored.appendCompactionSummary(part_id, "追加摘要")
        card = restored._part_widgets[part_id]
        assert isinstance(card, CompactionSeparator)
        assert card.summary() == "追加摘要"
        assert restored._find_part(part_id).text == "追加摘要"

    def test_aborted_turn_settles_compaction_card(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        part_id = bubble.beginCompaction()
        bubble.endStream(ElaChatStatusType.Stopped)
        card = bubble._part_widgets[part_id]
        assert card._status == ElaChatStatusType.Done
        assert "压缩中" not in card._label.text()

    @staticmethod
    def _press(widget) -> None:
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(widget.rect().center()),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(widget, event)

    def test_header_icon_and_chevron_toggle(self, qapp, make):
        card = make(CompactionSeparator)
        card.setSummary("摘要")
        assert card.opened() is False
        self._press(card._chevron)
        assert card.opened() is True
        self._press(card._icon)
        assert card.opened() is False


class TestLockedToolCardClick:
    def test_locked_pending_card_click_builds_nothing(self, qapp, make):
        call = ElaChatToolCall(
            id="c1", name="bash", status=ElaChatToolStatusType.Pending
        )
        card = make(ToolCallCard, None, tool_call=call, allowOpenWhilePending=False)
        assert card.isExpandable() is False
        card._header.click()
        assert card.isOpened() is False
        assert card._body_built is False

    def test_shell_pending_card_still_opens(self, qapp, make):
        call = ElaChatToolCall(
            id="c2", name="shell", status=ElaChatToolStatusType.Pending
        )
        card = make(ToolCallCard, None, tool_call=call, allowOpenWhilePending=True)
        card._header.click()
        assert card.isOpened() is True
        assert card._body_built is True


class TestPermissionRecordDirtyAnswer:
    def test_non_string_list_items_render(self, qapp, make):
        permission = ElaChatPermission(
            request_id="r1",
            action="question",
            questions=(ElaChatQuestion(key="q0", header="H", question="?"),),
            answer='{"q0": [1, 2]}',
            status=ElaChatPermissionStatusType.Allowed,
        )
        record = make(PermissionRecord, permission)
        assert record._raw_detail(permission) == "H: 1、2"


class TestViewContract:
    def test_type_and_strict_checks_on_mutators(self, qapp, make):
        view = make(ElaChatView)
        mid = view.addMessage(ElaChatRoleType.User, "x")
        with pytest.raises(TypeError):
            view.removeMessage("1")
        with pytest.raises(TypeError):
            view.removeMessagesFrom(None)
        with pytest.raises(TypeError):
            view.resolvePermission("1", "r1", "allowed")

        view.setStrictIds(True)
        with pytest.raises(KeyError):
            view.removeMessage(999)
        with pytest.raises(KeyError):
            view.resolvePermission(999, "r1", "allowed")
        view.setStrictIds(False)

        view.removeMessage(mid)
        assert view.count() == 0

    def test_read_getters_reject_non_int_ids(self, qapp, make):
        view = make(ElaChatView)
        calls = (
            lambda: view.pendingPermissions("1"),
            lambda: view.permissionCard("1", "r"),
            lambda: view.permissionAnswers("1", "r"),
            lambda: view.interactivePermissionCard("1", "r"),
            lambda: view.toolCalls("1"),
        )
        for call in calls:
            with pytest.raises(TypeError):
                call()

    def test_failed_import_keeps_current_session(self, qapp, make):
        view = make(ElaChatView)
        view.addMessage(ElaChatRoleType.User, "keep")
        bad = {
            "messages": [
                {"id": 5, "role": "assistant", "parts": []},
                {"id": 5, "role": "assistant", "parts": []},
            ]
        }
        with pytest.raises(ValueError):
            view.importSession(bad)
        assert view.count() == 1

    def test_restore_emits_message_added_once_with_content(self, qapp, make):
        view = make(ElaChatView)
        seen = []
        view.messageAdded.connect(
            lambda mid, role: seen.append((mid, view.message(mid).text))
        )
        restored = view.restoreMessages(
            [
                {"id": 1, "role": "user", "text": "u"},
                {
                    "id": 2,
                    "role": "assistant",
                    "parts": [
                        {"id": "p1", "kind": "text", "text": "hello", "status": "done"}
                    ],
                },
            ]
        )
        assert seen == list(zip(restored, ["u", "hello"]))


class TestInputAndToolbar:
    def test_queue_disabled_disables_send_and_enter_falls_through(self, qapp, make):
        chat = make(ElaChatWidget)
        inp = chat.chatInput()
        chat.setQueueEnabled(False)
        inp.setText("draft")
        inp.setGenerating(True)
        assert inp.submit() is False
        assert inp._button.isEnabled() is False
        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
        )
        assert inp._handle_edit_key(event) is False

    def test_mentions_requires_head_boundary(self, qapp, make):
        chat = make(ElaChatWidget)
        inp = chat.chatInput()
        inp.setText("prefix@Al ")
        inp._mentions.append(("id1", "@Al "))
        assert inp.mentions() == []
        inp.setText("@Al ")
        assert inp.mentions() == ["id1"]

    def test_toolbar_clear_removes_registered_stretch(self, qapp, make):
        toolbar = make(ElaChatToolBar)
        assert toolbar._trailing.count() == 0
        toolbar.addStretch("trailing")
        toolbar.addButton(text="x", zone="trailing")
        assert toolbar._trailing.count() == 2
        toolbar.clear()
        assert toolbar._trailing.count() == 0


class TestQuestionCommitPaths:
    @staticmethod
    def _card(make, questions, request_id="r1") -> PermissionCard:
        card = make(PermissionCard)
        card.setPermission(
            ElaChatPermission(
                request_id=request_id,
                action="question",
                questions=tuple(questions),
                status=ElaChatPermissionStatusType.Pending,
            )
        )
        return card

    def test_escape_then_submit_still_commits_text(self, qapp, make):
        card = self._card(make, (_question(),))
        card._enter_editing("q0")
        row = card._custom_row("q0")
        row.setEditorText("typed")
        row._on_editor_dismissed()  # Esc：退出编辑但保留文本
        assert row.editorText() == "typed"

        card._go_next()
        assert card.answers() == {"q0": ["typed"]}
        assert json.loads(card._build_answer()) == {"q0": "typed"}

    def test_escape_then_switch_tab_keeps_answer(self, qapp, make):
        card = self._card(make, (_question("q0"), _question("q1")))
        card._enter_editing("q0")
        row = card._custom_row("q0")
        row.setEditorText("draft")
        row._on_editor_dismissed()
        card._go_next()
        assert card.answers() == {"q0": ["draft"]}
        card._go_back()
        assert card._custom_row("q0").editorText() == "draft"

    def test_same_request_refresh_keeps_editor_and_draft(self, qapp, make):
        question = _question()
        permission = ElaChatPermission(
            request_id="r1",
            action="question",
            questions=(question,),
            status=ElaChatPermissionStatusType.Pending,
        )
        card = make(PermissionCard)
        card.setPermission(permission)
        card._enter_editing("q0")
        card._custom_row("q0").setEditorText("draft")
        card.setResponding(True)
        card.setPermission(permission)  # 两段式回填：同一 request

        assert card._editing == "q0"
        assert card._custom_row("q0").editorText() == "draft"
        card._go_next()
        assert json.loads(card._build_answer()) == {"q0": "draft"}

    def test_blank_custom_text_still_not_an_answer(self, qapp, make):
        card = self._card(make, (_question(),))
        card._enter_editing("q0")
        row = card._custom_row("q0")
        row.setEditorText("   ")
        row._on_editor_dismissed()
        card._go_next()
        assert card.answers() == {}
