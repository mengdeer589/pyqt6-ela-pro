"""Tests for ElaMarkdownViewer P1 enhancements.

Covers: subscript/superscript, inline highlight, emoji shortcodes,
callouts, heading anchors/TOC, footnotes.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCharFormat, QTextTable

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


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


def _fragments_with_text(viewer: ElaMarkdownViewer, text: str) -> list:
    return [f for f in _fragments(viewer) if text in f.text()]


def _blocks(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        result.append(block)
        block = block.next()
    return result


class TestInlineSubSup:
    def test_subscript_and_superscript(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("H~2~O 与 x^2^")

        subs = [
            f
            for f in _fragments_with_text(v, "2")
            if f.charFormat().verticalAlignment()
            == QTextCharFormat.VerticalAlignment.AlignSubScript
        ]
        sups = [
            f
            for f in _fragments_with_text(v, "2")
            if f.charFormat().verticalAlignment()
            == QTextCharFormat.VerticalAlignment.AlignSuperScript
        ]
        assert subs and sups
        assert "<sub>" not in v.document().toPlainText()
        v.deleteLater()

    def test_strikethrough_not_broken(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("a ~~gone~~ b")

        assert "gone" in v.document().toPlainText()
        assert "<sub>" not in v.document().toPlainText()
        assert "~" not in v.document().toPlainText()
        v.deleteLater()

    def test_sub_sup_inside_code_untouched(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("`x^2^` 与 `H~2~O`")

        code = "".join(f.text() for f in _fragments(v) if f.charFormat().fontFamilies())
        assert "x^2^" in code and "H~2~O" in code
        v.deleteLater()


class TestInlineHighlight:
    def test_mark_applied(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("这是 ==重点== 内容")

        marks = _fragments_with_text(v, "重点")
        assert marks
        assert marks[0].charFormat().background().color() == v._mark_bg
        assert "==" not in v.document().toPlainText()
        v.deleteLater()

    def test_mark_with_markdown_special_left_alone(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("==*not* mark==")

        text = v.document().toPlainText()
        assert "==" in text and "not" in text
        marks = _fragments_with_text(v, "not")
        assert marks
        assert marks[0].charFormat().background().style() == Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_mark_inside_inline_code_untouched(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("`==x==`")

        assert "==x==" in v.document().toPlainText()
        v.deleteLater()


class TestEmoji:
    def test_known_shortcode_replaced(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("出发 :rocket: 完成 :check:")

        text = v.document().toPlainText()
        assert "🚀" in text and "✅" in text
        assert ":rocket:" not in text
        v.deleteLater()

    def test_unknown_shortcode_kept(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(":nosuchcode:")

        assert ":nosuchcode:" in v.document().toPlainText()
        v.deleteLater()

    def test_emoji_inside_inline_code_kept(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("` :smile: `")

        assert ":smile:" in v.document().toPlainText()
        v.deleteLater()


class TestCallout:
    def test_warning_callout_styled(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("> [!WARNING]\n> 危险操作\n\n后续段落")

        text = v.document().toPlainText()
        assert "警告" in text and "危险操作" in text
        assert "[!WARNING]" not in text
        callout_blocks = [b for b in _blocks(v) if b.blockFormat().leftMargin() >= 20.0]
        assert callout_blocks
        for block in callout_blocks:
            background = block.blockFormat().background()
            assert background.style() != Qt.BrushStyle.NoBrush
        normal = [b for b in _blocks(v) if b.text() == "后续段落"]
        assert normal and normal[0].blockFormat().background().style() == Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_note_label_and_multiple_blocks(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("> [!NOTE]\n> 第一段\n>\n> 第二段")

        text = v.document().toPlainText()
        assert "提示" in text and "第一段" in text and "第二段" in text
        v.deleteLater()

    def test_callout_inside_code_fence_untouched(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```\n> [!NOTE]\n```")

        text = v.document().toPlainText()
        assert "[!NOTE]" in text
        v.deleteLater()


class TestHeadingAnchorsAndToc:
    def test_heading_anchors_collected_with_dedupe(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("# Hello World\n\n## 中文标题\n\n# Hello World")

        slugs = [slug for _level, _text, slug in v._headings]
        assert slugs == ["hello-world", "中文标题", "hello-world-1"]

        anchored = set()
        for fragment in _fragments(v):
            fmt = fragment.charFormat()
            if fmt.isAnchor():
                anchored.update(fmt.anchorNames())
        assert "hello-world" in anchored and "中文标题" in anchored
        v.deleteLater()

    def test_toc_links_generated(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("# A\n\n[toc]\n\n## B")

        hrefs = {
            f.charFormat().anchorHref()
            for f in _fragments(v)
            if f.charFormat().isAnchor() and f.charFormat().anchorHref()
        }
        assert "#a" in hrefs and "#b" in hrefs
        text = v.document().toPlainText()
        assert "• A" in text and "• B" in text
        v.deleteLater()

    def test_toc_without_headings_removed(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("[toc]\n\n没有标题")

        assert "[toc]" not in v.document().toPlainText()
        v.deleteLater()

    def test_links_underlined(self):
        """opencode TUI 风格：链接带下划线。"""
        v = ElaMarkdownViewer()
        v.setMarkdown("访问 [示例](https://example.com) 链接")

        anchors = [
            fragment
            for fragment in _fragments(v)
            if fragment.charFormat().isAnchor() and fragment.charFormat().anchorHref()
        ]
        assert anchors
        assert all(fragment.charFormat().fontUnderline() for fragment in anchors)
        v.deleteLater()


class TestFootnotes:
    SOURCE = "正文引用[^a] 与第二处[^b]\n\n[^a]: 第一条脚注\n[^b]: 第二条脚注\n"

    def test_refs_and_defs_rendered(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        text = v.document().toPlainText()
        assert "[^a]" not in text and "[^b]" not in text
        assert "第一条脚注" in text and "第二条脚注" in text

        refs = [
            f
            for f in _fragments(v)
            if f.charFormat().isAnchor() and f.charFormat().anchorHref() == "#fn-a"
        ]
        assert refs
        assert (
            refs[0].charFormat().verticalAlignment()
            == QTextCharFormat.VerticalAlignment.AlignSuperScript
        )
        v.deleteLater()

    def test_definition_block_has_anchor(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        anchors = set()
        for fragment in _fragments(v):
            fmt = fragment.charFormat()
            if fmt.isAnchor():
                anchors.update(fmt.anchorNames())
        assert "fn-a" in anchors and "fn-b" in anchors
        v.scrollToAnchor("fn-b")
        v.deleteLater()

    def test_definition_number_links_back(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        anchors = set()
        back_links = []
        for fragment in _fragments(v):
            fmt = fragment.charFormat()
            if fmt.isAnchor():
                anchors.update(fmt.anchorNames())
                if fmt.anchorHref().startswith("#fnref-"):
                    back_links.append(fmt.anchorHref())
        assert "fnref-a" in anchors and "fnref-b" in anchors
        assert "#fnref-a" in back_links and "#fnref-b" in back_links
        v.deleteLater()

    def test_duplicate_reference_replaced_once(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("一[^a] 二[^a] 三[^b]\n\n[^a]: A\n[^b]: B")

        text = v.document().toPlainText()
        assert "elafnref" not in text
        assert text.count("[1]") >= 1
        first_anchored = [
            f for f in _fragments(v) if "fnref-a" in f.charFormat().anchorNames()
        ]
        assert len(first_anchored) == 1
        v.deleteLater()

    def test_undefined_ref_kept_literal(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("引用[^missing] 但未定义")

        assert "[^missing]" in v.document().toPlainText()
        v.deleteLater()

    def test_definition_line_removed_from_body(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("A[^1]\n\n[^1]: note")

        blocks = [b.text() for b in _blocks(v)]
        body = [b for b in blocks if b.startswith("A")]
        assert body and "[^1]:" not in "".join(blocks[:2])
        v.deleteLater()


class TestTableStillWorksWithEnhancements:
    def test_table_and_code_unaffected(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nx = 1\n```\n\nH~2~O"
        )

        tables = []
        stack = [v.document().rootFrame()]
        while stack:
            frame = stack.pop()
            for child in frame.childFrames():
                if isinstance(child, QTextTable):
                    tables.append(child)
                stack.append(child)
        assert tables
        assert "x = 1" in v.document().toPlainText()
        v.deleteLater()
