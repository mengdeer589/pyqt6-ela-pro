"""入场 / 过渡动画驱动。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QVariantAnimation,
    pyqtSignal,
)

from ..._motion import ElaMotionKindType, motion
from .._tokens import (
    ANIM_DURATION,
    ANIM_EASING,
)


class ChartAnimation(QObject):
    """0→1 进度动画（QVariantAnimation，缓出），渲染器按 ``anim_t`` 插值。
    ``setProgress(v)`` 支持无事件循环环境手动推进；``finished`` 在进度到达
    1.0 后发射一次。
    """

    #: 一次入场 / 过渡动画播放完毕（ECharts ``finished`` 事件源）
    finished = pyqtSignal()

    def __init__(self, on_update=None, parent: QObject = None):
        super().__init__(parent)
        self._t = 0.0
        self._raw = 0.0
        self._requested_duration = ANIM_DURATION
        self._curve = QEasingCurve(ANIM_EASING)
        self._on_update = on_update
        self._finished_pending = False
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(ANIM_DURATION)
        # 全局曲线在 ``_apply`` 里应用：系列需要线性时间做各自的时长 / 缓动
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.valueChanged.connect(self._on_value)

    @property
    def t(self) -> float:
        """当前（全局缓动后的）进度 ∈ [0,1]。"""
        return self._t

    @property
    def raw(self) -> float:
        """线性时间进度 ∈ [0,1]（系列按时长 / 缓动自行映射）。"""
        return self._raw

    @property
    def duration(self) -> int:
        """本次动画时长（ms）。"""
        return self._anim.duration()

    @property
    def requested(self) -> int:
        """按 option 请求的完整时长（ms，未受动效策略压缩）。"""
        return int(self._requested_duration)

    @property
    def easing(self):
        """全局缓动曲线类型。"""
        return self._curve.type()

    def start(self) -> None:
        """从头播放（setOption / 过渡动画时调用）。"""
        self._anim.stop()
        self._finished_pending = True
        self._anim.start()

    def stop(self) -> None:
        """停止动画（取消，不再补发 ``finished``）。"""
        self._anim.stop()
        self._finished_pending = False

    def complete(self) -> None:
        """直接置满进度并发射 ``finished``（``animation=false`` 路径）。"""
        self._anim.stop()
        self._finished_pending = True
        self._apply(1.0)

    def startResolved(self, full_ms: int, easing=None) -> bool:
        """按全局动效策略启动过渡，返回是否真的播放。

        刻意不用 :func:`pyqt6_ela_pro._motion.start_transition`：本类没有 Qt 属性
        目标，收尾靠 ``_apply`` 里的阈值判断，而那个 helper 挂的是属性动画。
        """
        duration_ms, snap = motion.plan(full_ms, ElaMotionKindType.Transition)
        self._requested_duration = max(0, int(full_ms))
        self.setDuration(duration_ms)
        self.setEasing(easing)
        if snap:
            self.complete()
            return False
        self.start()
        return True

    def setDuration(self, duration: int) -> None:
        """设置动画时长（ms，ECharts ``animationDuration``）。"""
        try:
            self._anim.setDuration(max(0, int(duration)))
        except (TypeError, ValueError, OverflowError):
            pass

    def setEasing(self, easing) -> None:
        """设置全局缓动曲线（``QEasingCurve.Type`` / ``QEasingCurve``）。"""
        if easing is None:
            return
        if isinstance(easing, QEasingCurve):
            easing = easing.type()
        self._curve = QEasingCurve(easing)

    def isRunning(self) -> bool:
        return self._anim.state() == QAbstractAnimation.State.Running

    def setProgress(self, v: float) -> None:
        """手动设置进度并触发重绘回调（测试 / 无动画路径用）。"""
        self._apply(max(0.0, min(1.0, float(v))), ease=False)

    def _on_value(self, v) -> None:
        self._apply(float(v))

    def _apply(self, v: float, *, ease: bool = True) -> None:
        self._raw = v
        self._t = self._curve.valueForProgress(v) if ease else v
        if callable(self._on_update):
            self._on_update()
        if v >= 1.0 and self._finished_pending:
            self._finished_pending = False
            self.finished.emit()
