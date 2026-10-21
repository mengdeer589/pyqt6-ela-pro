"""全局动效策略（motion policy）。

把「动画时长」从各组件的硬编码字面量收进一处令牌表，并提供一个可运行时切换的
全局偏好（``Full`` / ``Reduced`` / ``Disabled``）。对齐 Fluent-Qt 的 ``MotionPolicy``
设计，核心是**双轴**语义：``Reduced`` 不是「关掉动画」，而是「保留状态过渡、砍到
≤50ms，同时停掉所有持续动效」。

三档模式
--------
``Full``      正常播放，全时长。
``Reduced``   状态过渡压到 ``_REDUCED_TRANSITION_MS``（50ms），持续动效停止。
``Disabled``  一切过渡**同步落终值**（不占用一帧），持续动效停止。

默认从系统读（``SPI_GETCLIENTAREAANIMATION``，Win7 起可用）。宿主/测试可用
:meth:`MotionPolicy.setOverrideSystem` 固定住，:meth:`MotionPolicy.setMode` 强制指定。

**收尾不变量（必须守住）**
----------------------------
``Disabled`` 下动画时长为 0，Qt 的 ``QPropertyAnimation`` 不会跑。因此本模块**不用**
``setDuration(0)``，而是走 :func:`start_transition` 的 snap 路径：先 ``start()`` 让
动画进入 Running，再 ``setCurrentTime(duration())`` 跳到终点。这样终值经由真实 Qt
路径落盘、``finished`` 照常发出，且**落点确定在 ``setCurrentTime`` 里而不是
``start()`` 里** —— 时长为 0 时 ``start()`` 自己就会同步发 ``finished``（实测），
会让调用点的栈还没铺好就跑收尾。

不要用 ``anim.stop()`` + ``setCurrentTime()``：对 **Stopped** 的动画
``setCurrentTime`` 是个空操作（值不变、``finished`` 不发，实测）。

不属于本模块的计时器
--------------------
本模块只管**过渡**。下面这些 ``QTimer`` 看着像动画，其实是别的机制，**缩放它们会改变
行为而不只是改变观感**，守卫测试 ``tests/motion/test_motion_blacklist.py`` 会拒绝它们
引用本模块：

* **合帧 / 调度**（改「什么时候干活」）：``chat/view.py`` 的 ``_follow_timer`` /
  ``_hold_timer`` / ``_resize_reflow_timer`` / ``_render_timer`` / ``_suspension_timer``、
  ``chat/blocks.py`` 的 ``_flush_timer``、``terminal_view.py`` 的
  ``_FLUSH_INTERVAL_MS`` / ``_FILTER_DEBOUNCE_MS``、``ela_markdown_viewer.py`` 的
  ``_stream_timer`` / ``_large_render_timer`` / ``_layout_timer`` /
  ``_mermaid_priority_timer`` / ``_mermaid_pump_timer``、``charts/core.py`` 的
  ``lazyUpdate``、``table_view.py`` 的 ``_poll_retired_threads``、
  ``blueprint/canvas.py`` 的 ``_zoom_settle``、``taskbar_progress.py`` 的
  ``_attach_timer``、``selection_assistant/*``、``window_embedder.py`` /
  ``browser_embedder.py`` 的全部轮询。
* **等上游动画**：``ela_ghost_box.py`` 的 ``_footer_retry(450)`` —— 它等的是
  ElaWidgetTools C++ ``showPopup`` 自己的动画结束，缩放它会让页脚抢在 C++ 动画前面
  重排（页脚落错位置）。
* **持续动效**（属 ``ElaMotionKindType.Continuous``，本模块的 ``shouldAnimate`` 够用，但
  **必须额外画静态基态**，不能只停定时器）：``chat/blocks.py`` 的 ``_StatusDot``
  呼吸、``blueprint/_spinner.py`` / ``blueprint/node_widget.py`` /
  ``blueprint/canvas.py``、``charts/core.py`` 的 loading spinner、
  ``charts/series_cartesian.py`` 的 ripple、``charts/series_hierarchy.py`` 的流动高亮、
  ``charts/interact.py`` 的 timeline autoPlay、``tooltips.py`` 的
  ``_rotateTimer``、``ela_markdown_viewer.py`` 的 ``_caret_timer``。
  上游 C++ ``ElaProgressRing`` 的两个 ``QPropertyAnimation`` 同样管不了，只能靠
  ``setIsBusying(False)``。

图表动画是例外
--------------
``charts/core.py`` 的 ``ChartAnimation`` **不适用** :func:`start_transition`：它没有
Qt 属性目标，收尾是在 ``_apply`` 里用 ``valueChanged`` 阈值判断的（``v >= 1.0``），
不挂 ``QAbstractAnimation.finished``。它有自己的 ``complete()``（同步 ``_apply(1.0)``），
那本来就是正确的 snap 实现 —— 只需让 ``charts/_tokens.ANIM_DURATION`` 读本模块。
"""

from __future__ import annotations

import ctypes
from enum import IntEnum
from typing import Callable, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from ._internal import catch_error, is_deleted


#: ``Reduced`` 模式下状态过渡的时长上限（毫秒）。
_REDUCED_TRANSITION_MS = 50

#: snap 路径给动画的时长下限。**别设成 0**：时长为 0 时
#: ``QAbstractAnimation.start()`` 自己就同步发 ``finished``（实测），收尾会在调用点
#: 栈还没铺好时执行。设 1 让 emit 落在 ``setCurrentTime()`` 里。
_SNAP_MIN_DURATION_MS = 1

#: Windows ``SPI_GETCLIENTAREAANIMATION``（``winuser.h``）。返回 0 = 系统关闭了动画。
#:
#: **值就是 ``0x1042``，别改**：``0x0049`` 是 ``SPI_SETANIMATION``（写操作，期望
#: ``ANIMATIONINFO``），``0x004B`` 是另一个 SET 项 —— 拿 SET 常量当 GET 调用的
#: 后果是「探测恒假 + 有改写用户系统设置的风险」（本仓库踩过两次）。
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
    """问系统「关掉动画了吗」（``SPI_GETCLIENTAREAANIMATION``）。

    非 Windows / ctypes 不可用一律返回 ``False``（按正常播放处理）—— 猜错方向选「有
    动画」是因为漏放动画只是没无障碍，错关动画是所有人都受影响。
    """
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
    """全局动效策略单例。

    默认跟随系统（``SPI_GETCLIENTAREAANIMATION``），首次查询时探测一次并缓存。
    :meth:`setOverrideSystem` 固定住不再探测（测试与宿主强制用），
    :meth:`setMode` 无论如何都能指定。

    Example::

        from pyqt6_ela_pro import motion, ElaMotionModeType

        motion.setMode(ElaMotionModeType.Full)
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

    # -- 模式 ---------------------------------------------------------------

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
        """是否固定模式而不再跟随系统。

        ``True``  = 立刻按系统定一次，此后只听 :meth:`setMode`。
        ``False`` = 退回「下次查询时重新探测」。

        .. note:: 两条路径都**不发** ``modeChanged``（与 :meth:`setMode` 不同），
           所以运行期切这里不会停掉已登记的持续动效循环。
        """
        on = bool(on)
        if on == self._override_system:
            return
        self._override_system = on
        if on:
            self._mode = ElaMotionModeType.Reduced if self.systemReduced() else ElaMotionModeType.Full
        else:
            self._mode = None

    # -- 解析 ---------------------------------------------------------------

    def shouldAnimate(
        self,
        kind: ElaMotionKindType = ElaMotionKindType.Transition,
        local_enabled: bool = True,
    ) -> bool:
        """这次动效允许播吗。

        组件自身的开关优先：``local_enabled=False`` 时无论全局如何都不播。
        ``Reduced`` 只抑制 ``Continuous``，不抑制 ``Transition``。
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
        """一次解出 ``(时长, 是否 snap)``。

        ``snap=True`` 表示「不占用时间，同步落终值」，见 :func:`start_transition`。
        """
        return (
            self.duration(full_ms, kind, local_enabled),
            not self.shouldAnimate(kind, local_enabled),
        )


#: 全局单例。
motion = MotionPolicy.instance()


#: 已登记的持续动效循环：``[(weakref(timer), interval_ms), ...]``。用 weakref 是因为
#: ``QTimer`` 是 sip 对象，控件销毁后包装器可能还在而 C++ 侧已经没了。
#:
#: **登记表里绝不能存 ``on_stop``** —— 它几乎总是控件的 bound method，会强引用住整个
#: 控件，与控件 ``__dict__`` 形成永不剪枝的环（实测每个助手消息约泄漏 945KB），
#: 所以改挂在 timer 包装器自己身上（``_ON_STOP_ATTR``）。详见 AGENTS.md。
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
    """策略切到 Reduced/Disabled 时停掉所有在跑的持续动效并落到静态基态。

    切回 ``Full`` **不**自动重启 —— 重启时机归调用方（它才知道该不该重画）。停之前
    先判存活：定时器的 C++ 对象可能已被控件析构带走。
    """
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
    """按策略启动一个**持续动效**循环（转圈 / 呼吸 / 流动 / 闪烁）。

    ``Reduced`` 与 ``Disabled`` 下持续动效一律**停掉，不是放慢** —— 转得更慢的圈看着
    像卡住，不像在忙。运行时切到 Reduced/Disabled 会自动停掉已登记的循环并调
    ``on_stop``；切回 ``Full`` 不自动重启。

    :param timer: 已 ``connect`` 好 tick 的 ``QTimer``
    :param on_stop: **落到静态基态**的钩子，``Reduced``/``Disabled`` 下停掉循环时调用。
        「停掉」不等于「不画」：旋转类自然冻结在最后一帧就是静态态，但**相位类必须
        显式摆好** —— 流式光标停在 phase 0 等于光标凭空消失。
    :returns: ``True`` = 循环已启动；``False`` = **该停**（``on_stop`` 已调用）。
    """
    import weakref

    from ._internal import safe_call

    ref = weakref.ref(timer)
    _prune_idle_loops()
    if not any(existing is ref for existing, _interval in _IDLE_LOOPS):
        _IDLE_LOOPS.append((ref, int(interval_ms)))
    # on_stop 挂 timer 上而不是进全局登记表 —— 见 _IDLE_LOOPS 的说明。
    # sip 包装器可设属性；万一哪个绑定层不给设，退化成「切策略时不回调
    # on_stop」—— 那是安全方向的降级（旋转类自然冻结即静态基态），好过
    # 为了保住回调又把强引用塞回全局。
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
    """按策略启动**手搓插值**过渡（``QTimer`` 逐帧累加进度那类）。

    库里有几处没走 ``QPropertyAnimation`` 而是自己累进度的（``ela_spotlight`` /
    ``splash_screen`` / ``ela_dashboard_gauge``）—— 它们是 ``QTimer``，**不能**用
    :func:`start_transition`（那个要求 ``QAbstractAnimation``）。这个是给它们的入口。

    时长不由这里决定：总时长归调用方。

    :returns: ``True`` = 计时器已启动，调用方继续跑自己的插值。``False`` = **该同步落
        终值**：计时器保持停止，**调用方必须自己把进度摆到终点并走收尾** ——
        ``QTimer`` 不会替你判断「跑完了」。

    :raises TypeError: ``timer`` 不是 ``QTimer``。
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
    """按全局策略启动一次**过渡**动画。**这是收尾的唯一注册点** —— 调用点不要自己再
    连 ``anim.finished``（叠连接会让收尾跑两遍）。

    不适用于 ``charts`` 的 ``ChartAnimation``（它不挂 ``QAbstractAnimation.finished``，
    自带 ``complete()``）。收尾会跑在 Qt 回调链上，本函数连接时已用 ``catch_error``
    包过一层，调用方不必重复包。

    :param local_enabled: 组件自身开关，``False`` 时等价于 ``Disabled``
    :param on_complete: 收尾回调。**只在完整路径挂一次**（幂等重复连接），正常播放与
        snap 都由它收尾
    :param deletion_policy: 传给 ``QAbstractAnimation.start()``，默认
        ``KeepWhenStopped``。``DeleteWhenStopped`` 的动画停止后 C++ 对象即销毁，之后
        所有读取都要先 ``is_deleted()`` 判存活。
    :returns: ``True`` = 会播；``False`` = 已同步落终值
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

    # **无条件**调 —— ``on_complete=None`` 的语义是「取消收尾」，不是「保留上一次的
    # 收尾」；加了 ``if on_complete is not None`` 会让旧槽留在 ``anim.finished`` 上，
    # 表现为「一次注册的收尾在后续无参调用里照常触发」（通知会自己关掉自己）。
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
    """把收尾槽接到 ``anim.finished``，重复调用不叠连接。

    叠连接的后果是收尾跑两次（``close()`` / ``deleteLater()`` 各两次）。所以先断旧的
    （未连过会抛 ``TypeError``，吞掉）。
    """
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
