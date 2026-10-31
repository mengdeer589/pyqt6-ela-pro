"""输入区 shell 模式。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import ElaChatInput


class TestShellMode:
    def test_toggle_and_submit(self, qapp, make):
        inp = make(ElaChatInput)
        seen = []
        inp.shellSubmitted.connect(seen.append)
        inp.setShellMode(True)
        assert inp.shellMode()
        assert inp.textEdit().font().styleHint() is not None
        inp.setText("echo hi")
        assert inp.submit()
        assert seen == ["echo hi"]
        assert inp.text() == ""

    def test_escape_exits(self, qapp, make):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent

        inp = make(ElaChatInput)
        inp.setShellMode(True)
        inp.setText("x")
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
        )
        inp.textEdit().keyPressEvent(event)
        assert not inp.shellMode()
