"""ElaMarkdownViewer 流式生命周期测试：控件销毁后定时器回调必须安全退出。

真实场景：窗口关闭 / 消息重建时，流式刷新定时器可能已排队，回调会在
C++ 对象销毁后执行——此前会抛 RuntimeError 导致 PyQt abort（0xC0000409）。
"""

from __future__ import annotations

import time

from PyQt6 import sip

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


class TestStreamAfterDelete:
    def test_flush_after_delete_is_ignored(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.resize(420, 320)
        viewer.show()
        viewer.beginStream()
        viewer.appendMarkdown("# 标题\n\n这是一段**流式**正文。")
        qapp.processEvents()

        # 直接销毁 C++ 对象（等价于窗口关闭 / 消息重建后的迟到回调场景）
        sip.delete(viewer)
        assert sip.isdeleted(viewer)

        # 修复前：_flush_stream 访问已删除的浏览器 → RuntimeError → abort
        viewer._stream_flush()
        viewer._toggle_stream_caret()
        viewer._stop_stream()
        viewer._on_layout_refresh()

    def test_large_render_step_after_delete_is_ignored(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.show()
        viewer.setMarkdown("\n\n".join(f"第 {i} 段" for i in range(5)))
        qapp.processEvents()

        sip.delete(viewer)
        assert sip.isdeleted(viewer)

        viewer._render_large_step()
        viewer._refresh_mermaid_priorities()
        viewer._pump_mermaid()


class TestStreamFallback:
    def test_render_error_falls_back_to_full_render(self, qapp, monkeypatch):
        viewer = ElaMarkdownViewer()
        viewer.resize(420, 320)
        viewer.show()
        viewer.beginStream()
        viewer.appendMarkdown("这是会被保底的正文内容。")

        def boom(*_args, **_kwargs):
            raise RuntimeError("模拟增量渲染异常")

        monkeypatch.setattr(viewer, "_render_fragment", boom)
        viewer._stream_flush()  # 不应抛异常

        assert viewer.isStreaming() is False
        assert "保底的正文" in viewer.toPlainText()
        viewer.deleteLater()
        qapp.processEvents()


class TestReplayAfterStaticRender:
    """静态内容含代码块时重新流式播放：旧表格对象失效必须安全。"""

    def test_replay_does_not_touch_stale_tables(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.resize(480, 360)
        viewer.show()
        viewer.setMarkdown("# 静态\n\n```python\nprint('hi')\n```\n")
        for _ in range(10):
            qapp.processEvents()
        assert viewer._code_buttons_tables

        # 重新播放：beginStream 清空文档（销毁旧表格）后立刻重绘
        viewer.beginStream()
        assert viewer._code_buttons_tables == []
        viewer.repaint()
        qapp.processEvents()

        viewer.appendMarkdown("# 重播\n\n```python\nx = 1\n```\n")
        for _ in range(10):
            qapp.processEvents()
            viewer.repaint()
        viewer.endStream()
        for _ in range(10):
            qapp.processEvents()
            viewer.repaint()

        assert "x = 1" in viewer.toPlainText()
        assert viewer._code_buttons_tables
        viewer.deleteLater()
        qapp.processEvents()

    def test_large_render_clears_stale_tables(self, qapp):
        """超长文档分块渲染：清空文档后旧代码表引用必须先失效。"""

        viewer = ElaMarkdownViewer()
        viewer.resize(480, 360)
        viewer.show()
        viewer.setMarkdown("# 静态\n\n```python\nprint('hi')\n```\n")
        for _ in range(10):
            qapp.processEvents()
        assert viewer._code_buttons_tables

        big = (
            "# 大文档\n\n```python\nx = 1\n```\n\n" + "段落内容。" * 40 + "\n\n"
        ) * 400
        viewer.setMarkdown(big)
        # 分块渲染期间事件循环仍会重绘：表格引用必须已清空
        assert viewer._code_buttons_tables == []

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            qapp.processEvents()
            viewer.repaint()
            if viewer._code_buttons_tables:
                break
        assert viewer._code_buttons_tables
        viewer.deleteLater()
        qapp.processEvents()
