"""Ctrl+Enter 备选投递。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from pyqt6_ela_pro.chat import ElaChatSuggestion, ElaChatWidget


def _ctrl_enter(widget):
    event = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ControlModifier,
    )
    widget.chatInput().textEdit().keyPressEvent(event)


def _with_mention(chat: ElaChatWidget, text: str) -> None:
    inp = chat.chatInput()
    inp.setMentionProvider(
        lambda _query: [
            ElaChatSuggestion(id="alice", label="Al", insert_text="@Al ", kind="agent")
        ]
    )
    inp.setText(text)
    inp.popup().activateCurrent()


class TestAlternateDelivery:
    def test_steer_when_generating(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.chatInput().setText("插一句")
        _ctrl_enter(chat)
        assert chat.steerCount() == 1
        assert chat.chatInput().text() == ""

    def test_send_when_idle(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.chatInput().setText("普通")
        _ctrl_enter(chat)
        assert chat.chatView().count() == 1
        assert chat.chatInput().text() == ""

    def test_idle_send_keeps_mentions(self, qapp, make):
        chat = make(ElaChatWidget)
        _with_mention(chat, "@Al")
        _ctrl_enter(chat)
        message = chat.chatView().lastMessage()
        assert message.text == "@Al"
        assert len(message.mentions) == 1
        mention = message.mentions[0]
        assert message.text[mention.start : mention.end] == "@Al"

    def test_steer_disabled_falls_back_to_queue(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.setSteerEnabled(False)
        chat.chatInput().setText("排队去")
        _ctrl_enter(chat)
        assert chat.steerCount() == 0
        assert chat.queueCount() == 1
        assert chat.queuedMessages()[0]["text"] == "排队去"
        assert chat.chatInput().text() == ""

    def test_steer_disabled_falls_back_to_queue_even_when_queue_disabled(
        self, qapp, make
    ):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.setSteerEnabled(False)
        chat.setQueueEnabled(False)
        chat.chatInput().setText("排队去")
        _ctrl_enter(chat)
        assert chat.steerCount() == 0
        assert chat.queueCount() == 1

    def test_steer_keeps_mentions(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        _with_mention(chat, "@Al")
        _ctrl_enter(chat)
        pending = [
            message
            for message in chat.chatView().messages()
            if message.delivery == "steer"
        ]
        assert len(pending) == 1
        mention = pending[0].mentions[0]
        assert pending[0].text[mention.start : mention.end] == "@Al"
        assert chat.steerMessages()[0]["mentions"]


class TestFollowUpDelivery:
    def test_default_is_queue(self, qapp, make):
        chat = make(ElaChatWidget)
        assert chat.followUpDelivery() == "queue"

    def test_enter_uses_steer_when_configured(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.setFollowUpDelivery("steer")
        chat.chatInput().setText("插一句")
        chat.chatInput().submit()
        assert chat.steerCount() == 1
        assert chat.queueCount() == 0

    def test_enter_falls_back_to_queue_when_steer_disabled(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.setFollowUpDelivery("steer")
        chat.setSteerEnabled(False)
        chat.chatInput().setText("排队")
        chat.chatInput().submit()
        assert chat.steerCount() == 0
        assert chat.queueCount() == 1

    def test_enter_is_blocked_when_queue_disabled(self, qapp, make):
        """``queueEnabled=False`` 仍按输入区原语义拦截生成中提交。"""
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.setFollowUpDelivery("steer")
        chat.setSteerEnabled(False)
        chat.setQueueEnabled(False)
        chat.chatInput().setText("直接发")
        assert chat.chatInput().submit() is False
        assert chat.steerCount() == 0
        assert chat.queueCount() == 0
        assert chat.chatView().count() == 0

    def test_ctrl_enter_uses_the_other_channel(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.setFollowUpDelivery("steer")
        chat.chatInput().setText("排队")
        _ctrl_enter(chat)
        assert chat.steerCount() == 0
        assert chat.queueCount() == 1

    def test_invalid_delivery_raises(self, qapp, make):
        chat = make(ElaChatWidget)
        with pytest.raises(ValueError):
            chat.setFollowUpDelivery("sideways")
