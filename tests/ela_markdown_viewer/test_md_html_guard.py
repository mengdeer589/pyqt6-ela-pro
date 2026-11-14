"""裸 HTML 标签守卫：未配对标签不得吞掉后续正文。"""

from __future__ import annotations

from _qthelpers import wait_until

from pyqt6_ela_pro.ela_markdown_viewer import _LARGE_RENDER_CHARS, ElaMarkdownViewer
from pyqt6_ela_pro.markdown_viewer.html_guard import guard_unpaired_html


class TestGuardFunction:
    def test_unpaired_open_and_close_are_escaped(self):
        assert guard_unpaired_html("a <stub> b") == "a &lt;stub> b"
        assert guard_unpaired_html("a </stub> b") == "a &lt;/stub> b"

    def test_void_open_tags_become_self_closing(self):
        assert guard_unpaired_html("a<br>b") == "a<br/>b"
        assert guard_unpaired_html('a<img src="x">b') == 'a<img src="x"/>b'
        assert guard_unpaired_html("a<hr/>b") == "a<hr/>b"

    def test_paired_and_self_closing_tags_are_kept(self):
        assert guard_unpaired_html("<b>x</b>") == "<b>x</b>"
        assert guard_unpaired_html("<stub>x</stub>") == "<stub>x</stub>"
        assert guard_unpaired_html("<br />") == "<br />"
        assert guard_unpaired_html("<sub>2</sub>") == "<sub>2</sub>"

    def test_autolinks_and_escaped_tags_are_kept(self):
        assert guard_unpaired_html("see <https://x> tail") == "see <https://x> tail"
        assert guard_unpaired_html("mail <a@b.com> tail") == "mail <a@b.com> tail"
        assert guard_unpaired_html(r"text \<stub> tail") == r"text \<stub> tail"

    def test_non_tags_and_link_destinations_are_kept(self):
        assert guard_unpaired_html("a < 3 and <中文> tail") == "a < 3 and <中文> tail"
        assert guard_unpaired_html("[x](<foo>) tail") == "[x](<foo>) tail"
        assert (
            guard_unpaired_html('[x](<foo> "title") tail') == '[x](<foo> "title") tail'
        )
        assert guard_unpaired_html("<stub tail") == "<stub tail"

    def test_indented_code_lines_are_kept(self):
        assert guard_unpaired_html("    <div>x") == "    <div>x"
        assert guard_unpaired_html("    <br>") == "    <br>"
        assert guard_unpaired_html(">     <br>") == ">     <br>"
        assert guard_unpaired_html("- 项目\n\n      <br>") == "- 项目\n\n      <br>"

    def test_nested_unclosed_tag_is_escaped(self):
        assert guard_unpaired_html("<div><stub>x</div>") == "<div>&lt;stub>x</div>"

    def test_tag_longer_than_scan_chunk_is_still_guarded(self):
        payload = "x" * 5000
        source = f'<stub attr="{payload}"> tail'
        guarded = guard_unpaired_html(source)
        assert guarded.startswith("&lt;stub attr=")
        assert guarded.endswith("> tail")
        assert payload in guarded


class TestViewerIntegration:
    def test_unpaired_tag_keeps_tail(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("before <stub> after")
        text = viewer.toPlainText()
        assert "before" in text
        assert "after" in text
        assert "<stub>" in text

    def test_unpaired_tag_in_list_keeps_following_items(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("first line\n- one<stub>\n- two continues")
        text = viewer.toPlainText()
        assert "one" in text
        assert "two continues" in text

    def test_br_in_table_keeps_cell_and_tail(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("| h<br>s |\n|---|\n| v |\n\ntail x mid y end")
        text = viewer.toPlainText()
        assert "h" in text
        assert "s" in text
        assert "v" in text
        assert "tail x mid y end" in text

    def test_paired_html_still_renders(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("<b>bold</b> tail")
        text = viewer.toPlainText()
        assert "bold" in text
        assert "tail" in text
        assert "<b>" not in text

    def test_inline_and_fenced_code_are_protected(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("a `<stub>` b\n\n```\n<img>\n```\n\ntail")
        text = viewer.toPlainText()
        assert "<stub>" in text
        assert "<img>" in text
        assert "tail" in text

    def test_indented_code_is_protected(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("    <div>unclosed\n\n    <br>\n\ntail")
        text = viewer.toPlainText()
        assert "&lt;" not in text
        assert "<div>unclosed" in text
        assert "<br>" in text
        assert "tail" in text

    def test_autolink_and_link_destination_keep_tail(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("[x](<foo>) and <https://example.com> tail")
        text = viewer.toPlainText()
        assert "<foo>" not in text
        assert "example.com" in text
        assert "tail" in text


class TestLargeDocument:
    def test_chunked_render_and_zoom_keep_tail(self, qapp, make):
        filler = "填充段落包含足够多的文字用于超过分块阈值。\n" * 2000
        source = filler + "\nbefore <stub> after\n\n" + filler
        assert len(source) > _LARGE_RENDER_CHARS

        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown(source)
        assert viewer.isRendering() is True
        assert wait_until(
            qapp,
            lambda: not viewer.isRendering(),
            timeout_ms=10000,
        )
        text = viewer.textBrowser().document().toPlainText()
        assert "after" in text

        viewer.setZoomFactor(1.1)
        text = viewer.textBrowser().document().toPlainText()
        assert "after" in text
