"""布局刷新的图片扫描门控：无图片候选的文档不再跑整篇「块 × 片段」遍历。

``_apply_images`` 是一次全文档 Python 遍历（235KB 文档三趟 ≈ 16ms），而绝大多数
文档没有任何图片。门控条件 = **Markdown 图片语法 / `<img>`（processed 文本）或
Mermaid 块**——Mermaid 图片由 ``_embed_mermaid`` 异步插入，但仍靠这条路径做
超宽缩放，所以不能只看图片语法。
"""

from __future__ import annotations

from PyQt6.QtTest import QTest

from pyqt6_ela_pro import ela_markdown_viewer as md_module
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _spy_apply_images(viewer) -> list:
    """记录布局刷新里的 ``_apply_images`` 调用（返回调用时传入的 start_block）。"""
    calls: list = []
    real = viewer._apply_images

    def wrapper(document, *args, **kwargs):
        calls.append(kwargs.get("start_block", 0))
        return real(document, *args, **kwargs)

    viewer._apply_images = wrapper
    return calls


class TestImageScanGate:
    def test_plain_document_skips_layout_scan(self, make):
        v = make(ElaMarkdownViewer)
        v.setMarkdown("# 标题\n\n正文 `code` 与 **加粗**，没有图片。")
        assert v._image_candidates is False
        calls = _spy_apply_images(v)
        v._on_layout_refresh()
        assert calls == []

    def test_markdown_image_keeps_layout_scan(self, make):
        v = make(ElaMarkdownViewer)
        v.setMarkdown("正文\n\n![缺图](missing-image.png)")
        assert v._image_candidates is True
        calls = _spy_apply_images(v)
        v._on_layout_refresh()
        assert calls, "有图片语法的文档必须保留布局刷新扫描"

    def test_html_image_keeps_layout_scan(self, make):
        v = make(ElaMarkdownViewer)
        v.setMarkdown('正文\n\n<img src="missing-image.png">')
        assert v._image_candidates is True

    def test_mermaid_block_keeps_layout_scan(self, make):
        v = make(ElaMarkdownViewer)
        # 假渲染器：不触发真实 mermaid 引擎，只验证「可能有图片 → 保留扫描」
        v.setMermaidRenderer(lambda code, theme: None)
        v.setMarkdown("```mermaid\ngraph TD; A-->B;\n```")
        assert v._image_candidates is True
        calls = _spy_apply_images(v)
        v._on_layout_refresh()
        assert calls, "Mermaid 图片靠这条路径缩放，不能按图片语法门控"

    def test_streaming_appended_image_enables_scan(self, make):
        v = make(ElaMarkdownViewer)
        v.beginStream()
        v.appendMarkdown("纯文字段落。\n\n")
        v._stream_timer.stop()
        v._flush_stream()
        assert v._image_candidates is False
        calls = _spy_apply_images(v)
        v._on_layout_refresh()
        assert calls == []

        v.appendMarkdown("![缺图](missing-image.png)\n\n")
        v._stream_timer.stop()
        v._flush_stream()
        assert v._image_candidates is True
        v._on_layout_refresh()
        assert calls, "流式追加的图片必须让后续布局刷新恢复扫描"

    def test_full_render_resets_candidates(self, make):
        v = make(ElaMarkdownViewer)
        v.setMarkdown("![缺图](missing-image.png)")
        assert v._image_candidates is True
        v.setMarkdown("普通正文，无图片。")
        assert v._image_candidates is False

    def test_chunked_render_accumulates_candidates(self, make, qapp, monkeypatch):
        """图片在**后面的分块**里：分块渲染期间累积的标志必须留住它。"""
        monkeypatch.setattr(md_module, "_LARGE_RENDER_CHARS", 10)
        monkeypatch.setattr(md_module, "_LARGE_RENDER_CHUNK", 10)
        v = make(ElaMarkdownViewer)
        v.setMarkdown(
            "纯文字段落。" * 30
            + "\n\n![缺图](missing-image.png)\n\n"
            + "更多文字。" * 30
        )
        for _ in range(200):
            if not v.isRendering():
                break
            qapp.processEvents()
            QTest.qWait(2)
        assert not v.isRendering()
        assert v._image_candidates is True
