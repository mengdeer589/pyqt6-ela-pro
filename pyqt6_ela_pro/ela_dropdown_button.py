"""
下拉按钮组件，风格参考 ElaWidgetTools 的 ElaDropDownButton。

点击展开下拉菜单。

用法::

    from pyqt6_ela_pro import ElaDropDownButton

    btn = ElaDropDownButton(text="操作", icon=ElaIconType.IconName.Gear, parent=self)

    menu = ElaMenu(btn)
    menu.addAction("选项一")
    btn.setMenu(menu)
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QSize, QPoint, QEvent
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QFont,
    QFontMetrics,
    QPaintEvent,
    QMouseEvent,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaThemeType, ElaIconType, ElaMenu

from ._colors import state_tint
from ._internal import is_deleted
from ._styles import iconGlyph, paintRoundedCard
from ._theme import text, textDisabled
from .widget_base import ElaThemeWidget

#: 全透明（基础态 / 禁用态不画底）
_TRANSPARENT = QColor(0, 0, 0, 0)

#: 控件高度：与按钮族一致（ElaPushButton V3.0 / ElaButton middle 都是 30）
_HEIGHT = 30


class ElaDropDownButton(ElaThemeWidget):
    """下拉按钮：点击展开 ElaMenu，支持图标 + 文字居中，右侧带下拉箭头。"""

    def __init__(
        self,
        text: str = "",
        icon: ElaIconType.IconName = ElaIconType.IconName.None_,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._text = text
        self._icon = icon
        self._border_radius = 6
        self._menu: Optional[ElaMenu] = None
        self._is_hover = False
        self._is_pressed = False

        self.setObjectName("ElaDropDownButton")
        self.setFixedHeight(_HEIGHT)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._icon_font = QFont("ElaAwesome")
        self._arrow_font = QFont("ElaAwesome")

    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def setElaIcon(self, icon: ElaIconType.IconName) -> None:
        self._icon = icon
        self.updateGeometry()
        self.update()

    def elaIcon(self) -> ElaIconType.IconName:
        return self._icon

    def setBorderRadius(self, r: int) -> None:
        self._border_radius = r
        self.update()

    def borderRadius(self) -> int:
        return self._border_radius

    def setMenu(self, menu: Optional[ElaMenu]) -> None:
        """设置下拉菜单；传 ``None`` 清空（此时点击不再弹菜单）。"""
        self._menu = menu

    def menu(self) -> Optional[ElaMenu]:
        return self._menu

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── 取色（透明底 + 状态层）────────────────────────────

    def _state_layer(self) -> QColor:
        """悬浮 / 按下状态层；基础态与禁用态**全透明**（不画底）。"""
        if not self.isEnabled():
            return QColor(_TRANSPARENT)
        if self._is_pressed:
            return state_tint(self._theme_mode, pressed=True)
        if self._is_hover:
            return state_tint(self._theme_mode)
        return QColor(_TRANSPARENT)

    def _content_color(self) -> QColor:
        """文字 / 图标色；禁用走 ``textDisabled``。"""
        if not self.isEnabled():
            return textDisabled(self._theme_mode)
        return text(self._theme_mode)

    # ── Events ────────────────────────────────────────────

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.EnabledChange:
            # 禁用期间收不到 hover / leave 事件，残留状态会让重新启用后误画一层
            self._is_hover = False
            self._is_pressed = False
            self.update()
        super().changeEvent(event)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.HoverEnter:
            self._is_hover = True
            self.update()
        elif event.type() == QEvent.Type.HoverLeave:
            self._is_hover = False
            self.update()
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_pressed = False
            self.update()
            # **必须判存活**：宿主动态重建菜单时会先删旧菜单，而 ``bool(已删除
            # 包装器)`` 仍是 True —— 不判存活就对死对象调 ``popup()`` 抛
            # RuntimeError，穿出 Qt 回调 = 0xC0000409 崩溃（实测）
            if (
                self._menu is not None
                and not is_deleted(self._menu)
                and self.rect().contains(event.position().toPoint())
            ):
                self._menu.popup(self.mapToGlobal(QPoint(0, self.height())))
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._is_hover = False
        self._is_pressed = False
        self.update()
        super().leaveEvent(event)

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 透明底：基础态不画底，只有悬浮 / 按下叠一层状态层（**无边框**）
        paintRoundedCard(
            painter,
            QRectF(self.rect()),
            background=self._state_layer(),
            radius=self._border_radius,
        )

        text_color = self._content_color()
        arrow_w = 20
        arrow_margin = 8
        content_left = 10
        content_right = self.width() - arrow_w

        icon_w = 0
        if self._icon != ElaIconType.IconName.None_:
            self._icon_font.setPixelSize(16)
            icon_w = QFontMetrics(self._icon_font).horizontalAdvance(
                iconGlyph(self._icon)
            )

        text_w = 0
        if self._text:
            text_font = self.font()
            text_w = QFontMetrics(text_font).horizontalAdvance(self._text)

        gap = 6 if (icon_w > 0 and text_w > 0) else 0
        total_w = icon_w + gap + text_w
        dx = content_left + (content_right - content_left - total_w) // 2

        # Icon
        if self._icon != ElaIconType.IconName.None_:
            self._icon_font.setPixelSize(16)
            painter.setFont(self._icon_font)
            painter.setPen(text_color)
            painter.drawText(
                QRect(dx, 0, icon_w, self.height()),
                Qt.AlignmentFlag.AlignCenter,
                iconGlyph(self._icon),
            )
            dx += icon_w + gap

        # Text
        if self._text:
            painter.setFont(self.font())
            painter.setPen(text_color)
            painter.drawText(
                QRect(dx, 0, text_w, self.height()),
                Qt.AlignmentFlag.AlignCenter,
                self._text,
            )

        self._arrow_font.setPixelSize(16)
        painter.setFont(self._arrow_font)
        painter.setPen(text_color)
        painter.drawText(
            QRect(self.width() - arrow_w - arrow_margin, 0, arrow_w, self.height()),
            Qt.AlignmentFlag.AlignCenter,
            chr(ElaIconType.IconName.AngleDown.value),
        )

    def sizeHint(self) -> QSize:
        icon_w = 0
        if self._icon != ElaIconType.IconName.None_:
            self._icon_font.setPixelSize(16)
            icon_w = QFontMetrics(self._icon_font).horizontalAdvance(
                iconGlyph(self._icon)
            )

        text_w = 0
        if self._text:
            text_font = QFont()
            text_font.setPixelSize(14)
            text_w = QFontMetrics(text_font).horizontalAdvance(self._text)

        gap = 6 if (icon_w > 0 and text_w > 0) else 0
        total = 10 + icon_w + gap + text_w + 20 + 8 + 10
        return QSize(int(total), _HEIGHT)
