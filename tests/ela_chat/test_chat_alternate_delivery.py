"""Ctrl+Enter 备选投递。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from pyqt6_ela_pro.chat import ElaChatWidget


def _ctrl_enter(widget):
    event = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ControlModifier,
    )
    widget.chatInput().textEdit().keyPressEvent(event)


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
