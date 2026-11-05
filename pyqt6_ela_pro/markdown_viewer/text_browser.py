"""内部 QTextBrowser 子类：拦截远程图片、自绘装饰层、图片点击。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QTextDocument
from PyQt6.QtWidgets import QTextBrowser, QWidget


class _ElaTextBrowser(QTextBrowser):
    """内部 QTextBrowser：按开关拦截远程图片资源（默认关闭）。"""

    #: 左键单击图片时发射（参数为文档位置）
    imageClicked = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.remote_images_enabled = False
        #: 嵌入模式：滚轮事件不消费，交给外层滚动容器
        self.forward_wheel = False
        self._press_pos = None

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        # 圆角 mask 按浏览器自身尺寸重建（父查看器的 resize 与本控件不同步）
        viewer = self.parent()
        sync = getattr(viewer, "_sync_viewport_mask", None)
        if callable(sync):
            sync()

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self.forward_wheel:
            event.ignore()
            return
        super().wheelEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """先画行内代码底、再走文档绘制、最后画装饰线（Bear / Ink）。
        自绘两趟都按 ``event.rect()``（本次真正暴露的区域）裁剪：嵌入模式下
        ``viewport()`` 是整篇文档的高度（查看器没有自己的滚动条），拿它当
        """
        viewer = self.parent()
        exposed = event.rect()
        pending = getattr(viewer, "_schedule_pending_render", None)
        if callable(pending):
            pending()
        under = getattr(viewer, "_paint_inline_code_backgrounds", None)
        if callable(under):
            painter = QPainter(self.viewport())
            try:
                under(self, painter, exposed)
            finally:
                painter.end()
        super().paintEvent(event)
        over = getattr(viewer, "_paint_document_decorations", None)
        if callable(over):
            painter = QPainter(self.viewport())
            try:
                over(self, painter, exposed)
            finally:
                painter.end()

    def loadResource(self, resource_type, url):  # noqa: N802 (Qt 命名)
        if (
            resource_type == QTextDocument.ResourceType.ImageResource
            and not self.remote_images_enabled
            and url.scheme() in ("http", "https")
        ):
            return None
        return super().loadResource(resource_type, url)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        press_pos = self._press_pos
        self._press_pos = None
        if (
            press_pos is None
            or (event.position().toPoint() - press_pos).manhattanLength() > 4
        ):
            return
        if self.textCursor().hasSelection():
            return
        cursor = self.cursorForPosition(event.position().toPoint())
        if cursor.charFormat().isImageFormat():
            self.imageClicked.emit(cursor.position())
