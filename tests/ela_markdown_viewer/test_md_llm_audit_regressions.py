"""LLM Markdown 审计回归：链接占位符、裸 URL、缩进代码公式与容器围栏。"""

from __future__ import annotations

import base64

from PyQt6.QtCore import QBuffer, Qt
from PyQt6.QtGui import QFont, QImage, QTextTable

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


def _hrefs(viewer: ElaMarkdownViewer) -> list[str]:
    return [
        fragment.charFormat().anchorHref()
        for fragment in _fragments(viewer)
        if fragment.charFormat().isAnchor()
    ]


def _tables(viewer: ElaMarkdownViewer) -> list[QTextTable]:
    result = []
    stack = [viewer.document().rootFrame()]
    while stack:
        frame = stack.pop()
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                result.append(child)
            stack.append(child)
    return result


def _code_tables(viewer: ElaMarkdownViewer) -> list[QTextTable]:
    return [
        table
        for table in _tables(viewer)
        if table.columns() == 1
        and table.cellAt(0, 0).format().background().color() == viewer._code_bg
    ]


def _data_uri() -> str:
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    encoded = base64.b64encode(bytes(buffer.data())).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _list_starts(viewer: ElaMarkdownViewer) -> set[int]:
    starts = set()
    block = viewer.document().begin()
    while block.isValid():
        text_list = block.textList()
        if text_list is not None and text_list.count() > 0:
            starts.add(text_list.item(0).position())
        block = block.next()
    return starts


def _heading_count(viewer: ElaMarkdownViewer) -> int:
    count = 0
    block = viewer.document().begin()
    while block.isValid():
        if block.blockFormat().headingLevel() > 0:
            count += 1
        block = block.next()
    return count


class TestLinkTokens:
    def test_url_label_keeps_outer_href(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[https://example.com](https://target.example)")

        assert _hrefs(viewer) == ["https://target.example"]

    def test_www_label_keeps_outer_href(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[www.example.com](https://target.example)")

        assert _hrefs(viewer) == ["https://target.example"]

    def test_bold_url_label_keeps_outer_href(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[**www.example.com**](https://target.example)")

        assert _hrefs(viewer) == ["https://target.example"]

    def test_inline_code_label_keeps_href(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[`code`](https://target.example)")

        assert _hrefs(viewer) == ["https://target.example"]

    def test_mark_label_keeps_href(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[==mark==](https://target.example)")

        assert _hrefs(viewer) == ["https://target.example"]

    def test_math_label_keeps_href(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[$x$](https://target.example)")

        assert _hrefs(viewer) == ["https://target.example"]

    def test_nested_autolink_does_not_leak_placeholder(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[foo<https://example.com/?q=1](uri)>")

        text = viewer.toPlainText()
        assert "\ue000" not in text and "\ue001" not in text

    def test_image_only_link_keeps_href(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown(f"[![alt]({_data_uri()})](https://target.example)")

        assert _hrefs(viewer) == ["https://target.example"]


class TestBareUrls:
    def test_star_stays_in_url(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("see https://example.com/a*b*c now")

        assert "https://example.com/a*b*c" in _hrefs(viewer)
        assert "a*b*c" in viewer.toPlainText()

    def test_path_specials_are_autolinked(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown(
            "https://example.com/foo(bar) "
            "https://example.com/a%20b "
            "https://example.com/a~b~c "
            "https://example.com/a==b==c "
            "https://example.com/a[b]c"
        )

        hrefs = _hrefs(viewer)
        assert "https://example.com/foo(bar)" in hrefs
        assert "https://example.com/a%20b" in hrefs
        assert "https://example.com/a~b~c" in hrefs
        assert "https://example.com/a==b==c" in hrefs
        assert "https://example.com/a[b]c" in hrefs

    def test_mailto_and_www_autolink(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown(
            "mailto:a@b.com and xmpp:a@b.com and www.example.com/path_(x)"
        )

        hrefs = _hrefs(viewer)
        assert "mailto:a@b.com" in hrefs
        assert "xmpp:a@b.com" in hrefs
        assert "http://www.example.com/path_(x)" in hrefs

    def test_trailing_punctuation_is_not_part_of_href(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("(https://example.com/x).")

        assert "https://example.com/x" in _hrefs(viewer)


class TestIndentedCodeMath:
    def test_indented_code_is_not_formula(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("    x = \\[1,2\\] and $y$\n")

        text = viewer.toPlainText()
        assert "\\[1,2\\]" in text and "$y$" in text
        assert not any(
            fragment.charFormat().isImageFormat() for fragment in _fragments(viewer)
        )

    def test_list_indented_code_is_not_formula(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("- item\n\n      x = \\(a\\)\n")

        assert "x = \\(a\\)" in viewer.toPlainText()
        assert not any(
            fragment.charFormat().isImageFormat() for fragment in _fragments(viewer)
        )


class TestMathDelimiters:
    def test_empty_escaped_parentheses_stay_literal(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("\\(\\) and \\( \\)")

        assert "()" in viewer.toPlainText()
        assert "( )" in viewer.toPlainText()
        assert not any(
            fragment.charFormat().isImageFormat() for fragment in _fragments(viewer)
        )

    def test_escaped_dollar_inside_math(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("$x\\$y$ end")

        assert (
            sum(
                1
                for fragment in _fragments(viewer)
                if fragment.charFormat().isImageFormat()
            )
            == 1
        )

    def test_escaped_brackets_are_not_math(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown(r"\[\\\]")

        assert not any(
            fragment.charFormat().isImageFormat() for fragment in _fragments(viewer)
        )

    def test_invalid_display_keeps_delimiters(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("$$\n\\frac{1}{\n$$")

        text = viewer.toPlainText()
        assert text.startswith("$$") and text.rstrip().endswith("$$")


class TestContainerFences:
    def test_list_fence_keeps_one_list_and_dedents(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("- item\n\n  ```python\n  print(1)\n  ```\n\n- next\n")

        assert len(_list_starts(viewer)) == 1
        code_tables = _code_tables(viewer)
        assert len(code_tables) == 1
        assert code_tables[0].cellAt(0, 0).firstCursorPosition().block().text() == (
            "print(1)"
        )

    def test_list_fence_indents_code_card(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("- item\n\n  ```python\n  print(1)\n  ```\n\n- next\n")

        code_tables = _code_tables(viewer)
        assert len(code_tables) == 1
        assert code_tables[0].format().leftMargin() > 0

    def test_quote_fence_becomes_code_card(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("> quote\n>\n> ```python\n> print(1)\n> ```\n")

        code_tables = _code_tables(viewer)
        assert len(code_tables) == 1
        assert code_tables[0].cellAt(0, 0).firstCursorPosition().block().text() == (
            "print(1)"
        )

    def test_table_right_after_alert_marker(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("> [!NOTE]\n> | A | B |\n> |---|---|\n> | 1 | 2 |\n")

        assert len(_tables(viewer)) == 1
        assert "A" in viewer.toPlainText() and "2" in viewer.toPlainText()


class TestTableContracts:
    def test_header_alignment_matches_body(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("| L | C | R |\n|:--|:-:|--:|\n| a | b | c |\n")

        table = _tables(viewer)[0]
        for column in range(table.columns()):
            header = table.cellAt(0, column).firstCursorPosition().blockFormat()
            body = table.cellAt(1, column).firstCursorPosition().blockFormat()
            assert header.alignment() == body.alignment()

    def test_code_span_pipe_in_table_is_unescaped(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("| A | B |\n|---|---|\n| `a\\|b` | c |\n")

        text = viewer.toPlainText()
        assert "a|b" in text and "a\\|b" not in text

    def test_code_span_pipe_outside_table_is_kept(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("`a\\|b` outside")

        assert "a\\|b" in viewer.toPlainText()


class TestFootnotes:
    def test_multiline_definition_stays_in_footnote(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("a[^1]\n\n[^1]: line1\n    line2\n\n    para2\n")

        text = viewer.toPlainText()
        assert text.index("line2") > text.index("[1]")
        assert text.index("para2") > text.index("[1]")

    def test_duplicate_definition_does_not_leak(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("a[^1]\n\n[^1]: one\n[^1]: two\n")

        text = viewer.toPlainText()
        assert "one" in text and "two" not in text

    def test_indented_list_continuation_stays_in_footnote(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("a[^1]\n\n[^1]: - a\n    - b\n")

        text = viewer.toPlainText()
        assert text.index("- b") > text.index("[1]")


class TestFrontMatter:
    def test_plain_dashes_are_not_front_matter(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("---\ntext\n---\n\nbody\n")

        assert "text" in viewer.toPlainText()
        assert "body" in viewer.toPlainText()
        assert not any(lang == "yaml" for lang, _code, _closed in viewer._fenced_blocks)

    def test_toml_front_matter_is_fenced(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown('+++\ntitle = "x"\n+++\n\n# Body\n')

        assert any(lang == "toml" for lang, _code, _closed in viewer._fenced_blocks)
        assert "Body" in viewer.toPlainText()


class TestEntities:
    def test_html5_named_entities(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("&check; &cross; &star; &Dcaron; &HilbertSpace;")

        text = viewer.toPlainText()
        assert "✓" in text and "✗" in text and "Ď" in text and "ℋ" in text
        assert "&check;" not in text

    def test_xml_entities_do_not_create_tags(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("&lt;div&gt; literal &amp; text")

        text = viewer.toPlainText()
        assert "<div>" in text and "&" in text

    def test_escaped_entity_is_not_decoded(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("\\&ouml; not an entity")

        assert "&ouml;" in viewer.toPlainText()
        assert "ö" not in viewer.toPlainText()

    def test_uppercase_xml_entities_do_not_create_tags(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("&LT;script&GT;alert(1)&LT;/script&GT; after")

        text = viewer.toPlainText()
        assert "alert(1)" in text
        assert "after" in text

    def test_numeric_newline_entities_keep_word_boundary(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("foo&#10;&#10;bar")

        text = viewer.toPlainText()
        assert "foobar" not in text
        assert "foo" in text and "bar" in text


class TestMarkAndDetails:
    def test_mark_with_nested_bold(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("==**bold**==")

        matches = [
            fragment for fragment in _fragments(viewer) if "bold" in fragment.text()
        ]
        assert matches
        assert matches[0].charFormat().background().color() == viewer._mark_bg
        assert matches[0].charFormat().fontWeight() >= QFont.Weight.Bold

    def test_mark_with_inline_code(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("==`code`==")

        matches = [
            fragment for fragment in _fragments(viewer) if "code" in fragment.text()
        ]
        assert matches
        assert matches[0].charFormat().background().color() == viewer._mark_bg

    def test_mark_with_link(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("==[x](https://e.com)==")

        assert "https://e.com" in _hrefs(viewer)
        matches = [
            fragment for fragment in _fragments(viewer) if "x" in fragment.text()
        ]
        assert matches
        assert matches[0].charFormat().background().color() == viewer._mark_bg

    def test_details_summary_markdown(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown(
            "<details>\n<summary>**Bold** `code`</summary>\n\nbody\n\n</details>\n"
        )

        matches = [
            fragment for fragment in _fragments(viewer) if "Bold" in fragment.text()
        ]
        assert matches
        assert matches[0].charFormat().fontWeight() >= QFont.Weight.Bold

    def test_inline_details_is_folded(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("<details><summary>S</summary>body</details>\n")

        assert viewer.toPlainText().startswith("+ S")

    def test_details_summary_on_open_line_is_folded(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown(
            "<details><summary>**More** `code`</summary>\n\nbody\n\n</details>\n"
        )

        assert viewer.toPlainText().startswith("+ More code")

    def test_details_summary_link_is_clickable(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown(
            "<details><summary>[x](https://e.com)</summary>\n\nbody\n\n</details>\n"
        )

        assert "https://e.com" in _hrefs(viewer)

    def test_details_open_starts_expanded_and_can_collapse(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("<details open><summary>S</summary>\n\nbody\n\n</details>\n")

        assert "body" in viewer.toPlainText()
        viewer._toggle_fold_expanded("0")
        assert "body" not in viewer.toPlainText()


class TestEmptyStructure:
    def test_empty_headings_are_preserved(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("##\n#\n### ###\n")

        assert _heading_count(viewer) == 3

    def test_empty_list_items_are_preserved(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("-\n- a\n")

        assert len(_list_starts(viewer)) == 1
        assert viewer.toPlainText().count("\n") == 1


class TestMalformedCodeSpan:
    def test_wrapped_backticks_stay_literal(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("```foo``")

        assert "```foo``" in viewer.toPlainText()
        assert not _code_tables(viewer)
