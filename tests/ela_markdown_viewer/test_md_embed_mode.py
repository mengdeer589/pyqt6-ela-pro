"""ElaMarkdownViewer 嵌入模式测试（聊天消息等外层滚动容器场景）。"""

from __future__ import annotations


from _qthelpers import wait_until as _wait_until
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QRegion, QWheelEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

SHORT = "一行文本"
LONG = "\n\n".join(f"第 {i} 段正文，用于把文档高度撑起来。" for i in range(20))
CODE = "```python\nprint('hi')\nprint('there')\n```"


def _render_image(
    viewer: ElaMarkdownViewer, width: int = 320, height: int = 240
) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    viewer.resize(width, height)
    viewer.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return image


class TestEmbeddedMode:
    def test_background_transparent_when_embedded(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setMarkdown(SHORT)
        viewer.show()
        qapp.processEvents()

        opaque = _render_image(viewer).pixelColor(4, 4)
        assert opaque.alpha() == 255

        viewer.setEmbeddedMode(True)
        qapp.processEvents()
        transparent = _render_image(viewer).pixelColor(4, 4)
        assert transparent.alpha() == 0

        viewer.setEmbeddedMode(False)
        qapp.processEvents()
        restored = _render_image(viewer).pixelColor(4, 4)
        assert restored.alpha() == 255
        viewer.deleteLater()

    def test_scrollbars_and_wheel(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setMarkdown(LONG)
        browser = viewer.textBrowser()

        viewer.setEmbeddedMode(True)
        assert (
            browser.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert (
            browser.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert browser.forward_wheel is True

        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(browser.viewport(), event)  # 真实滚轮事件由 viewport 投递
        assert not event.isAccepted()

        viewer.setEmbeddedMode(False)
        assert browser.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        assert browser.forward_wheel is False
        viewer.deleteLater()

    def test_height_follows_document(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setEmbeddedMode(True)
        viewer.show()
        viewer.setMarkdown(SHORT)
        qapp.processEvents()
        short_height = viewer.height()

        viewer.setMarkdown(LONG)
        qapp.processEvents()
        long_height = viewer.height()
        assert long_height > short_height

        document_height = viewer.document().size().height()
        assert abs(long_height - document_height) <= 4
        assert viewer.minimumHeight() == viewer.maximumHeight() == long_height
        viewer.deleteLater()

    def test_height_updates_while_streaming(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setEmbeddedMode(True)
        viewer.show()
        viewer.beginStream()
        viewer.appendMarkdown("第一段")
        assert _wait_until(qapp, lambda: viewer.height() > 10)
        first = viewer.height()
        viewer.appendMarkdown("\n\n" + "\n\n".join(f"更多内容 {i}" for i in range(15)))
        assert _wait_until(qapp, lambda: viewer.height() > first)
        viewer.endStream()
        assert _wait_until(
            qapp,
            lambda: abs(viewer.height() - viewer.document().size().height()) <= 4,
        )
        viewer.deleteLater()

    def test_theme_switch_keeps_transparent(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setMarkdown(SHORT)
        viewer.setEmbeddedMode(True)
        viewer.show()
        qapp.processEvents()

        viewer._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        qapp.processEvents()
        pixel = _render_image(viewer).pixelColor(4, 4)
        assert pixel.alpha() == 0
        assert viewer.embeddedMode() is True
        viewer.deleteLater()

    def test_code_copy_buttons_still_available(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setEmbeddedMode(True)
        viewer.setMarkdown(CODE)
        viewer.show()
        qapp.processEvents()
        assert viewer._code_buttons
        viewer.deleteLater()

    def test_extra_padding_applied(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setEmbeddedMode(True)
        viewer.show()
        viewer.setMarkdown(SHORT)
        qapp.processEvents()
        base = viewer.height()
        assert base > 10, "先决条件：布局完成后高度必须贴合文档（不是 2px 细缝）"
        viewer.setEmbeddedExtra(20)
        qapp.processEvents()
        assert viewer.height() == base + 18  # 20 - 默认 2
        assert viewer.embeddedExtra() == 20
        viewer.deleteLater()

    def test_trim_bottom_hugs_content(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setEmbeddedMode(True)
        assert viewer.embeddedTrimBottom() is False

        viewer.setEmbeddedTrimBottom(True)
        assert viewer.embeddedTrimBottom() is True
        viewer.show()
        viewer.setMarkdown(SHORT)
        qapp.processEvents()

        document = viewer.document()
        last_rect = document.documentLayout().blockBoundingRect(document.lastBlock())
        # 文末段落下边距（12px）不再计入高度
        assert viewer.height() < document.size().height()
        # 正文没有被裁剪：最后一行底边仍在控件内
        assert viewer.height() >= last_rect.bottom()
        viewer.deleteLater()

    def test_trim_bottom_keeps_table_bottom(self, qapp):
        viewer = ElaMarkdownViewer()
        viewer.setEmbeddedMode(True)
        viewer.setEmbeddedTrimBottom(True)
        viewer.show()
        viewer.setMarkdown("| a | b |\n|---|---|\n| 1 | 2 |")
        qapp.processEvents()

        document = viewer.document()
        last_rect = document.documentLayout().blockBoundingRect(document.lastBlock())
        # 表格 / 非段落结尾走 min 守卫：内容边界不会被裁掉
        assert last_rect.height() > 0
        assert viewer.height() >= last_rect.bottom()
        viewer.deleteLater()


class TestEmbeddedHeightSlowLayout:
    """慢机器时序护栏：不可信的测量值不得被 ``setFixedHeight`` 冻结。

    真实故障形态（Win7 + 慢 CPU，偶发且能整轮可见）：查看器刚创建 / ``beginStream``
    刚清空文档时页面还没完成首次布局，此时按占位宽度（实测 98px）折行测出的高度
    一旦套用就被冻结，直到下一次流式 flush / 80ms 重排才纠正 —— 聊天里表现为
    「思考内容与后续分段之间多出数行空白」。修复后：测量不可信时保留上一次高度，
    由宽度变化时的同步重算（``resizeEvent``）与后续 flush 纠正。
    """

    TEXT = "先确认目标、约束与呈现格式，然后核对测试里钉住的不变量和边界条件。"
    FLOW = "内容" * 300

    def test_unlaid_out_measurement_is_not_frozen(self, qapp, make):
        """布局未完成时测出的 0 高度不得把控件压成 2px 细缝。"""
        viewer = make(ElaMarkdownViewer)
        viewer.setEmbeddedMode(True)
        viewer.setEmbeddedTrimBottom(True)
        viewer.beginStream()
        viewer.appendMarkdown(self.TEXT)

        # 旧实现的确定性症状：beginStream 清空文档后首次 flush 测出 0 高度，
        # setFixedHeight(2) 把正文整段压成细缝。
        assert viewer.minimumHeight() > 2
        assert viewer.maximumHeight() > 2

        # 真实布局完成后按文档自愈，且内容没有被裁
        viewer.show()
        assert _wait_until(qapp, lambda: viewer.height() > 2)
        document = viewer.document()
        last_rect = document.documentLayout().blockBoundingRect(document.lastBlock())
        assert viewer.height() >= last_rect.bottom() - 1

    def test_first_chunk_lands_without_throttle_wait(self, qapp, make):
        """首条分片不等 24ms 节流：屏幕上不留「空查看器」窗口。"""
        viewer = make(ElaMarkdownViewer)
        viewer.setEmbeddedMode(True)
        viewer.show()
        qapp.processEvents()

        viewer.beginStream()
        viewer.appendMarkdown("第一段正文")
        # 刻意不 processEvents / 不等待定时器
        assert viewer.document().toPlainText().strip() != ""

    def test_width_change_resyncs_height_without_further_content(self, qapp, make):
        """宽度变化后高度立即跟随重排后的文档，不必等 80ms 去抖或新分片。"""
        viewer = make(ElaMarkdownViewer)
        viewer.setEmbeddedMode(True)
        viewer.show()
        viewer.setMarkdown(self.FLOW)
        qapp.processEvents()
        wide_height = viewer.height()
        wide_doc = viewer.document().size().height()
        assert wide_height > 40

        viewer.resize(240, viewer.height())
        qapp.processEvents()  # 只跑投递事件，不等 80ms 重排定时器
        narrow_doc = viewer.document().size().height()
        assert narrow_doc > wide_doc, "前提：窄宽度下文档确实重排了"
        assert abs(viewer.height() - narrow_doc) <= 4, (
            f"宽度变化后高度应同步跟随文档：{viewer.height()} vs {narrow_doc:.1f}"
        )
