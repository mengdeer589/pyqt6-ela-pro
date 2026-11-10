"""工具类别 / 位置 / 计时：推导、序列化与 journal。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatToolCall,
    ElaChatToolKindType,
    ElaChatToolLocation,
    ElaChatTurnJournal,
)
from pyqt6_ela_pro.chat.blocks import toolKindOf, toolLocationsOf


class TestKindInference:
    def test_common_names(self):
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="read")) == ElaChatToolKindType.Read
        )
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="sandbox_read"))
            == ElaChatToolKindType.Read
        )
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="sandbox_edit"))
            == ElaChatToolKindType.Edit
        )
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="sandbox_shell"))
            == ElaChatToolKindType.Execute
        )
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="glob"))
            == ElaChatToolKindType.Search
        )
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="webfetch"))
            == ElaChatToolKindType.Fetch
        )
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="delegate_task"))
            == ElaChatToolKindType.Subagent
        )
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="submit_plan"))
            == ElaChatToolKindType.Think
        )
        assert (
            toolKindOf(ElaChatToolCall(id="1", name="unknown_thing"))
            == ElaChatToolKindType.Other
        )

    def test_explicit_kind_wins(self):
        call = ElaChatToolCall(id="1", name="read", kind=ElaChatToolKindType.Execute)
        assert toolKindOf(call) == ElaChatToolKindType.Execute

    def test_locations_from_args_or_metadata(self):
        call = ElaChatToolCall(
            id="1", name="read", arguments='{"path": "a.py", "line": 12}'
        )
        locations = toolLocationsOf(call)
        assert locations[0].path == "a.py"
        assert locations[0].line == 12
        call = call.withLocations([ElaChatToolLocation("b.py", 3)])
        assert toolLocationsOf(call)[0].line == 3


class TestToolCallSerialization:
    def test_roundtrip_new_fields(self):
        call = ElaChatToolCall(
            id="c1",
            name="edit",
            kind=ElaChatToolKindType.Edit,
            title="改 demo.py",
            locations=(ElaChatToolLocation("demo.py", 4),),
            parent_id="p1",
            started_at=1700000000.5,
            duration_ms=1234.0,
        )
        restored = ElaChatToolCall.fromDict(call.toDict())
        assert restored.kind == ElaChatToolKindType.Edit
        assert restored.title == "改 demo.py"
        assert restored.locations == call.locations
        assert restored.parent_id == "p1"
        assert restored.started_at == call.started_at
        assert restored.duration_ms == call.duration_ms

    def test_bad_kind_falls_back(self):
        call = ElaChatToolCall.fromDict({"id": "1", "name": "read", "kind": "wat"})
        assert call.kind == ""
        assert toolKindOf(call) == ElaChatToolKindType.Read


class TestJournalTiming:
    def test_duration_and_locations(self):
        now = [100.0]
        journal = ElaChatTurnJournal(messageId=1, clock=lambda: now[0]).begin(1)
        journal.toolStart(
            "c1",
            "read",
            "{}",
            kind="read",
            locations=[ElaChatToolLocation("a.py", 2)],
        )
        now[0] = 102.5
        journal.toolEnd("c1", "ok", ok=True)
        journal.end()
        call = journal.message().tool_calls[0]
        assert call.kind == "read"
        assert call.locations[0].path == "a.py"
        assert call.duration_ms == 2500.0
