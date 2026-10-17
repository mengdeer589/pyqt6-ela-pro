"""流式 / 分块提交必须继承片段首块的 ``QTextBlockFormat``。

``_flush_stream`` 与 ``_render_large_step`` 造分块时若用默认 ``QTextBlockFormat()``，
``insertFragment`` 会把片段首块并入该默认块，于是稳定段的段距（正文 12px / 标题 16px）
与行高（160%）全丢：实测四段思考流式期间 ``document().size().height()`` = 120.8、
``endStream()`` 后 = 188.0 —— 聊天里表现为「思考内容定稿那一瞬间掉下数行」。
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QVBoxLayout, QWidget

import pyqt6_ela_pro.ela_markdown_viewer as M
from _qthelpers import wait_until as _wait_until
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

DOC = (
    "Para one about the repo.\n\n"
    "# 一级标题\n\n"
    "Para two with enough words to make the paragraph wrap around "
    "a couple of times inside the card.\n\n"
    "## 二级标题\n\n"
    "Para three closes the thinking."
)


def _format_table(viewer: ElaMarkdownViewer) -> list:
    """逐块 ``(首词, top, bottom, lineHeight, left)``，与定稿 / 静态渲染对拍。"""
    table = []
    block = viewer.document().firstBlock()
    while block.isValid():
        fmt = block.blockFormat()
        table.append(
            (
                block.text().strip().split(" ")[0][:12],
                round(fmt.topMargin(), 1),
                round(fmt.bottomMargin(), 1),
                round(fmt.lineHeight(), 1),
                round(fmt.leftMargin(), 1),
            )
        )
        block = block.next()
    return table


def _make_viewer(make, qapp, width: int = 420) -> ElaMarkdownViewer:
    viewer = make(ElaMarkdownViewer)
    viewer.setEmbeddedMode(True)
    viewer.setEmbeddedTrimBottom(True)
    host = make(QWidget)
    host.resize(width + 20, 500)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.addWidget(viewer)
    layout.addStretch(1)
    viewer.show()
    host.show()
    qapp.processEvents()
    return viewer


def _stream(viewer: ElaMarkdownViewer, qapp, step: int = 30) -> None:
    """按 ``step`` 字符分片喂入并同步 flush（不等节流定时器）。"""
    viewer.beginStream()
    for i in range(0, len(DOC), step):
        viewer.appendMarkdown(DOC[i : i + step])
        viewer._stream_timer.stop()
        viewer._flush_stream()
    qapp.processEvents()


class TestStreamKeepsBlockFormats:
    def test_streamed_formats_match_static(self, qapp, make):
        """流式逐块格式与一次性 ``setMarkdown`` 完全一致。"""
        streamed = _make_viewer(make, qapp)
        _stream(streamed, qapp)
        reference = _make_viewer(make, qapp)
        reference.setMarkdown(DOC)
        qapp.processEvents()

        rows = _format_table(streamed)
        # 鉴别力：正文 12px 段距、标题 16px 都在表里（不是两边一起塌成 0 也算「一致」）
        assert rows[0][2] == 12.0
        assert rows[1][2] == 16.0
        assert rows == _format_table(reference)

    def test_document_height_does_not_jump_on_settle(self, qapp, make):
        """``endStream()`` 不得改变文档高度 —— 「定稿瞬间掉下数行」的直接判据。"""
        viewer = _make_viewer(make, qapp)
        _stream(viewer, qapp)
        height_before = viewer.document().size().height()
        widget_before = viewer.height()

        viewer.endStream()
        qapp.processEvents()

        assert abs(viewer.document().size().height() - height_before) < 0.05
        assert viewer.height() == widget_before

    def test_heading_started_segment_keeps_heading_format(self, qapp, make):
        """以标题开头的稳定段：标题块格式不得被造分块的默认格式吃掉。"""
        viewer = _make_viewer(make, qapp)
        _stream(viewer, qapp)
        rows = {r[0]: r for r in _format_table(viewer)}
        assert rows["一级标题"][1:3] == (16.0, 16.0)
        assert rows["二级标题"][1:3] == (16.0, 16.0)


class TestChunkedLargeRenderKeepsBlockFormats:
    """``_render_large_step`` 是同一条造块路径，超阈值分块渲染同样要继承格式。"""

    def test_chunked_blocks_keep_typography(self, monkeypatch, qapp, make):
        monkeypatch.setattr(M, "_LARGE_RENDER_CHARS", 120)
        monkeypatch.setattr(M, "_LARGE_RENDER_CHUNK", 40)
        assert len(DOC) > 3 * M._LARGE_RENDER_CHUNK, "前置条件：必须切成多块才有鉴别力"

        chunked = _make_viewer(make, qapp)
        chunked.setMarkdown(DOC)
        assert _wait_until(qapp, lambda: not chunked.isRendering(), timeout_ms=15000)
        reference = _make_viewer(make, qapp)
        monkeypatch.setattr(M, "_LARGE_RENDER_CHARS", 10**9)
        reference.setMarkdown(DOC)
        qapp.processEvents()

        # 分块边界可落在段落中间（既有行为，与格式无关），所以只比格式值不比块数：
        # 回退成默认 QTextBlockFormat() 造块时，每块首块都是 (0,0,-1,0)，必不在静态集合里
        static_formats = {r[1:] for r in _format_table(reference) if r[0]}
        rows = [r for r in _format_table(chunked) if r[0]]
        assert len(rows) > len(_format_table(reference)) // 2
        assert {r[1:] for r in rows} <= static_formats


@pytest.mark.parametrize(
    ("index", "expected_margin"),
    [(0, 12.0), (1, 16.0), (3, 16.0)],
    ids=["paragraph", "h1", "h2"],
)
def test_streamed_block_carries_expected_margin(qapp, make, index, expected_margin):
    """单点钉数值：回退成 ``QTextBlockFormat()`` 造块时这里必红。"""
    viewer = _make_viewer(make, qapp)
    _stream(viewer, qapp)
    assert _format_table(viewer)[index][2] == pytest.approx(expected_margin)
