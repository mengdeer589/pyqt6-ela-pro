"""Binder / Journal 流式回合契约：同一事件序列应得到同一消息语义。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatStats,
    ElaChatStatusType,
    ElaChatStreamBinder,
    ElaChatTurnJournal,
    ElaChatWidget,
)
from pyqt6_ela_pro.chat._flow import TurnStreamState


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0


def test_binder_and_journal_agree_on_semantic_snapshot(make, qapp):
    clock = _Clock()
    chat = make(ElaChatWidget)
    binder = ElaChatStreamBinder(chat, clock)
    chat.sendUserMessage("question")
    message_id = chat.beginAssistantMessage()
    turn = binder.beginTurn()

    journal = ElaChatTurnJournal(messageId=message_id, clock=clock).begin(message_id)

    clock.advance(100)
    binder.beginRound()
    binder.reasoning("thinking")

    clock.advance(200)
    binder.answer("hello")
    binder.toolStart("t1", "read", {"path": "a.txt"})
    binder.toolEnd("t1", "ok")
    stats = ElaChatStats(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    binder.stats(stats, ttftMs=120, tps=42)

    journal.reasoning("thinking")
    clock.advance(200)
    journal.endReasoning()
    journal.text("hello")
    journal.toolStart("t1", "read", {"path": "a.txt"})
    journal.toolEnd("t1", "ok")
    journal.stats(stats)

    binder.finish(turn, ElaChatStatusType.Done)
    journal.end(status=ElaChatStatusType.Done)

    view_message = chat.chatView().message(message_id)
    journal_message = journal.message()

    assert view_message is not None
    assert view_message.text == journal_message.text == "hello"
    assert view_message.reasoning == journal_message.reasoning == "thinking"
    assert [(c.name, c.status) for c in view_message.tool_calls] == [
        (c.name, c.status) for c in journal_message.tool_calls
    ]
    assert view_message.status == journal_message.status == ElaChatStatusType.Done
    assert view_message.stats is not None and journal_message.stats is not None
    assert view_message.stats.total_tokens == journal_message.stats.total_tokens


def test_shared_state_supports_zero_based_clock():
    """注入从 0 开始的时钟时，耗时仍按显式状态位判断而不是真值判断。"""

    now = [0.0]
    state = TurnStreamState(lambda: now[0])
    state.begin_turn()
    state.begin_round()
    now[0] = 1.5
    assert state.turn_duration_ms() == 1500
    assert state.round_duration_ms() == 1500


def test_reused_journal_discards_dropped_turn_buffers():
    """复用 journal 且上一回合未 ``end()`` 时，在途分片不能带进新回合。"""

    journal = ElaChatTurnJournal(clock=lambda: 0.0)
    journal.begin(1)
    journal.text("A")
    journal.text("B")
    journal.begin(2)
    journal.text("C")
    journal.text("D")
    assert journal.message().text == "CD"
