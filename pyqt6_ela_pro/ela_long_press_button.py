"""
长按按钮组件。

按住按钮一段时间后才能触发点击事件的按钮组件，
带有进度条动画显示。继承自 ElaPushButton。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal, QTimer, QPointF, Qt, QRect, QRectF, QSize
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QLinearGradient,
    QPainterPath,
    QPaintEvent,
    QMouseEvent,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import (
    eTheme,
    ElaThemeType,
    ElaPushButton,
    ElaIcon,
    ElaIconType,
)

from ._internal import _ThemeAwareMixin
from ._styles import coerceElaIcon
from .ela_button import _FACE_INSET


class ElaLongPressButton(_ThemeAwareMixin, ElaPushButton):
    """长按按钮。

    按住按钮一段时间（默认 500ms）后才能触发点击事件的按钮。
    按压过程中会显示进度条填充动画。

    继承自 ElaPushButton，支持主题适配和图标。

    :param duration: 触发长按所需的时长（毫秒），默认 500ms
    :param text: 按钮文本
    :param icon: 图标名称
    :param iconSize: 图标大小，默认 16
    :param parent: 父控件

    Example::

        button = ElaLongPressButton(duration=800, text="长按保存", icon=ElaIconType.IconName.FloppyDisk, parent=parent)
        button.longPressed.connect(lambda: print("长按完成！"))
    """

    longPressed = pyqtSignal()
    progressChanged = pyqtSignal(float)

    def __init__(
        self,
        duration: int = 500,
        text: Optional[str] = None,
        icon: Optional[ElaIconType.IconName] = None,
        iconSize: int = 16,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setText(text if text is not None else "长按触发")

        self._duration = duration
        self._progress = 0.0
        self._triggered = False
        self._progress_color = QColor()
        self._custom_progress_color = False
        self._icon_name = None
        self._icon_size = iconSize

        if icon is not None:
            self.setElaIcon(icon, iconSize)

        self._mouse_pressed_timer = self._make_timer(self._onMousePressedTick)
        self._go_backwards_timer = self._make_timer(self._onGoBackwardsTick)
        self._backward_step = 0.0

        self._theme_mode = eTheme.getThemeMode()
        self._onThemeChanged(self._theme_mode)

    def _make_timer(self, callback) -> QTimer:
        timer = QTimer(self)
        timer.setInterval(16)
        timer.timeout.connect(callback)
        return timer

    def setDuration(self, ms: int) -> None:
        """长按触发所需的时长（毫秒），必须 > 0。"""
        if ms > 0:
            self._duration = ms

    def duration(self) -> int:
        return self._duration

    def setProgressColor(self, color: QColor) -> None:
        self._custom_progress_color = True
        self._progress_color = color
        self.update()

    def setElaIcon(self, icon, iconSize: int = 16) -> None:
        """设置 ElaAwesome 图标（``ElaIconType.IconName`` 或其整数值；``None`` 清除）。

        入口即归一：``getElaIcon`` 只接受枚举成员，非数值输入在 setter 期
        响亮失败（而不是在绘制期崩进程）。
        """
        self._icon_name = None if icon is None else coerceElaIcon(icon)
        self._icon_size = iconSize
        if self._icon_name is None:
            self.setIcon(QIcon())
        else:
            self.setIcon(
                ElaIcon.getInstance().getElaIcon(
                    self._icon_name, QColor(255, 255, 255)
                )
            )
        self.setIconSize(QSize(iconSize, iconSize))
        self.update()

    def _getCurrentBgColor(self) -> QColor:
        mode = self._theme_mode
        if not self.isEnabled():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicDisable)
        if self.isDown():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)
        if self.underMouse():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicHover)
        return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        if not self._custom_progress_color:
            self._progress_color = eTheme.getThemeColor(
                mode, ElaThemeType.ThemeColor.PrimaryNormal
            )
        self.update()

    def deleteLater(self) -> None:
        self._theme_cleanup()
        self._mouse_pressed_timer.stop()
        self._go_backwards_timer.stop()
        super().deleteLater()

    def progressColor(self) -> QColor:
        return self._progress_color

    def progress(self) -> float:
        """当前进度，范围 0.0 ~ 1.0。"""
        return self._progress

    def _stepLength(self) -> float:
        # 注意：这里**故意不接**全局动效策略（_motion.start_transition_timer）。
        #
        # 进度环不是装饰动效，是**功能契约**：`setDuration(ms)` 的语义就是
        # 「要按这么久才触发」，进度环是用户唯一的计时反馈。接到策略上会有两个后果：
        #   * Reduced 下 min(duration, 50) → 800ms 的长按变 50ms，一碰就触发；
        #   * Disabled 下直接落终值 → 长按按钮退化成单击按钮。
        # 两者都让控件行为不可预测，属于 bug 而不是无障碍。机器守卫见
        # tests/motion/test_motion_blacklist.py::test_essential_gesture_not_scaled。
        steps = self._duration / 16.0
        return 1.0 / steps if steps >= 1 else 1.0

    def _onMousePressedTick(self) -> None:
        new_progress = min(1.0, self._progress + self._stepLength())

        if new_progress >= 1.0:
            self._triggered = True
            self._mouse_pressed_timer.stop()
            self._go_backwards_timer.stop()
            self._progress = 0.0
            self.progressChanged.emit(1.0)
            self.longPressed.emit()
            self.update()
        else:
            self._progress = new_progress
            self.progressChanged.emit(self._progress)
            self.update()

    def _onGoBackwardsTick(self) -> None:
        self._progress = max(0.0, self._progress - self._backward_step)
        self.progressChanged.emit(self._progress)
        self.update()
        if self._progress <= 0:
            self._go_backwards_timer.stop()
            self._triggered = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.isEnabled():
            return
        super().mousePressEvent(event)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._mouse_pressed_timer.isActive()
        ):
            self._mouse_pressed_timer.start()
            self._go_backwards_timer.stop()
            self._triggered = False

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self._mouse_pressed_timer.stop()
        if not self._triggered and self._progress > 0:
            self._backward_step = self._stepLength() * 3
            self._go_backwards_timer.start()

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._progress <= 0:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        face_inset = _FACE_INSET
        rect = QRect(
            face_inset,
            face_inset,
            self.width() - 2 * face_inset,
            self.height() - 2 * face_inset,
        )

        bg_color = self._getCurrentBgColor()

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 3, 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawPath(path)

        border_color = eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicBaseLine
        )
        border_pen = QPen(border_color, 1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.save()
        painter.setClipPath(path)

        p = min(self._progress, 1.0)
        gradient = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.topRight()))
        gradient.setColorAt(0, self._progress_color)
        gradient.setColorAt(p, self._progress_color)
        gradient.setColorAt(min(p + 0.05, 1.0), QColor(0, 0, 0, 0))
        gradient.setColorAt(1, QColor(0, 0, 0, 0))
        painter.fillRect(rect, gradient)

        painter.restore()

        if self.isEnabled():
            text_color = eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.BasicText
            )
        else:
            text_color = eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.BasicTextDisable
            )
        painter.setPen(text_color)

        icon = self.icon()
        icon_size = self.iconSize()
        has_icon = not icon.isNull() and icon_size.width() > 0
        spacing = 8
        if has_icon:
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(self.text())
            total_width = icon_size.width() + spacing + text_width
            start_x = rect.x() + (rect.width() - total_width) // 2
            icon_y = rect.y() + (rect.height() - icon_size.height()) // 2
            icon_rect = QRect(start_x, icon_y, icon_size.width(), icon_size.height())
            text_rect = QRect(
                icon_rect.right() + spacing, rect.y(), text_width, rect.height()
            )
            painter.drawPixmap(icon_rect, icon.pixmap(icon_size))
        else:
            text_rect = rect
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())
