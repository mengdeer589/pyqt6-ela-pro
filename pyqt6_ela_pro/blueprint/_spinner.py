"""
内置精简旋转圈指示器（SpinnerArc）。

源引擎的节点运行状态依赖 ``anim.painted.SpinnerArc``（52 动画预设包中的
一个组件）。此处内置等价的精简实现（QTimer 驱动圆弧旋转、主题主色），
避免为单个组件引入整个动画包；行为对齐源实现：``start()`` / ``stop()`` /
``isRunning()``。

移植自 InstructionX_UIKit.anim.painted.SpinnerArc（原库为 PyQt6，
主题令牌经 blueprint._tokens 适配 eTheme；原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .._motion import start_idle_loop
from ._tokens import T, theme_changed_slot

__all__ = ["SpinnerArc"]


class SpinnerArc(QWidget):
    """旋转圈加载指示器（``QTimer`` 驱动圆弧旋转，线宽默认 ``size // 8``）。"""

    def __init__(self, size=32, line_width=None, speed=10.0, interval=16, parent=None):
        super().__init__(parent)
        self._size = int(size)
        self._lw = int(line_width) if line_width else max(2, self._size // 8)
        self._speed = float(speed)
        self._angle = 0.0
        self.setFixedSize(self._size, self._size)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        theme_changed_slot(self, self.update)
        self._interval = max(5, int(interval))
        # 持续动效：Reduced/Disabled 下不转。停掉时角度冻结在当前值 —— 那就是
        # 静态基态（仍是一段可见的弧，不是空白），所以不需要额外的摆姿态钩子。
        self.start()

    def start(self) -> None:
        """启动旋转（受全局动效策略约束；Reduced/Disabled 下不转）。"""
        start_idle_loop(self._timer, self._interval)

    def stop(self) -> None:
        """停止旋转。"""
        self._timer.stop()

    def isRunning(self) -> bool:
        return self._timer.isActive()

    def _advance(self) -> None:
        self._angle = (self._angle + self._speed) % 360.0
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self._lw / 2.0 + 1.0
        rect = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        pen = QPen(QColor(T("color.border")))
        pen.setWidthF(float(self._lw))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, 360 * 16)
        pen.setColor(QColor(T("color.primary")))
        p.setPen(pen)
        p.drawArc(rect, int(-self._angle * 16), 110 * 16)
        p.end()
