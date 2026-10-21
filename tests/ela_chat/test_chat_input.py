"""ElaChatInput 输入区测试：提交、快捷键、生成态、附件与工具栏。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFocusEvent, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFrame
from PyQt6ElaWidgetTools import ElaIconType

from pyqt6_ela_pro.chat import ElaChatInput, ElaChatToolBar
from pyqt6_ela_pro.chat._theme import accent_color, card_border_color
from pyqt6_ela_pro.chat.input import _MENTION_TAIL


class TestSubmit:
    def test_button_submit(self, qapp, make):
        widget = make(ElaChatInput)
        submitted = []
        widget.submitted.connect(submitted.append)
        widget.setText("  你好  ")
        widget._button.click()
        assert submitted == ["你好"]
        assert widget.text() == ""

    def test_empty_ignored(self, qapp, make):
        widget = make(ElaChatInput)
        submitted = []
        widget.submitted.connect(submitted.append)
        assert widget.submit() is False
        widget.setText("   ")
        assert widget.submit() is False
        assert submitted == []

    def test_enter_sends_shift_enter_newline(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        submitted = []
        widget.submitted.connect(submitted.append)
        edit = widget.textEdit()
        edit.setFocus()
        QTest.keyClicks(edit, "hi")
        QTest.keyClick(edit, Qt.Key.Key_Return)
        assert submitted == ["hi"]

        QTest.keyClicks(edit, "line1")
        QTest.keyClick(edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClicks(edit, "line2")
        assert submitted == ["hi"]
        assert "\n" in widget.text()

    def test_send_on_enter_disabled(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        widget.setSendOnEnter(False)
        submitted = []
        widget.submitted.connect(submitted.append)
        edit = widget.textEdit()
        edit.setFocus()
        QTest.keyClicks(edit, "x")
        QTest.keyClick(edit, Qt.Key.Key_Return)
        assert submitted == []
        assert widget.sendOnEnter() is False


class TestGenerating:
    def test_button_and_enter_switch(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        stops = []
        submitted = []
        widget.stopRequested.connect(lambda: stops.append(1))
        widget.submitted.connect(submitted.append)

        widget.setGenerating(True)
        assert widget.isGenerating()
        # 草稿为空 → 停止（图标按钮，用 tooltip 判断状态）
        assert widget._button.toolTip() == "停止"
        assert widget._button.color() == "danger"

        widget._button.click()
        assert stops == [1]

        # 有草稿 → 发送（对齐 opencode：流式中可提交排队）
        edit = widget.textEdit()
        edit.setFocus()
        QTest.keyClicks(edit, "next")
        qapp.processEvents()
        assert widget._button.toolTip() == "发送"
        assert widget._button.color() == "primary"
        QTest.keyClick(edit, Qt.Key.Key_Return)
        assert submitted == ["next"]

        widget.setGenerating(False)
        assert widget._button.toolTip() == "发送"

    def test_submit_queue_toggle_while_generating(self, qapp, make):
        widget = make(ElaChatInput)
        widget.setText("x")
        widget.setGenerating(True)
        # 默认允许排队提交
        assert widget.queueEnabled() is True
        assert widget.submit() is True

        widget.setText("y")
        widget.setQueueEnabled(False)
        assert widget.submit() is False


class TestHeight:
    def test_grows_and_clamps(self, qapp, make):
        widget = make(ElaChatInput)
        widget.setMinLines(1)
        widget.setMaxLines(4)
        widget.show()
        qapp.processEvents()
        base = widget.textEdit().height()

        widget.setText("\n".join(f"行 {i}" for i in range(3)))
        qapp.processEvents()
        grown = widget.textEdit().height()
        assert grown > base

        widget.setText("\n".join(f"行 {i}" for i in range(30)))
        qapp.processEvents()
        clamped = widget.textEdit().height()
        assert clamped == max(grown, clamped)
        line = widget._line_height()
        assert clamped <= line * 4 + 6
        assert widget.maxLines() == 4

    def test_default_min_lines(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        line = widget._line_height()
        assert widget.minLines() == 3
        assert widget.maxLines() == 8
        assert widget.textEdit().height() >= line * 3

        widget.setMinLines(5)
        qapp.processEvents()
        assert widget.textEdit().height() >= line * 5
        # min 不得超过 max
        widget.setMaxLines(2)
        assert widget.maxLines() == 5


class TestTexts:
    def test_custom_button_texts(self, qapp, make):
        widget = make(ElaChatInput)
        widget.setSendText("发送消息")
        assert widget.sendText() == "发送消息"
        assert widget._button.toolTip() == "发送消息"
        widget.setStopText("中止")
        widget.setGenerating(True)
        assert widget._button.toolTip() == "中止"

    def test_placeholder_roundtrip(self, qapp, make):
        widget = make(ElaChatInput)
        widget.setPlaceholderText("说点什么")
        assert widget.placeholderText() == "说点什么"


class TestLayers:
    def test_layers_order(self, qapp, make):
        widget = make(ElaChatInput)
        layout = widget.layout()
        # 0 补全浮层 / 1 输入卡片（附件条 / 编辑框 / 工具栏都在卡片内）
        assert layout.itemAt(0).widget() is widget.popup()
        assert layout.itemAt(1).widget() is widget.inputSurface()
        surface_layout = widget.inputSurface().layout()
        assert surface_layout.itemAt(0).widget() is widget.attachmentStrip()
        assert surface_layout.itemAt(1).widget() is widget.textEdit()
        assert surface_layout.itemAt(2).widget() is widget.toolBar()

    def test_toolbar_type(self, qapp, make):
        widget = make(ElaChatInput)
        assert isinstance(widget.toolBar(), ElaChatToolBar)

    def test_edit_is_borderless(self, qapp, make):
        """编辑框不再自绘边框（原生 CE_ShapedFrame 被代理 style 拦掉）。"""
        widget = make(ElaChatInput)
        assert widget.textEdit().frameWidth() == 0
        assert widget.textEdit().frameShape() == QFrame.Shape.NoFrame

    def test_layers_inside_card(self, qapp, make):
        """附件条 / 编辑框 / 工具栏的可视父级都是输入卡片。"""
        widget = make(ElaChatInput)
        surface = widget.inputSurface()
        assert widget.attachmentStrip().parentWidget() is surface
        assert widget.textEdit().parentWidget() is surface
        assert widget.toolBar().parentWidget() is surface

    def test_card_focus_accent(self, qapp, make):
        """聚焦时卡片边框换强调色（跟随 Ela 主题令牌）。"""

        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        surface = widget.inputSurface()
        mode = surface._theme_mode
        # show 后焦点可能自动落到编辑框，先显式送出 FocusOut 归零
        QApplication.sendEvent(
            widget.textEdit(), QFocusEvent(QFocusEvent.Type.FocusOut)
        )
        assert surface.focused() is False
        assert surface._border.name() == card_border_color(mode).name()

        QApplication.sendEvent(widget.textEdit(), QFocusEvent(QFocusEvent.Type.FocusIn))
        assert surface.focused() is True
        assert surface._border.name() == accent_color(mode).name()

        QApplication.sendEvent(
            widget.textEdit(), QFocusEvent(QFocusEvent.Type.FocusOut)
        )
        assert surface.focused() is False
        assert surface._border.name() == card_border_color(mode).name()

    def test_send_button_disabled_when_empty(self, qapp, make):
        """opencode 同款：空草稿置灰，有草稿 / 「停止」态恢复可用。"""
        widget = make(ElaChatInput)
        assert widget._button.isEnabled() is False

        widget.setText("你好")
        assert widget._button.isEnabled() is True

        widget.setText("")
        assert widget._button.isEnabled() is False

        # 生成中且草稿为空 → 按钮是「停止」，保持可用
        widget.setGenerating(True)
        assert widget._button.isEnabled() is True
        widget.setGenerating(False)


class TestToolBarExtension:
    def test_custom_tool_button(self, qapp, make):
        widget = make(ElaChatInput)
        clicks = []
        button = widget.toolBar().addButton(
            icon=ElaIconType.IconName.Bolt,
            tooltip="自定义工具",
            key="custom",
            callback=lambda: clicks.append(1),
        )
        button.click()
        assert clicks == [1]
        # 内置按钮顺序：新建话题 → 上传 → 清空上下文 → 上下文占用圆环，
        # 宿主自定义接在其后
        assert widget.toolBar().keys() == [
            "new_topic",
            "upload",
            "clear",
            "usage",
            "widget-1",
            "custom",
        ]

    def test_upload_button_and_picker(self, qapp, tmp_path, make):
        widget = make(ElaChatInput)
        assert widget.uploadButton() is widget.toolBar().toolButton("upload")
        file_path = tmp_path / "说明.txt"
        file_path.write_text("hello", encoding="utf-8")
        requests = []
        widget.uploadRequested.connect(lambda: requests.append(1))
        widget.setFilePicker(lambda: [str(file_path)])
        widget.uploadButton().click()
        assert requests == [1]
        attachments = widget.attachments()
        assert len(attachments) == 1
        assert attachments[0].name == "说明.txt"
        assert attachments[0].size == 5

    def test_upload_visibility(self, qapp, make):
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        assert widget.uploadVisible()
        widget.setUploadVisible(False)
        assert not widget.uploadVisible()

    def test_toolbar_has_no_menu_or_shell_controls(self, qapp, make):
        """工具栏只剩「上传 / 清空上下文 / 新建话题」+ 宿主自定义：

        `+` 菜单与 Shell 开关已彻底移除。
        """
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        assert widget.uploadVisible()
        assert widget.clearVisible()
        assert widget.newTopicVisible()
        toolbar = widget.toolBar()
        assert toolbar.toolButton("add_menu") is None
        assert toolbar.toolButton("shell") is None
        for removed in (
            "menuButton",
            "menu",
            "addMenuItem",
            "setMenuVisible",
            "menuVisible",
            "setShellVisible",
            "shellVisible",
            "shellToggle",
            "setMode",
            "mode",
        ):
            assert not hasattr(widget, removed), removed

    def test_bang_is_plain_text_now(self, qapp, make):
        """``!`` 不再是 Shell 模式前缀，就是普通字符。"""
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        widget.textEdit().setFocus()
        QTest.keyClicks(widget.textEdit(), "!")
        qapp.processEvents()
        assert widget.text() == "!"

    def test_clear_button_emits_request_only(self, qapp, make):
        """输入区只发 ``clearRequested``，**不自己清空**（清空是 widget 职责）。"""
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        assert widget.clearButton() is widget.toolBar().toolButton("clear")
        requested = []
        widget.clearRequested.connect(lambda: requested.append(1))
        widget.clearButton().click()
        qapp.processEvents()
        assert requested == [1]
        # 输入区自身不碰消息（它也没有消息）
        widget.setText("草稿仍在")

    def test_new_topic_button_emits_signal(self, qapp, make):
        """「新建话题」按钮只发 ``newTopicRequested``，话题 / 会话由宿主创建。"""
        widget = make(ElaChatInput)
        widget.show()
        qapp.processEvents()
        assert widget.newTopicButton() is widget.toolBar().toolButton("new_topic")
        assert widget.newTopicVisible() is True
        requested = []
        widget.newTopicRequested.connect(lambda: requested.append(1))

        widget.newTopicButton().click()
        qapp.processEvents()

        assert requested == [1]
        # 组件不做任何事：草稿与附件都留着，等宿主决定新话题怎么开
        widget.setText("草稿仍在")
        assert widget.text() == "草稿仍在"
        widget.setNewTopicVisible(False)
        assert widget.newTopicVisible() is False


class TestAttachments:
    def test_add_and_remove(self, qapp, tmp_path, make):
        widget = make(ElaChatInput)
        first = tmp_path / "a.txt"
        second = tmp_path / "b.txt"
        first.write_text("a", encoding="utf-8")
        second.write_text("b", encoding="utf-8")
        changes = []
        widget.attachmentsChanged.connect(lambda items: changes.append(len(items)))

        added = widget.addAttachments([str(first), str(second)])
        assert len(added) == 2
        assert widget.attachmentCount() == 2
        assert widget.attachments()[0].path == str(first)

        widget.removeAttachment(0)
        assert widget.attachmentCount() == 1
        assert widget.attachments()[0].name == "b.txt"

        widget.clearAttachments()
        assert widget.attachmentCount() == 0
        assert changes == [2, 1, 0]

    def test_set_attachments_dicts(self, qapp, make):
        widget = make(ElaChatInput)
        widget.setAttachments(
            [{"name": "报告.pdf", "path": "C:/tmp/报告.pdf", "size": 2048}]
        )
        attachment = widget.attachments()[0]
        assert attachment.name == "报告.pdf"
        assert attachment.displaySize == "2.0 KB"

    def test_strip_signal(self, qapp, make):
        widget = make(ElaChatInput)
        clicked = []
        removed = []
        widget.attachmentStrip().attachmentClicked.connect(clicked.append)
        widget.attachmentStrip().attachmentRemoved.connect(removed.append)
        widget.addAttachment("x.txt", "C:/tmp/x.txt", 3)
        widget.attachmentStrip().removeAttachment(0)
        assert removed == ["C:/tmp/x.txt"]
        assert widget.attachmentCount() == 0

    def test_attachment_paths(self, qapp, tmp_path, make):
        widget = make(ElaChatInput)
        first = tmp_path / "a.txt"
        second = tmp_path / "b.txt"
        first.write_text("a", encoding="utf-8")
        second.write_text("b", encoding="utf-8")
        widget.addAttachments([str(first), str(second)])
        assert widget.attachmentPaths() == [str(first), str(second)]

        # 无路径附件（剪贴板图片等）不进入路径列表，但仍保留在快照中
        widget.addAttachment("粘贴的图片.png")
        assert len(widget.attachments()) == 3
        assert widget.attachmentPaths() == [str(first), str(second)]


class TestSubmitWithAttachments:
    def test_submitted_full(self, qapp, tmp_path, make):
        widget = make(ElaChatInput)
        file_path = tmp_path / "a.txt"
        file_path.write_text("a", encoding="utf-8")
        widget.addAttachments([str(file_path)])
        widget.setText("  带附件  ")
        received = []
        widget.submittedFull.connect(
            lambda text, items: received.append((text, len(items)))
        )
        plain = []
        widget.submitted.connect(plain.append)
        assert widget.submit() is True
        assert plain == ["带附件"]
        assert received == [("带附件", 1)]
        assert widget.attachmentCount() == 0
        assert widget.text() == ""


class TestDragAndDrop:
    def _drop(self, widget, paths):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # offscreen 下 QApplication.sendEvent 的拖放路由不可靠，直接投递
        widget.dropEvent(event)
        return event

    def _drop_mime(self, widget, mime):
        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.dropEvent(event)
        return event

    def test_drop_files_adds_attachments(self, qapp, tmp_path, make):
        widget = make(ElaChatInput)
        file_path = tmp_path / "拖入.txt"
        file_path.write_text("x", encoding="utf-8")
        dropped = []
        widget.filesAdded.connect(dropped.append)
        event = self._drop(widget, [str(file_path)])
        assert event.isAccepted()
        assert dropped and os.path.normpath(dropped[0][0]) == os.path.normpath(
            str(file_path)
        )
        assert widget.attachmentCount() == 1
        assert widget.attachments()[0].name == "拖入.txt"

    def test_drop_ignores_non_files(self, qapp, tmp_path, make):
        widget = make(ElaChatInput)
        event = self._drop(widget, [str(tmp_path / "不存在.txt")])
        assert not event.isAccepted()
        assert widget.attachmentCount() == 0

    def test_drop_image_adds_attachment(self, qapp, make):
        """拖进来的图片（浏览器里拖图，mime 只有图片没有文件 URL）也进附件。"""
        widget = make(ElaChatInput)
        image = QImage(24, 24, QImage.Format.Format_ARGB32)
        image.fill(QColor("#123456"))
        mime = QMimeData()
        mime.setImageData(image)
        pasted = []
        widget.imagePasted.connect(pasted.append)

        event = self._drop_mime(widget, mime)

        assert event.isAccepted()
        assert widget.attachmentCount() == 1
        assert widget.attachments()[0].isImage
        assert len(pasted) == 1

    def test_drag_enter_accepts_files_and_images_only(self, qapp, tmp_path, make):
        widget = make(ElaChatInput)
        file_path = tmp_path / "接受.txt"
        file_path.write_text("x", encoding="utf-8")

        def enter(mime):
            event = QDragEnterEvent(
                QPoint(5, 5),
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            widget.dragEnterEvent(event)
            return event.isAccepted()

        file_mime = QMimeData()
        file_mime.setUrls([QUrl.fromLocalFile(str(file_path))])
        image_mime = QMimeData()
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        image_mime.setImageData(image)
        text_mime = QMimeData()
        text_mime.setText("只是文字")

        assert enter(file_mime) is True
        assert enter(image_mime) is True
        assert enter(text_mime) is False  # 文字拖进编辑框走 Qt 原生，卡片不收


class TestBuiltinButtonState:
    def test_visible_getters_report_intent(self, qapp, make):
        """未 show 时也要如实报告：判据是 isHidden 而非父链可见的 isVisible。"""
        widget = make(ElaChatInput)
        assert widget.uploadVisible() is True
        widget.setUploadVisible(False)
        assert widget.uploadVisible() is False
        widget.setClearVisible(False)
        assert widget.clearVisible() is False
        widget.setNewTopicVisible(False)
        assert widget.newTopicVisible() is False

    def test_icon_cache_tracks_state(self, qapp, make):
        widget = make(ElaChatInput)
        assert widget._button_icon == ElaIconType.IconName.ArrowUp
        widget.setGenerating(True)
        assert widget._button_icon == ElaIconType.IconName.CircleStop
        widget.setGenerating(False)
        widget.setText("x")
        assert widget._button_icon == ElaIconType.IconName.ArrowUp

    def test_focus_out_clears_preedit(self, qapp, make):
        """失焦后组合标记必须清掉，否则回车会被一直当成组合中。"""
        widget = make(ElaChatInput)
        widget._preedit = "组合中"
        qapp.sendEvent(widget.textEdit(), QFocusEvent(QEvent.Type.FocusOut))
        assert widget._preedit == ""


class TestAttachMimeDedup:
    def test_duplicate_files_return_false(self, qapp, make, tmp_path):
        """重复拖同一文件：不再重复发 ``filesAdded``，返回值也是 False。"""
        widget = make(ElaChatInput)
        path = tmp_path / "dup.txt"
        path.write_text("x", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        dropped = []
        widget.filesAdded.connect(dropped.append)

        assert widget.attachMime(mime) is True
        assert len(dropped) == 1
        assert os.path.normpath(dropped[0][0]) == os.path.normpath(str(path))

        assert widget.attachMime(mime) is False
        assert len(dropped) == 1
        assert widget.attachmentCount() == 1


class TestMentionTail:
    @pytest.mark.parametrize(
        "text,matched",
        [
            ("@Al ", True),
            ("@Al", True),
            ("@Al.", True),
            ("@Al㐀", False),  # CJK 扩展 A
            ("@Al𠀀", False),  # CJK 扩展 B
            ("@Al@x", False),  # 后面紧跟 @：这个 token 已被改写
            ("@Album", False),
        ],
    )
    def test_tail_covers_cjk_extensions(self, text, matched):
        found = re.search(re.escape("@Al") + _MENTION_TAIL, text) is not None
        assert found is matched


class TestLargePasteToAttachment:
    """大段粘贴转附件：临时文件走附件管线；写盘失败回退直插。

    阈值见 ``chat.input`` 的 ``_LARGE_PASTE_CHARS``(8000) / ``_LARGE_PASTE_LINES``(120)。
    """

    @staticmethod
    def _paste(widget, text):
        mime = QMimeData()
        mime.setText(text)
        widget.textEdit().insertFromMimeData(mime)

    def test_large_paste_becomes_attachment(self, qapp, make):
        widget = make(ElaChatInput)
        added = []
        widget.filesAdded.connect(added.append)
        big = "行内容\n" * 200  # 200 行 ≥ _LARGE_PASTE_LINES

        self._paste(widget, big)

        assert widget.text() == "", "大段粘贴不该塞进编辑框"
        assert widget.attachmentCount() == 1
        path = widget.attachmentPaths()[0]
        assert Path(path).read_text(encoding="utf-8") == big, "临时文件内容要逐字节一致"
        assert added and added[0] == [path], "要经 filesAdded 通知宿主（宿主零改动可用）"

    def test_small_paste_stays_inline(self, qapp, make):
        widget = make(ElaChatInput)

        self._paste(widget, "短文本")

        assert widget.text() == "短文本"
        assert widget.attachmentCount() == 0

    def test_same_content_pasted_twice_dedups(self, qapp, make):
        widget = make(ElaChatInput)
        big = "x" * 9000  # ≥ _LARGE_PASTE_CHARS

        self._paste(widget, big)
        self._paste(widget, big)

        assert widget.attachmentCount() == 1, "同内容同路径应被附件条去重"

    def test_write_failure_falls_back_to_inline(self, qapp, make, monkeypatch):
        widget = make(ElaChatInput)
        big = "y" * 9000

        def boom(self, *args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", boom)

        with pytest.warns(RuntimeWarning):
            self._paste(widget, big)

        assert widget.attachmentCount() == 0
        assert widget.text() == big, "写盘失败不能静默丢内容，要回退直插"
