"""
拆分按钮组件，风格参考 ElaWidgetTools 的 ElaSplitButton。

左侧为主要按钮区域（文字 + 可选图标），右侧为下拉箭头，
点击箭头弹出菜单。

用法::

    from pyqt6_ela_pro import ElaSplitButton
    from PyQt6ElaWidgetTools import ElaMenu

    btn = ElaSplitButton(text="保存", icon=ElaIconType.IconName.FloppyDisk, parent=self)
    btn.clicked.connect(lambda: print("保存"))

    menu = ElaMenu(btn)                       # Ela 风格菜单（别用裸 QMenu）
    menu.addElaIconAction(ElaIconType.IconName.FloppyDisk, "另存为")
    btn.setMenu(menu)
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRectF, QSize, pyqtSignal, QPoint, QEvent
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QFont,
    QFontMetrics,
    QPaintEvent,
    QMouseEvent,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaThemeType, ElaIconType, ElaMenu

from ._colors import state_tint
from ._styles import iconGlyph
from ._theme import blend, border, surface, text, textDisabled
from .widget_base import ElaThemeWidget

#: 全透明（基础态 / 禁用态不画底）
_TRANSPARENT = QColor(0, 0, 0, 0)

#: 控件高度：与按钮族一致（ElaPushButton V3.0 / ElaButton middle 都是 30）
_HEIGHT = 30


class ElaSplitButton(ElaThemeWidget):
    """拆分按钮：左侧为主操作区域（文字 + 可选图标），右侧为下拉箭头。

    点击左侧发出 ``clicked()``，点击右侧弹出菜单。
    """

    clicked = pyqtSignal()

    def __init__(
        self,
        text: str = "",
        icon: ElaIconType.IconName = ElaIconType.IconName.None_,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._text = text
        self._icon = icon
        self._border_radius = 3
        self._dropdown_width = 30
        self._menu: Optional[ElaMenu] = None
        self._is_left_hovered = False
        self._is_right_hovered = False
        self._is_left_pressed = False
        self._is_right_pressed = False

        self.setObjectName("ElaSplitButton")
        self.setFixedHeight(_HEIGHT)
        self.setMouseTracking(True)
        self._icon_font = QFont("ElaAwesome")
        self._arrow_font = QFont("ElaAwesome")

        font = self.font()
        font.setPixelSize(15)
        self.setFont(font)

    # ── Public API ────────────────────────────────────────

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

    def setBorderRadius(self, radius: int) -> None:
        self._border_radius = radius
        self.update()

    def borderRadius(self) -> int:
        return self._border_radius

    def setMenu(self, menu: ElaMenu) -> None:
        """点击右侧箭头时弹出。"""
        self._menu = menu

    def menu(self) -> Optional[ElaMenu]:
        return self._menu

    # ── Internal ──────────────────────────────────────────

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── 取色（透明底 + 状态层）────────────────────────────

    def _state_layer(self, *, pressed: bool, hovered: bool) -> QColor:
        """某半边的悬浮 / 按下状态层；基础态与禁用态**全透明**（不画底）。"""
        if not self.isEnabled():
            return QColor(_TRANSPARENT)
        if pressed:
            return state_tint(self._theme_mode, pressed=True)
        if hovered:
            return state_tint(self._theme_mode)
        return QColor(_TRANSPARENT)

    def _divider_color(self) -> QColor:
        """两半之间的 1px 分隔线（**不是**外框 —— 外框已去掉）；禁用时变淡。"""
        color = border(self._theme_mode)
        if not self.isEnabled():
            return blend(color, surface(self._theme_mode), 0.55)
        return color

    def _content_color(self) -> QColor:
        """文字 / 图标 / 箭头色；禁用走 ``textDisabled``。"""
        if not self.isEnabled():
            return textDisabled(self._theme_mode)
        return text(self._theme_mode)

    # ── Events ────────────────────────────────────────────

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.EnabledChange:
            # 禁用期间收不到 hover / leave 事件，残留状态会让重新启用后误画一层
            self._is_left_hovered = False
            self._is_right_hovered = False
            self._is_left_pressed = False
            self._is_right_pressed = False
            self.update()
        super().changeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            split_x = self.width() - self._dropdown_width
            if event.position().toPoint().x() < split_x:
                self._is_left_pressed = True
            else:
                self._is_right_pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            split_x = self.width() - self._dropdown_width
            if self._is_left_pressed and event.position().toPoint().x() < split_x:
                self.clicked.emit()
            elif self._is_right_pressed and event.position().toPoint().x() >= split_x:
                if self._menu:
                    pos = self.mapToGlobal(QPoint(0, self.height()))
                    self._menu.popup(pos)
            self._is_left_pressed = False
            self._is_right_pressed = False
            self.update()
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        split_x = self.width() - self._dropdown_width
        left_hovered = event.position().toPoint().x() < split_x
        right_hovered = not left_hovered
        if (
            self._is_left_hovered != left_hovered
            or self._is_right_hovered != right_hovered
        ):
            self._is_left_hovered = left_hovered
            self._is_right_hovered = right_hovered
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._is_left_hovered = False
        self._is_right_hovered = False
        self._is_left_pressed = False
        self._is_right_pressed = False
        self.update()
        super().leaveEvent(event)

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        br = self._border_radius
        split_x = w - self._dropdown_width

        left_rect = QRectF(0, 0, split_x, h)
        right_rect = QRectF(split_x, 0, self._dropdown_width, h)
        full_rect = QRectF(0, 0, w, h)

        text_color = self._content_color()

        # 透明底：基础态不画底，只有鼠标所在那半边叠一层状态层（圆角由 clip 保证）
        path = QPainterPath()
        path.addRoundedRect(full_rect, br, br)
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        left_layer = self._state_layer(
            pressed=self._is_left_pressed, hovered=self._is_left_hovered
        )
        right_layer = self._state_layer(
            pressed=self._is_right_pressed, hovered=self._is_right_hovered
        )
        if left_layer.alpha():
            painter.setBrush(left_layer)
            painter.drawRect(left_rect)
        if right_layer.alpha():
            painter.setBrush(right_layer)
            painter.drawRect(right_rect)
        painter.setClipping(False)

        # 无外框：只保留两半之间的分隔线
        painter.setPen(QPen(self._divider_color(), 1))
        painter.drawLine(split_x, 4, split_x, h - 4)

        painter.setPen(text_color)
        if self._icon != ElaIconType.IconName.None_:
            self._icon_font.setPixelSize(18)
            fm_icon = QFontMetrics(self._icon_font)
            icon_w = fm_icon.horizontalAdvance(iconGlyph(self._icon))

            text_font = self.font()
            text_fm = QFontMetrics(text_font)
            text_w = 0 if not self._text else text_fm.horizontalAdvance(self._text)

            spacing = 0 if not self._text else 8
            total_w = icon_w + spacing + text_w
            start_x = left_rect.x() + (left_rect.width() - total_w) // 2

            painter.setFont(self._icon_font)
            painter.drawText(
                QRectF(start_x, left_rect.y(), icon_w, left_rect.height()),
                Qt.AlignmentFlag.AlignCenter,
                iconGlyph(self._icon),
            )

            if self._text:
                painter.setFont(text_font)
                painter.drawText(
                    QRectF(
                        start_x + icon_w + spacing,
                        left_rect.y(),
                        text_w,
                        left_rect.height(),
                    ),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    self._text,
                )
        else:
            painter.setFont(self.font())
            painter.drawText(left_rect, Qt.AlignmentFlag.AlignCenter, self._text)

        self._arrow_font.setPixelSize(14)
        painter.setFont(self._arrow_font)
        painter.setPen(text_color)
        painter.drawText(
            right_rect,
            Qt.AlignmentFlag.AlignCenter,
            chr(ElaIconType.IconName.AngleDown.value),
        )

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        text_w = 0 if not self._text else fm.horizontalAdvance(self._text)
        icon_w = 24 if self._icon != ElaIconType.IconName.None_ else 0
        spacing = (
            0 if (not self._text or self._icon == ElaIconType.IconName.None_) else 8
        )
        left_w = icon_w + spacing + text_w + 20
        return QSize(left_w + self._dropdown_width, _HEIGHT)
