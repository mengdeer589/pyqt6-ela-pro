"""2026-11 审查回归：数据完整性 / 回合收尾 / 搜索 / 轨迹。"""

from __future__ import annotations

import json

import pytest

from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatInput,
    ElaChatMessage,
    ElaChatOption,
    ElaChatPart,
    SESSION_SCHEMA_VERSION,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatQuestion,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
    ElaChatView,
    ElaChatWidget,
    formatCost,
    migrateSessionBundle,
)
from pyqt6_ela_pro.chat._changes import changesFromParts, summaryChangesFromParts
from pyqt6_ela_pro.chat._trace import buildTraceRows
from pyqt6_ela_pro.chat._usage import stats_from_usage
from pyqt6_ela_pro.chat.journal import ElaChatTurnJournal
from pyqt6_ela_pro.chat.prompt_history import ElaChatPromptHistory
from pyqt6_ela_pro.chat.session import ElaChatSessionStats


class TestMessageTolerance:
    def test_question_options_ignore_none(self):
        question = ElaChatQuestion.fromDict(
            {"key": "k", "options": [{}, {"label": "a"}]}
        )
        assert [item.label for item in question.options] == ["a"]
        assert question.toDict()["options"] == [{"label": "a", "description": ""}]

    def test_permission_questions_ignore_none(self):
        permission = ElaChatPermission.fromDict(
            {
                "request_id": "r",
                "action": "q",
                "questions": [{}, {"key": "k", "options": [{}, {"label": "a"}]}],
            }
        )
        assert len(permission.questions) == 1
        assert len(permission.questions[0].options) == 1
        assert permission.toDict()["questions"][0]["options"][0]["label"] == "a"


class TestJournalRecovery:
    def test_batched_append_round_trips(self, tmp_path):
        journal = ElaChatTurnJournal(messageId=1, clock=lambda: 0.0)
        journal.begin(1)
        journal.beginStep()
        journal.text("a")
        first = journal.dumpsNewLines()
        journal.text("b")
        second = journal.dumpsNewLines()
        path = tmp_path / "turn.jsonl"
        path.write_text(first, encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(second)
        restored = ElaChatTurnJournal.fromLines([path.read_text(encoding="utf-8")])
        assert restored.message().text == "ab"

    def test_append_to_and_load_from_file(self, tmp_path):
        path = tmp_path / "journal.jsonl"
        journal = ElaChatTurnJournal(messageId=1, clock=lambda: 0.0)
        journal.begin(1)
        journal.beginStep()
        journal.text("a")
        assert journal.appendTo(path) > 0
        journal.text("b")
        assert journal.appendTo(path) > 0
        restored = ElaChatTurnJournal.loadFrom(path)
        assert restored.message().text == "ab"

    def test_compaction_count_and_error_type_survive(self):
        journal = ElaChatTurnJournal(messageId=1, clock=lambda: 0.0)
        journal.begin(1, agent="a", model="m")
        journal.beginStep()
        journal.beginCompaction()
        journal.compactionSummary("sum")
        journal.endCompaction(historyCount=42)
        journal.end(
            ElaChatStatusType.Error,
            "boom",
            errorType="Timeout",
        )
        message = journal.message()
        assert message.agent == "a"
        assert message.model == "m"
        assert message.error_type == "Timeout"
        compaction = next(
            part
            for part in message.parts
            if part.kind == ElaChatPartKindType.Compaction
        )
        assert compaction.history_count == 42


class TestUsageAndStats:
    def test_dict_usage(self):
        stats = stats_from_usage(
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
        assert stats.prompt_tokens == 10
        assert stats.completion_tokens == 5
        assert stats.total_tokens == 15

    def test_tiny_cost_not_zero(self):
        assert formatCost(0.00004) == "<$0.0001"

    def test_zero_last_step_falls_back(self):
        old = ElaChatMessage(
            id=1,
            role=ElaChatRoleType.Assistant,
            created_at=1.0,
            parts=(
                ElaChatPart(
                    id="s1",
                    kind=ElaChatPartKindType.Stats,
                    stats=ElaChatStats(prompt_tokens=1000),
                ),
            ),
        )
        new = ElaChatMessage(
            id=2,
            role=ElaChatRoleType.Assistant,
            created_at=2.0,
            parts=(
                ElaChatPart(
                    id="s2",
                    kind=ElaChatPartKindType.Stats,
                    stats=ElaChatStats(),
                ),
            ),
        )
        stats = ElaChatSessionStats.fromMessages([old, new], 10000)
        assert stats.total_tokens == 1000
        assert stats.last_activity == 1.0


class TestPromptHistory:
    def test_attachments_and_draft_survive(self):
        history = ElaChatPromptHistory()
        history.add("x", [{"name": "a.txt", "path": "C:/a.txt"}])
        text = json.dumps(history.toDict())
        restored = ElaChatPromptHistory.fromDict(json.loads(text))
        assert restored.items()[0]["attachments"][0]["name"] == "a.txt"

        draft = {
            "text": "draft",
            "attachments": [{"name": "d.png", "path": "C:/d.png"}],
            "mentions": [],
        }
        assert restored.previous("normal", draft)["text"] == "x"
        back = restored.next("normal")
        assert back["draft"] is True
        assert back["attachments"][0]["name"] == "d.png"

    def test_attachment_only_entry_survives(self):
        history = ElaChatPromptHistory()
        history.add("", [{"name": "only.png"}])
        restored = ElaChatPromptHistory.fromDict(history.toDict())
        assert len(restored.items()) == 1


class TestChangesConsistency:
    def test_summary_matches_full(self):
        call = ElaChatToolCall(
            id="c",
            name="edit",
            arguments='{"path":"a.py","oldString":"a\\nb","newString":"a\\nc"}',
            status=ElaChatStatusType.Done,
        )
        part = ElaChatPart(id="p", kind=ElaChatPartKindType.Tool, tool_call=call)
        summary = summaryChangesFromParts([part])
        full = changesFromParts([part])
        assert (summary.additions, summary.deletions) == (
            full.additions,
            full.deletions,
        )


class TestTraceFailure:
    def test_top_level_failed_tool_marks_turn(self):
        call = ElaChatToolCall(
            id="t1", name="shell", status="error", duration_ms=300, result="boom"
        )
        message = ElaChatMessage(
            id=2,
            role=ElaChatRoleType.Assistant,
            duration_ms=2200,
            parts=(
                ElaChatPart(
                    id="p1",
                    kind=ElaChatPartKindType.Tool,
                    tool_call=call,
                    step=1,
                    status=ElaChatStatusType.Done,
                ),
            ),
        )
        user = ElaChatMessage(id=1, role=ElaChatRoleType.User, text="q")
        result = buildTraceRows([user, message])
        assert result.error_count == 1
        assert result.rows[0].error_below is True


class TestQueueReorder:
    def test_dock_reorder_signal_moves_item(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.enqueueMessage("a")
        chat.enqueueMessage("b")
        second = chat.queuedMessages()[1]["id"]
        chat.queueDock().reorderRequested.emit(second, 0)
        assert [item["text"] for item in chat.queuedMessages()] == ["b", "a"]


class TestQueueSendUndo:
    def test_send_now_clears_undo_history(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.enqueueMessage("a")
        queue_id = chat.queuedMessages()[0]["id"]
        chat.sendQueuedNow(queue_id)
        assert chat.canUndoQueue() is False


class TestToolPartStatus:
    def test_successful_tool_part_stays_done_on_error_turn(self, qapp, make):

        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        call_id = bubble.addToolCall("read", "{}")
        bubble.setToolCallResult(call_id, "ok", ok=True)
        bubble.setError("boom", "Timeout")
        part = next(
            item for item in bubble.parts() if item.kind == ElaChatPartKindType.Tool
        )
        assert part.tool_call.status == ElaChatToolStatusType.Done
        assert part.status == ElaChatStatusType.Done


class TestInputToolbar:
    def test_clear_keeps_builtins_alive(self, qapp, make):

        widget = make(ElaChatInput)
        widget.toolBar().clear()
        widget.setGenerating(True)
        widget.setShellMode(True)
        widget.setShellMode(False)
        assert widget.toolBar().count() >= 4


class TestSearchGhostHits:
    def test_removing_message_prunes_hits(self, qapp, make):
        chat = make(ElaChatWidget)
        view = chat.chatView()
        first = view.addMessage(ElaChatRoleType.Assistant, "needle one")
        view.addMessage(ElaChatRoleType.Assistant, "needle two")
        assert view.searchText("needle") == 2
        view.removeMessage(first)
        assert len(view.searchHits()) == 1
        assert view.searchIndex() == 0


class TestQueueEditAttachments:
    def test_edit_replaces_attachments_even_with_empty_list(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.chatInput().addAttachment("draft.txt", "C:/draft.txt", 1)
        chat.enqueueMessage("queued", [])
        queue_id = chat.queuedMessages()[0]["id"]
        chat.editQueuedMessage(queue_id)
        assert chat.chatInput().attachments() == []


class TestPermissionSegments:
    def test_segments_disabled_while_responding(self, qapp, make):
        chat = make(ElaChatWidget)
        message_id = chat.beginAssistantMessage()
        request = ElaChatPermission(
            request_id="r",
            action="question",
            questions=(
                ElaChatQuestion(
                    key="a", header="A", options=(ElaChatOption(label="x"),)
                ),
                ElaChatQuestion(
                    key="b", header="B", options=(ElaChatOption(label="y"),)
                ),
            ),
        )
        part_id = chat.chatView().beginPermission(message_id, request)
        card = chat.chatView().bubble(message_id).interactivePermissionCard(part_id)
        card.setResponding(True)
        assert all(not segment.isEnabled() for segment in card._segments)
        card._goto(1)
        assert card.tabIndex() == 0


class TestSubagentUpdates:
    def test_same_child_id_updates_and_unknown_result_ignored(self, qapp, make):
        chat = make(ElaChatWidget)
        message_id = chat.beginAssistantMessage()
        view = chat.chatView()
        parent_id = view.addToolCall(message_id, "delegate_task", "{}", "p1")
        bubble = view.bubble(message_id)
        parent = bubble._tool_cards[parent_id]
        parent.addChild(ElaChatToolCall(id="c1", name="read", arguments='{"path":"a"}'))
        parent.addChild(
            ElaChatToolCall(
                id="c1",
                name="read",
                arguments='{"path":"b"}',
                result="ok",
                status=ElaChatToolStatusType.Done,
            )
        )
        assert "b" in parent.toolCall("c1").arguments
        before = parent.result()
        parent.updateResult("typo", "should be ignored", ok=False)
        assert parent.result() == before


class TestRenderQueueRecovery:
    def test_exception_restores_updates(self, qapp, make):
        view = make(ElaChatView)
        message_id = view.addMessage(ElaChatRoleType.Assistant, "x")
        view._render_queue.append(message_id)
        view._scroll.viewport().setUpdatesEnabled(False)
        original = view._materialize_shell

        def boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        view._materialize_shell = boom
        try:
            view._process_render_queue()
        finally:
            view._materialize_shell = original
        assert view._scroll.viewport().updatesEnabled() is True
        assert not view._render_queue


class TestSearchLegacy:
    def test_legacy_assistant_text_is_searchable(self, qapp, make):
        chat = make(ElaChatWidget)
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.Assistant, "legacy needle")
        assert view.searchText("needle") == 1

    def test_search_bar_shows_preview(self, qapp, make):
        chat = make(ElaChatWidget)
        view = chat.chatView()
        view.addMessage(ElaChatRoleType.User, "前文 needle 后文")
        bar = view.showSearchBar("needle")
        assert "needle" in bar.preview()


class TestBundleMigration:
    def test_v0_bundle_is_migrated(self, qapp, make):
        bundle = {"messages": [{"role": "user", "text": "hi"}]}
        migrated = migrateSessionBundle(bundle)
        assert migrated["schema"] == SESSION_SCHEMA_VERSION
        assert migrated["view"] == {}
        view = make(ElaChatView)
        assert view.importSession(bundle, clear=True) == 1

    def test_future_bundle_is_rejected(self, qapp, make):
        view = make(ElaChatView)
        with pytest.raises(ValueError):
            view.importSession({"schema": 99, "messages": []}, clear=True)


class TestQueueUndo:
    def test_clear_drops_undo_history(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.enqueueMessage("a")
        chat.clear()
        assert chat.canUndoQueue() is False


class TestErrorTurn:
    def test_empty_error_clears_state(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        chat.chatView().setMessageError(mid, "boom", "Timeout")
        chat.chatView().setMessageError(mid, "")
        message = chat.chatView().message(mid)
        assert message.error == ""
        assert message.status != ElaChatStatusType.Error

    def test_error_emits_stream_finished(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        seen = []
        chat.chatView().messageStreamFinished.connect(
            lambda message_id, status: seen.append((message_id, status))
        )
        chat.chatView().setMessageError(mid, "boom", "Timeout")
        assert seen == [(mid, ElaChatStatusType.Error)]


class TestStreamIdempotence:
    def test_end_stream_finishes_once(self, qapp, make):

        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        seen = []
        bubble.streamFinished.connect(lambda: seen.append(1))
        bubble.beginStream()
        bubble.endStream()
        bubble.endStream()
        assert seen == [1]


class TestTurnIdentity:
    def test_ending_old_message_keeps_current_stream(self, qapp, make):
        chat = make(ElaChatWidget)
        first = chat.beginAssistantMessage()
        chat.endAssistantMessage(first)
        second = chat.beginAssistantMessage()
        chat.endAssistantMessage(first)
        assert chat.streamingMessageId() == second
        assert chat.isGenerating() is True


class TestViewRemoval:
    def test_removing_streaming_message_stops_generating(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        chat.chatView().removeMessage(mid)
        assert chat.streamingMessageId() is None
        assert chat.isGenerating() is False
