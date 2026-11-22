"""崩溃恢复日志的往返 / 复用回归（P0：载入后不能导空、不能与旧回合串内容）。"""

from __future__ import annotations

from pyqt6_ela_pro.chat.journal import ElaChatTurnJournal


def test_loaded_journal_keeps_events_and_dumps():
    journal = ElaChatTurnJournal(1).begin()
    journal.text("旧内容")
    journal.end()
    raw = journal.dumps()

    loaded = ElaChatTurnJournal.fromLines(raw)

    assert loaded.events()
    assert loaded.dumps() == raw


def test_loaded_journal_reuse_does_not_merge_old_turn():
    journal = ElaChatTurnJournal(1).begin()
    journal.text("旧内容")
    journal.end()
    loaded = ElaChatTurnJournal.fromLines(journal.dumps())

    loaded.begin(2)
    loaded.text("新内容")
    loaded.end()

    assert loaded.message().text == "新内容"


def test_duplicate_tool_start_keeps_settled_result():
    journal = ElaChatTurnJournal(1).begin()
    journal.toolStart("c1", "read", '{"path": "a"}')
    journal.toolEnd("c1", "OK", True)
    journal.toolStart("c1", "read", '{"path": "b"}')
    journal.end()

    message = journal.message()
    call = next(part.tool_call for part in message.parts if part.tool_call is not None)

    assert call.status == "done"
    assert call.result == "OK"
    assert call.arguments == '{"path": "b"}'
