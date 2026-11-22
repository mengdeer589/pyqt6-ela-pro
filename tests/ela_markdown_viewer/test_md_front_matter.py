"""首行 frontmatter 不能交给 Qt 的 Markdown 导入器静默吞掉。"""

from __future__ import annotations

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def test_front_matter_preserved_as_yaml_fence(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown("---\nname: demo\ndescription: >\n  多行描述\n---\n\n# 正文")
    text = viewer.document().toPlainText()
    assert "name: demo" in text
    assert "多行描述" in text
    assert "正文" in text
    assert any(
        lang == "yaml" and "name: demo" in code
        for lang, code, _closed in viewer._fenced_blocks
    )


def test_strip_mode_restores_qt_behavior(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setFrontMatterMode("strip")
    viewer.setMarkdown("---\nname: demo\n---\n\n# 正文")
    text = viewer.document().toPlainText()
    assert "name: demo" not in text
    assert "正文" in text


def test_unclosed_dash_is_not_front_matter(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown("---\n# 标题\n正文")
    text = viewer.document().toPlainText()
    assert "正文" in text
    assert not any(lang == "yaml" for lang, _code, _closed in viewer._fenced_blocks)


def test_fence_is_longer_than_backticks_in_content(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown("---\nnote: |\n  ```\n  code\n  ```\n---\n\n# 正文")
    text = viewer.document().toPlainText()
    assert "```" in text
    assert "code" in text
    assert "正文" in text


def test_bom_front_matter_is_detected(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown("\ufeff---\nname: demo\n---\n\n# 正文")
    assert "name: demo" in viewer.document().toPlainText()


def test_source_keeps_original_front_matter(make):
    viewer = make(ElaMarkdownViewer)
    source = "---\nname: demo\n---\n\n# 正文"
    viewer.setMarkdown(source)
    assert viewer.markdown() == source
