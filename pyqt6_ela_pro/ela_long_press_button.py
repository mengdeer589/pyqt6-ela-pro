"""
长按按钮组件。

按住按钮一段时间后才发 ``longPressed`` 的按钮，按住期间在按钮面上叠加
进度填充；提前松开时进度回流。继承 :class:`~pyqt6_ela_pro.ela_button.ElaButton`，
因此尺寸 / 变体 / 颜色与 ``ElaButton`` 完全一致。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaIconType

from ._colors import parse_color
from .ela_button import (
    ElaButton,
    ElaButtonColor,
    ElaButtonSize,
    ElaButtonVariant,
    paintProgressFill,
)


class ElaLongPressButton(ElaButton):
    """长按按钮。

    按住一段时间（默认 500ms）才发 :attr:`longPressed`，期间按钮面上有进度
    填充；提前松开时进度回流清零。**短按不会发** ``longPressed``（Qt 仍会
    照常发 ``clicked``，宿主应只连前者）。

    按住期间按钮被禁用 / 隐藏 / 失焦会主动中断，不会补发 ``longPressed``。

    :param text: 按钮文本
    :param icon: ElaAwesome 图标（``ElaIconType.IconName`` 或其整数值）
    :param iconSize: 图标大小，默认 16
    :param variant: 变体，取值见 :data:`ElaButtonVariant`
    :param color: 色彩，取值见 :data:`ElaButtonColor`
    :param danger: 危险色（等价 ``color="danger"``）
    :param size: 尺寸档位 ``small`` / ``middle`` / ``large``（22 / 30 / 38）
    :param duration: 触发长按所需的时长（毫秒），默认 500ms
    :param parent: 父控件

    Example::

        button = ElaLongPressButton(
            "长按卸载", variant="outlined", size="small", duration=800, parent=parent
        )
        button.longPressed.connect(lambda: print("长按完成！"))
    """

    longPressed = pyqtSignal()
    progressChanged = pyqtSignal(float)

    #: 可以「按住」的键（键盘可达性）。autoRepeat 的重复按键不算重新开始。
    _HOLD_KEYS = frozenset({Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter})

    # 类级默认值：主题信号可能在本类 ``__init__`` 走到属性赋值之前回调
    _custom_progress_color: bool = False
    _progress_color: QColor = QColor()

    def __init__(
        self,
        text: Optional[str] = None,
        icon: Optional[ElaIconType.IconName] = None,
        iconSize: int = 16,
        variant: ElaButtonVariant = "outlined",
        color: ElaButtonColor = "default",
        danger: bool = False,
        size: ElaButtonSize = "middle",
        duration: int = 500,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            text=text,
            icon=icon,
            iconSize=iconSize,
            variant=variant,
            color=color,
            danger=danger,
            size=size,
            parent=parent,
        )
        if not self.text():
            self.setText("长按触发")

        self._duration = duration
        self._progress = 0.0
        self._triggered = False
        self._backward_step = 0.0

        self._mouse_pressed_timer = self._make_timer(self._onMousePressedTick)
        self._go_backwards_timer = self._make_timer(self._onGoBackwardsTick)

    def _make_timer(self, callback) -> QTimer:
        timer = QTimer(self)
        timer.setInterval(16)
        timer.timeout.connect(callback)
        return timer

    # ── Public API ────────────────────────────────────────

    def setDuration(self, ms: int) -> None:
        """长按触发所需的时长（毫秒），必须 > 0。"""
        if ms > 0:
            self._duration = ms

    def duration(self) -> int:
        return self._duration

    def setProgressColor(self, color) -> None:
        """自定义进度填充色（支持 ``QColor`` 与 ``#rrggbb`` / ``rgba(...)``）。"""
        self._custom_progress_color = True
        self._progress_color = parse_color(color)
        self.update()

    def progressColor(self) -> QColor:
        """当前**生效**的填充色（未自定义时是主题主色，不是 ``PrimaryNormal``）。"""
        if self._custom_progress_color:
            return QColor(self._progress_color)
        return self._progress_fill_color()

    def progress(self) -> float:
        """当前进度，范围 0.0 ~ 1.0。"""
        return self._progress

    def isHolding(self) -> bool:  # noqa: N802
        """是否正在按住计时（按住期间为 ``True``）。"""
        return self._mouse_pressed_timer.isActive()

    # ── 计时 ──────────────────────────────────────────────

    def _stepLength(self) -> float:
        # 注意：这里**故意不接**全局动效策略（_motion.start_transition_timer）。
        #
        # 进度环不是装饰动效，是**功能契约**：`setDuration(ms)` 的语义就是
        # 「要按这么久才触发」，进度环是用户唯一的计时反馈。接到策略上会有两个后果：
        #   * Reduced 下 min(duration, 50) → 800ms 的长按变 50ms，一碰就触发；
        #   * Disabled 下直接落终值 → 长按按钮退化成单击按钮。
        # 两者都让控件行为不可预测，属于 bug 而不是无障碍。机器守卫见
        # tests/motion/test_motion_policy.py::test_essential_gesture_not_scaled。
        steps = self._duration / 16.0
        return 1.0 / steps if steps >= 1 else 1.0

    def _start_hold(self) -> None:
        if not self.isEnabled() or self.isLoading():
            return
        self._go_backwards_timer.stop()
        self._triggered = False
        if not self._mouse_pressed_timer.isActive():
            self._mouse_pressed_timer.start()

    def _end_hold(self) -> None:
        self._mouse_pressed_timer.stop()
        if not self._triggered and self._progress > 0:
            self._backward_step = self._stepLength() * 3
            self._go_backwards_timer.start()

    def _cancel_hold(self) -> None:
        """中断长按并清空进度（禁用 / 隐藏 / 失焦时调用，不发 ``longPressed``）。"""
        timer = getattr(self, "_mouse_pressed_timer", None)
        if timer is None:  # 构造期的事件（早于定时器创建）
            return
        timer.stop()
        self._go_backwards_timer.stop()
        self._triggered = False
        if self._progress > 0:
            self._progress = 0.0
            self.progressChanged.emit(0.0)
            self.update()

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

    # ── 事件 ──────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.isEnabled():
            return
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_hold()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self._end_hold()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in self._HOLD_KEYS and not event.isAutoRepeat():
            self._start_hold()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() in self._HOLD_KEYS and not event.isAutoRepeat():
            self._end_hold()
        super().keyReleaseEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self._cancel_hold()

    def hideEvent(self, event) -> None:
        self._cancel_hold()
        super().hideEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._cancel_hold()

    def deleteLater(self) -> None:
        self._mouse_pressed_timer.stop()
        self._go_backwards_timer.stop()
        super().deleteLater()

    # ── 绘制 / 主题 ───────────────────────────────────────

    def _paint_face_overlay(self, painter: QPainter, path: QPainterPath) -> None:
        color = (
            self._progress_color
            if self._custom_progress_color
            else self._progress_fill_color()
        )
        paintProgressFill(painter, path, self._progress, color)
