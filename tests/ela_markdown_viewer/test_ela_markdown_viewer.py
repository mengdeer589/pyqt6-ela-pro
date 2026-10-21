from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette, QTextLength, QTextTable
from PyQt6ElaWidgetTools import ElaScrollBar, ElaThemeType, eTheme

from pyqt6_ela_pro import ela_markdown_viewer as viewer_module
from pyqt6_ela_pro.ela_markdown_viewer import _INLINE_CODE_MARK, ElaMarkdownViewer


def _fragments(viewer: ElaMarkdownViewer) -> list:
    """收集文档中的全部文本片段。"""
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


def _tables(viewer: ElaMarkdownViewer) -> list:
    """收集文档中的全部表格。"""

    result = []
    stack = [viewer.document().rootFrame()]
    while stack:
        frame = stack.pop()
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                result.append(child)
            stack.append(child)
    return result


def _code_tables(viewer: ElaMarkdownViewer) -> list:
    """收集代码块包裹表（单元格底色为代码底色）。"""
    return [
        table
        for table in _tables(viewer)
        if table.cellAt(0, 0).format().background().color() == viewer._code_bg
    ]


def _cell_text(viewer: ElaMarkdownViewer, table) -> str:
    """拼接单元格内全部块文本。"""
    document = viewer.document()
    cell = table.cellAt(0, 0)
    first = cell.firstCursorPosition().blockNumber()
    last = cell.lastCursorPosition().blockNumber()
    return "\n".join(
        document.findBlockByNumber(n).text() for n in range(first, last + 1)
    )


class TestElaMarkdownViewerInit:
    def test_initialization_with_defaults(self):
        v = ElaMarkdownViewer()
        assert v._border_radius == 0
        assert v._text_browser is not None
        assert v._text_browser.isReadOnly() is True
        # Qt 层必须为 False：openExternalLinks 为真时 QTextBrowser 会先 openUrl()
        # 再 return，anchorClicked 永不发出，内部锚点（任务复选框 / 折叠 / 目录跳转）
        # 全部失效。外部链接改由 _on_anchor_clicked 自行打开。
        assert v._text_browser.openExternalLinks() is False
        # 对外语义不变：外部链接仍默认交给系统浏览器
        assert v.openExternalLinks() is True
        v.deleteLater()

    def test_initially_no_markdown(self):
        v = ElaMarkdownViewer()
        assert v.markdown() == ""
        v.deleteLater()


class TestElaMarkdownViewerMarkdown:
    def test_set_markdown(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("# Hello\nWorld")
        assert "# Hello" in v.markdown()
        v.deleteLater()

    def test_set_markdown_empty(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("")
        assert v.markdown() == ""
        v.deleteLater()


class TestElaMarkdownViewerBorderRadius:
    def test_border_radius_default(self):
        v = ElaMarkdownViewer()
        assert v.borderRadius() == 0
        v.deleteLater()

    def test_set_border_radius(self):
        v = ElaMarkdownViewer()
        v.setBorderRadius(8)
        assert v.borderRadius() == 8
        v.deleteLater()


class TestElaMarkdownViewerTheme:
    def test_on_theme_changed_applies_style(self):
        v = ElaMarkdownViewer()

        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert v._theme_mode == ElaThemeType.ThemeMode.Dark
        v.deleteLater()


class TestElaMarkdownViewerDeleteLater:
    def test_delete_later_cleans_up(self):
        v = ElaMarkdownViewer()
        v.deleteLater()


class TestElaMarkdownViewerContent:
    def test_markdown_returns_original_source(self):
        v = ElaMarkdownViewer()
        source = "# Hello\n\n```python\nx = 1\n```\n"
        v.setMarkdown(source)
        assert v.markdown() == source
        v.deleteLater()

    def test_clear(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("# Hello")
        v.clear()
        assert v.markdown() == ""
        assert v.document().toPlainText() == ""
        v.deleteLater()

    def test_text_browser_accessor(self):
        v = ElaMarkdownViewer()
        assert v.textBrowser() is v._text_browser
        assert v.document() is v._text_browser.document()
        v.deleteLater()

    def test_open_external_links_toggle(self):
        v = ElaMarkdownViewer()
        v.setOpenExternalLinks(False)
        assert v.openExternalLinks() is False
        v.setOpenExternalLinks(True)
        assert v.openExternalLinks() is True
        v.deleteLater()

    def test_horizontal_scrollbar_is_ela(self):

        v = ElaMarkdownViewer()
        assert isinstance(v.textBrowser().horizontalScrollBar(), ElaScrollBar)
        assert isinstance(v.textBrowser().verticalScrollBar(), ElaScrollBar)
        v.deleteLater()


class TestElaMarkdownViewerCodeStyle:
    def test_fenced_code_styled(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```\ncode()\n```")

        tables = _code_tables(v)
        assert len(tables) == 1
        cell = tables[0].cellAt(0, 0)
        assert cell.format().background().color() == v._code_bg
        cell_format = cell.format().toTableCellFormat()
        assert cell_format.topPadding() == 9
        assert cell_format.leftPadding() == 14
        assert tables[0].format().topMargin() == 8
        assert tables[0].format().bottomMargin() == 8

        width = tables[0].format().width()
        assert width.type() == QTextLength.Type.PercentageLength
        assert width.rawValue() == 100

        frags = [f for f in _fragments(v) if f.text() == "code()"]
        assert len(frags) == 1
        assert frags[0].charFormat().fontFamilies()[0] == v.codeFontFamily()
        v.deleteLater()

    def test_inline_code_styled_and_content_preserved(self):

        v = ElaMarkdownViewer()
        v.setMarkdown("a `inl<x>()` b")

        assert "inl<x>()" in v.document().toPlainText()
        frags = [f for f in _fragments(v) if f.text() == "inl<x>()"]
        assert len(frags) == 1
        fmt = frags[0].charFormat()
        assert fmt.fontFamilies()[0] == v.codeFontFamily()
        assert fmt.fontFixedPitch() is True
        # Typora 风格：底色/圆角由自绘提供，字符格式只带标记属性
        assert fmt.property(_INLINE_CODE_MARK) is True
        assert fmt.background().style() == Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_fenced_code_content_escaped(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```\n<b>&amp;\n```")

        assert "<b>&amp;" in v.document().toPlainText()
        v.deleteLater()

    def test_set_code_font_family(self, qapp):
        v = ElaMarkdownViewer()
        v.show()  # 隐藏时主题 / 配色 / 代码字体的重建懒做（见 viewer 懒渲染契约）
        qapp.processEvents()
        v.setMarkdown("```\ncode()\n```")
        v.setCodeFontFamily("Courier New")

        assert v.codeFontFamily() == "Courier New"
        frag = next(f for f in _fragments(v) if f.text() == "code()")
        assert frag.charFormat().fontFamilies()[0] == "Courier New"
        v.deleteLater()

    def test_inline_code_same_text_as_fenced_code_still_styled(self):

        v = ElaMarkdownViewer()
        v.setMarkdown("```\nfoo\n```\n\ninline `foo` here")

        frags = [f for f in _fragments(v) if f.text() == "foo"]
        assert len(frags) == 2
        # 第二个 foo 是行内代码，必须被定位标记（等宽 + 固定间距 + 自绘标记）
        assert frags[1].charFormat().fontFixedPitch() is True
        assert frags[1].charFormat().property(_INLINE_CODE_MARK) is True
        v.deleteLater()


class TestElaMarkdownViewerThemeColors:
    def _find(self, viewer: ElaMarkdownViewer, text: str):
        return next(f for f in _fragments(viewer) if f.text() == text)

    def test_plain_text_uses_palette_color(self):
        """纯正文**不带显式前景色**：由控件 palette 的 ``Text`` 提供（随主题）。

        每段正文 merge 一次正文色实测占整渲染 ~16ms（117KB 文档 8260 个
        片段里 3736 个是纯正文）；改为 palette 提供后屏幕逐像素等价，
        ``toHtml()`` 不再输出正文 ``color:``、PDF / 打印走默认调色板。
        """
        v = ElaMarkdownViewer()
        v.setMarkdown("plain text")

        fragment = self._find(v, "plain text")
        assert fragment.charFormat().foreground().style() == Qt.BrushStyle.NoBrush
        expected = eTheme.getThemeColor(
            v._theme_mode, ElaThemeType.ThemeColor.BasicText
        )
        palette = v.textBrowser().palette()
        assert palette.color(QPalette.ColorRole.Text).name() == expected.name()
        v.deleteLater()

    def test_plain_text_uses_palette_color_in_dark_theme(self):
        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            v = ElaMarkdownViewer()
            v.setMarkdown("plain text")

            fragment = self._find(v, "plain text")
            assert fragment.charFormat().foreground().style() == Qt.BrushStyle.NoBrush
            palette = v.textBrowser().palette()
            expected = eTheme.getThemeColor(
                ElaThemeType.ThemeMode.Dark, ElaThemeType.ThemeColor.BasicText
            )
            assert palette.color(QPalette.ColorRole.Text).name() == expected.name()
            v.deleteLater()
        finally:
            eTheme.setThemeMode(previous)

    def test_link_color_follows_theme(self):

        v = ElaMarkdownViewer()
        v.setMarkdown("[link](https://example.com)")

        theme = viewer_module._MD_THEMES["opencode"]
        expected = QColor(
            theme["dark" if v._is_dark_theme else "light"]["semantic"]["link"]
        )
        assert (
            self._find(v, "link").charFormat().foreground().color().name()
            == expected.name()
        )
        v.deleteLater()

    def test_theme_switch_recolors_existing_content(self, qapp):

        v = ElaMarkdownViewer()
        v.show()  # 隐藏时换肤只标记、showEvent 补渲染；这里要立刻读渲染结果
        qapp.processEvents()
        v.setMarkdown("[link](https://example.com)\n\n```\ncode()\n```")
        light_code_bg = v._code_bg.name()

        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)

        expected_link = QColor(
            viewer_module._MD_THEMES["opencode"]["dark"]["semantic"]["link"]
        )
        expected_code_bg = v._code_bg
        assert light_code_bg != expected_code_bg.name()
        link = self._find(v, "link")
        assert link.charFormat().foreground().color().name() == expected_link.name()
        table = _code_tables(v)[0]
        assert (
            table.cellAt(0, 0).format().background().color().name()
            == expected_code_bg.name()
        )
        v.deleteLater()


class TestElaMarkdownViewerTableStyle:
    MD = "| A | B |\n|:--|--:|\n| 1 | 2 |"

    def test_grid_and_padded(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.MD)

        table = _tables(v)[0]
        fmt = table.format()
        assert fmt.border() == 0
        assert fmt.borderCollapse() is True
        assert fmt.cellSpacing() == 0

        # Typora（github.css）：全网格 1px + 单元格 6px 13px 内边距
        cell = table.cellAt(1, 0).format().toTableCellFormat()
        assert cell.topPadding() == 6
        assert cell.bottomPadding() == 6
        assert cell.leftPadding() == 13
        assert cell.rightPadding() == 13
        assert cell.topBorder() == 1.0
        assert cell.bottomBorder() == 1.0
        assert cell.leftBorder() == 1.0
        assert cell.rightBorder() == 1.0
        v.deleteLater()

    def test_header_row_styled(self):

        v = ElaMarkdownViewer()
        v.setMarkdown(self.MD)

        table = _tables(v)[0]
        header = table.cellAt(0, 0).format()
        body = table.cellAt(1, 0).format()
        assert header.background().color().alphaF() > 0
        assert int(header.fontWeight()) == int(QFont.Weight.Bold)
        assert body.background().style() == Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_table_colors_adapt_to_theme(self):

        v = ElaMarkdownViewer()
        v.setMarkdown(self.MD)
        light_header = v._table_header_bg.name(QColor.NameFormat.HexArgb)

        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)

        dark_header = v._table_header_bg.name(QColor.NameFormat.HexArgb)
        assert light_header != dark_header
        table = _tables(v)[0]
        header_bg = table.cellAt(0, 0).format().background().color()
        assert header_bg.alphaF() > 0
        v.deleteLater()

    def test_table_cell_alignment_preserved(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.MD)

        table = _tables(v)[0]
        left = table.cellAt(1, 0).firstCursorPosition().blockFormat().alignment()
        right = table.cellAt(1, 1).firstCursorPosition().blockFormat().alignment()
        assert bool(left & Qt.AlignmentFlag.AlignLeft)
        assert bool(right & Qt.AlignmentFlag.AlignRight)
        v.deleteLater()


class TestElaMarkdownViewerBlockSpacing:
    @staticmethod
    def _block_formats(viewer: ElaMarkdownViewer) -> dict:
        result = {}
        block = viewer.document().begin()
        while block.isValid():
            result[block.text()] = block.blockFormat()
            block = block.next()
        return result

    def test_code_block_uses_padded_table(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("para\n\n```\ncode()\n```\n\nafter")

        tables = _code_tables(v)
        assert len(tables) == 1
        assert tables[0].format().topMargin() == 8
        assert tables[0].format().bottomMargin() == 8
        # 代码行位于表格内，不再依赖相邻块 margin
        assert _cell_text(v, tables[0]) == "code()"
        v.deleteLater()

    def test_inline_code_paragraph_not_spaced_as_code_block(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("`inline` text\n\nafter")

        assert _code_tables(v) == []
        formats = self._block_formats(v)
        # 默认段落 margin 为 6，不应被代码块间距逻辑改成 7
        assert formats["inline text"].bottomMargin() != 7
        assert formats["after"].topMargin() != 7
        v.deleteLater()

    def test_table_block_has_margins(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("para\n\n| A | B |\n|---|---|\n| 1 | 2 |")

        table = _tables(v)[0]
        before = v.document().findBlock(table.firstPosition() - 1)
        after = v.document().findBlock(table.lastPosition() + 1)
        # 间距加在表格外的相邻块上，避免把表头首格文字顶下来
        assert before.blockFormat().bottomMargin() == 12
        assert after.blockFormat().topMargin() == 12
        header = table.cellAt(0, 0).firstCursorPosition().block()
        assert header.blockFormat().topMargin() != 12
        v.deleteLater()
