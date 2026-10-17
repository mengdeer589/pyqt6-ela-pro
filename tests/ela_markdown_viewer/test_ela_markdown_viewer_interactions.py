"""Tests for ElaMarkdownViewer P2 enhancements.

Covers: images (base URL, scaling, remote blocking), placeholder text,
link signal, zoom, search, export helpers and context menu.
"""

from __future__ import annotations

from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer, QUrl
from PyQt6.QtGui import (
    QColor,
    QContextMenuEvent,
    QImage,
    QPixmap,
    QTextCursor,
    QTextTable,
)
from PyQt6.QtWidgets import QApplication
from PyQt6ElaWidgetTools import ElaMenu

from pyqt6_ela_pro._internal import is_deleted
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


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


def _image_fragments(viewer: ElaMarkdownViewer) -> list:
    return [f for f in _fragments(viewer) if f.charFormat().isImageFormat()]


def _make_image(tmp_path, name: str, width: int, height: int) -> str:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    path = tmp_path / name
    image.save(str(path))
    return str(path)


class TestPlaceholder:
    def test_set_and_get(self):
        v = ElaMarkdownViewer()
        v.setPlaceholderText("正在生成…")
        assert v.placeholderText() == "正在生成…"

        v.resize(240, 120)

        pixmap = QPixmap(v.size())
        v.render(pixmap)
        v.deleteLater()

    def test_hidden_when_content_present(self):
        v = ElaMarkdownViewer()
        v.setPlaceholderText("空")
        v.setMarkdown("内容")
        assert v._source
        v.deleteLater()


class TestLinkSignal:
    def test_anchor_clicked_reemits(self):
        v = ElaMarkdownViewer()
        received = []
        v.linkActivated.connect(received.append)
        v.setMarkdown("[内部](#section) 与 [外部](https://example.com)")

        v.textBrowser().anchorClicked.emit(QUrl("#section"))
        assert received and received[-1].endswith("#section")
        v.deleteLater()


class TestZoom:
    def test_zoom_changes_document_font(self):
        v = ElaMarkdownViewer()
        base = v._base_font_point_size
        v.setZoomFactor(1.5)
        assert abs(v.document().defaultFont().pointSizeF() - base * 1.5) < 0.01
        v.zoomOut(0.5)
        assert abs(v.zoomFactor() - 1.0) < 1e-6
        v.deleteLater()

    def test_zoom_clamped(self):
        v = ElaMarkdownViewer()
        v.setZoomFactor(99)
        assert v.zoomFactor() == 4.0
        v.setZoomFactor(0)
        assert v.zoomFactor() == 0.25
        v.deleteLater()


class TestSearch:
    def test_search_highlights_and_counts(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("alpha beta alpha gamma Alpha")

        assert v.searchText("alpha") == 3
        assert len(v.textBrowser().extraSelections()) == 3
        assert v.searchText("alpha", caseSensitive=True) == 2
        v.deleteLater()

    def test_find_next_cycles(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("alpha x alpha y alpha")
        assert v.searchText("alpha") == 3

        first = v.textBrowser().textCursor().selectionStart()
        assert v.findNext()
        second = v.textBrowser().textCursor().selectionStart()
        assert second != first
        assert v.findNext()
        assert v.findNext()
        assert v.textBrowser().textCursor().selectionStart() == first
        v.deleteLater()

    def test_clear_search(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("alpha alpha")
        v.searchText("alpha")
        v.clearSearch()
        assert v.textBrowser().extraSelections() == []
        assert not v.findNext()
        v.deleteLater()


class TestImages:
    def test_local_image_scaled_to_viewport(self, tmp_path):
        path = _make_image(tmp_path, "wide.png", 1200, 600)
        v = ElaMarkdownViewer()
        v.resize(320, 240)
        v.setBaseUrl(str(tmp_path))
        v.setMarkdown(f"![宽图]({path.replace(chr(92), '/')})")

        images = _image_fragments(v)
        assert len(images) == 1
        fmt = images[0].charFormat().toImageFormat()
        assert 0 < fmt.width() <= max(v.textBrowser().viewport().width() - 24, 120)
        # 纵横比保持
        assert abs(fmt.width() / fmt.height() - 2.0) < 0.05
        v.deleteLater()

    def test_local_image_relative_path(self, tmp_path):
        _make_image(tmp_path, "pic.png", 40, 20)
        v = ElaMarkdownViewer()
        v.setBaseUrl(str(tmp_path))
        v.setMarkdown("![图](pic.png)")

        images = _image_fragments(v)
        assert len(images) == 1
        assert "pic.png" in images[0].charFormat().toImageFormat().name()
        v.deleteLater()

    def test_empty_alt_image_still_renders(self, tmp_path):
        """``![](src)`` 必须照常渲染。

        Qt 5.15 的 Markdown 导入器对 alt 为空的图片**整张静默丢弃**（没有图片
        片段、没有降级记录，``![ ](src)`` 反而正常）—— 预处理里补一个空格绕过。
        """
        _make_image(tmp_path, "noalt.png", 40, 20)
        v = ElaMarkdownViewer()
        v.setBaseUrl(str(tmp_path))
        v.setMarkdown("![](noalt.png)")

        images = _image_fragments(v)
        assert len(images) == 1, "空 alt 图片被 Qt 丢弃了"
        assert "noalt.png" in images[0].charFormat().toImageFormat().name()
        v.deleteLater()

    def test_empty_alt_reference_image_still_renders(self, tmp_path):
        """引用式 ``![][ref]`` 同样是空 alt，走同一条预处理。"""
        _make_image(tmp_path, "ref.png", 40, 20)
        v = ElaMarkdownViewer()
        v.setBaseUrl(str(tmp_path))
        v.setMarkdown("![][ref]\n\n[ref]: ref.png")

        images = _image_fragments(v)
        assert len(images) == 1, "空 alt 引用式图片被 Qt 丢弃了"
        assert "ref.png" in images[0].charFormat().toImageFormat().name()
        v.deleteLater()

    def test_literal_empty_brackets_in_text_untouched(self):
        """正文里字面量 ``![]``（后面不是 ``(`` / ``[``）不该被改写。"""
        v = ElaMarkdownViewer()
        v.setMarkdown("输入 ![] 是空图片语法")

        assert "![] 是空图片语法" in v.document().toPlainText()
        v.deleteLater()

    def test_missing_image_becomes_placeholder(self, tmp_path):
        v = ElaMarkdownViewer()
        v.setBaseUrl(str(tmp_path))
        v.setMarkdown("![缺失](nope.png)")

        assert "[图片]" in v.document().toPlainText()
        assert _image_fragments(v) == []
        v.deleteLater()

    def test_remote_images_blocked_by_default(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("![远程](https://example.com/a.png)")

        assert "[图片]" in v.document().toPlainText()
        assert _image_fragments(v) == []
        assert v.remoteImagesEnabled() is False
        v.deleteLater()

    def test_remote_images_kept_when_enabled(self):
        v = ElaMarkdownViewer()
        v.setRemoteImagesEnabled(True)
        v.setMarkdown("![远程](https://example.com/a.png)")

        images = _image_fragments(v)
        assert len(images) == 1
        assert images[0].charFormat().toImageFormat().name().startswith("https://")
        v.deleteLater()


class TestExportAndMenu:
    def test_export_helpers(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("# 标题\n\n正文 **加粗**")

        assert "标题" in v.toPlainText()
        assert "标题" in v.toHtml()
        v.deleteLater()

    def test_context_menu_actions(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nprint(1)\n```")
        menu = v._create_context_menu()
        labels = [action.text() for action in menu.actions()]
        assert "复制代码块" in labels and "复制全文" in labels
        menu.deleteLater()
        v.deleteLater()

    def test_context_menu_is_ela_style(self):
        """右键菜单必须是 ElaMenu（Ela 外观 + Ela 图标），不是 Qt 自带菜单。

        ``addElaIconAction`` 不设 ``QIcon``，而是把图标写进动作的
        ``ElaIconType`` 属性（由 ElaMenu 自绘）—— 所以这里查属性而不是 icon()。
        """

        v = ElaMarkdownViewer()
        menu = v._create_context_menu()
        assert isinstance(menu, ElaMenu)
        assert menu.getMenuItemHeight() > 0
        actions = [a for a in menu.actions() if not a.isSeparator()]
        assert actions
        assert all(a.property("ElaIconType") is not None for a in actions)
        menu.deleteLater()
        v.deleteLater()

    def test_context_menu_on_viewport_reaches_our_menu(self, qapp, monkeypatch):
        """回归：右键事件投给 **viewport**，不是 QTextBrowser 本体。

        只拦本体的话会落到 Qt 自带的「复制 / Copy Link Location / 全选」菜单 ——
        自建 ElaMenu 可达性为 0（事件根本不到过滤器）。
        """

        v = ElaMarkdownViewer()
        v.setMarkdown("正文 [链接](https://example.com)")
        calls = []
        monkeypatch.setattr(
            type(v), "_show_context_menu", lambda self, pos: calls.append(pos)
        )
        viewport = v.textBrowser().viewport()
        global_pos = viewport.mapToGlobal(viewport.rect().center())
        QApplication.sendEvent(
            viewport,
            QContextMenuEvent(QContextMenuEvent.Reason.Mouse, global_pos, global_pos),
        )
        assert calls == [global_pos]
        v.deleteLater()

    def test_show_context_menu_execs_the_menu(self, qapp, make):
        """``_show_context_menu`` 真的把菜单弹出来（execElaMenu：兜底 + 回收）。

        ``QMenu.exec`` 会**阻塞到菜单被关闭**（PyQt6 里 ``ElaMenu.exec`` 是
        shiboken 方法，类级打补丁拦不住 —— 实测 ``menu.exec`` 绕过 Python 类属性），
        所以这里放一个**挂在 viewer 上的定时器**把弹层关掉，再验证兜底与回收。
        """
        v = make(ElaMarkdownViewer)
        pos = v.mapToGlobal(v.rect().center())

        opened: list = []
        closer = QTimer(v)
        closer.setInterval(10)

        def _close_popup() -> None:
            popup = QApplication.activePopupWidget()
            if popup is None:
                return
            opened.append(popup)
            closer.stop()
            popup.close()

        closer.timeout.connect(_close_popup)
        closer.start()
        v._show_context_menu(pos)
        assert opened, "右键菜单没有弹出来"
        menu = opened[0]
        # execElaMenu 的兜底：非主屏上 ElaMenu 偶发不按 sizeHint 撑开
        assert menu.minimumSize() == menu.sizeHint()
        # execElaMenu 在关闭后回收菜单（deleteLater —— 显式冲刷 DeferredDelete）
        QCoreApplication.sendPostedEvents(menu, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert is_deleted(menu)

    def test_copy_code_at_cursor_emits_signal(self, qapp, requires_clipboard):
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nprint(1)\n```")

        table = None
        stack = [v.document().rootFrame()]
        while stack:
            frame = stack.pop()
            for child in frame.childFrames():
                if isinstance(child, QTextTable):
                    table = child
                stack.append(child)
        assert table is not None

        cursor = QTextCursor(v.document())
        cursor.setPosition(table.cellAt(0, 0).firstCursorPosition().position())
        v.textBrowser().setTextCursor(cursor)

        received = []
        v.codeCopied.connect(received.append)
        v._copy_code_at_cursor()
        qapp.processEvents()
        assert received and received[0].strip() == "print(1)"
        assert (
            _wait_for_clipboard(
                qapp,
                lambda text: text.strip() == "print(1)",
                v._copy_code_at_cursor,
            ).strip()
            == "print(1)"
        )
        v.deleteLater()

    def test_copy_full_text(self, qapp, requires_clipboard):
        v = ElaMarkdownViewer()
        v.setMarkdown("hello world")
        v._copy_all()
        qapp.processEvents()
        got = _wait_for_clipboard(qapp, lambda text: "hello world" in text, v._copy_all)
        assert "hello world" in got
        v.deleteLater()


class TestFeatureGetters:
    def test_mermaid_enabled_getter(self):
        v = ElaMarkdownViewer()
        assert v.mermaidEnabled() is True
        v.setMermaidEnabled(False)
        assert v.mermaidEnabled() is False
        v.setMermaidEnabled(True)
        assert v.mermaidEnabled() is True
        v.deleteLater()

    def test_highlight_cache_size_getter(self):
        v = ElaMarkdownViewer()
        v.setHighlightCacheSize(10)
        assert v.highlightCacheSize() == 10
        v.setHighlightCacheSize(-1)
        assert v.highlightCacheSize() == 0
        v.deleteLater()
