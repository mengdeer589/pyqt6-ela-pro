"""Tests for ElaMarkdownViewer P1 batch.

Covers: reasoning fold blocks, ``<details>`` folds, diff line shading,
front matter stripping, link tooltips and ``renderIssues``.
"""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtTest import QTest

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _plain(viewer: ElaMarkdownViewer) -> str:
    return viewer.document().toPlainText()


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


class TestReasoningFold:
    SOURCE = "前置\n\n<think>\n内部推理\n</think>\n\n后置"

    def test_collapsed_by_default(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        text = _plain(v)
        assert "▸ 思考过程" in text
        assert "内部推理" not in text
        assert "前置" in text and "后置" in text
        assert "elafold" not in text
        v.deleteLater()

    def test_expand_and_collapse(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        v._toggle_fold_expanded("0")
        text = _plain(v)
        assert "▾ 思考过程" in text
        assert "内部推理" in text

        v._toggle_fold_expanded("0")
        assert "内部推理" not in _plain(v)
        v.deleteLater()

    def test_anchor_click_toggles(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        v._on_anchor_clicked(QUrl("#elafold-0"))
        assert "内部推理" in _plain(v)
        v.deleteLater()

    def test_custom_label(self):
        v = ElaMarkdownViewer()
        v.setReasoningLabel("推理链")
        v.setMarkdown(self.SOURCE)
        assert "▸ 推理链" in _plain(v)
        assert v.reasoningLabel() == "推理链"
        v.deleteLater()

    def test_disable_tag_renders_content(self):
        v = ElaMarkdownViewer()
        v.setReasoningTag(None)
        v.setMarkdown("<思考>\n内部推理\n</思考>")
        text = _plain(v)
        assert "内部推理" in text
        assert "思考过程" not in text
        assert v.reasoningTag() is None
        v.deleteLater()

    def test_stream_pending_label(self, qapp):
        v = ElaMarkdownViewer()
        v.beginStream()
        v.appendMarkdown("<think>\n还没结束")
        QTest.qWait(80)

        text = _plain(v)
        assert "思考中…" in text
        assert "还没结束" not in text
        v.endStream()
        assert "还没结束" not in _plain(v)
        v.deleteLater()


class TestDetailsFold:
    SOURCE = "<details>\n<summary>更多信息</summary>\n隐藏内容\n</details>"

    def test_collapsed_and_expand(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        text = _plain(v)
        assert "▸ 更多信息" in text
        assert "隐藏内容" not in text

        v._toggle_fold_expanded("0")
        text = _plain(v)
        assert "▾ 更多信息" in text
        assert "隐藏内容" in text
        v.deleteLater()

    def test_default_summary_label(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("<details>\n无摘要内容\n</details>")
        assert "▸ 详情" in _plain(v)
        v.deleteLater()


class TestFrontMatter:
    SOURCE = "---\ntitle: t\ntags: [a]\n---\n\n# 标题"

    def test_full_render_strips_front_matter(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        text = _plain(v)
        assert "title" not in text
        assert "tags" not in text
        assert "标题" in text
        v.deleteLater()

    def test_fragment_render_strips_front_matter(self, qapp):
        """Qt 6 的 Markdown 导入器原生剥离 front matter：流式 / 全量一致。

        （Qt 5.15 没有这个能力，旧实现自己在 ``_preprocess`` 里剥；迁移到 Qt6
        后那套机制是死代码，已删除 —— 这里钉「流式中途也不会漏出 front matter」。）
        """
        v = ElaMarkdownViewer()
        v.beginStream()
        v.appendMarkdown(self.SOURCE)
        QTest.qWait(80)
        text = _plain(v)
        assert "title: t" not in text
        assert "标题" in text  # 正文已经渲染出来

        v.endStream()
        assert "title: t" not in _plain(v)
        v.deleteLater()


class TestDiffHighlight:
    SOURCE = "```diff\n@@ -1 +1 @@\n-old\n+new\n```\n\n间隔段落"

    def test_line_backgrounds(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)

        table = [t for t in v._iter_tables(v.document()) if v._is_code_table(t)][0]
        cell = table.cellAt(table.rows() - 1, 0)
        colors = set()
        for number in range(
            cell.firstCursorPosition().blockNumber(),
            cell.lastCursorPosition().blockNumber() + 1,
        ):
            block = v.document().findBlockByNumber(number)
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.text().strip():
                    colors.add(fragment.charFormat().background().color().name())
                iterator += 1
        assert v._diff_hunk_bg.name() in colors
        assert v._diff_del_bg.name() in colors
        assert v._diff_add_bg.name() in colors
        v.deleteLater()


class TestLinkTooltip:
    def test_external_link_has_url_tooltip(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("见 [站点](https://example.com) 说明")

        tooltips = {
            fragment.charFormat().toolTip()
            for fragment in _fragments(v)
            if fragment.charFormat().isAnchor()
        }
        assert "https://example.com" in tooltips
        v.deleteLater()

    def test_control_anchors_have_no_tooltip(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(
            "- [ ] 待办\n\n<details>\n<summary>摘要</summary>\n内容\n</details>"
        )

        for fragment in _fragments(v):
            fmt = fragment.charFormat()
            if fmt.isAnchor() and fmt.anchorHref().startswith("#"):
                assert not fmt.toolTip()
        v.deleteLater()


class TestRenderIssues:
    def test_clean_render_has_no_issues(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("# 正常\n\n```python\nx = 1\n```")
        assert v.renderIssues() == []
        v.deleteLater()

    def test_missing_image_recorded(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("![缺失](C:/no/such/dir/none.png)")

        issues = v.renderIssues()
        assert any(kind == "image" for kind, _ in issues)
        assert "[图片]" in v.document().toPlainText()
        v.deleteLater()

    def test_issues_reset_on_full_render(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("![缺失](C:/no/such/dir/none.png)")
        assert v.renderIssues()

        v.setMarkdown("# 正常")
        assert v.renderIssues() == []
        v.deleteLater()
