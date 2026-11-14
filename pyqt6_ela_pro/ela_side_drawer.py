"""
ElaDrawer SiliconUI 风格侧边抽屉组件。

支持上下左右四个方向滑出的抽屉面板，带遮罩层和动画效果；``setMaskEnabled(False)``
可切到无遮罩侧栏（不挡、不灰，抽屉外仍可操作）。参考 SiliconUI 的 SiLayerDrawer 设计。
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Optional

from PyQt6.QtCore import Qt, QPropertyAnimation, pyqtSignal, QRect, QRectF, QEvent
from PyQt6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QRegion,
)
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._colors import parse_color
from ._motion import Duration, Easing, start_transition
from ._ownership import ContentSlot, ElaWidgetOwnershipType
from ._styles import SHADOW_MARGIN, paintOverlayShadow
from .widget_base import ElaThemeWidget

logger = logging.getLogger(__name__)


class ElaDrawerPositionType(IntEnum):
    Left = 0
    Right = 1
    Top = 2
    Bottom = 3


class ElaDrawerPanel(QWidget):
    def __init__(
        self,
        corner_radius: int = 12,
        position: ElaDrawerPositionType = ElaDrawerPositionType.Right,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._corner_radius = corner_radius
        self._position = position
        self._bg_color = QColor(0, 0, 0, 0)
        self._shadow_margin = SHADOW_MARGIN

    def setBgColor(self, color: QColor) -> None:
        self._bg_color = parse_color(color)
        self.update()

    def setPosition(self, position: ElaDrawerPositionType) -> None:
        self._position = position
        self.update()

    def setCornerRadius(self, radius: int) -> None:
        self._corner_radius = int(radius)
        self.update()

    def _card_rect(self) -> QRectF:
        m = self._shadow_margin
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _shape_path(self) -> QPainterPath:
        rect = self._card_rect()
        left, top, right, bottom = (
            rect.left(),
            rect.top(),
            rect.right(),
            rect.bottom(),
        )
        r = self._corner_radius
        path = QPainterPath()

        if self._position == ElaDrawerPositionType.Left:
            path.moveTo(right, top + r)
            path.quadTo(right, top, right - r, top)
            path.lineTo(left, top)
            path.lineTo(left, bottom)
            path.lineTo(right - r, bottom)
            path.quadTo(right, bottom, right, bottom - r)
        elif self._position == ElaDrawerPositionType.Right:
            path.moveTo(left, top + r)
            path.quadTo(left, top, left + r, top)
            path.lineTo(right, top)
            path.lineTo(right, bottom)
            path.lineTo(left + r, bottom)
            path.quadTo(left, bottom, left, bottom - r)
        elif self._position == ElaDrawerPositionType.Top:
            path.moveTo(left + r, bottom)
            path.quadTo(left, bottom, left, bottom - r)
            path.lineTo(left, top)
            path.lineTo(right, top)
            path.lineTo(right, bottom - r)
            path.quadTo(right, bottom, right - r, bottom)
        else:  # Bottom
            path.moveTo(left + r, top)
            path.quadTo(left, top, left, top + r)
            path.lineTo(left, bottom)
            path.lineTo(right, bottom)
            path.lineTo(right, top + r)
            path.quadTo(right, top, right - r, top)

        path.closeSubpath()
        return path

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            paintOverlayShadow(
                painter,
                self.rect(),
                margin=self._shadow_margin,
                radius=self._corner_radius,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(self._shape_path(), self._bg_color)
        finally:
            painter.end()


class ElaDrawerDim(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self._bg_color = QColor(0, 0, 0, 102)

    def setBgColor(self, color: QColor) -> None:
        self._bg_color = color
        palette = self.palette()
        palette.setColor(self.backgroundRole(), color)
        self.setPalette(palette)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)


class ElaDrawer(ElaThemeWidget):
    """SiliconUI 风格侧边抽屉：四向滑入、半透明遮罩（点击可关）、平滑动画。"""

    closed = pyqtSignal()
    opened = pyqtSignal()

    def __init__(
        self,
        position: ElaDrawerPositionType = ElaDrawerPositionType.Right,
        drawer_size: int = 360,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._position = position
        self._drawer_size = drawer_size
        self._is_opened = False
        self._is_closing = False
        self._close_on_dim_clicked = True
        #: 是否显示遮罩层；False = 无遮罩侧栏（遮罩不挡、不灰，抽屉外仍可操作）
        self._mask_enabled = True
        self._animation_duration = Duration.Normal
        self._corner_radius = 12
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

        self._dim_widget = ElaDrawerDim(self)
        self._dim_widget.clicked.connect(self._onDimClicked)
        self._dim_widget.hide()

        self._drawer_widget = ElaDrawerPanel(
            corner_radius=self._corner_radius, position=self._position, parent=self
        )

        self._main_layout = QVBoxLayout(self._drawer_widget)
        # 面板四周预留阴影边距；内容槽与可见卡片重合。
        m = SHADOW_MARGIN
        self._main_layout.setContentsMargins(m, m, m, m)
        self._main_layout.setSpacing(0)

        self._content_slot = ContentSlot(self, "drawer-content")
        self._content_slot.widgetChanged.connect(self._on_content_changed)

        self._show_anim = QPropertyAnimation(self._drawer_widget, b"geometry")
        self._show_anim.setEasingCurve(Easing.type_name(Easing.Decelerate))

        self._hide_anim = QPropertyAnimation(self._drawer_widget, b"geometry")
        self._hide_anim.setEasingCurve(Easing.type_name(Easing.Accelerate))

        self._dim_anim = QPropertyAnimation(self._dim_widget, b"windowOpacity")

        if parent:
            parent.installEventFilter(self)

        self._onThemeChanged(self._theme_mode)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        # 表面跟内容基面（ElaThemeWidget 的 BasicPress）一致：QScrollArea.setWidget()
        # 会强制内容 autoFillBackground(True)，用 DialogBase 会在暗色下露出一块更亮的底。
        bg_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)
        self._drawer_widget.setBgColor(bg_color)
        dim_color = QColor(0, 0, 0, 102)
        self._dim_widget.setBgColor(dim_color)

    def _getStartRect(self, parent: QWidget) -> QRect:
        m = SHADOW_MARGIN
        size = self._drawer_size
        if self._position == ElaDrawerPositionType.Left:
            return QRect(-size - m, -m, size + 2 * m, parent.height() + 2 * m)
        elif self._position == ElaDrawerPositionType.Right:
            return QRect(parent.width(), -m, size + 2 * m, parent.height() + 2 * m)
        elif self._position == ElaDrawerPositionType.Top:
            return QRect(-m, -size - m, parent.width() + 2 * m, size + 2 * m)
        else:  # Bottom
            return QRect(-m, parent.height(), parent.width() + 2 * m, size + 2 * m)

    def _getEndRect(self, parent: QWidget) -> QRect:
        m = SHADOW_MARGIN
        size = self._drawer_size
        if self._position == ElaDrawerPositionType.Left:
            return QRect(-m, -m, size + 2 * m, parent.height() + 2 * m)
        elif self._position == ElaDrawerPositionType.Right:
            return QRect(
                parent.width() - size - m,
                -m,
                size + 2 * m,
                parent.height() + 2 * m,
            )
        elif self._position == ElaDrawerPositionType.Top:
            return QRect(-m, -m, parent.width() + 2 * m, size + 2 * m)
        else:  # Bottom
            return QRect(
                -m,
                parent.height() - size - m,
                parent.width() + 2 * m,
                size + 2 * m,
            )

    def contentWidget(self) -> Optional[QWidget]:
        """当前内容组件（已被外部销毁时返回 ``None``）。"""
        return self._content_slot.widget()

    def contentOwnership(self) -> ElaWidgetOwnershipType:
        """内容组件的所有权策略，默认 ``Borrowed``。"""
        return self._content_slot.ownership()

    def setContentWidget(
        self, widget: QWidget, ownership=ElaWidgetOwnershipType.Borrowed
    ) -> "ElaDrawer":
        current = self._content_slot.widget()
        if current is not None:
            self._main_layout.removeWidget(current)
        if not self._content_slot.setWidget(widget, ownership):
            return self
        hosted = self._content_slot.widget()
        if hosted is not None:
            self._main_layout.addWidget(hosted)
        return self

    def takeContentWidget(self) -> Optional[QWidget]:
        """取回内容组件：从布局摘下、**无父**返回、**从不删除**。"""
        current = self._content_slot.widget()
        if current is not None:
            self._main_layout.removeWidget(current)
        return self._content_slot.takeWidget()

    def setDrawerSize(self, size: int) -> "ElaDrawer":
        self._drawer_size = size
        return self

    def setCornerRadius(self, radius: int) -> "ElaDrawer":
        self._corner_radius = int(radius)
        # 必须下发给真正绘制圆角的子面板：paintEvent 读的是
        # ``_drawer_widget._corner_radius``，只改抽屉自身的字段没有任何效果。
        panel = getattr(self, "_drawer_widget", None)
        if panel is not None:
            panel.setCornerRadius(self._corner_radius)
        return self

    def setCloseOnDimClicked(self, on: bool) -> "ElaDrawer":
        self._close_on_dim_clicked = on
        return self

    def setMaskEnabled(self, on: bool = True) -> "ElaDrawer":
        """设置是否使用遮罩层（默认 ``True``）。

        ``False`` = 无遮罩侧栏：不显示 dim、不拦截抽屉外的鼠标事件；抽屉仍然
        从侧边滑入，只是不再把整页压暗。运行中切换立即生效。
        """
        self._mask_enabled = bool(on)
        if self._mask_enabled:
            self.clearMask()
            if self._is_opened and not self._is_closing:
                self._dim_widget.setWindowOpacity(1.0)
                self._dim_widget.show()
        else:
            self._dim_anim.stop()
            self._dim_widget.hide()
            if self._is_opened and not self._is_closing:
                self._apply_mask()
        return self

    def maskEnabled(self) -> bool:
        """是否使用遮罩层。"""
        return self._mask_enabled

    def _apply_mask(self) -> None:
        """无遮罩模式下只保留抽屉一侧的命中区域，外部点击穿透。"""
        if self._mask_enabled:
            return
        margin = SHADOW_MARGIN
        width = min(self.width(), self._drawer_size + margin)
        height = min(self.height(), self._drawer_size + margin)
        if self._position == ElaDrawerPositionType.Left:
            rect = QRect(0, 0, width, self.height())
        elif self._position == ElaDrawerPositionType.Right:
            rect = QRect(self.width() - width, 0, width, self.height())
        elif self._position == ElaDrawerPositionType.Top:
            rect = QRect(0, 0, self.width(), height)
        else:
            rect = QRect(0, self.height() - height, self.width(), height)
        self.setMask(QRegion(rect))

    def setAnimationDuration(self, duration: int) -> "ElaDrawer":
        self._animation_duration = duration
        self._show_anim.setDuration(duration)
        self._hide_anim.setDuration(duration)
        self._dim_anim.setDuration(duration)
        return self

    def isOpened(self) -> bool:
        return self._is_opened

    def _on_content_changed(self, widget) -> None:
        """内容被替换时把新内容挂进布局（``ContentSlot`` 管所有权，这里只管布局）。
        **``widget is None``（内容被外部销毁）时什么都不做**：``destroyed`` 在
        ``~QWidget`` 内部发出，此刻 ``QLayout`` 可能还没清理完，动它 = 0xC0000005。
        """
        if widget is None:
            return
        if self._main_layout.indexOf(widget) < 0:
            self._main_layout.addWidget(widget)

    def showDrawer(self) -> None:
        """打开抽屉（带动画）。"""
        if self._is_opened:
            return

        if not self._content_slot.widget():
            return

        win = self.window() if self.parentWidget() else None
        if not win:
            return
        if self.parentWidget() is not win:
            self.setParent(win)
            win.installEventFilter(self)
        try:
            self.resize(win.size())
            self._dim_widget.resize(self.size())

            start_rect = self._getStartRect(win)
            end_rect = self._getEndRect(win)

            self._drawer_widget.setGeometry(start_rect)
            self._drawer_widget.show()
            self._drawer_widget.raise_()
            if self._mask_enabled:
                self._dim_widget.setWindowOpacity(0)
                self._dim_widget.show()
            else:
                self._dim_widget.hide()
            self.show()
            if not self._mask_enabled:
                self._apply_mask()

            self._show_anim.setStartValue(start_rect)
            self._show_anim.setEndValue(end_rect)
            start_transition(self._show_anim, self._animation_duration)

            if self._mask_enabled:
                self._dim_anim.setStartValue(0)
                self._dim_anim.setEndValue(1)
                start_transition(self._dim_anim, self._animation_duration)
        except Exception as e:
            # **异常必须回滚到「关闭态」**：只 print 后 return 会让面板 / 遮罩
            # 已 show() 但 ``_is_opened`` 仍为 False，closeDrawer() 首行直接返回，
            # 抽屉关不掉。残留动画也要停，否则会把视觉继续推向打开态。
            self._show_anim.stop()
            self._dim_anim.stop()
            self._drawer_widget.hide()
            self._dim_widget.hide()
            self.clearMask()
            self.hide()
            logger.warning("showDrawer 失败，已回滚到关闭态: %s", e)
            return

        self._is_closing = False
        self._is_opened = True
        self.opened.emit()

    def closeDrawer(self) -> None:
        """关闭抽屉（带动画）。"""
        if not self._is_opened or self._is_closing:
            return

        win = self.window() if self.parentWidget() else None
        if not win:
            return

        current_rect = self._drawer_widget.geometry()
        end_rect = self._getStartRect(win)

        self._hide_anim.setStartValue(current_rect)
        self._hide_anim.setEndValue(end_rect)
        # 关闭动画在跑，_is_opened 要等 _onHideFinished 才复位（唯一复位点），
        # 故另立 _is_closing；否则动画期间再 toggle 会被旧 _is_opened 带进 closeDrawer。
        # **必须在 start_transition 前置位**：Disabled 下收尾同步跑完，再置位就清不掉。
        self._is_closing = True
        start_transition(
            self._hide_anim, self._animation_duration, on_complete=self._onHideFinished
        )

        if self._mask_enabled:
            self._dim_anim.setStartValue(1)
            self._dim_anim.setEndValue(0)
            start_transition(self._dim_anim, self._animation_duration)
        else:
            self._dim_anim.stop()
            self._dim_widget.hide()

    def _onDimClicked(self) -> None:
        if self._close_on_dim_clicked:
            self.closeDrawer()

    def _onHideFinished(self) -> None:
        self._dim_widget.hide()
        self._drawer_widget.hide()
        self.clearMask()
        self.hide()
        self._is_closing = False
        self._is_opened = False
        self.closed.emit()

    def toggleDrawer(self) -> None:
        """切换抽屉开关状态。关闭动画进行中忽略（否则会卡在打开态）。"""
        if self._is_closing:
            return
        if self._is_opened:
            self.closeDrawer()
        else:
            self.showDrawer()

    def eventFilter(self, watched, event) -> bool:
        if watched == self.parentWidget() and self._is_opened:
            if event.type() == QEvent.Type.Resize:
                self.resize(event.size())
                self._dim_widget.resize(self.size())
                parent = watched
                end_rect = self._getEndRect(parent)
                self._drawer_widget.setGeometry(end_rect)
                self._apply_mask()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._is_opened:
            self._dim_widget.resize(self.size())
            parent = self.parentWidget()
            if parent:
                end_rect = self._getEndRect(parent)
                self._drawer_widget.setGeometry(end_rect)
            self._apply_mask()
