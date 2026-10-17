"""输入区补全 / 粘贴图片 / 排队语义测试。"""

from __future__ import annotations

import os

from PyQt6.QtCore import QMimeData, Qt, QUrl
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from _pixels import skip_if_no_pixels

from pyqt6_ela_pro.chat import ElaChatInput, ElaChatSuggestion
from pyqt6_ela_pro.chat.suggestions import SuggestionPopup


class TestSuggestionPopup:
    def test_open_and_activate(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        activated = []
        widget.popup().suggestionActivated.connect(activated.append)
        widget.popup().open(
            [
                ElaChatSuggestion(id="a", label="alpha"),
                ElaChatSuggestion(id="b", label="beta", insert_text="/beta "),
            ]
        )
        assert widget.popup().isOpen()
        assert len(widget.popup().items()) == 2
        assert widget.popup().currentIndex() == 0
        widget.popup().moveSelection(1)
        assert widget.popup().currentIndex() == 1
        assert widget.popup().activateCurrent() is True
        assert activated and activated[0].id == "b"
        assert not widget.popup().isOpen()

    def test_move_selection_wraps(self, qapp, make):
        widget = make(ElaChatInput)
        widget.popup().open(
            [ElaChatSuggestion(id=str(i), label=str(i)) for i in range(3)]
        )
        widget.popup().setCurrentIndex(2)
        widget.popup().moveSelection(1)
        assert widget.popup().currentIndex() == 0
        widget.popup().moveSelection(-1)
        assert widget.popup().currentIndex() == 2


class TestNoStyleSheetOnElaListView:
    """补全浮层不得对 ``ElaListView`` 挂 QSS（库内禁用 QStyle / QSS 路线）。

    ``ElaListView`` 自带 ``ElaListViewStyle``（``QProxyStyle``），它在
    ``drawControl`` 里用 ``ElaThemeColor(BasicText)`` 自绘 item 文本
    （``ElaListViewStyle.cpp:146-149``），并自己连 ``themeModeChanged``。
    所以：

    - QSS 的 ``color:`` **无效**（style 硬编码颜色，无视 palette）——
      实测「带 QSS vs 不带」渲染 0 / 19800 像素差异，纯死代码；
    - ``setStyleSheet()`` 会**整体替换**构造函数里的
      ``#ElaListView{background-color:transparent;}``
      （``ElaListView.cpp:14``），漏写 ``background: transparent`` 底色立刻
      变不透明（实测 19772 像素变化）。
    """

    def test_list_keeps_upstream_stylesheet(self, qapp, make):
        popup = make(SuggestionPopup)
        sheet = popup._view.styleSheet()
        assert "#ElaListView" in sheet, f"上游透明规则被覆盖：{sheet!r}"
        assert "background-color:transparent" in sheet.replace(" ", "")
        qapp.processEvents()

    def test_no_type_selector_reaching_the_list(self, qapp, make):
        """``QListView { ... }`` 这类类型选择器会命中 ElaListView 本体。"""
        popup = make(SuggestionPopup)
        sheet = popup._view.styleSheet()
        assert "QListView" not in sheet, f"不应出现类型选择器：{sheet!r}"
        qapp.processEvents()

    def test_dead_theme_hooks_removed(self, qapp, make):
        """取色交给 ElaListViewStyle，浮层不需要自己的主题钩子。"""
        popup = make(SuggestionPopup)
        assert not hasattr(popup, "_apply_theme")
        assert not hasattr(popup, "_onThemeChanged")
        qapp.processEvents()

    def test_items_still_render_after_removal(self, qapp, make):
        """删掉 QSS 不能让列表变瞎。"""

        popup = make(SuggestionPopup)
        popup.resize(240, 96)
        popup.open(
            [ElaChatSuggestion(id=str(i), label=f"src/f{i}.py") for i in range(3)]
        )
        popup.show()
        for _ in range(8):
            qapp.processEvents()
        image = QImage(popup.width(), popup.height(), QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        # PyQt6 的 ``render`` 只接受绘图设备（``render(painter)`` 需要 targetOffset，
        # 抛错会让 QPainter 悬空 → 后续用例 abort）
        popup.render(image)
        painted = 0
        colors = set()
        for y in range(image.height()):
            for x in range(image.width()):
                color = QColor(image.pixel(x, y))
                if color.alpha() > 0:
                    painted += 1
                    colors.add(color.name())
        skip_if_no_pixels(colors, "补全浮层内容")
        assert painted > 500, f"浮层几乎没画出内容（{painted} 像素）"
        qapp.processEvents()


class TestMentionProvider:
    def test_mention_insert_and_tracking(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        widget.setMentionProvider(
            lambda query: [ElaChatSuggestion(id="src/a.py", label="src/a.py")]
        )
        selected = []
        widget.mentionSelected.connect(lambda mid, label: selected.append((mid, label)))
        widget.setText("看看 @src")
        qapp.processEvents()
        assert widget.popup().isOpen()
        widget.popup().activateCurrent()
        assert widget.text() == "看看 @src/a.py "
        assert widget.mentions() == ["src/a.py"]
        assert selected == [("src/a.py", "src/a.py")]

        # 删除文本后引用失效
        widget.setText("")
        assert widget.mentions() == []

    def test_escape_closes_popup(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        widget.setMentionProvider(
            lambda query: [ElaChatSuggestion(id="a.py", label="a.py")]
        )
        widget.setText("看 @a")
        qapp.processEvents()
        assert widget.popup().isOpen()
        edit = widget.textEdit()
        edit.setFocus()
        QTest.keyClick(edit, Qt.Key.Key_Escape)
        assert not widget.popup().isOpen()

    def test_enter_activates_popup_instead_of_submit(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        widget.setMentionProvider(
            lambda query: [ElaChatSuggestion(id="a.py", label="a.py")]
        )
        submitted = []
        widget.submitted.connect(submitted.append)
        widget.setText("看 @a")
        qapp.processEvents()
        edit = widget.textEdit()
        edit.setFocus()
        QTest.keyClick(edit, Qt.Key.Key_Return)
        assert submitted == []
        assert widget.text() == "看 @a.py "


class TestShellModeRemoved:
    """Shell 模式整套移除：``!`` 前缀、开关按钮、等宽字体、模式信号。"""

    def test_bang_is_plain_text(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        edit = widget.textEdit()
        edit.setFocus()
        QTest.keyClicks(edit, "!")
        qapp.processEvents()
        assert widget.text() == "!"
        assert edit.font().family() != "Consolas"

    def test_mode_apis_gone(self, qapp, make):
        widget = make(ElaChatInput)
        for removed in ("setMode", "mode", "shellToggle", "modeChanged"):
            assert not hasattr(widget, removed), removed

    def test_upload_button_always_enabled(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        assert widget.uploadButton().isEnabled() is True


class TestPasteAndAttachments:
    def test_paste_image_dedup(self, qapp, make):
        widget = make(ElaChatInput)
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor("#336699"))
        pasted = []
        widget.imagePasted.connect(pasted.append)
        widget._on_image_pasted(image)
        widget._on_image_pasted(image)
        assert widget.attachmentCount() == 1
        assert widget.attachments()[0].isImage
        assert len(pasted) == 1

    def test_paste_clipboard_image_adds_attachment(
        self, qapp, requires_clipboard, make
    ):
        """Ctrl+V 粘贴截图：走编辑框 ``insertFromMimeData``，不插入文本。"""
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        image = QImage(16, 16, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ff8800"))
        QApplication.clipboard().setImage(image)

        widget.textEdit().paste()
        qapp.processEvents()

        assert widget.attachmentCount() == 1
        assert widget.attachments()[0].isImage
        assert widget.text() == ""
        qapp.processEvents()

    def test_paste_copied_file_adds_attachment(
        self, qapp, tmp_path, requires_clipboard, make
    ):
        """粘贴「复制的文件」（资源管理器 Ctrl+C）：进附件，而不是插一串 file:// 路径。"""
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        file_path = tmp_path / "复制的文件.txt"
        file_path.write_text("x", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(file_path))])
        QApplication.clipboard().setMimeData(mime)
        dropped = []
        widget.filesAdded.connect(dropped.append)

        widget.textEdit().paste()
        qapp.processEvents()

        assert widget.attachmentCount() == 1
        assert widget.attachments()[0].name == "复制的文件.txt"
        assert dropped and os.path.normpath(dropped[0][0]) == os.path.normpath(
            str(file_path)
        )
        assert widget.text() == ""
        qapp.processEvents()

    def test_large_paste_inserts_directly(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        mime = QMimeData()
        mime.setText("行\n" * 200)
        widget.textEdit().insertFromMimeData(mime)
        assert widget.text().count("\n") == 200


class TestSubmitSemantics:
    def test_submit_with_attachments_clears(self, qapp, make):
        widget = make(ElaChatInput)
        widget.addAttachment("a.txt", "C:/a.txt", 3)
        widget.setText("消息")
        got = []
        widget.submittedFull.connect(lambda t, a: got.append((t, len(a))))
        assert widget.submit() is True
        assert got == [("消息", 1)]
        assert widget.attachmentCount() == 0
