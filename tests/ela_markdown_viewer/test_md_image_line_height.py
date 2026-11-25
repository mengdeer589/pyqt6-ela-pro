"""图片块行高：百分比行高不能乘以图片高度（图后 65% 图高空白）。"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QImage, QTextBlockFormat
from _qthelpers import wait_until

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _make_image(tmp_path, width=1200, height=800) -> str:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("#cc3333"))
    path = tmp_path / "figure.png"
    image.save(str(path))
    return str(path)


def _render(make, qapp, path, theme="bear", markdown=None):
    viewer = make(ElaMarkdownViewer)
    viewer.resize(620, 900)
    viewer.setStickToBottom(False)
    viewer.setMarkdownTheme(theme)
    viewer.setMarkdown(
        markdown or f'![x]({path})\n<p align="center">caption</p>\n\nnext paragraph'
    )
    viewer.show()
    assert wait_until(
        qapp,
        lambda: viewer.document().documentLayout().documentSize().height() > 0,
    )
    return viewer


def _image_block(viewer):
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                return block
            iterator += 1
        block = block.next()
    raise AssertionError("no image block")


class TestImageBlockLineHeight:
    def test_caption_line_starts_below_image(self, qapp, make, tmp_path):
        viewer = _render(make, qapp, _make_image(tmp_path))
        block = _image_block(viewer)
        layout = block.layout()
        assert layout.lineCount() >= 2, "图注应换到图片下一行"
        image_line = layout.lineAt(0)
        caption_line = layout.lineAt(1)
        gap = caption_line.y() - (image_line.y() + image_line.height())
        assert gap < 30, f"图注被推远 {gap:.1f}px（图高 {image_line.height():.1f}）"
        assert "caption" in block.text()

    def test_image_only_block_has_no_gap(self, qapp, make, tmp_path):
        path = _make_image(tmp_path)
        viewer = _render(make, qapp, path, markdown=f"![x]({path})\n\nnext paragraph")
        block = _image_block(viewer)
        layout = viewer.document().documentLayout()
        following = block.next()
        assert following.isValid()
        gap = (
            layout.blockBoundingRect(following).top()
            - layout.blockBoundingRect(block).bottom()
        )
        assert gap < 30

    def test_image_block_uses_minimum_line_height(self, qapp, make, tmp_path):
        viewer = _render(make, qapp, _make_image(tmp_path))
        block_format = _image_block(viewer).blockFormat()
        assert (
            block_format.lineHeightType()
            == QTextBlockFormat.LineHeightTypes.MinimumHeight.value
        )
        assert block_format.lineHeight() > 0

    def test_text_block_keeps_proportional_line_height(self, qapp, make, tmp_path):
        viewer = _render(make, qapp, _make_image(tmp_path))
        block = viewer.document().findBlockByNumber(1)
        assert block.text().startswith("next paragraph")
        block_format = block.blockFormat()
        assert block_format.lineHeight() == 165.0
        assert (
            block_format.lineHeightType()
            == QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
        )

    def test_caption_gap_across_theme_line_height(self, qapp, make, tmp_path):
        viewer = _render(make, qapp, _make_image(tmp_path), theme="typo")
        block = _image_block(viewer)
        layout = block.layout()
        assert layout.lineCount() >= 2
        image_line = layout.lineAt(0)
        caption_line = layout.lineAt(1)
        gap = caption_line.y() - (image_line.y() + image_line.height())
        assert gap < 30, f"typo 主题图注被推远 {gap:.1f}px"
