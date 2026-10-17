"""Tests for ElaMarkdownViewer P1 polish batch.

Covers: drag guard for copy buttons, streaming highlight throttle,
streaming caret, formula tooltip/copy, PDF export.
"""

from __future__ import annotations

import pytest
from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QPixmap, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.ela_markdown_viewer import (
    _STREAM_HIGHLIGHT_MAX_CHARS,
    ElaMarkdownViewer,
)


def _fragments(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                result.append(fragment)
            iterator += 1
        block = block.next()
    return result


def _code_tables(viewer: ElaMarkdownViewer) -> list:
    return [
        t for t in viewer._iter_tables(viewer.document()) if viewer._is_code_table(t)
    ]


def _code_text_colors(viewer: ElaMarkdownViewer, table) -> set:
    document = viewer.document()
    cell = table.cellAt(table.rows() - 1, 0)
    first = cell.firstCursorPosition().blockNumber()
    last = cell.lastCursorPosition().blockNumber()
    colors = set()
    for number in range(first, last + 1):
        block = document.findBlockByNumber(number)
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.text().strip():
                colors.add(fragment.charFormat().foreground().color().name())
            iterator += 1
    return colors


class TestDragGuard:
    def _prepare(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(420, 320)
        v.setMarkdown("```python\nx = 1\n```")
        v.show()
        qapp.processEvents()
        QTest.qWait(150)
        return v

    def _send(self, viewport, pos, buttons):
        QApplication.sendEvent(
            viewport,
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(pos),
                Qt.MouseButton.NoButton,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    def test_hover_no_button_pressed(self, qapp):
        v = self._prepare(qapp)
        rect = v._code_button_rects[0]
        viewport = v.textBrowser().viewport()
        self._send(viewport, rect.center(), Qt.MouseButton.NoButton)
        assert v._code_buttons[0].isVisible()
        v.close()
        v.deleteLater()

    def test_hover_hidden_while_dragging(self, qapp):
        v = self._prepare(qapp)
        rect = v._code_button_rects[0]
        viewport = v.textBrowser().viewport()
        self._send(viewport, rect.center(), Qt.MouseButton.NoButton)
        assert v._code_buttons[0].isVisible()

        self._send(viewport, rect.center(), Qt.MouseButton.LeftButton)
        assert not v._code_buttons[0].isVisible()
        v.close()
        v.deleteLater()


class TestStreamHighlightThrottle:
    LINES = "x = 1\n" * 900

    def test_large_unclosed_fence_plain(self):
        v = ElaMarkdownViewer()
        source = "```python\n" + self.LINES
        assert len(self.LINES) > _STREAM_HIGHLIGHT_MAX_CHARS
        v.setMarkdown(source)

        tables = _code_tables(v)
        assert len(tables) == 1
        assert len(_code_text_colors(v, tables[0])) == 1
        v.deleteLater()

    def test_closed_fence_highlighted(self):
        pytest.importorskip("pygments")
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\n" + self.LINES + "```")

        tables = _code_tables(v)
        assert len(tables) == 1
        assert len(_code_text_colors(v, tables[0])) >= 2
        v.deleteLater()

    def test_small_unclosed_fence_still_highlighted(self):
        pytest.importorskip("pygments")
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\ndef add(a, b):\n    return a + b\n")

        tables = _code_tables(v)
        assert len(tables) == 1
        assert len(_code_text_colors(v, tables[0])) >= 2
        v.deleteLater()


class TestStreamingCaret:
    def test_timer_lifecycle(self):
        v = ElaMarkdownViewer()
        assert not v._caret_timer.isActive()

        v.beginStream()
        assert v._caret_timer.isActive()
        assert v._caret_visible

        v.endStream()
        assert not v._caret_timer.isActive()
        assert not v._caret_visible
        v.deleteLater()

    def test_paint_no_crash(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(320, 200)
        v.beginStream()
        v.appendMarkdown("流式内容\n\n段落")
        v._stream_timer.stop()
        v._flush_stream()
        v.show()
        qapp.processEvents()

        pixmap = QPixmap(v.size())
        v.render(pixmap)
        v.endStream()
        v.close()
        v.deleteLater()


class TestFormulaTooltipAndCopy:
    SOURCE = "质能方程 $E=mc^2$ 很有名"

    def _image_fragment(self, v):
        for fragment in _fragments(v):
            if fragment.charFormat().isImageFormat():
                return fragment
        raise AssertionError("formula image not found")

    def test_tooltip_contains_latex(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        fragment = self._image_fragment(v)
        assert fragment.charFormat().toImageFormat().toolTip() == "LaTeX: E=mc^2"
        v.deleteLater()

    def test_copy_formula(self, qapp, requires_clipboard):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        fragment = self._image_fragment(v)

        cursor = QTextCursor(v.document())
        cursor.setPosition(fragment.position() + 1)
        v.textBrowser().setTextCursor(cursor)
        assert v._formula_latex_at_cursor() == "E=mc^2"

        received = []
        v.formulaCopied.connect(received.append)
        v._copy_formula_at_cursor()
        qapp.processEvents()
        assert received == ["E=mc^2"]
        assert (
            _wait_for_clipboard(qapp, "E=mc^2", v._copy_formula_at_cursor) == "E=mc^2"
        )
        v.deleteLater()

    def test_menu_action_enabled_only_on_formula(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        cursor = QTextCursor(v.document())
        cursor.setPosition(0)
        v.textBrowser().setTextCursor(cursor)
        menu = v._create_context_menu()
        actions = {action.text(): action for action in menu.actions()}
        assert "复制 LaTeX 公式" in actions
        assert not actions["复制 LaTeX 公式"].isEnabled()
        menu.deleteLater()

        fragment = self._image_fragment(v)
        cursor.setPosition(fragment.position() + 1)
        v.textBrowser().setTextCursor(cursor)
        menu = v._create_context_menu()
        actions = {action.text(): action for action in menu.actions()}
        assert actions["复制 LaTeX 公式"].isEnabled()
        menu.deleteLater()
        v.deleteLater()


class TestPdfExport:
    def test_export_pdf(self, tmp_path):
        v = ElaMarkdownViewer()
        v.setMarkdown("# 标题\n\n正文 **加粗** 与 `代码`\n\n```python\nx = 1\n```")

        target = tmp_path / "export.pdf"
        assert v.exportPdf(str(target)) is True
        assert target.exists()
        assert target.read_bytes()[:5] == b"%PDF-"
        v.deleteLater()

    def test_export_pdf_invalid_path(self, tmp_path):
        v = ElaMarkdownViewer()
        v.setMarkdown("内容")
        assert v.exportPdf("") is False
        v.deleteLater()
