"""内置 MWeb 主题的排版覆盖（标题 / 引用 / 表格 / 标题线）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtTest import QTest
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro import ElaMarkdownViewer
from pyqt6_ela_pro.markdown_viewer.appearance import _resolve_body_font_family

SOURCE = """# 一级

## 二级

> 引用

| A | B |
|---|---|
| 1 | 2 |
| 3 | 4 |
"""


def _blocks(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        result.append(block)
        block = block.next()
    return result


def _heading(viewer: ElaMarkdownViewer, text: str):
    return next(block for block in _blocks(viewer) if block.text().strip() == text)


def _fragment_format(viewer: ElaMarkdownViewer, text: str):
    block = _heading(viewer, text)
    cursor = QTextCursor(block)
    cursor.movePosition(
        QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
    )
    return cursor.charFormat()


def _table(viewer: ElaMarkdownViewer):
    return [
        table
        for table in viewer._iter_tables(viewer.document())
        if not viewer._is_code_table(table)
    ][0]


def _code_table(viewer: ElaMarkdownViewer):
    return [
        table
        for table in viewer._iter_tables(viewer.document())
        if viewer._is_code_table(table)
    ][0]


def _fragment_color(viewer: ElaMarkdownViewer, needle: str) -> str:
    block = viewer.document().begin()
    while block.isValid():
        if needle in block.text():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and needle in fragment.text():
                    return fragment.charFormat().foreground().color().name()
                iterator += 1
        block = block.next()
    return ""


class TestThemeLayouts:
    def test_lark_headings_and_quote(self):
        v = ElaMarkdownViewer()
        v.setMarkdownTheme("lark")
        v.setMarkdown(SOURCE)
        h2 = _fragment_format(v, "二级")
        assert _heading(v, "一级").blockFormat().lineHeight() == 140.0
        assert int(h2.fontWeight()) == int(QFont.Weight.DemiBold)
        quote = next(block for block in _blocks(v) if block.text().strip() == "引用")
        assert quote.blockFormat().background().style() == Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_typo_thin_headings_and_table_header(self):
        v = ElaMarkdownViewer()
        v.setMarkdownTheme("typo")
        v.setMarkdown(SOURCE)
        h1 = _fragment_format(v, "一级")
        assert int(h1.fontWeight()) == int(QFont.Weight.Light)
        assert _heading(v, "一级").blockFormat().lineHeight() == 135.0
        table = _table(v)
        header = table.cellAt(0, 0).format().toTableCellFormat()
        assert header.background().style() != Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_vue_zebra_and_h2_rule(self):
        v = ElaMarkdownViewer()
        v.setMarkdownTheme("vue")
        v.setMarkdown(SOURCE)
        assert v.tableZebra() is True
        table = _table(v)
        assert table.cellAt(2, 0).format().background().style() != Qt.BrushStyle.NoBrush
        v._ensure_paint_index()
        h1 = _heading(v, "一级")
        h2 = _heading(v, "二级")
        assert h1.blockNumber() not in v._paint_index_decorations
        assert h2.blockNumber() in v._paint_index_decorations

        v.setTableZebra(False)
        assert v.tableZebra() is False
        v.deleteLater()

    def test_indigo_heading_left_rule(self):
        v = ElaMarkdownViewer()
        v.setMarkdownTheme("indigo")
        v.setMarkdown(SOURCE)
        v._ensure_paint_index()
        h1 = _heading(v, "一级")
        h2 = _heading(v, "二级")
        assert h1.blockFormat().leftMargin() > 0
        assert h2.blockFormat().leftMargin() > 0
        assert h1.blockNumber() in v._paint_index_decorations
        assert h2.blockNumber() in v._paint_index_decorations
        v.deleteLater()

    def test_typo_link_underline(self):
        v = ElaMarkdownViewer()
        v.setMarkdownTheme("typo")
        v.setMarkdown("[链接](https://example.com)")
        block = next(block for block in _blocks(v) if "链接" in block.text())
        iterator = block.begin()
        fragment = iterator.fragment()
        assert fragment.isValid() and fragment.text() == "链接"
        assert fragment.charFormat().fontUnderline() is True
        v.deleteLater()

    def test_theme_switch_rebuilds_layout(self):
        v = ElaMarkdownViewer()
        v.setMarkdownTheme("bear")
        v.setMarkdown(SOURCE)
        assert v.tableZebra() is False

        v.setMarkdownTheme("vue")
        v.setMarkdown(SOURCE)
        assert v.tableZebra() is True
        v._ensure_paint_index()
        assert _heading(v, "二级").blockNumber() in v._paint_index_decorations

        v.setMarkdownTheme("bear")
        v.setMarkdown(SOURCE)
        assert v.tableZebra() is False
        v._ensure_paint_index()
        assert _heading(v, "二级").blockNumber() not in v._paint_index_decorations
        v.deleteLater()

    def test_paper_body_font_and_reading_width(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(1000, 620)
        v.show()
        v.setMarkdownTheme("paper")
        v.setMarkdown("Hello\n\n```python\nx = 1\ny = 2\n```")
        QTest.qWait(120)

        frame = v.document().rootFrame().frameFormat()
        assert v._content_text_width() == 820
        expected_margin = (v.textBrowser().viewport().width() - 820) / 2
        assert abs(frame.leftMargin() - expected_margin) <= 1
        assert abs(frame.rightMargin() - expected_margin) <= 1
        assert v.document().defaultFont().family() == _resolve_body_font_family(
            "serif", v._base_font_family
        )
        rect = v._code_table_viewport_rect(_code_table(v))
        assert rect.width() <= 822
        assert rect.left() >= 80
        v.close()
        v.deleteLater()

    def test_paper_width_is_ignored_when_embedded(self):
        v = ElaMarkdownViewer()
        v.resize(1000, 620)
        v.setMarkdownTheme("paper")
        v.setEmbeddedMode(True)
        v.setMarkdown("Hello")
        v._apply_content_width()
        frame = v.document().rootFrame().frameFormat()
        assert frame.leftMargin() == v.document().documentMargin()
        assert frame.rightMargin() == v.document().documentMargin()
        v.deleteLater()

    def test_paper_surface_follows_theme_mode(self):
        v = ElaMarkdownViewer()
        v.setMarkdownTheme("paper")
        assert v._base_bg.name() == "#f7f1e3"
        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert v._base_bg.name() == "#1f1b17"
        v._onThemeChanged(ElaThemeType.ThemeMode.Light)
        assert v._base_bg.name() == "#f7f1e3"
        v.deleteLater()

    def test_github_heading_rule_and_table_header(self):
        v = ElaMarkdownViewer()
        v.setMarkdownTheme("github")
        v.setMarkdown(SOURCE)
        v._ensure_paint_index()
        h1 = _heading(v, "一级")
        h2 = _heading(v, "二级")
        assert h1.blockNumber() in v._paint_index_decorations
        assert h2.blockNumber() in v._paint_index_decorations
        table = _table(v)
        header = table.cellAt(0, 0).format().toTableCellFormat()
        assert header.background().style() != Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_nord_dark_link_color(self):
        v = ElaMarkdownViewer()
        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        v.setMarkdownTheme("nord")
        v.setMarkdown("[link](https://example.com)")
        assert _fragment_color(v, "link") == "#88c0d0"
        v.deleteLater()
