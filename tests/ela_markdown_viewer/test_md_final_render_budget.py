"""流式收尾（``endStream``）的大文档渲染预算回归。

收尾的全量重渲染是正确性契约（列表 / 表格 / 脚注在提交边界上只有全量渲染
才对）。这份守卫只钉**哪里可以分帧**：可见内容必须同步渲染完（分帧会先清空
文档再逐块长回来 = 闪烁），不可见的后台查看器走分块渲染，且读取入口会先把
在途渲染补完。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QStackedWidget, QWidget

from pyqt6_ela_pro.ela_markdown_viewer import (
    _LARGE_RENDER_CHARS,
    ElaMarkdownViewer,
)

_CHUNK = "这是一个用于验证流式收尾渲染的段落，包含 `行内代码` 与普通文本。"


def _big_markdown() -> str:
    text = _CHUNK * 2600
    assert len(text) > _LARGE_RENDER_CHARS
    return text


def _stream(viewer: ElaMarkdownViewer, source: str, chunk: int = 2000) -> None:
    viewer.beginStream()
    for start in range(0, len(source), chunk):
        viewer.appendMarkdown(source[start : start + chunk])


def _reference_text(qapp, make, source: str) -> str:
    reference = make(ElaMarkdownViewer)
    reference.resize(600, 400)
    reference.show()
    reference.setMarkdown(source)
    qapp.processEvents()
    return reference.toPlainText()


class TestFinalRenderBudget:
    def test_hidden_viewer_renders_in_chunks(self, qapp, make):
        """后台标签页：收尾不阻塞，内容在后续 tick 里补齐。"""
        host = make(QWidget)
        host.resize(800, 600)
        stack = make(QStackedWidget, host)
        stack.resize(800, 600)
        front = make(QWidget)
        back = make(QWidget)
        stack.addWidget(front)
        stack.addWidget(back)
        viewer = make(ElaMarkdownViewer, back)
        host.show()
        qapp.processEvents()
        assert viewer.isVisible() is False
        assert viewer.window().isVisible() is True

        source = _big_markdown()
        _stream(viewer, source)
        finished: list = []
        viewer.streamFinished.connect(lambda: finished.append(True))

        viewer.endStream()
        assert finished == [True], "streamFinished 必须立即发出"
        assert viewer.isRendering() is True, "不可见的大文档应分帧渲染"
        # 读取入口先补完在途渲染（结果与一次性渲染一致）
        assert viewer.toPlainText() == _reference_text(qapp, make, source)
        assert viewer.isRendering() is False

    def test_visible_viewer_renders_synchronously(self, qapp, make):
        """可见内容必须同步收尾：分帧会先清空文档（闪烁）。"""
        host = make(QWidget)
        host.resize(800, 600)
        stack = make(QStackedWidget, host)
        stack.resize(800, 600)
        page = make(QWidget)
        stack.addWidget(page)
        viewer = make(ElaMarkdownViewer, page)
        host.show()
        stack.setCurrentWidget(page)
        qapp.processEvents()
        assert viewer.isVisible() is True

        source = _big_markdown()
        _stream(viewer, source)
        viewer.endStream()
        assert viewer.isRendering() is False
        assert viewer.toPlainText() == _reference_text(qapp, make, source)

    def test_never_shown_viewer_renders_synchronously(self, qapp, make):
        """未显示过的独立控件不分帧：调用方不能拿到异步结果。"""
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        source = _big_markdown()
        _stream(viewer, source)
        viewer.endStream()
        assert viewer.isRendering() is False
        assert viewer.toPlainText() == _reference_text(qapp, make, source)

    def test_small_document_never_chunks(self, qapp, make):
        host = make(QWidget)
        host.resize(800, 600)
        stack = make(QStackedWidget, host)
        front = make(QWidget)
        back = make(QWidget)
        stack.addWidget(front)
        stack.addWidget(back)
        viewer = make(ElaMarkdownViewer, back)
        host.show()
        qapp.processEvents()

        source = _CHUNK * 40
        assert len(source) < _LARGE_RENDER_CHARS
        _stream(viewer, source)
        viewer.endStream()
        assert viewer.isRendering() is False
        assert viewer.toPlainText() == _reference_text(qapp, make, source)
