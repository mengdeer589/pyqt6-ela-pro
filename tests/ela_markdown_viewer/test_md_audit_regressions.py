"""本轮审计修复的回归守卫：分块 / 缩放 / 链接 / 搜索 / 折叠导出 / 目录 / 选区 / 脚注。"""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QTextCursor

import pyqt6_ela_pro.markdown_viewer.stream as stream_module
import pyqt6_ela_pro.markdown_viewer.viewer as viewer_module
from _qthelpers import wait_until
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _wait_render(viewer: ElaMarkdownViewer, qapp) -> None:
    assert wait_until(qapp, lambda: not viewer.isRendering(), timeout_ms=15000)


def _tables(viewer: ElaMarkdownViewer) -> list:
    doc = viewer.document()
    tables = []
    seen = set()
    block = doc.begin()
    while block.isValid():
        table = QTextCursor(block).currentTable()
        if table is not None and id(table) not in seen:
            seen.add(id(table))
            tables.append(table)
        block = block.next()
    return tables


def _block_point(viewer: ElaMarkdownViewer, needle: str) -> float:
    block = viewer.document().begin()
    while block.isValid():
        if needle in block.text():
            points = []
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.text().strip():
                    points.append(fragment.charFormat().fontPointSize())
                iterator += 1
            return max(points, default=0.0)
        block = block.next()
    return 0.0


def _anchor_hrefs(viewer: ElaMarkdownViewer) -> list:
    hrefs = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isAnchor():
                hrefs.append(fragment.charFormat().anchorHref())
            iterator += 1
        block = block.next()
    return hrefs


class TestLargeRenderKeepsBlocks:
    """大文档分块不能把围栏代码 / 表格 / 长段落拆开。"""

    @staticmethod
    def _viewer(make, monkeypatch):
        monkeypatch.setattr(viewer_module, "_LARGE_RENDER_CHARS", 100)
        monkeypatch.setattr(stream_module, "_LARGE_RENDER_CHARS", 100)
        monkeypatch.setattr(stream_module, "_LARGE_RENDER_CHUNK", 40)
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        return viewer

    def test_code_fence_not_split(self, qapp, make, monkeypatch):
        code = "\n".join(
            f"line_{i} = {i}" + ("\n" if i % 5 == 0 else "") for i in range(20)
        )
        viewer = self._viewer(make, monkeypatch)
        viewer.setMarkdown("前文\n\n```python\n" + code + "\n```\n\n后文")
        _wait_render(viewer, qapp)

        code_tables = [t for t in _tables(viewer) if viewer._is_code_table(t)]
        assert len(code_tables) == 1
        text = viewer.toPlainText()
        assert "line_0 = 0" in text and "line_19 = 19" in text
        assert "```" not in text
        assert "后文" in text

    def test_table_not_split(self, qapp, make, monkeypatch):
        rows = "\n".join(f"| row_{i} | value_{i} |" for i in range(20))
        viewer = self._viewer(make, monkeypatch)
        viewer.setMarkdown("前文\n\n| A | B |\n|---|---|\n" + rows + "\n\n后文")
        _wait_render(viewer, qapp)

        tables = _tables(viewer)
        assert len(tables) == 1
        assert tables[0].rows() == 21
        text = viewer.toPlainText()
        assert "row_19" in text
        assert "| row_" not in text
        assert "后文" in text

    def test_long_paragraph_not_split(self, qapp, make, monkeypatch):
        para = "这是一个很长的段落没有空行。" * 20
        viewer = self._viewer(make, monkeypatch)
        viewer.setMarkdown(para)
        _wait_render(viewer, qapp)

        assert viewer.document().blockCount() == 1
        assert "\n" not in viewer.toPlainText()

    def test_whitespace_document_finishes(self, qapp, make, monkeypatch):
        viewer = self._viewer(make, monkeypatch)
        viewer.setMarkdown("\n" * 200)
        _wait_render(viewer, qapp)


class TestZoomScalesCode:
    def test_code_block_follows_zoom(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setZoomFactor(1.5)
        viewer.setMarkdown("前文 `inline` 结尾。\n\n```python\nx = 1\n```\n")
        qapp.processEvents()

        code_before = _block_point(viewer, "x = 1")
        inline_before = _block_point(viewer, "inline")
        assert code_before > 0 and inline_before > 0

        viewer.setZoomFactor(2.0)
        qapp.processEvents()
        code_after = _block_point(viewer, "x = 1")
        inline_after = _block_point(viewer, "inline")
        assert code_after > code_before * 1.15
        assert inline_after > inline_before * 1.15


class TestSearchAfterRender:
    def test_search_selections_rebuilt_after_zoom(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown("正文 A\n\n正文 B\n\n正文 C\n")
        qapp.processEvents()

        assert viewer.searchText("正文") == 3
        before = [s.cursor.selectionStart() for s in viewer._search_selections]
        assert len(set(before)) == 3

        viewer.setZoomFactor(2.0)
        qapp.processEvents()
        after = [s.cursor.selectionStart() for s in viewer._search_selections]
        assert after == before
        assert viewer.findNext() is True


class TestLinkDestinationProtection:
    def test_remote_base_url_directory_gets_slash(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setBaseUrl("https://example.com/docs")
        resolved = viewer._resolve_image_url("img.png", viewer.baseUrl())
        assert resolved.toString() == "https://example.com/docs/img.png"

    def test_markdown_destination_keeps_inline_syntax(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        urls = (
            "https://example.com/~user~",
            "https://example.com/?q=a==b==",
            "https://example.com/a^b^",
        )
        for url in urls:
            viewer.setMarkdown(f"[home]({url})")
            qapp.processEvents()
            assert url in _anchor_hrefs(viewer)

    def test_bare_url_with_special_chars_keeps_text(self, qapp, make):
        """Qt 的 autolink 不识别 `~` / `==`；至少要保证文本不被行内转换改写。"""
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("https://example.com/~user")
        qapp.processEvents()
        assert "https://example.com/~user" in viewer.toPlainText()

        viewer.setMarkdown("https://example.com/?q=a==b==")
        qapp.processEvents()
        assert "https://example.com/?q=a==b==" in viewer.toPlainText()


class TestCollapsedExport:
    def test_collapsed_code_export_includes_hidden_lines(self, qapp, make):
        code = "\n".join(f"line_{i} = {i}" for i in range(12))
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setCodeBlockCollapseLines(4)
        viewer.setMarkdown("前文\n\n```python\n" + code + "\n```\n\n后文")
        qapp.processEvents()

        assert "line_10" not in viewer.toPlainText()
        assert "line_10" in viewer.toHtml()
        assert "line_10" not in viewer.toPlainText()

    def test_collapsed_details_export_includes_content(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown(
            "<details>\n<summary>详情</summary>\n\n隐藏内容\n\n</details>"
        )
        qapp.processEvents()

        assert "隐藏内容" not in viewer.toPlainText()
        assert "隐藏内容" in viewer.toHtml()
        assert "隐藏内容" not in viewer.toPlainText()


class TestDuplicateToc:
    def test_two_toc_tokens_both_replaced(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[toc]\n\n# A\n\n中间\n\n[toc]\n\n# B")
        qapp.processEvents()
        text = viewer.toPlainText()
        assert not any(0xE000 <= ord(ch) <= 0xF8FF for ch in text)
        assert text.count("•") >= 2


class TestTableSelection:
    def test_table_cell_selection_returns_markdown(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown("# T\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n后文")
        qapp.processEvents()

        block = viewer.document().begin()
        while block.isValid() and block.text().strip() != "1":
            block = block.next()
        assert block.isValid()
        cursor = QTextCursor(viewer.document())
        cursor.setPosition(block.position())
        cursor.setPosition(
            block.position() + block.length() - 1,
            QTextCursor.MoveMode.KeepAnchor,
        )
        viewer.textBrowser().setTextCursor(cursor)

        quote = viewer.markdownSelection()
        assert "| 1 | 2 |" in quote


class TestBlockquoteTasks:
    def test_blockquote_task_toggles(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown("> - [ ] 引用任务")
        qapp.processEvents()

        assert viewer._task_items
        assert "□" in viewer.toPlainText()
        viewer._on_anchor_clicked(QUrl("#elatask-0"))
        qapp.processEvents()
        assert "[x]" in viewer._source


class TestFootnoteReferenceOrder:
    def test_numbering_follows_first_reference(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("引用 [^b] 然后 [^a]\n\n[^a]: 定义 A\n[^b]: 定义 B")
        qapp.processEvents()

        # 直接扫描锚点文本 / href
        pairs = []
        block = viewer.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isAnchor():
                    href = fragment.charFormat().anchorHref()
                    if href.startswith("#fn-"):
                        pairs.append((fragment.text(), href))
                iterator += 1
            block = block.next()
        assert ("[1]", "#fn-b") in pairs
        assert ("[2]", "#fn-a") in pairs
        text = viewer.toPlainText()
        assert text.index("[1] 定义 B") < text.index("[2] 定义 A")
