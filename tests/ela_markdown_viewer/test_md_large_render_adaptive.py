"""超大文档分块粒度与可见文档切主题分块。"""

from __future__ import annotations

from _qthelpers import wait_until

import pyqt6_ela_pro.markdown_viewer.appearance as appearance_module
import pyqt6_ela_pro.markdown_viewer.stream as stream_module
import pyqt6_ela_pro.markdown_viewer.viewer as viewer_module
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _source(paragraphs: int = 100) -> str:
    return "\n\n".join(f"段落 {index} " + "x" * 40 for index in range(paragraphs))


def test_very_large_source_uses_smaller_chunks(monkeypatch, qapp, make):
    monkeypatch.setattr(viewer_module, "_LARGE_RENDER_CHARS", 100)
    monkeypatch.setattr(stream_module, "_LARGE_RENDER_CHARS", 100)
    monkeypatch.setattr(stream_module, "_LARGE_RENDER_LARGE_CHARS", 1000)
    monkeypatch.setattr(stream_module, "_LARGE_RENDER_CHUNK", 4096)
    monkeypatch.setattr(stream_module, "_LARGE_RENDER_CHUNK_LARGE", 128)

    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown(_source())
    assert viewer.isRendering() is True
    chunks = viewer._large_render_chunks
    assert len(chunks) > 20
    assert max(len(chunk) for chunk in chunks) < 400
    viewer._cancel_large_render()


def test_large_visible_theme_switch_is_chunked(monkeypatch, qapp, make):
    monkeypatch.setattr(appearance_module, "_THEME_CHUNK_CHARS", 100)
    source = "# 唯一标记\n\n" + _source(80)

    viewer = make(ElaMarkdownViewer)
    viewer.show()
    qapp.processEvents()
    viewer.setMarkdown(source)
    progress: list[int] = []
    viewer.renderingProgress.connect(progress.append)

    assert viewer.setMarkdownTheme("github") is True
    assert viewer.isRendering() is True
    assert wait_until(qapp, lambda: not viewer.isRendering(), timeout_ms=15000)
    assert progress and progress[-1] == 100
    assert viewer.toPlainText().count("唯一标记") == 1
