"""Tests for Typora-style typography and the categorized example samples."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor, QTextFormat

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer
from pyqt6_ela_pro.example.markdown_page import (
    _MARKDOWN_ALL,
    _MARKDOWN_CODE,
    _MARKDOWN_MATH,
    _MARKDOWN_MERMAID,
    _MARKDOWN_TEXT,
)


def _blocks(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        result.append(block)
        block = block.next()
    return result


def _heading_size(viewer: ElaMarkdownViewer, needle: str) -> float:
    for block in _blocks(viewer):
        if block.text().strip() != needle:
            continue
        cursor = QTextCursor(block)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        return cursor.charFormat().fontPointSize()
    raise AssertionError(needle)


class TestTypography:
    def test_heading_scales(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("# 一级\n\n## 二级\n\n正文段落")

        h1 = _heading_size(v, "一级")
        h2 = _heading_size(v, "二级")
        body = v.document().defaultFont().pointSizeF()
        assert h1 > h2 > body
        v.deleteLater()

    def test_body_line_height(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("正文段落")

        block = _blocks(v)[0]
        assert block.blockFormat().lineHeight() == 160.0
        v.deleteLater()

    def test_heading_inline_format_keeps_uniform_size(self):
        """标题内的行内加粗不能比同段文字大一号（导入器的 FontSizeAdjustment）。"""
        v = ElaMarkdownViewer()
        v.setMarkdown("### 结论：**是两个互相独立的问题**，都给你最小复现\n")
        sizes = set()
        for block in _blocks(v):
            if block.blockFormat().headingLevel() != 3:
                continue
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.text():
                    fmt = fragment.charFormat()
                    assert not fmt.hasProperty(
                        QTextFormat.Property.FontSizeAdjustment
                    ), fragment.text()
                    font = fmt.font()
                    sizes.add((round(font.pointSizeF(), 3), font.pixelSize()))
                iterator += 1
        assert len(sizes) == 1, sizes
        v.deleteLater()

    def test_heading_uses_semantic_color(self):
        """标题使用语义标题色（opencode TUI 调色板）。"""
        v = ElaMarkdownViewer()
        v.setMarkdown("## 标题")

        cursor = QTextCursor(_blocks(v)[0])
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        color = cursor.charFormat().foreground().color()
        assert color.name() == v._md_heading_color.name()
        v.deleteLater()

    def test_paragraph_bottom_margin(self):
        """普通段落有下边距（Typora 0.8em ≈ 12px 段落节奏）。"""
        v = ElaMarkdownViewer()
        v.setMarkdown("正文段落")

        assert _blocks(v)[0].blockFormat().bottomMargin() == 12.0
        v.deleteLater()

    def test_table_full_grid(self):
        """Typora 表格：单元格四边 1px 全网格 + 表头底色。"""
        v = ElaMarkdownViewer()
        v.setMarkdown("| a | b |\n| --- | --- |\n| 1 | 2 |")

        table = [t for t in v._iter_tables(v.document()) if not v._is_code_table(t)][0]
        header = table.cellAt(0, 0).format().toTableCellFormat()
        body = table.cellAt(1, 0).format().toTableCellFormat()
        for cell in (header, body):
            assert cell.topBorder() == 1.0
            assert cell.bottomBorder() == 1.0
            assert cell.leftBorder() == 1.0
            assert cell.rightBorder() == 1.0
        assert header.background().style() != Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_quote_rail_and_italic_text(self):
        """opencode TUI 引用块：无底色、左侧竖线（自绘）、斜体引用色。"""
        v = ElaMarkdownViewer()
        v.setMarkdown("> 引用内容")

        quote = _blocks(v)[0]
        assert quote.blockFormat().background().style() == Qt.BrushStyle.NoBrush
        assert quote.blockFormat().leftMargin() >= 20.0
        cursor = QTextCursor(quote)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        color = cursor.charFormat().foreground().color()
        assert color.name() == v._md_quote_color.name()
        assert cursor.charFormat().fontItalic()
        v.deleteLater()

    def test_table_after_quote_keeps_header_single_block(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("> 引用\n\n| 能力 | API |\n|:-----|:----|\n| 搜索 | 1 |")

        table = [t for t in v._iter_tables(v.document()) if not v._is_code_table(t)][0]
        cell = table.cellAt(0, 0)
        first = cell.firstCursorPosition().blockNumber()
        last = cell.lastCursorPosition().blockNumber()
        assert first == last
        # 首格不应被额外顶下（曾误加 7px 边距 + 前导空块）
        top = cell.firstCursorPosition().block().blockFormat().topMargin()
        other = (
            table.cellAt(0, 1).firstCursorPosition().block().blockFormat().topMargin()
        )
        assert top == other == 0
        v.deleteLater()

    def test_multicolumn_table_is_not_code_table(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("| 能力 | API |\n|:-----|:----|\n| 搜索 | 1 |")

        table = v._iter_tables(v.document())[0]
        assert not v._is_code_table(table)
        v.deleteLater()


class TestCategorizedSamples:
    def test_all_is_concatenation(self):
        assert _MARKDOWN_ALL == "\n\n".join(
            (_MARKDOWN_TEXT, _MARKDOWN_CODE, _MARKDOWN_MATH, _MARKDOWN_MERMAID)
        )

    def test_each_sample_renders_clean(self):
        for source in (
            _MARKDOWN_TEXT,
            _MARKDOWN_CODE,
            _MARKDOWN_MATH,
            _MARKDOWN_MERMAID,
        ):
            v = ElaMarkdownViewer()
            v.setMermaidEnabled(False)
            v.setMarkdown(source)
            text = v.document().toPlainText()
            assert text.strip()
            for token in ("elacode", "elamark", "elafn", "elatoc", "elacallout"):
                assert token not in text
            v.deleteLater()

    def test_samples_cover_categories(self):
        assert "```python" in _MARKDOWN_CODE
        assert "```diff" in _MARKDOWN_CODE
        assert "\\boxed" in _MARKDOWN_MATH
        assert "\\begin{pmatrix}" in _MARKDOWN_MATH
        assert "flowchart" in _MARKDOWN_MERMAID
        assert "sequenceDiagram" in _MARKDOWN_MERMAID
        assert "```diff" not in _MARKDOWN_TEXT
        assert "+ 更多信息" not in _MARKDOWN_TEXT  # 折叠标签为渲染产物，源码不应包含

    def test_text_sample_has_no_stale_toc_fragment(self):
        assert "[toc]` 自动生成）" not in _MARKDOWN_TEXT
