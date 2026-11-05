"""Tests for ElaMarkdownViewer P2 code block advanced features.

Covers: long code collapse/expand, line numbers, custom token palette.
"""

from __future__ import annotations

import pytest
from _pixels import opaque_colors, skip_if_no_pixels
from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from PyQt6.QtCore import QRectF, QUrl
from PyQt6.QtTest import QTest

from pyqt6_ela_pro.markdown_viewer import code as code_module
from pyqt6_ela_pro.ela_markdown_viewer import (
    _MD_THEMES,
    ElaMarkdownViewer,
)

LONG_CODE = "\n".join(f"line{i} = {i}" for i in range(1, 11))
LONG_MARKDOWN = "```python\n" + LONG_CODE + "\n```"


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


def _code_table(viewer: ElaMarkdownViewer):
    tables = [
        t for t in viewer._iter_tables(viewer.document()) if viewer._is_code_table(t)
    ]
    assert tables
    return tables[0]


class TestCodeCollapse:
    def test_disabled_by_default(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(LONG_MARKDOWN)
        assert "展开其余" not in v.document().toPlainText()
        v.deleteLater()

    def test_collapsed_shows_head_and_link(self):
        v = ElaMarkdownViewer()
        v.setCodeBlockCollapseLines(3)
        v.setMarkdown(LONG_MARKDOWN)

        text = v.document().toPlainText()
        assert "line1 = 1" in text and "line3 = 3" in text
        assert "line4 = 4" not in text
        assert "展开其余 7 行" in text
        v.deleteLater()

    def test_copy_uses_full_text(self, qapp, requires_clipboard):
        v = ElaMarkdownViewer()
        v.setCodeBlockCollapseLines(3)
        v.setMarkdown(LONG_MARKDOWN)
        v.resize(420, 320)
        v.show()
        qapp.processEvents()
        QTest.qWait(150)

        v._copy_code_block(0)
        qapp.processEvents()
        assert (
            _wait_for_clipboard(qapp, LONG_CODE, lambda: v._copy_code_block(0))
            == LONG_CODE
        )
        v.close()
        v.deleteLater()

    def test_expand_and_collapse_roundtrip(self):
        v = ElaMarkdownViewer()
        v.setCodeBlockCollapseLines(3)
        v.setMarkdown(LONG_MARKDOWN)

        v._on_anchor_clicked(QUrl("#elacode-expand-0"))
        text = v.document().toPlainText()
        assert "line10 = 10" in text
        assert "收起" in text

        v._on_anchor_clicked(QUrl("#elacode-expand-0"))
        text = v.document().toPlainText()
        assert "line10 = 10" not in text
        assert "展开其余 7 行" in text
        v.deleteLater()

    def test_set_markdown_resets_expanded(self):
        v = ElaMarkdownViewer()
        v.setCodeBlockCollapseLines(3)
        v.setMarkdown(LONG_MARKDOWN)
        v._on_anchor_clicked(QUrl("#elacode-expand-0"))
        assert "line10 = 10" in v.document().toPlainText()

        v.setMarkdown(LONG_MARKDOWN)
        assert "line10 = 10" not in v.document().toPlainText()
        v.deleteLater()

    def test_no_collapse_while_streaming(self):
        v = ElaMarkdownViewer()
        v.setCodeBlockCollapseLines(3)
        v.beginStream()
        v.appendMarkdown(LONG_MARKDOWN)
        v._stream_timer.stop()
        v._flush_stream()

        assert "展开其余" not in v.document().toPlainText()
        v.endStream()
        v.deleteLater()


class TestLineNumbers:
    def test_disabled_by_default(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nx = 1\ny = 2\n```")
        prefixes = [f.text() for f in _fragments(v) if f.text().startswith("1 ")]
        assert not prefixes
        v.deleteLater()

    def test_toggle_is_paint_only(self, monkeypatch):
        """行号只走绘制层：开关不得重渲染、不得改动文档。"""
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nx = 1\ny = 2\nz = 3\n```")
        table = _code_table(v)
        assert table.cellAt(0, 0).format().toTableCellFormat().leftPadding() > 14

        calls = []
        monkeypatch.setattr(v, "_render", lambda *args, **kwargs: calls.append(1))
        revision = v.document().revision()
        v.setLineNumbersEnabled(True)

        assert calls == []
        assert v.lineNumbersEnabled() is True
        assert v.document().revision() == revision
        assert "1  x = 1" not in v.toPlainText()
        v.deleteLater()

    def test_toggle_repaints_line_numbers(self, qapp):
        """开关必须改变视口像素，而不只是改标志位。"""
        v = ElaMarkdownViewer()
        v.resize(520, 320)
        v.show()
        v.setMarkdown("```python\nx = 1\ny = 2\nz = 3\n```\n\n正文")
        qapp.processEvents()
        QTest.qWait(120)
        viewport = v.textBrowser().viewport()
        off = viewport.grab().toImage()
        skip_if_no_pixels(opaque_colors(viewport), "代码行号像素")

        v.setLineNumbersEnabled(True)
        qapp.processEvents()
        QTest.qWait(80)
        on = viewport.grab().toImage()
        assert off.constBits().asstring(off.sizeInBytes()) != on.constBits().asstring(
            on.sizeInBytes()
        ), "行号开关没有触发重绘"
        v.close()
        v.deleteLater()

    def test_paint_helper_numbers_each_code_line(self):
        class _Painter:
            def __init__(self):
                self.texts = []

            def setFont(self, *_args):
                pass

            def setPen(self, *_args):
                pass

            def drawText(self, _point, text, *_args):
                self.texts.append(text)

        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nx = 1\ny = 2\nz = 3\n```")
        table = _code_table(v)
        painter = _Painter()
        document = v.document()
        v._paint_code_line_numbers(
            v.textBrowser(),
            painter,
            table,
            QRectF(10, 10, 400, 200),
            0,
            1000,
            document.firstBlock(),
            document.lastBlock(),
        )
        assert painter.texts == ["1", "2", "3"]
        v.deleteLater()

    def test_paint_helper_skips_fold_link(self):
        class _Painter:
            def __init__(self):
                self.texts = []

            def setFont(self, *_args):
                pass

            def setPen(self, *_args):
                pass

            def drawText(self, _point, text, *_args):
                self.texts.append(text)

        v = ElaMarkdownViewer()
        v.setCodeBlockCollapseLines(2)
        v.setMarkdown(LONG_MARKDOWN)
        table = _code_table(v)
        painter = _Painter()
        document = v.document()
        v._paint_code_line_numbers(
            v.textBrowser(),
            painter,
            table,
            QRectF(10, 10, 400, 200),
            0,
            1000,
            document.firstBlock(),
            document.lastBlock(),
        )
        assert painter.texts == ["1", "2"]
        v.deleteLater()

    def test_line_number_metrics_cached(self, monkeypatch):
        real_metrics = code_module.QFontMetricsF
        calls = []

        class _CountingMetrics:
            def __new__(cls, font):
                calls.append(1)
                return real_metrics(font)

        monkeypatch.setattr(code_module, "QFontMetricsF", _CountingMetrics)
        v = ElaMarkdownViewer()
        v.setMarkdown(("```python\nx = 1\n```\n\n") * 40)
        assert len(calls) == 1, f"行号 metrics 每个代码块都重建：{len(calls)}"
        v.deleteLater()

    def test_highlight_cache_hit_skips_base_format(self, monkeypatch):
        pytest.importorskip("pygments")
        v = ElaMarkdownViewer()
        calls = []
        real = v._font_for_code

        def counting(text):
            calls.append(text)
            return real(text)

        monkeypatch.setattr(v, "_font_for_code", counting)
        v.setMarkdown("```python\nx = 1\n```\n\n```python\nx = 1\n```")
        assert len(calls) == 1, f"高亮 cache hit 仍构造 base 格式：{len(calls)}"
        v.deleteLater()

    def test_copy_excludes_line_numbers(self, qapp, requires_clipboard):
        v = ElaMarkdownViewer()
        v.setLineNumbersEnabled(True)
        v.setMarkdown("```python\nx = 1\ny = 2\n```")
        v.resize(420, 320)
        v.show()
        qapp.processEvents()
        QTest.qWait(150)

        v._copy_code_block(0)
        qapp.processEvents()
        expected = "x = 1\ny = 2"
        assert (
            _wait_for_clipboard(qapp, expected, lambda: v._copy_code_block(0))
            == expected
        )
        v.close()
        v.deleteLater()


class TestTokenPalette:
    def test_custom_keyword_color(self):
        pytest.importorskip("pygments")
        v = ElaMarkdownViewer()
        v.setCodeTokenColors({"keyword": "#123456"})
        v.setMarkdown("```python\ndef foo():\n    return 1\n```")

        colors = {
            f.charFormat().foreground().color().name()
            for f in _fragments(_code_table(v))
            if f.text().strip()
        }
        assert "#123456" in colors
        assert v.codeTokenColors()["keyword"] == "#123456"
        v.deleteLater()

    def test_reset_palette(self):
        v = ElaMarkdownViewer()
        v.setCodeTokenColors({"keyword": "#123456"})
        v.setCodeTokenColors(None)
        variant = "dark" if v._is_dark_theme else "light"
        assert (
            v.codeTokenColors()["keyword"]
            == _MD_THEMES["bear"][variant]["syntax"]["keyword"]
        )
        v.deleteLater()

    def test_unknown_keys_ignored(self):
        v = ElaMarkdownViewer()
        v.setCodeTokenColors({"nosuch": "#000000"})
        assert "nosuch" not in v.codeTokenColors()
        v.deleteLater()
