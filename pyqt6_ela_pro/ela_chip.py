"""
标签纸片组件，风格参考 Ant Design Tag / Material Chip。

支持 16 种颜色主题（同 ElaButton 色系），可关闭、可选择、可点击。

视觉规范：

- 彩色 chip = **不透明** ``accentBg`` 底 + 1px accent 描边 + ``accentText`` 彩字
  （对比度 ≥ 4.5，见 :func:`pyqt6_ela_pro._colors.accent_text`）—— 不再用
  「accent 半透明叠色 + 原始 accent 彩字」那种字底不同档、跨表面漂移的画法；
- 选中态 = 实心 accent 底 + ``solidText`` 字（Material filter chip 语义）；
- hover / press = 状态层叠加，hover 有 150ms 淡入淡出（随全局动效策略）；
- ``setPill(True)`` 全圆角；``setLeadingIcon()`` 前置图标；关闭按钮命中区 20px
  并有 hover 反馈 + 120ms 淡出。

用法::

    from pyqt6_ela_pro import ElaChip

    chip = ElaChip("标签", parent=self)
    chip.setClosable(True)
    chip.closed.connect(lambda: print("关闭"))
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from ._internal import is_deleted
from PyQt6.QtCore import Qt, QRectF, QSize, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import eTheme, ElaIconType, ElaThemeType

from ._colors import accent_text, get_color_scheme
from ._motion import Duration, start_transition
from ._styles import drawElaIcon
from ._theme import blend
from .widget_base import ElaThemeWidget


class ElaChip(ElaThemeWidget):
    """标签纸片组件。

    支持 16 种颜色主题（同 ElaButton 色系），可关闭、可选择、可点击。
    """

    class ElaChipColorType(IntEnum):
        Default = 0
        Primary = 1
        Danger = 2
        Blue = 3
        Purple = 4
        Cyan = 5
        Green = 6
        Magenta = 7
        Pink = 8
        Red = 9
        Orange = 10
        Yellow = 11
        Volcano = 12
        Geekblue = 13
        Lime = 14
        Gold = 15

    closed = pyqtSignal()
    clicked = pyqtSignal()
    checkedChanged = pyqtSignal(bool)

    #: 关闭按钮命中区宽度（px）。原 16px 太难点，且没有 hover 反馈。
    _CLOSE_WIDTH = 20
    #: 前置图标槽宽度（px）
    _ICON_WIDTH = 14
    #: hover 状态层透明度（≈8%）
    _HOVER_ALPHA = 20
    #: press 状态层透明度（≈12%）
    _PRESS_ALPHA = 31

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._text = text
        self._border_radius = 6
        self._is_pill = False
        self._is_closable = False
        self._is_checkable = False
        self._is_checked = False
        self._chip_color = self.ElaChipColorType.Default
        self._close_btn_width = self._CLOSE_WIDTH
        self._check_icon_width = 16
        self._padding = 8
        self._icon_font = QFont("ElaAwesome")
        self._leading_icon: Optional[ElaIconType.IconName] = None

        self._hovered = False
        self._pressed = False
        self._close_hovered = False
        self._hover_t = 0.0
        self._fade_opacity = 1.0
        self._fg_cache: tuple = ()

        self.setObjectName("ElaChip")
        self.setMouseTracking(True)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.valueChanged.connect(self._onHoverValue)
        self._close_anim: Optional[QVariantAnimation] = None

    # ── Public API ────────────────────────────────────────

    def setText(self, text: str) -> None:
        self._text = text
        self._updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def setBorderRadius(self, radius: int) -> None:
        """``setPill(True)`` 时忽略，按高度取全圆角。"""
        self._border_radius = radius
        self.update()

    def borderRadius(self) -> int:
        return self._border_radius

    def setPill(self, pill: bool = True) -> None:  # noqa: N802 (Qt 命名)
        self._is_pill = pill
        self.update()

    def isPill(self) -> bool:  # noqa: N802 (Qt 命名)
        return self._is_pill

    def setLeadingIcon(self, icon: Optional[ElaIconType.IconName]) -> None:  # noqa: N802
        """选中态下由勾选标记接管该槽位。"""
        self._leading_icon = icon
        self._updateGeometry()
        self.update()

    def leadingIcon(self) -> Optional[ElaIconType.IconName]:  # noqa: N802
        return self._leading_icon

    def setClosable(self, closable: bool) -> None:
        self._is_closable = closable
        self._updateGeometry()
        self.update()

    def isClosable(self) -> bool:
        return self._is_closable

    def setCheckable(self, checkable: bool) -> None:
        self._is_checkable = checkable
        self._updateGeometry()
        self.update()

    def isCheckable(self) -> bool:
        return self._is_checkable

    def setChecked(self, checked: bool) -> None:
        """仅在 :meth:`isCheckable` 为真时生效。"""
        self._is_checked = checked
        self._updateGeometry()
        self.update()

    def isChecked(self) -> bool:
        return self._is_checked

    def setColor(self, color: int) -> None:
        self._chip_color = color
        self.update()

    def color(self) -> int:
        return self._chip_color

    # ── ElaChipColorType name mapping ────────────────────────────────

    _COLOR_NAMES = {
        ElaChipColorType.Default: "default",
        ElaChipColorType.Primary: "primary",
        ElaChipColorType.Danger: "danger",
        ElaChipColorType.Blue: "blue",
        ElaChipColorType.Purple: "purple",
        ElaChipColorType.Cyan: "cyan",
        ElaChipColorType.Green: "green",
        ElaChipColorType.Magenta: "magenta",
        ElaChipColorType.Pink: "pink",
        ElaChipColorType.Red: "red",
        ElaChipColorType.Orange: "orange",
        ElaChipColorType.Yellow: "yellow",
        ElaChipColorType.Volcano: "volcano",
        ElaChipColorType.Geekblue: "geekblue",
        ElaChipColorType.Lime: "lime",
        ElaChipColorType.Gold: "gold",
    }

    # ── Internal ──────────────────────────────────────────

    def _is_colored(self) -> bool:
        return self._chip_color != self.ElaChipColorType.Default

    def _scheme(self) -> dict:
        return get_color_scheme(
            self._COLOR_NAMES.get(self._chip_color, "default"), self._theme_mode
        )

    def _state_layer(self) -> QColor:
        """状态层颜色：暗色叠白、亮色叠黑（Fluent 语义）。"""
        if self._theme_mode == ElaThemeType.ThemeMode.Dark:
            return QColor(255, 255, 255)
        return QColor(0, 0, 0)

    def _tint_alpha(self, hovered: bool, pressed: bool) -> int:
        """彩色 chip 半透明底的 accent 透明度（保持原来的「浅色药丸」观感）。"""
        dark = self._theme_mode == ElaThemeType.ThemeMode.Dark
        if pressed:
            return 115 if dark else 65
        if hovered:
            return 85 if dark else 45
        return 55 if dark else 25

    def _surface_color(self) -> QColor:
        """chip 所在的主题表面（文字对比度按「半透明底合成到它上面」计算）。"""
        return eTheme.getThemeColor(self._theme_mode, ElaThemeType.ThemeColor.BasicBase)

    def _getBackgroundColor(self) -> QColor:
        """空闲态底色（彩色为 accent 半透明 tint，随所在表面透出）。"""
        mode = self._theme_mode
        if not self._is_colored():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase)
        tint = QColor(self._scheme()["accent"])
        tint.setAlpha(self._tint_alpha(False, False))
        return tint

    def _getForegroundColor(self) -> QColor:
        """彩字：按「半透明底合成到主题表面」后的实际颜色取可读档（≥4.5）。"""
        mode = self._theme_mode
        if not self._is_colored():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
        key = (self._chip_color, mode)
        if self._fg_cache and self._fg_cache[0] == key:
            return QColor(self._fg_cache[1])
        # 按**最强档 tint（press）**合成后的底色取色：hover / 空闲的对比度只会更高
        tint = QColor(self._scheme()["accent"])
        tint.setAlpha(self._tint_alpha(True, True))
        composited = blend(
            self._surface_color(),
            QColor(tint.red(), tint.green(), tint.blue()),
            tint.alphaF(),
        )
        color = accent_text(
            self._COLOR_NAMES.get(self._chip_color, "default"), mode, composited
        )
        self._fg_cache = (key, color)
        return QColor(color)

    def _resolve_colors(self, hovered: bool, pressed: bool) -> tuple:
        """按状态解析 ``(底, 描边, 文字)``。"""
        mode = self._theme_mode
        if not self._is_colored():
            base = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase)
            border = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBorder)
            text = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
            alpha = self._PRESS_ALPHA if pressed else self._HOVER_ALPHA
            if hovered or pressed:
                base = blend(base, self._state_layer(), alpha / 255.0)
            return base, border, text

        scheme = self._scheme()
        if self._is_checkable and self._is_checked:
            bg = scheme["solid"]
            if pressed:
                bg = scheme["solidActive"]
            elif hovered:
                bg = scheme["solidHover"]
            return bg, QColor(bg), scheme["solidText"]

        accent = QColor(scheme["accent"])
        bg = QColor(accent)
        bg.setAlpha(self._tint_alpha(hovered, pressed))
        border = QColor(accent)
        if hovered or pressed:
            border.setAlpha(150)
        else:
            border.setAlpha(115 if mode == ElaThemeType.ThemeMode.Dark else 77)
        return bg, border, self._getForegroundColor()

    def _close_rect(self) -> QRectF:
        return QRectF(
            self.width() - self._close_btn_width - self._padding // 2,
            0,
            self._close_btn_width,
            self.height(),
        )

    def _updateGeometry(self) -> None:
        self.updateGeometry()
        self.adjustSize()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── Motion ────────────────────────────────────────────

    def _onHoverValue(self, value) -> None:  # noqa: ANN001
        self._hover_t = float(value)
        self.update()

    def _fade_hover(self, target: float) -> None:
        anim = self._hover_anim
        anim.stop()
        anim.setStartValue(self._hover_t)
        anim.setEndValue(float(target))
        start_transition(anim, Duration.Fast)

    def _onCloseValue(self, value) -> None:  # noqa: ANN001
        self._fade_opacity = float(value)
        self.update()

    def _finish_close(self) -> None:
        if is_deleted(self):
            return
        self._fade_opacity = 1.0
        self.closed.emit()
        self.hide()
        self.update()

    def _animate_close(self) -> None:
        """关闭前 150ms 淡出；策略关闭动效时同步收尾。"""
        if self._close_anim is None:
            self._close_anim = QVariantAnimation(self)
            self._close_anim.valueChanged.connect(self._onCloseValue)
        anim = self._close_anim
        anim.stop()
        anim.setStartValue(self._fade_opacity)
        anim.setEndValue(0.0)
        start_transition(anim, Duration.Fast, on_complete=self._finish_close)

    # ── Events ────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._fade_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._close_hovered = False
        self.unsetCursor()
        self._fade_hover(0.0)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_closable:
            over = self._close_rect().contains(event.position().toPoint())
            if over != self._close_hovered:
                self._close_hovered = over
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor
                    if over
                    else Qt.CursorShape.ArrowCursor
                )
                self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_closable and self._close_rect().contains(event.position().toPoint()):
                self._animate_close()
                event.accept()
                return
            self._pressed = True
            if self._is_checkable:
                self._is_checked = not self._is_checked
                self._updateGeometry()
                self.checkedChanged.emit(self._is_checked)
            self.clicked.emit()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pressed:
            self._pressed = False
            self.update()
        super().mouseReleaseEvent(event)

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._fade_opacity)

        w = self.width()
        h = self.height()
        radius = h / 2.0 if self._is_pill else float(self._border_radius)

        bg0, border0, fg_color = self._resolve_colors(False, False)
        if self._pressed:
            bg_color, border_color = self._resolve_colors(True, True)[:2]
        elif self._hover_t > 0.0:
            bg1, border1, _ = self._resolve_colors(True, False)
            bg_color = blend(bg0, bg1, self._hover_t)
            border_color = blend(border0, border1, self._hover_t)
        else:
            bg_color, border_color = bg0, border0

        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), radius, radius)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(bg_color)
        painter.drawPath(path)

        x_offset = self._padding

        # 勾选标记 / 前置图标（共用一个槽位）
        if self._is_checkable and self._is_checked:
            self._icon_font.setPixelSize(12)
            painter.setFont(self._icon_font)
            painter.setPen(fg_color)
            painter.drawText(
                QRectF(x_offset, 0, self._check_icon_width, h),
                Qt.AlignmentFlag.AlignCenter,
                chr(0xEA6C),
            )
            x_offset += self._check_icon_width
        elif self._leading_icon is not None:
            drawElaIcon(
                painter,
                QRectF(x_offset, 0, self._ICON_WIDTH, h),
                self._leading_icon,
                fg_color,
            )
            x_offset += self._ICON_WIDTH + 6

        painter.setFont(self.font())
        painter.setPen(fg_color)
        text_width = w - x_offset - self._padding
        if self._is_closable:
            text_width -= self._close_btn_width
        painter.drawText(
            QRectF(x_offset, 0, text_width, h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._text,
        )

        if self._is_closable:
            close_rect = self._close_rect()
            if self._close_hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(
                    blend(bg_color, self._state_layer(), self._PRESS_ALPHA / 255.0)
                )
                painter.drawEllipse(close_rect.center(), 9.0, 9.0)
            self._icon_font.setPixelSize(10)
            painter.setFont(self._icon_font)
            painter.setPen(fg_color)
            painter.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, chr(0xF4CE))

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self._text) + self._padding * 2
        if self._is_closable:
            w += self._close_btn_width
        if self._is_checkable and self._is_checked:
            w += self._check_icon_width
        elif self._leading_icon is not None:
            w += self._ICON_WIDTH + 6
        return QSize(max(w, 32), 28)
