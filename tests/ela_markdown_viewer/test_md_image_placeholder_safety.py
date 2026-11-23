"""图片占位替换回归：收集阶段只读、多张坏图安全降级、锚点保留。

原先 ``_apply_images`` 在 ``QTextBlock`` 片段迭代中直接改写文档，片段迭代器
失效 → 0xC0000005。这里钉住两阶段形状（收集不改文档）与降级结果。
"""

from __future__ import annotations

import logging

from PyQt6.QtGui import QTextDocument

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

#: 报告里的形状：表格内 HTML ``<img>`` + 同一行多个 markdown 图片，全部坏链
_BROKEN = (
    "# t\n\n"
    "<table>\n"
    '<tr><td>姓名</td><td><img src="images/missing_1.jpg" /></td></tr>\n'
    '<tr><td><img src="images/missing_2.jpg" /></td>'
    '<td><img src="images/missing_3.jpg" /></td></tr>\n'
    "</table>\n\n"
    "![a](images/missing_4.png) ![b](images/missing_5.png)\n\nend\n"
)


def _fragments(document: QTextDocument) -> list:
    result = []
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                result.append(fragment)
            iterator += 1
        block = block.next()
    return result


def _image_fragments(document: QTextDocument) -> list:
    return [
        fragment
        for fragment in _fragments(document)
        if fragment.charFormat().isImageFormat()
    ]


def test_collect_phase_does_not_mutate_document(make):
    viewer = make(ElaMarkdownViewer)
    document = QTextDocument()
    document.setMarkdown("![a](missing_1.png) ![b](missing_2.png)")
    before_text = document.toPlainText()
    before_count = document.characterCount()

    actions = viewer._collect_image_actions(document)

    assert actions, "坏链图片应产生占位动作"
    assert document.characterCount() == before_count
    assert document.toPlainText() == before_text


def test_collect_then_apply_replaces_every_broken_image(make):
    viewer = make(ElaMarkdownViewer)
    document = QTextDocument()
    document.setMarkdown("![a](missing_1.png) ![b](missing_2.png)")

    viewer._apply_image_actions(document, viewer._collect_image_actions(document))

    assert document.toPlainText() == "[图片] [图片]"
    assert _image_fragments(document) == []


def test_report_shape_all_images_degrade(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown(_BROKEN)

    text = viewer.document().toPlainText()
    assert text.count("[图片]") == 5
    assert "end" in text
    assert _image_fragments(viewer.document()) == []

    issues = viewer.renderIssues()
    assert len(issues) == 5
    assert all(kind == "image" for kind, _ in issues)


def test_failed_image_inside_link_keeps_anchor(make):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown("[![alt](missing.png)](https://target.example)")

    assert "[图片]" in viewer.document().toPlainText()
    hrefs = [
        fragment.charFormat().anchorHref()
        for fragment in _fragments(viewer.document())
        if fragment.charFormat().isAnchor()
    ]
    assert "https://target.example" in hrefs


def test_layout_refresh_slot_swallows_exceptions(make, mocker, caplog):
    """定时器槽异常穿出 Qt = 0xC0000409，必须被吞并记录。"""
    viewer = make(ElaMarkdownViewer)
    mocker.patch.object(
        viewer, "_apply_content_width", side_effect=RuntimeError("boom")
    )

    with caplog.at_level(logging.ERROR):
        viewer._on_layout_refresh()

    assert "布局刷新失败" in caplog.text
