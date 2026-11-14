"""子代理嵌套：父子工具卡、结果路由、持久化与 journal 重放。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatToolStatusType,
    ElaChatTurnJournal,
    ElaChatView,
    SubagentCard,
)
from pyqt6_ela_pro.chat.blocks import ToolCallCard


def _view(make) -> tuple[ElaChatView, int]:
    view = make(ElaChatView)
    view.resize(720, 520)
    messageId = view.beginMessage(ElaChatRoleType.Assistant)
    return view, messageId


class TestSubagentNesting:
    def test_parent_and_child(self, qapp, make):
        view, messageId = _view(make)
        parent = view.addToolCall(
            messageId,
            "delegate_task",
            '{"agent_name": "researcher", "task": "查资料"}',
            "p1",
        )
        child = view.addToolCall(
            messageId, "read", '{"path": "a.py"}', "c1", parentId="p1"
        )
        assert parent == "p1" and child == "c1"
        bubble = view.bubble(messageId)
        parent_card = bubble._tool_cards["p1"]
        assert isinstance(parent_card, SubagentCard)
        assert isinstance(parent_card.childCard("c1"), ToolCallCard)
        assert bubble.toolPanel().counts() == (0, 1)
        calls = view.toolCalls(messageId)
        assert [call.id for call in calls] == ["p1", "c1"]
        assert calls[1].parent_id == "p1"

        view.setToolCallResult(messageId, "c1", "文件内容", ok=True)
        assert parent_card.childCard("c1").result() == "文件内容"
        assert parent_card.childCard("c1").status() == ElaChatToolStatusType.Done

        view.setToolCallResult(messageId, "p1", "最终结论", ok=True)
        assert parent_card.result() == "最终结论"
        assert bubble.toolPanel().counts() == (1, 1)
        view.endMessage(messageId)

    def test_bundle_roundtrip(self, qapp, make):
        view, messageId = _view(make)
        view.addToolCall(messageId, "delegate_task", '{"task": "x"}', "p1")
        view.addToolCall(messageId, "grep", '{"pattern": "x"}', "c1", parentId="p1")
        view.setToolCallResult(messageId, "c1", "匹配", ok=True)
        view.setToolCallResult(messageId, "p1", "完成", ok=True)
        view.endMessage(messageId)

        bundle = view.exportSession()
        other = make(ElaChatView)
        other.importSession(bundle, clear=True)
        calls = {call.id: call for call in other.toolCalls(other.messages()[0].id)}
        assert calls["c1"].parent_id == "p1"
        assert calls["c1"].status == ElaChatToolStatusType.Done
        assert calls["p1"].result == "完成"

    def test_child_before_parent_falls_back(self, qapp, make):
        view, messageId = _view(make)
        view.bubble(messageId).setToolGrouping(False)
        view.addToolCall(
            messageId, "read", '{"path": "a.py"}', "c1", parentId="missing"
        )
        view.addToolCall(messageId, "delegate_task", "{}", "p1")
        calls = {call.id: call for call in view.toolCalls(messageId)}
        assert calls["c1"].parent_id == ""
        bubble = view.bubble(messageId)
        assert isinstance(bubble._tool_cards["c1"], ToolCallCard)
        assert not isinstance(bubble._tool_cards["c1"], SubagentCard)

    def test_many_children_are_lazy(self, qapp, make):
        view, messageId = _view(make)
        view.addToolCall(messageId, "delegate_task", "{}", "p1")
        for index in range(30):
            view.addToolCall(
                messageId,
                "read",
                '{"path": "a.py"}',
                f"c{index}",
                parentId="p1",
            )
        bubble = view.bubble(messageId)
        parent = bubble._tool_cards["p1"]
        assert isinstance(parent, SubagentCard)
        assert all(not parent.childCard(f"c{index}")._body_built for index in range(30))
        assert len(parent.childCalls()) == 30

    def test_large_child_set_is_paged_and_updates_pending(self, qapp, make):
        view, messageId = _view(make)
        view.addToolCall(messageId, "delegate_task", "{}", "p1")
        for index in range(100):
            view.addToolCall(
                messageId,
                "read",
                '{"path": "a.py"}',
                f"c{index}",
                parentId="p1",
            )
        bubble = view.bubble(messageId)
        parent = bubble._tool_cards["p1"]
        assert not parent._child_cards
        assert len(parent._pending_children) == 100
        assert len(parent.childCalls()) == 100

        view.setToolCallResult(messageId, "c0", "内容", ok=True)
        assert not parent._child_cards
        assert parent.childCalls()[0].result == "内容"

        parent.setOpened(True)
        assert len(parent._child_cards) == 16
        assert len(parent._pending_children) == 84

    def test_nested_subagent(self, qapp, make):
        view, messageId = _view(make)
        view.addToolCall(messageId, "delegate_task", "{}", "p1")
        view.addToolCall(messageId, "delegate_task", "{}", "s1", parentId="p1")
        view.addToolCall(messageId, "read", "{}", "c1", parentId="s1")
        bubble = view.bubble(messageId)
        parent = bubble._tool_cards["p1"]
        assert isinstance(parent, SubagentCard)
        nested = parent.childCard("s1")
        assert isinstance(nested, SubagentCard)
        assert isinstance(nested.childCard("c1"), ToolCallCard)
        assert bubble.toolPanel().counts() == (0, 1)

    def test_clear_tool_calls_is_safe(self, qapp, make):
        view, messageId = _view(make)
        view.addToolCall(messageId, "delegate_task", "{}", "p1")
        view.addToolCall(messageId, "read", "{}", "c1", parentId="p1")
        view.clearToolCalls(messageId)
        assert view.toolCalls(messageId) == []
        qapp.processEvents()


class TestSubagentJournal:
    def test_replay_nests_children(self, qapp, make):
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.toolStart("p1", "delegate_task", "{}", kind="subagent")
        journal.toolStart("c1", "read", "{}", parentId="p1")
        journal.toolEnd("c1", "内容", ok=True)
        journal.toolEnd("p1", "结论", ok=True)
        journal.end()

        view = make(ElaChatView)
        journal.replayInto(view)
        messageId = view.messages()[0].id
        bubble = view.bubble(messageId)
        parent = bubble._tool_cards["p1"]
        assert isinstance(parent, SubagentCard)
        assert parent.childCard("c1").result() == "内容"
        assert parent.result() == "结论"
        parts = [
            part
            for part in view.message(messageId).parts
            if part.kind == ElaChatPartKindType.Tool
        ]
        assert [part.tool_call.parent_id for part in parts] == ["", "p1"]
