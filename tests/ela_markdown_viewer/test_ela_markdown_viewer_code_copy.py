"""Tests for ElaMarkdownViewer P3 code block enhancements.

Covers: code card without language header (Typora style), floating copy
buttons (hover, copy, feedback, resync on re-render).
"""

from __future__ import annotations

from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QTextTable
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.ela_markdown_viewer import (
    _CODE_LANG_PROPERTY,
    ElaMarkdownViewer,
)


def _tables(viewer: ElaMarkdownViewer) -> list:
    result = []
    stack = [viewer.document().rootFrame()]
    while stack:
        frame = stack.pop()
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                result.append(child)
            stack.append(child)
    result.sort(key=lambda t: t.firstPosition())
    return result


def _code_tables(viewer: ElaMarkdownViewer) -> list:
    return [t for t in _tables(viewer) if viewer._is_code_table(t)]


class TestCodeCard:
    def test_single_row_with_language_property(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\ndef foo():\n    return 1\n```")

        tables = _code_tables(v)
        assert len(tables) == 1
        table = tables[0]
        # Typora 风格：语言不占头栏，存表格式供复制按钮 tooltip 使用
        assert table.rows() == 1
        assert table.format().property(_CODE_LANG_PROPERTY) == "python"
        code_cell = table.cellAt(0, 0)
        cursor = code_cell.firstCursorPosition()
        cursor.setPosition(
            code_cell.lastCursorPosition().position(),
            cursor.MoveMode.KeepAnchor,
        )
        assert "def foo():" in cursor.selection().toPlainText()
        v.deleteLater()

    def test_no_language_single_row(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```\nplain\n```")

        tables = _code_tables(v)
        assert len(tables) == 1
        assert tables[0].rows() == 1
        # 未设置的自定义属性在 Qt6 里读回 None / 空——断言「假值」而不是等于空串
        # （PyQt5 时代是 ""，见 MIGRATION）
        assert not tables[0].format().property(_CODE_LANG_PROPERTY)
        v.deleteLater()

    def test_code_table_text_strips_header(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nx = 1\ny = 2\n```")

        table = _code_tables(v)[0]
        assert v._code_table_text(table) == "x = 1\ny = 2"
        v.deleteLater()

    def test_copy_button_tooltip_has_language(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(420, 320)
        v.setMarkdown("```python\nx = 1\n```")
        v.show()
        qapp.processEvents()
        for _ in range(20):
            QTest.qWait(10)
            if v._code_buttons:
                break
        assert v._code_buttons
        assert "python" in v._code_buttons[0].toolTip()
        v.deleteLater()


class TestCopyButtons:
    def _prepare(self, qapp, markdown: str, size=(420, 320)):
        v = ElaMarkdownViewer()
        v.resize(*size)
        v.setMarkdown(markdown)
        v.show()
        qapp.processEvents()
        for _ in range(40):
            QTest.qWait(20)
            if not v._code_buttons:
                break
            if all(not rect.isNull() for rect in v._code_button_rects):
                break
        return v

    def test_buttons_created_per_code_block(self, qapp):
        v = self._prepare(qapp, "```python\nx = 1\n```\n\ntext\n\n```\ny = 2\n```")
        assert len(v._code_buttons) == 2
        assert all(not b.isVisible() for b in v._code_buttons)
        v.close()
        v.deleteLater()

    def test_hover_shows_button(self, qapp):
        v = self._prepare(qapp, "```python\nx = 1\n```")
        rect = v._code_button_rects[0]
        assert not rect.isNull()

        viewport = v._text_browser.viewport()
        assert viewport.hasMouseTracking()

        self._send_move(viewport, QPointF(rect.center()))
        assert v._code_buttons[0].isVisible()

        self._send_move(viewport, QPointF(2, viewport.height() - 2))
        assert not v._code_buttons[0].isVisible()
        v.close()
        v.deleteLater()

    def test_leave_hides_button(self, qapp):
        v = self._prepare(qapp, "```python\nx = 1\n```")
        rect = v._code_button_rects[0]
        viewport = v._text_browser.viewport()
        self._send_move(viewport, QPointF(rect.center()))
        assert v._code_buttons[0].isVisible()

        outside = viewport.mapToGlobal(QPoint(int(rect.center().x()), -40))
        v._on_viewport_leave(outside)
        assert not v._code_buttons[0].isVisible()
        v.close()
        v.deleteLater()

    def test_leave_keeps_button_when_cursor_over_block(self, qapp):
        v = self._prepare(qapp, "```python\nx = 1\n```")
        rect = v._code_button_rects[0]
        viewport = v._text_browser.viewport()
        self._send_move(viewport, QPointF(rect.center()))
        assert v._code_buttons[0].isVisible()

        # 光标仍在代码块（按钮）范围内：保持显示，避免点击前消失
        over_button = viewport.mapToGlobal(
            QPoint(int(rect.right()) - 10, int(rect.top()) + 10)
        )
        v._on_viewport_leave(over_button)
        assert v._code_buttons[0].isVisible()
        v.close()
        v.deleteLater()

    @staticmethod
    def _send_move(viewport, pos) -> None:
        QApplication.sendEvent(
            viewport,
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(pos),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    def test_click_copies_and_emits(self, qapp, requires_clipboard):
        v = self._prepare(qapp, "```python\nx = 1\ny = 2\n```")
        received = []
        v.codeCopied.connect(received.append)

        v._copy_code_block(0)
        qapp.processEvents()
        assert received == ["x = 1\ny = 2"]
        assert (
            _wait_for_clipboard(qapp, "x = 1\ny = 2", lambda: v._copy_code_block(0))
            == "x = 1\ny = 2"
        )
        v.close()
        v.deleteLater()

    def test_button_click_triggers_copy(self, qapp, requires_clipboard):
        v = self._prepare(qapp, "```python\nx = 1\n```")
        received = []
        v.codeCopied.connect(received.append)
        v._code_buttons[0].click()
        qapp.processEvents()
        assert received == ["x = 1"]
        assert _wait_for_clipboard(qapp, "x = 1", v._code_buttons[0].click) == "x = 1"
        v.close()
        v.deleteLater()

    def test_restore_icon_is_safe(self, qapp):
        v = self._prepare(qapp, "```python\nx = 1\n```")
        v._copy_code_block(0)
        v._restore_code_button_icon(v._code_buttons[0])
        v.close()
        v.deleteLater()

    def test_buttons_resync_after_rerender(self, qapp):
        v = self._prepare(qapp, "```python\nx = 1\n```")
        assert len(v._code_buttons) == 1

        v.setMarkdown("no code here")
        QTest.qWait(150)
        assert len(v._code_buttons) == 0
        v.close()
        v.deleteLater()

    def test_context_menu_copy_code_uses_stored_text(self, qapp):
        v = self._prepare(qapp, "```js\nconst a = 1;\n```")
        menu = v._create_context_menu()
        labels = [action.text() for action in menu.actions()]
        assert "复制代码块" in labels
        menu.deleteLater()
        v.close()
        v.deleteLater()
