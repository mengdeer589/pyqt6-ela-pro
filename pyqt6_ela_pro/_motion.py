"""全局动效策略（Full / Reduced / Disabled）。

``Reduced`` 只把状态过渡压到 50ms 并停持续动效；``Disabled`` 让一切过渡同步落终值。
实现约束与不属于本模块的计时器见 ``docs/core.md``。
"""

from __future__ import annotations

import ctypes
from enum import IntEnum
from typing import Callable, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from ._internal import catch_error, is_deleted


#: ``Reduced`` 模式下状态过渡的时长上限（毫秒）。
_REDUCED_TRANSITION_MS = 50

#: snap 时长下限。不能设 0：时长为 0 时 ``start()`` 会同步发 ``finished``，
#: 收尾在调用方栈未铺好时执行；设 1 让 emit 落在 ``setCurrentTime()`` 内。
_SNAP_MIN_DURATION_MS = 1

#: Windows ``SPI_GETCLIENTAREAANIMATION``（0x1042，只读）；返回 0 = 系统关闭动画。
#: 别改成 0x0049 / 0x004B —— 那是 SET 写操作，会探测恒假并有改写系统设置的风险。
_SPI_GETCLIENTAREAANIMATION = 0x1042

_SLOT_ATTR = "_ela_motion_slot"


class ElaMotionModeType(IntEnum):
    """全局动效偏好。"""

    Full = 0
    """正常播放。"""

    Reduced = 1
    """状态过渡压到 ≤50ms，持续动效停止。"""

    Disabled = 2
    """一切过渡同步落终值，持续动效停止。"""


class ElaMotionKindType(IntEnum):
    """动效的存活期，决定 ``Reduced`` 下是否被抑制。"""

    Transition = 0
    """有限的状态变化（展开/淡入/滑出）。``Reduced`` 下保留，只是变快。"""

    Continuous = 1
    """持续/空闲动效（转圈、呼吸、流动）。``Reduced`` 下停止。"""


class Duration:
    """时长令牌（毫秒）。组件引用令牌而不是写字面量。"""

    Fast = 150
    """即时反馈：按钮按下、小控件开关。"""

    Normal = 250
    """标准展开/折叠、简单进出。"""

    Slow = 400
    """可察觉的页面、弹层、布局过渡。"""

    VerySlow = 700
    """大容器首次加载。"""


class Easing:
    """意图命名的缓动。组件说 ``Decelerate``，不写死 ``OutCubic``。"""

    Standard = "standard"
    Accelerate = "accelerate"
    Decelerate = "decelerate"
    Entrance = "entrance"
    Exit = "exit"

    _CURVES = {
        # 名字 → (QEasingCurve.Type 名字, amplitude 或 None)
        "standard": ("InOutSine", None),
        "accelerate": ("InCubic", None),
        "decelerate": ("OutCubic", None),
        "entrance": ("OutBack", 0.5),
        "exit": ("InQuint", None),
    }

    @staticmethod
    def curve(name: str) -> "object":
        """把意图名解析成 ``QEasingCurve``。未知名字回落到 ``OutCubic``。"""
        from PyQt6.QtCore import QEasingCurve

        entry = Easing._CURVES.get(str(name).strip().lower())
        if entry is None:
            return QEasingCurve.Type.OutCubic
        type_name, amplitude = entry
        curve = QEasingCurve(getattr(QEasingCurve.Type, type_name))
        if amplitude is not None:
            curve.setAmplitude(amplitude)
        return curve

    @staticmethod
    def type_name(name: str) -> "object":
        """只要 ``QEasingCurve.Type``（不带 amplitude 的场合）。"""
        from PyQt6.QtCore import QEasingCurve

        entry = Easing._CURVES.get(str(name).strip().lower())
        if entry is None:
            return QEasingCurve.Type.OutCubic
        return getattr(QEasingCurve.Type, entry[0])


def _probe_system_reduced() -> bool:
    """系统是否关闭了动画；非 Windows / ctypes 不可用时按正常播放处理。"""
    user32 = getattr(ctypes, "windll", None)
    if user32 is None:  # 非 Windows
        return False
    try:
        enabled = ctypes.c_int(0)
        ok = user32.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
    except (OSError, AttributeError):
        return False
    return bool(ok) and enabled.value == 0


class MotionPolicy(QObject):
    """全局动效策略单例；默认跟随系统，首次查询时探测一次并缓存。

    ``setOverrideSystem`` 固定模式，``setMode`` 强制指定。
    """

    modeChanged = pyqtSignal(object)

    _instance: Optional["MotionPolicy"] = None

    def __init__(self) -> None:
        super().__init__()
        self._mode: Optional[ElaMotionModeType] = None
        self._system_reduced: Optional[bool] = None
        self._override_system = False

    @classmethod
    def instance(cls) -> "MotionPolicy":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


    def mode(self) -> ElaMotionModeType:
        """当前生效的模式。未显式指定过时按系统探测（只探一次）。"""
        if self._mode is None:
            self._mode = ElaMotionModeType.Reduced if self.systemReduced() else ElaMotionModeType.Full
        return self._mode

    def setMode(self, mode) -> None:
        """指定模式。同值或非法值静默返回（非法值不抛，跟组件 setter 一致）。"""
        try:
            mode = ElaMotionModeType(mode)
        except ValueError:
            return
        if mode == self.mode():
            return
        self._mode = mode
        self.modeChanged.emit(mode)

    def systemReduced(self) -> bool:
        """系统是否关掉了动画。探测一次后缓存。"""
        if self._system_reduced is None:
            self._system_reduced = _probe_system_reduced()
        return self._system_reduced

    def setOverrideSystem(self, on: bool) -> None:
        """固定模式而不再跟随系统；不发 ``modeChanged``，不会停掉已登记的持续动效。"""
        on = bool(on)
        if on == self._override_system:
            return
        self._override_system = on
        if on:
            self._mode = ElaMotionModeType.Reduced if self.systemReduced() else ElaMotionModeType.Full
        else:
            self._mode = None


    def shouldAnimate(
        self,
        kind: ElaMotionKindType = ElaMotionKindType.Transition,
        local_enabled: bool = True,
    ) -> bool:
        """这次动效是否允许播放。

        ``local_enabled=False`` 一律不播；``Reduced`` 只抑制 ``Continuous``。
        """
        mode = self.mode()
        if not local_enabled or mode == ElaMotionModeType.Disabled:
            return False
        return mode == ElaMotionModeType.Full or kind == ElaMotionKindType.Transition

    def duration(
        self,
        full_ms: int,
        kind: ElaMotionKindType = ElaMotionKindType.Transition,
        local_enabled: bool = True,
    ) -> int:
        """把「全动效时长」解析成本次实际该用的时长。``Disabled`` 下是 0。"""
        if not self.shouldAnimate(kind, local_enabled):
            return 0
        bounded = max(0, int(full_ms))
        if self.mode() == ElaMotionModeType.Reduced:
            return min(bounded, _REDUCED_TRANSITION_MS)
        return bounded

    def plan(
        self,
        full_ms: int,
        kind: ElaMotionKindType = ElaMotionKindType.Transition,
        local_enabled: bool = True,
    ) -> Tuple[int, bool]:
        """一次解出 ``(时长, 是否 snap)``；``snap=True`` 表示同步落终值。"""
        return (
            self.duration(full_ms, kind, local_enabled),
            not self.shouldAnimate(kind, local_enabled),
        )


#: 全局单例。
motion = MotionPolicy.instance()


#: 已登记的持续动效循环 ``[(weakref(timer), interval_ms), ...]``。
#: 不存 ``on_stop``：bound method 会强引用控件形成无法回收的环，改挂 timer 自身。
_IDLE_LOOPS: list = []

#: timer 包装器上挂 ``on_stop`` 的属性名。
_ON_STOP_ATTR = "_ela_idle_on_stop"


def _idle_on_stop(timer) -> Optional[Callable[[], None]]:
    """取 timer 上登记的 ``on_stop``（没有则 ``None``）。"""
    return getattr(timer, _ON_STOP_ATTR, None)


def _prune_idle_loops() -> None:
    global _IDLE_LOOPS
    _IDLE_LOOPS = [entry for entry in _IDLE_LOOPS if entry[0]() is not None]


def _stop_idle_loops_on_mode_change(_mode) -> None:
    """切到 Reduced/Disabled 时停掉持续动效并落静态基态；切回 Full 不自动重启。"""
    from ._internal import safe_call

    _prune_idle_loops()
    if motion.shouldAnimate(ElaMotionKindType.Continuous):
        return
    for ref, _interval in list(_IDLE_LOOPS):
        timer = ref()
        if timer is None or is_deleted(timer):
            continue
        was_running = timer.isActive()
        timer.stop()
        # 只在「本来在跑」时才重画：没在跑的循环调用方已经摆好静态态了
        if was_running:
            safe_call(_idle_on_stop(timer))


motion.modeChanged.connect(_stop_idle_loops_on_mode_change)


def start_idle_loop(
    timer,
    interval_ms: int,
    *,
    local_enabled: bool = True,
    on_stop: Optional[Callable[[], None]] = None,
) -> bool:
    """按策略启动持续动效循环；Reduced/Disabled 下停掉而非放慢。

    :param timer: 已连接 tick 的 ``QTimer``
    :param on_stop: 落到静态基态的钩子；相位类动效必须传，否则会停在不可见相位
    :returns: ``True`` = 已启动；``False`` = 已停并调用 ``on_stop``
    """
    import weakref

    from ._internal import safe_call

    ref = weakref.ref(timer)
    _prune_idle_loops()
    if not any(existing is ref for existing, _interval in _IDLE_LOOPS):
        _IDLE_LOOPS.append((ref, int(interval_ms)))
    # on_stop 挂 timer 上而不进全局表：sip 包装器可设属性；设不了就退化为
    # 切换策略时不回调（安全方向），不能为了保住回调把强引用塞回全局。
    try:
        setattr(timer, _ON_STOP_ATTR, on_stop)
    except AttributeError:
        pass

    # 无论启不启动都写入间隔：少了这步，Reduced 下间隔永远停在 0，之后谁直接
    # timer.start() 就是 0ms 空转（烧满一个核）。
    timer.setInterval(int(interval_ms))

    if not motion.shouldAnimate(ElaMotionKindType.Continuous, local_enabled):
        was_running = timer.isActive()
        timer.stop()
        if was_running or on_stop is not None:
            safe_call(on_stop)
        return False

    if not timer.isActive():
        timer.start()
    return True


def idle_loop_running(timer) -> bool:
    """这个 ``QTimer`` 是不是在真的跑持续动效（已判存活）。"""
    try:
        return not is_deleted(timer) and timer.isActive()
    except RuntimeError:
        return False


def start_transition_timer(timer, *, local_enabled: bool = True) -> bool:
    """按策略启动手搓插值的 ``QTimer`` 过渡（``ela_spotlight`` / ``splash_screen`` 等）。

    :returns: ``True`` = 已启动；``False`` = 调用方必须同步落终值并收尾
    :raises TypeError: ``timer`` 不是 ``QTimer``
    """
    from PyQt6.QtCore import QTimer

    if not isinstance(timer, QTimer):
        raise TypeError(f"start_transition_timer 需要 QTimer，收到 {type(timer)!r}")

    if not motion.shouldAnimate(ElaMotionKindType.Transition, local_enabled):
        timer.stop()
        return False
    if not timer.isActive():
        timer.start()
    return True


def start_transition(
    anim,
    full_ms: int,
    *,
    local_enabled: bool = True,
    kind: ElaMotionKindType = ElaMotionKindType.Transition,
    on_complete: Optional[Callable[[], None]] = None,
    deletion_policy=None,
) -> bool:
    """按全局策略启动过渡动画，是 ``finished`` 收尾的唯一注册点。

    不适用于 ``charts.ChartAnimation``（它不走 ``QAbstractAnimation.finished``）。

    :param on_complete: 收尾回调；正常播放与 snap 都由它收尾
    :param deletion_policy: 默认 ``KeepWhenStopped``；``DeleteWhenStopped`` 后读取前须判存活
    :returns: ``True`` = 会播放；``False`` = 已同步落终值
    :raises TypeError: ``anim`` 不是 ``QAbstractAnimation``
    """
    from PyQt6.QtCore import QAbstractAnimation

    if not isinstance(anim, QAbstractAnimation):
        raise TypeError(
            f"start_transition 需要 QAbstractAnimation，收到 {type(anim)!r}"
        )

    duration_ms, snap = motion.plan(full_ms, kind, local_enabled)
    if deletion_policy is None:
        deletion_policy = QAbstractAnimation.DeletionPolicy.KeepWhenStopped

    # 无条件调用：``on_complete=None`` 表示取消收尾，不能留着上一次的槽。
    _connect_complete(anim, on_complete)

    if not snap:
        anim.setDuration(duration_ms)
        anim.start(deletion_policy)
        return True

    # snap 路径：先 start() 进 Running 再跳到终点。时长必须为正（见
    # _SNAP_MIN_DURATION_MS）；setCurrentTime 只对 Running 的动画生效。
    anim.setDuration(max(_SNAP_MIN_DURATION_MS, duration_ms))
    anim.start(deletion_policy)
    # 先把 duration 读出来再跳：DeleteWhenStopped 下 setCurrentTime 触发 Stops 时
    # C++ 对象当场销毁，之后再读 anim 就是解引用已释放内存。
    end_time = anim.duration()
    anim.setCurrentTime(end_time)
    return False


def _connect_complete(anim, on_complete: Optional[Callable[[], None]]) -> None:
    """把收尾槽接到 ``anim.finished``，重复调用不叠连接（旧槽先断）。"""
    previous = getattr(anim, _SLOT_ATTR, None)
    if previous is not None:
        try:
            anim.finished.disconnect(previous)
        except (TypeError, RuntimeError):
            pass
    setattr(anim, _SLOT_ATTR, None)
    if on_complete is None:
        # 「取消收尾」：只断旧，不连新
        return
    slot = catch_error(on_complete)
    setattr(anim, _SLOT_ATTR, slot)
    anim.finished.connect(slot)
