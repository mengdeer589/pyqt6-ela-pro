"""回合变更汇总：聚合、显隐、持久化与视图 API。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatRoleType,
    ElaChatToolCall,
    ElaChatView,
)
from pyqt6_ela_pro.chat._changes import (
    changesFromParts,
    filesFromToolCall,
)


def _call(callId: str, path: str, before: str, after: str, additions=0, deletions=0):
    return ElaChatToolCall(
        id=callId,
        name="edit",
        arguments="{}",
        metadata={
            "files": [
                {
                    "file": path,
                    "before": before,
                    "after": after,
                    "additions": additions,
                    "deletions": deletions,
                }
            ]
        },
    )


class TestChangeModel:
    def test_metadata_and_args_fallback(self):
        call = _call("e1", "a.py", "old\n", "new\n", additions=2, deletions=1)
        files = filesFromToolCall(call)
        assert files[0].path == "a.py"
        assert files[0].additions == 2
        assert files[0].deletions == 1

        args_call = ElaChatToolCall(
            id="e2",
            name="edit",
            arguments='{"path": "b.py", "oldString": "a", "newString": "b"}',
        )
        files = filesFromToolCall(args_call)
        assert files[0].path == "b.py"

    def test_merge_same_path(self):
        from pyqt6_ela_pro.chat.message import ElaChatPart, ElaChatPartKindType

        parts = [
            ElaChatPart(
                id="e1",
                kind=ElaChatPartKindType.Tool,
                tool_call=_call("e1", "a.py", "a", "b", 3, 1),
            ),
            ElaChatPart(
                id="e2",
                kind=ElaChatPartKindType.Tool,
                tool_call=_call("e2", "a.py", "b", "c", 2, 4),
            ),
        ]
        changes = changesFromParts(parts)
        assert changes.count == 1
        assert changes.additions == 5
        assert changes.deletions == 5


class TestChangeBubble:
    def test_hidden_while_streaming_and_shown_after(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.addToolCall(
            "edit",
            "{}",
            "e1",
            tool_call=_call("e1", "a.py", "a", "b", 1, 1),
        )
        assert bubble._changes_host.isHidden()
        bubble.setToolCallResult("e1", "ok", ok=True)
        bubble.endStream()
        assert not bubble._changes_host.isHidden()
        changes = bubble.turnChanges()
        assert changes.count == 1
        assert changes.additions == 1
        assert changes.deletions == 1
        assert bubble._changes_row is not None

    def test_toggle(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        bubble.addToolCall(
            "edit",
            "{}",
            "e1",
            tool_call=_call("e1", "a.py", "a", "b", 1, 1),
        )
        bubble.endStream()
        assert not bubble._changes_host.isHidden()
        bubble.setChangeSummaryEnabled(False)
        assert bubble._changes_host.isHidden()
        bubble.setChangeSummaryEnabled(True)
        assert not bubble._changes_host.isHidden()


class TestChangeView:
    def test_view_api_and_restore(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.addToolCall(
            messageId,
            "edit",
            "{}",
            "e1",
            metadata=_call("e1", "a.py", "a", "b", 2, 1).metadata,
        )
        view.setToolCallResult(messageId, "e1", "ok", ok=True)
        view.endMessage(messageId)
        changes = view.turnChanges(messageId)
        assert changes.count == 1
        assert changes.additions == 2

        bundle = view.exportSession()
        other = make(ElaChatView)
        other.importSession(bundle, clear=True)
        restored = other.messages()[0]
        assert other.turnChanges(restored.id).additions == 2

    def test_view_toggle(self, qapp, make):
        view = make(ElaChatView)
        view.setChangeSummaryEnabled(False)
        assert not view.changeSummaryEnabled()
        view.setChangeSummaryEnabled(True)
        assert view.changeSummaryEnabled()
