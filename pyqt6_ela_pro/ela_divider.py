"""
分割线组件，风格参考 Ant Design Divider。

支持水平/垂直方向，可带文字，支持实线/虚线样式，自动适配深浅色主题。

用法::

    from pyqt6_ela_pro import ElaDivider

    ElaDivider(parent=self)                          # 纯水平线
    ElaDivider(text="OR", parent=self)                # 居中文字
    ElaDivider(text="请登录", orientation="left")     # 左对齐文字
    ElaDivider(variant="dashed", parent=self)          # 虚线
    ElaDivider(vertical=True, parent=self)             # 垂直线
"""

from __future__ import annotations

from typing import Literal, Optional

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from .widget_base import ElaThemeWidget

ElaDividerOrientation = Literal["left", "center", "right", "top", "bottom"]
ElaDividerVariant = Literal["solid", "dashed"]


class ElaDivider(ElaThemeWidget):
    """分割线组件。"""

    def __init__(
        self,
        text: str = "",
        orientation: ElaDividerOrientation = "center",
        variant: ElaDividerVariant = "solid",
        vertical: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._text = text
        self._orientation = orientation
        self._variant = variant
        self._vertical = vertical

        if vertical:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._onThemeChanged(self._theme_mode)

    # ── Public API ────────────────────────────────────────

    def setText(self, text: str) -> None:
        self._text = text
        self.update()

    def text(self) -> str:
        return self._text

    def setOrientation(self, orientation: ElaDividerOrientation) -> None:
        self._orientation = orientation
        self.update()

    def orientation(self) -> str:
        return self._orientation

    def setVariant(self, variant: ElaDividerVariant) -> None:
        self._variant = variant
        self.update()

    def variant(self) -> str:
        return self._variant

    def setVertical(self, vertical: bool) -> None:
        self._vertical = vertical
        if vertical:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.update()

    def isVertical(self) -> bool:
        return self._vertical

    # ── Internal ──────────────────────────────────────────

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        if self._vertical:
            text_w = fm.horizontalAdvance(self._text) if self._text else 0
            w = max(2, text_w + 24)
            return QSize(w, 100)
        else:
            text_h = fm.height() if self._text else 0
            h = max(24, text_h + 16)
            return QSize(100, h)

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        mode = self._theme_mode
        line_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBorderDeep)
        text_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)

        if self._vertical:
            self._paint_vertical(painter, line_color, text_color)
        else:
            self._paint_horizontal(painter, line_color, text_color)

    def _make_line_pen(self, line_color) -> QPen:
        pen = QPen(line_color, 1)
        if self._variant == "dashed":
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([4, 4])
        return pen

    def _paint_horizontal(self, painter: QPainter, line_color, text_color) -> None:
        painter.setPen(self._make_line_pen(line_color))
        self._paint_line_with_text(painter, text_color, self.height(), True)

    def _paint_vertical(self, painter: QPainter, line_color, text_color) -> None:
        painter.setPen(self._make_line_pen(line_color))
        self._paint_line_with_text(painter, text_color, self.width(), False)

    def _paint_line_with_text(
        self, painter: QPainter, text_color, size: int, horizontal: bool
    ) -> None:
        gap = 8
        edge_pad = 24
        length = self.width() if horizontal else self.height()
        center = size // 2

        if not self._text:
            if horizontal:
                painter.drawLine(edge_pad, center, length - edge_pad, center)
            else:
                painter.drawLine(center, edge_pad, center, length - edge_pad)
            return

        fm = painter.fontMetrics()
        text_w = fm.horizontalAdvance(self._text)
        text_h = fm.height()

        if horizontal:
            if self._orientation == "left":
                t_start = edge_pad
            elif self._orientation == "right":
                t_start = length - edge_pad - text_w
            else:
                t_start = (length - text_w) // 2
            t_offset = center - text_h // 2
            text_rect = QRect(t_start, t_offset, text_w, text_h)

            if t_start - gap > 0:
                painter.drawLine(0, center, t_start - gap, center)
            end_start = t_start + text_w + gap
            if end_start < length:
                painter.drawLine(end_start, center, length, center)
        else:
            if self._orientation == "top":
                t_start = edge_pad
            elif self._orientation == "bottom":
                t_start = length - edge_pad - text_h
            else:
                t_start = (length - text_h) // 2
            t_offset = center - text_w // 2
            text_rect = QRect(t_offset, t_start, text_w, text_h)

            if t_start - gap > 0:
                painter.drawLine(center, 0, center, t_start - gap)
            end_start = t_start + text_h + gap
            if end_start < length:
                painter.drawLine(center, end_start, center, length)

        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._text)
