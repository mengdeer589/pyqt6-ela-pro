"""
ElaDrawer SiliconUI 风格侧边抽屉组件。

支持上下左右四个方向滑出的抽屉面板，带遮罩层和动画效果。
参考 SiliconUI 的 SiLayerDrawer 设计。
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Optional

from PyQt6.QtCore import Qt, QPropertyAnimation, pyqtSignal, QRect, QEvent
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QMouseEvent
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGraphicsDropShadowEffect

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._colors import parse_color
from ._motion import Duration, Easing, start_transition
from ._ownership import ContentSlot, ElaWidgetOwnershipType
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

    def setBgColor(self, color: QColor) -> None:
        self._bg_color = parse_color(color)
        self.update()

    def setPosition(self, position: ElaDrawerPositionType) -> None:
        self._position = position
        self.update()

    def setCornerRadius(self, radius: int) -> None:
        self._corner_radius = int(radius)
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        path = QPainterPath()
        r = self._corner_radius
        w, h = self.width(), self.height()

        if self._position == ElaDrawerPositionType.Left:
            path.moveTo(w, r)
            path.quadTo(w, 0, w - r, 0)
            path.lineTo(0, 0)
            path.lineTo(0, h)
            path.lineTo(w - r, h)
            path.quadTo(w, h, w, h - r)
        elif self._position == ElaDrawerPositionType.Right:
            path.moveTo(0, r)
            path.quadTo(0, 0, r, 0)
            path.lineTo(w, 0)
            path.lineTo(w, h)
            path.lineTo(r, h)
            path.quadTo(0, h, 0, h - r)
        elif self._position == ElaDrawerPositionType.Top:
            path.moveTo(r, h)
            path.quadTo(0, h, 0, h - r)
            path.lineTo(0, 0)
            path.lineTo(w, 0)
            path.lineTo(w, h - r)
            path.quadTo(w, h, w - r, h)
        else:  # Bottom
            path.moveTo(r, 0)
            path.quadTo(0, 0, 0, r)
            path.lineTo(0, h)
            path.lineTo(w, h)
            path.lineTo(w, r)
            path.quadTo(w, 0, w - r, 0)

        path.closeSubpath()
        painter.fillPath(path, self._bg_color)


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

        shadow = QGraphicsDropShadowEffect(self._drawer_widget)
        shadow.setColor(QColor(0, 0, 0, 60))
        if self._position == ElaDrawerPositionType.Left:
            shadow.setOffset(4, 0)
        elif self._position == ElaDrawerPositionType.Right:
            shadow.setOffset(-4, 0)
        elif self._position == ElaDrawerPositionType.Top:
            shadow.setOffset(0, 4)
        else:
            shadow.setOffset(0, -4)
        shadow.setBlurRadius(16)
        self._drawer_widget.setGraphicsEffect(shadow)

        self._main_layout = QVBoxLayout(self._drawer_widget)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
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
        bg_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.DialogBase)
        self._drawer_widget.setBgColor(bg_color)
        dim_color = QColor(0, 0, 0, 102)
        self._dim_widget.setBgColor(dim_color)

    def _getStartRect(self, parent: QWidget) -> QRect:
        if self._position == ElaDrawerPositionType.Left:
            return QRect(-self._drawer_size, 0, self._drawer_size, parent.height())
        elif self._position == ElaDrawerPositionType.Right:
            return QRect(parent.width(), 0, self._drawer_size, parent.height())
        elif self._position == ElaDrawerPositionType.Top:
            return QRect(0, -self._drawer_size, parent.width(), self._drawer_size)
        else:  # Bottom
            return QRect(0, parent.height(), parent.width(), self._drawer_size)

    def _getEndRect(self, parent: QWidget) -> QRect:
        if self._position == ElaDrawerPositionType.Left:
            return QRect(0, 0, self._drawer_size, parent.height())
        elif self._position == ElaDrawerPositionType.Right:
            return QRect(
                parent.width() - self._drawer_size,
                0,
                self._drawer_size,
                parent.height(),
            )
        elif self._position == ElaDrawerPositionType.Top:
            return QRect(0, 0, parent.width(), self._drawer_size)
        else:  # Bottom
            return QRect(
                0,
                parent.height() - self._drawer_size,
                parent.width(),
                self._drawer_size,
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

    def setAnimationDuration(self, duration: int) -> "ElaDrawer":
        self._animation_duration = duration
        self._show_anim.setDuration(duration)
        self._hide_anim.setDuration(duration)
        self._dim_anim.setDuration(duration)
        return self

    def isOpened(self) -> bool:
        return self._is_opened

    def _on_content_changed(self, widget) -> None:
        """内容被替换时把新内容挂进布局。

        ``ContentSlot`` 负责所有权与引用，这里只管布局 —— 两者分开才不会互相踩。

        **``widget is None``（内容被外部销毁）时什么都不做**：``destroyed`` 是在
        ``~QWidget`` **内部**发出的，此刻 ``QLayout`` 可能还没跑完它自己的清理
        （实测 Qt 会把项自动摘掉，count 1→0）。此时去 ``itemAt`` / ``removeWidget``
        就是重入布局改结构 = 0xC0000005。
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
            self._dim_widget.setWindowOpacity(0)
            self._dim_widget.show()
            self.show()

            self._show_anim.setStartValue(start_rect)
            self._show_anim.setEndValue(end_rect)
            start_transition(self._show_anim, self._animation_duration)

            self._dim_anim.setStartValue(0)
            self._dim_anim.setEndValue(1)
            start_transition(self._dim_anim, self._animation_duration)
        except Exception as e:
            # **异常必须回滚到「关闭态」**：此前只 ``print`` 后 return，
            # 而 ``_is_opened`` 保持 False —— 面板 / 遮罩已 show()，closeDrawer()
            # 首行守卫却直接返回，抽屉关不掉、isOpened() 还与视觉相反（实测）。
            # 残留的半截动画也要停掉，否则它可能继续把视觉推到打开态。
            self._show_anim.stop()
            self._dim_anim.stop()
            self._drawer_widget.hide()
            self._dim_widget.hide()
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
        # 关闭动画在跑。_is_opened 要等 _onHideFinished 才复位（那是唯一的复位点），
        # 所以这里必须另立一个标志，否则关闭动画期间再 toggle 一次会被
        # 「_is_opened 还是 True」带进 closeDrawer，抽屉就卡在打开态。
        #
        # **必须在 start_transition 之前置位**：Disabled 模式下收尾在
        # start_transition 内部同步跑完（_onHideFinished 会把 _is_closing 清回
        # False），之后才置位就再也清不掉了。
        self._is_closing = True
        start_transition(
            self._hide_anim, self._animation_duration, on_complete=self._onHideFinished
        )

        self._dim_anim.setStartValue(1)
        self._dim_anim.setEndValue(0)
        start_transition(self._dim_anim, self._animation_duration)

    def _onDimClicked(self) -> None:
        if self._close_on_dim_clicked:
            self.closeDrawer()

    def _onHideFinished(self) -> None:
        self._dim_widget.hide()
        self._drawer_widget.hide()
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
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._is_opened:
            self._dim_widget.resize(self.size())
            parent = self.parentWidget()
            if parent:
                end_rect = self._getEndRect(parent)
                self._drawer_widget.setGeometry(end_rect)
