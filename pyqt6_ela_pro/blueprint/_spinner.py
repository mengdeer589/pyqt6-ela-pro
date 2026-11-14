"""旋转圈加载指示器（``SpinnerArc``）：复用 ``ElaProgressRing`` 的 busy 动画。"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaProgressRing

from .._internal import safe_connect
from .._motion import ElaMotionKindType, motion

__all__ = ["SpinnerArc"]

#: 停转时保留的静态弧（0~100，约 110°），与「冻结在当前角度」语义一致。
_STATIC_VALUE = 30


class SpinnerArc(ElaProgressRing):
    """小尺寸加载圈；``start`` / ``stop`` 受全局动效策略约束。"""

    def __init__(self, size=32, line_width=None, speed=10.0, interval=16, parent=None):
        super().__init__(parent)
        size = max(12, int(size))
        self._running = False
        self.setIsDisplayValue(False)
        self.setBusyingWidth(int(line_width) if line_width else max(2, size // 8))
        self.setBusyingDurationTime(
            max(200, int(360.0 / max(float(speed), 0.1) * max(5, int(interval))))
        )
        self.setFixedSize(size, size)
        self.setValue(_STATIC_VALUE)
        safe_connect(motion, "modeChanged", self._on_motion_changed, "spinner.motion")
        self.start()

    def start(self) -> None:
        """启动旋转；Reduced/Disabled 下保留静态弧而不转。"""
        self._running = motion.shouldAnimate(ElaMotionKindType.Continuous)
        if self._running:
            self.setIsBusying(True)
        else:
            self.setIsBusying(False)
            self.setValue(_STATIC_VALUE)

    def stop(self) -> None:
        """停止旋转并落到静态弧。"""
        self._running = False
        self.setIsBusying(False)
        self.setValue(_STATIC_VALUE)

    def isRunning(self) -> bool:  # noqa: N802 (Qt 命名)
        return self._running

    def _on_motion_changed(self, _mode) -> None:
        if not self._running:
            return
        if not motion.shouldAnimate(ElaMotionKindType.Continuous):
            self.stop()
