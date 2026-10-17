from __future__ import annotations

import pytest
from _qthelpers import wait_until
from PyQt6.QtGui import QTextCursor

from pyqt6_ela_pro.ela_markdown_viewer import _LARGE_RENDER_CHARS, ElaMarkdownViewer

#: 明确标记旧文档内容的串 —— 新文档里绝不出现
STALE_MARK = "AAA"

SMALL_DOC = "\n\n".join(
    f"{STALE_MARK} 第{i}段\n\nBBB 第{i}段\n\nCCC 第{i}段\n\nDDD 第{i}段"
    for i in range(4)
)


def _big_doc() -> str:
    rows = [f"- 列表项 {i:05d} 内容填充 {i} 用于把文档推过阈值" for i in range(4000)]
    text = "\n\n".join(rows)
    assert len(text) > _LARGE_RENDER_CHARS
    return text


def _settle(viewer, qapp, timeout_ms=20000):
    wait_until(
        qapp, lambda: not viewer.isRendering(), timeout_ms=timeout_ms, use_qwait=True
    )
    qapp.processEvents()


def _select(viewer, block):
    """把光标放到该块并**建立真实选区**（PyQt5 无 SelectionType.Block）。"""
    cursor = QTextCursor(block)
    cursor.setPosition(
        block.position() + len(block.text()), QTextCursor.MoveMode.KeepAnchor
    )
    viewer._text_browser.setTextCursor(cursor)


@pytest.fixture
def viewer(make, qapp):
    widget = make(ElaMarkdownViewer)
    widget.resize(900, 600)
    widget.show()
    qapp.processEvents()
    return widget


class TestChunkedRenderSourceMap:
    def test_big_document_goes_through_chunked_path(self, viewer, qapp):
        viewer.setMarkdown(_big_doc())
        _settle(viewer, qapp)
        assert viewer.document().blockCount() > 1000

    def test_render_does_not_build_map_eagerly(self, viewer, qapp):
        """渲染路径不得提前建表（懒建）：51KB 文档建表实测 0.45s，而多数会话
        从不引用回复。"""
        viewer.setMarkdown(SMALL_DOC)
        qapp.processEvents()
        assert viewer._block_source_map is None
        viewer.setMarkdown(_big_doc())
        _settle(viewer, qapp)
        assert viewer._block_source_map is None

    def test_no_stale_mapping_from_previous_document(self, viewer, qapp):
        """核心：先小文档（建表）→ 再大文档，映射不得残留。"""
        viewer.setMarkdown(SMALL_DOC)
        qapp.processEvents()
        assert len(viewer._ensure_source_map()) > 0, "前置条件：小文档应建表"

        big = _big_doc()
        viewer.setMarkdown(big)
        _settle(viewer, qapp)
        assert viewer._block_source_map is None, "新文档加载后旧映射没被作废"

        lines = big.split("\n")
        leaked = []
        for number, rng in viewer._ensure_source_map().items():
            if rng is None:
                continue
            text = "\n".join(lines[rng[0] : rng[1]]).strip()
            if text and STALE_MARK in text:
                leaked.append((number, rng))
        assert not leaked, f"映射到了上一份文档的内容：{leaked[:3]}"

    def test_mapping_is_actually_built_for_chunked_document(self, viewer, qapp):
        viewer.setMarkdown(_big_doc())
        _settle(viewer, qapp)
        mapping = viewer._ensure_source_map()
        assert len(mapping) > 0, "分块渲染完成后仍没有源行映射"
        real = [rng for rng in mapping.values() if rng is not None]
        assert len(real) > 100, f"映射几乎全是 None（{len(real)}/{len(mapping)}）"

    def test_fresh_viewer_big_document_has_mapping(self, make, qapp):
        """全新 viewer 直接上>64KB：映射不应为空（此前必然是空的）。"""
        widget = make(ElaMarkdownViewer)
        widget.resize(900, 600)
        widget.show()
        qapp.processEvents()
        widget.setMarkdown(_big_doc())
        _settle(widget, qapp)
        assert len(widget._ensure_source_map()) > 0

    def test_markdown_selection_returns_new_document_source(self, viewer, qapp):
        viewer.setMarkdown(SMALL_DOC)
        qapp.processEvents()
        viewer.setMarkdown(_big_doc())
        _settle(viewer, qapp)

        number = viewer.document().blockCount() - 3
        block = viewer.document().findBlockByNumber(number)
        assert block is not None
        _select(viewer, block)
        selected = viewer.markdownSelection()
        assert selected.strip(), "分块渲染的文档取不到源行"
        assert STALE_MARK not in selected
        # 还原的是 **Markdown 源**，所以带列表标记；块文本没有
        assert selected.startswith("- ")
        assert selected.strip().lstrip("- ").strip() == block.text().strip()

    def test_multi_block_selection_returns_contiguous_slice(self, viewer, qapp):
        viewer.setMarkdown(_big_doc())
        _settle(viewer, qapp)
        first = viewer.document().findBlockByNumber(10)
        last = viewer.document().findBlockByNumber(12)
        cursor = QTextCursor(first)
        cursor.setPosition(
            last.position() + len(last.text()), QTextCursor.MoveMode.KeepAnchor
        )
        viewer._text_browser.setTextCursor(cursor)
        selected = viewer.markdownSelection()
        for index in (10, 11, 12):
            assert f"列表项 {index:05d}" in selected, selected[:120]

    def test_begin_large_render_clears_map_immediately(self, viewer, qapp):
        """作废必须发生在**渲染开始前**，否则中途查询仍能拿到旧映射。"""
        viewer.setMarkdown(SMALL_DOC)
        qapp.processEvents()
        assert len(viewer._ensure_source_map()) > 0
        viewer._begin_large_render()
        assert viewer._block_source_map is None, "分块渲染开始时旧映射没被作废"
        viewer._cancel_large_render()
