"""
Splitter 分割器组件

提供 ELA 主题风格的分割器，支持水平和垂直方向分割。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QEvent
from PyQt6.QtGui import QPainter, QPen, QPaintEvent, QMouseEvent
from PyQt6.QtWidgets import QSplitter, QSplitterHandle, QWidget, QBoxLayout

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._internal import _ThemeAwareMixin


class ElaSplitterHandle(_ThemeAwareMixin, QSplitterHandle):
    """ELA 风格分割器手柄，带中心线和圆角 grip 条。

    支持 Normal / Hover / Pressed 三种状态颜色。
    """

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._is_hover = False
        self._is_pressed = False
        self._grip_length = 36
        self.setMouseTracking(True)

        self._theme_mode = eTheme.getThemeMode()

    def set_grip_length(self, length: int) -> None:
        self._grip_length = length
        self.update()

    def get_grip_length(self) -> int:
        return self._grip_length

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    def enterEvent(self, event: QEvent) -> None:
        self._is_hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._is_hover = False
        self._is_pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._is_pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._is_pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h, mode = self.width(), self.height(), self._theme_mode
        is_horiz = self.orientation() == Qt.Orientation.Horizontal

        if self._is_hover or self._is_pressed:
            grip_color = eTheme.getThemeColor(
                mode, ElaThemeType.ThemeColor.PrimaryNormal
            )
        else:
            grip_color = eTheme.getThemeColor(
                mode, ElaThemeType.ThemeColor.BasicBorderDeep
            )

        line_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBorder)
        painter.setPen(QPen(line_color, 1))

        if is_horiz:
            cx = w // 2
            painter.drawLine(cx, 0, cx, h)
            gy = (h - self._grip_length) // 2
            grip_rect = QRectF(cx - 2, gy, 4, self._grip_length)
        else:
            cy = h // 2
            painter.drawLine(0, cy, w, cy)
            gx = (w - self._grip_length) // 2
            grip_rect = QRectF(gx, cy - 2, self._grip_length, 4)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grip_color)
        painter.drawRoundedRect(grip_rect, 2, 2)


class ElaSplitter(QSplitter):
    """ELA 主题风格的分割器：支持水平 / 垂直方向，Handle 带 grip 效果，跟随主题切换。"""

    def __init__(
        self,
        orientation: Qt.Orientation | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if orientation is not None:
            super().__init__(orientation, parent)
        else:
            super().__init__(parent)

        self._handle_width = 6
        self._grip_length = 36

        self.setHandleWidth(self._handle_width)
        self.setChildrenCollapsible(False)

    def createHandle(self):
        handle = ElaSplitterHandle(self.orientation(), self)
        handle.set_grip_length(self._grip_length)
        return handle

    def setHandleWidth(self, width: int) -> None:
        self._handle_width = width
        super().setHandleWidth(width)

    def handleWidth(self) -> int:
        return self._handle_width

    def set_grip_length(self, length: int) -> None:
        self._grip_length = length
        for i in range(self.count()):
            h = self.handle(i)
            if h and isinstance(h, ElaSplitterHandle):
                h.set_grip_length(length)

    def grip_length(self) -> int:
        return self._grip_length


def create_ela_splitter(
    widgets: list,
    orientation: Qt.Orientation = Qt.Orientation.Horizontal,
    handle_thickness: int = 6,
    sizes: Optional[list[int]] = None,
    parent: QWidget = None,
) -> QSplitter:
    """将组件列表（至少 2 个）以 ELA 风格 splitter 分割，返回配置好的 ``ElaSplitter``。"""
    if len(widgets) < 2:
        raise ValueError("组件列表至少需要 2 个组件")
    if sizes is not None and len(sizes) != len(widgets):
        raise ValueError("sizes 列表长度必须与组件列表长度一致")

    if parent is None and widgets:
        parent = widgets[0].parentWidget()

    splitter = ElaSplitter(orientation, parent)
    splitter.setHandleWidth(handle_thickness)

    if parent is not None and parent.layout() is not None:
        layout = parent.layout()
        if isinstance(layout, QBoxLayout):
            idx = layout.indexOf(widgets[0])
            if idx >= 0:
                layout.insertWidget(idx, splitter)
            else:
                layout.addWidget(splitter)
        else:
            layout.addWidget(splitter)

    for widget in widgets:
        splitter.addWidget(widget)

    if sizes is not None:
        splitter.setSizes(sizes)

    return splitter
