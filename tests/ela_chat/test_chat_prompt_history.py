"""提示历史与草稿。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from pyqt6_ela_pro.chat import ElaChatInput, ElaChatPromptHistory, ElaChatSuggestion


def _press(widget, key):
    event = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    widget.textEdit().keyPressEvent(event)


def _insert_mention(widget, text: str) -> None:
    widget.setMentionProvider(
        lambda _query: [
            ElaChatSuggestion(id="alice", label="Al", insert_text="@Al ", kind="agent")
        ]
    )
    widget.setText(text)
    widget.popup().activateCurrent()


class TestPromptHistory:
    def test_add_previous_next(self):
        history = ElaChatPromptHistory()
        history.add("one")
        history.add("two")
        assert history.previous("normal", "draft")["text"] == "two"
        assert history.previous("normal")["text"] == "one"
        assert history.next("normal")["text"] == "two"
        entry = history.next("normal")
        assert entry["text"] == "draft"
        assert entry["draft"] is True
        assert history.next("normal") is None

    def test_roundtrip(self):
        history = ElaChatPromptHistory()
        history.add("a", [{"name": "x"}], [])
        restored = ElaChatPromptHistory.fromDict(history.toDict())
        assert restored.items("normal")[0]["text"] == "a"

    def test_input_up_down(self, qapp, make):
        inp = make(ElaChatInput)
        history = ElaChatPromptHistory()
        history.add("first")
        history.add("second")
        inp.setHistory(history)
        inp.setText("draft")
        _press(inp, Qt.Key.Key_Up)
        assert inp.text() == "second"
        _press(inp, Qt.Key.Key_Up)
        assert inp.text() == "first"
        _press(inp, Qt.Key.Key_Down)
        assert inp.text() == "second"
        _press(inp, Qt.Key.Key_Down)
        assert inp.text() == "draft"

    def test_draft_state(self, qapp, make):
        inp = make(ElaChatInput)
        inp.setText("hello")
        inp.addAttachment("a.txt", "a.txt", 3)
        state = inp.draftState()
        assert state["text"] == "hello"
        assert state["attachments"][0]["name"] == "a.txt"
        other = make(ElaChatInput)
        other.setDraftState(state)
        assert other.text() == "hello"
        assert other.attachmentCount() == 1

    def test_draft_state_restores_mentions(self, qapp, make):
        inp = make(ElaChatInput)
        _insert_mention(inp, "hello @Al")
        state = inp.draftState()
        assert state["mentions"][0]["id"] == "alice"

        other = make(ElaChatInput)
        other.setDraftState(state)
        assert other.mentions() == ["alice"]
        span = other.mentionSpans()[0]
        assert other.text()[span.start : span.end] == "@Al"

    def test_history_restores_mentions(self, qapp, make):
        inp = make(ElaChatInput)
        history = ElaChatPromptHistory()
        inp.setHistory(history)
        _insert_mention(inp, "hello @Al")
        assert inp.submit()

        other = make(ElaChatInput)
        other.setHistory(history)
        other.setText("draft")
        _press(other, Qt.Key.Key_Up)
        assert other.mentions() == ["alice"]
        span = other.mentionSpans()[0]
        assert other.text()[span.start : span.end] == "@Al"
