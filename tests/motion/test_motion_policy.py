"""``pyqt6_ela_pro._motion`` 的单元测试。

三块：
1. 策略解析真值表（``plan()`` / ``shouldAnimate()`` / ``duration()``）
2. ``start_transition`` 的 snap 路径 —— 落终值 + 收尾恰好一次 + 不叠连接
3. 黑名单守卫：合帧/调度计时器不许接本模块
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from PyQt6.QtCore import (
    QAbstractAnimation,
    QPropertyAnimation,
    QVariantAnimation,
    pyqtProperty,
)
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro._motion import (
    Duration,
    Easing,
    ElaMotionKindType,
    ElaMotionModeType,
    MotionPolicy,
    motion,
    start_transition,
)


class _Animated(QWidget):
    """一个带 float 属性的宿主，给 QPropertyAnimation 当目标。"""

    _v = 0.0
    v = pyqtProperty(float, lambda s: s._v, lambda s, x: setattr(s, "_v", float(x)))

    def __init__(self) -> None:
        super().__init__()
        self.anim = QPropertyAnimation(self, b"v", self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)


@pytest.fixture(autouse=True)
def _restore_mode():
    previous = motion.mode()
    yield
    motion.setMode(previous)


# ── 1. 策略解析 ──────────────────────────────────────────────


class TestPolicyResolution:
    @pytest.mark.parametrize(
        "mode,kind,should,duration",
        [
            (ElaMotionModeType.Full, ElaMotionKindType.Transition, True, 300),
            (ElaMotionModeType.Full, ElaMotionKindType.Continuous, True, 300),
            # Reduced 只压时长、只杀 Continuous
            (ElaMotionModeType.Reduced, ElaMotionKindType.Transition, True, 50),
            (ElaMotionModeType.Reduced, ElaMotionKindType.Continuous, False, 0),
            (ElaMotionModeType.Disabled, ElaMotionKindType.Transition, False, 0),
            (ElaMotionModeType.Disabled, ElaMotionKindType.Continuous, False, 0),
        ],
        ids=lambda v: v.name if hasattr(v, "name") else str(v),
    )
    def test_truth_table(self, mode, kind, should, duration):
        motion.setMode(mode)
        assert motion.shouldAnimate(kind) is should
        assert motion.duration(300, kind) == duration

    def test_reduced_caps_rather_than_scales(self):
        """Reduced 取 min(全时长, 50)：本来就短的过渡不动，本来长的才被砍。"""
        motion.setMode(ElaMotionModeType.Reduced)
        assert motion.duration(30) == 30
        assert motion.duration(1000) == 50

    def test_duration_token_table_is_ordered(self):
        assert Duration.Fast < Duration.Normal < Duration.Slow < Duration.VerySlow

    def test_local_disabled_overrides_full(self):
        """组件自身开关优先于全局：``local_enabled=False`` 时任何模式都不播。"""
        for mode in ElaMotionModeType:
            motion.setMode(mode)
            assert motion.shouldAnimate(ElaMotionKindType.Transition, False) is False
            assert motion.duration(300, local_enabled=False) == 0

    def test_negative_duration_is_clamped(self):
        motion.setMode(ElaMotionModeType.Full)
        assert motion.duration(-100) == 0

    def test_plan_returns_snap_flag(self):
        motion.setMode(ElaMotionModeType.Full)
        assert motion.plan(300) == (300, False)
        motion.setMode(ElaMotionModeType.Disabled)
        assert motion.plan(300) == (0, True)

    def test_setMode_rejects_unknown_value(self):
        motion.setMode(ElaMotionModeType.Full)
        motion.setMode(999)
        assert motion.mode() == ElaMotionModeType.Full

    def test_setMode_same_value_does_not_emit(self, qapp):
        motion.setMode(ElaMotionModeType.Full)
        seen: list = []
        motion.modeChanged.connect(seen.append)
        motion.setMode(ElaMotionModeType.Full)
        assert seen == []
        motion.setMode(ElaMotionModeType.Reduced)
        assert seen == [ElaMotionModeType.Reduced]

    def test_system_probe_is_cached(self, monkeypatch):
        monkeypatch.setattr("pyqt6_ela_pro._motion._probe_system_reduced", lambda: True)
        policy = MotionPolicy()
        assert policy.systemReduced() is True
        monkeypatch.setattr(
            "pyqt6_ela_pro._motion._probe_system_reduced", lambda: False
        )
        assert policy.systemReduced() is True, "探测结果必须缓存，不该二次调用"

    def test_auto_mode_follows_system(self, monkeypatch):
        monkeypatch.setattr("pyqt6_ela_pro._motion._probe_system_reduced", lambda: True)
        policy = MotionPolicy()
        assert policy.mode() == ElaMotionModeType.Reduced

    def test_override_system_pins_then_releases(self, monkeypatch):
        monkeypatch.setattr("pyqt6_ela_pro._motion._probe_system_reduced", lambda: True)
        policy = MotionPolicy()
        policy.setOverrideSystem(True)
        assert policy.mode() == ElaMotionModeType.Reduced
        policy.setMode(ElaMotionModeType.Full)
        assert policy.mode() == ElaMotionModeType.Full
        policy.setOverrideSystem(False)
        assert policy.mode() == ElaMotionModeType.Reduced, "解除覆盖后重新跟随系统"


class TestEasingTokens:
    @pytest.mark.parametrize(
        "name",
        [
            Easing.Standard,
            Easing.Accelerate,
            Easing.Decelerate,
            Easing.Entrance,
            Easing.Exit,
        ],
    )
    def test_every_token_resolves(self, name):
        assert Easing.curve(name) is not None
        assert Easing.type_name(name) is not None

    def test_unknown_name_falls_back(self):
        from PyQt6.QtCore import QEasingCurve

        assert Easing.type_name("nope") == QEasingCurve.Type.OutCubic

    def test_entrance_carries_amplitude(self):
        assert Easing.curve(Easing.Entrance).amplitude() == pytest.approx(0.5)
        # type_name 只给 Type，不带 amplitude
        assert not hasattr(Easing.type_name(Easing.Entrance), "amplitude")


# ── 2. start_transition ──────────────────────────────────────


class TestStartTransition:
    def test_full_mode_plays_normally(self, qapp):
        motion.setMode(ElaMotionModeType.Full)
        w = _Animated()
        ran = start_transition(w.anim, 300, on_complete=lambda: None)
        assert ran is True
        assert w.anim.duration() == 300
        assert w.anim.state() == QPropertyAnimation.State.Running

    def test_disabled_snaps_to_end_value(self, qapp):
        """Disabled：终值当场落盘、收尾当场触发、动画不进 Running。"""
        motion.setMode(ElaMotionModeType.Disabled)
        w = _Animated()
        hits: list[int] = []
        ran = start_transition(w.anim, 300, on_complete=lambda: hits.append(1))
        assert ran is False
        assert w.v == pytest.approx(1.0)
        assert hits == [1]
        assert w.anim.state() == QAbstractAnimation.State.Stopped

    def test_disabled_duration_is_positive_not_zero(self, qapp):
        """snap 路径时长必须为正：0 会让 start() 自己同步发 finished（实测）。"""
        motion.setMode(ElaMotionModeType.Disabled)
        w = _Animated()
        start_transition(w.anim, 300)
        assert w.anim.duration() > 0

    def test_reduced_caps_duration(self, qapp):
        motion.setMode(ElaMotionModeType.Reduced)
        w = _Animated()
        start_transition(w.anim, 1000)
        assert w.anim.duration() == 50

    def test_reduced_transition_still_runs(self, qapp):
        motion.setMode(ElaMotionModeType.Reduced)
        w = _Animated()
        assert start_transition(w.anim, 1000) is True
        assert w.v == pytest.approx(0.0), "Reduced 下过渡要真的播（只是变快）"

    def test_continuous_snaps_under_reduced(self, qapp):
        """装饰性动效（shake_window 走这条）在 Reduced 下整体不播。"""
        motion.setMode(ElaMotionModeType.Reduced)
        w = _Animated()
        ran = start_transition(w.anim, 1000, kind=ElaMotionKindType.Continuous)
        assert ran is False
        assert w.v == pytest.approx(1.0)

    def test_repeated_calls_do_not_stack_completions(self, qapp):
        """重复启动**同一个动画对象**时收尾只跑一次。

        叠连接的代价：``tooltips`` 的 ``_onFadeOutFinished`` 会跑两遍 = 两次
        ``deleteLater()``。``QObject.receivers()`` 在 PyQt6 下不可用
        （见 MIGRATION），改为**数真实回调次数**。
        """
        motion.setMode(ElaMotionModeType.Full)
        w = _Animated()
        hits: list[int] = []
        for _ in range(3):
            start_transition(w.anim, 300, on_complete=lambda: hits.append(1))
        # 推到终点：收尾只应跑一次（最后一次注册的那个回调）
        w.anim.setCurrentTime(w.anim.duration())
        assert len(hits) == 1, f"收尾跑了 {len(hits)} 次（叠连接）"

    def test_each_transition_completes_once(self, qapp):
        """三次独立的过渡 = 三次收尾（不是叠连接，是三次各跑一次）。"""
        motion.setMode(ElaMotionModeType.Disabled)
        hits: list[int] = []
        for _ in range(3):
            w = _Animated()
            start_transition(w.anim, 300, on_complete=lambda: hits.append(1))
        assert len(hits) == 3

    def test_no_completion_when_omitted(self, qapp):
        motion.setMode(ElaMotionModeType.Disabled)
        w = _Animated()
        start_transition(w.anim, 300)
        assert w.v == pytest.approx(1.0)

    def test_completion_exception_does_not_escape(self, qapp):
        """收尾跑在 Qt 回调链上，抛异常就是 0xC0000409 静默终止，必须被吞。"""
        motion.setMode(ElaMotionModeType.Disabled)
        w = _Animated()

        def boom() -> None:
            raise RuntimeError("boom")

        start_transition(w.anim, 300, on_complete=boom)  # 不应抛出

    def test_rejects_non_animation(self, qapp):
        with pytest.raises(TypeError):
            start_transition(object(), 300)

    def test_works_with_qvariantanimation(self, qapp):
        motion.setMode(ElaMotionModeType.Disabled)
        anim = QVariantAnimation()
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        hits: list[int] = []
        start_transition(anim, 300, on_complete=lambda: hits.append(1))
        assert hits == [1]

    def test_deletion_policy_is_passed_through(self, qapp):
        motion.setMode(ElaMotionModeType.Full)
        w = _Animated()
        start_transition(
            w.anim,
            10,
            deletion_policy=QAbstractAnimation.DeletionPolicy.DeleteWhenStopped,
        )
        assert w.anim.state() == QAbstractAnimation.State.Running


# ── 3. 黑名单守卫 ────────────────────────────────────────────


_PKG = pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro"

_MOTION_SYMBOLS = {
    "motion",
    "start_transition",
    "Duration",
    "Easing",
    "ElaMotionModeType",
    "ElaMotionKindType",
    "MotionPolicy",
}

#: 这些计时器改的是「什么时候干活」，不是「怎么动」。缩放它们会改变**行为**而不只是
#: 观感：合帧间隔是吞吐预算，去抖延迟是用户感知的手感。
_BLACKLIST = {
    "chat/view.py": (
        "_follow_timer",
        "_hold_timer",
        "_resize_reflow_timer",
        "_render_timer",
        "_suspension_timer",
    ),
    "chat/blocks.py": ("_flush_timer",),
    "terminal_view.py": ("_flush_timer", "_filter_timer"),
    "ela_markdown_viewer.py": (
        "_stream_timer",
        "_large_render_timer",
        "_layout_timer",
        "_mermaid_priority_timer",
        "_mermaid_pump_timer",
    ),
    "table_view.py": ("_poll_retired_threads",),
    "taskbar_progress.py": ("_attach_timer",),
    "blueprint/canvas.py": ("_zoom_settle",),
    "window_embedder.py": ("_embedTimer", "_findTimer", "_resize_debounce"),
    "browser_embedder.py": ("_connect_timer", "_hwnd_timer", "_debug_url_timer"),
}

#: 耦合在**上游 C++ 动画时序**上的等待：ElaWidgetTools 的 ``showPopup`` 动画结束后
#: 才把 view 追加进容器布局，所以要等它跑完再重排页脚。缩放这个等待会让页脚
#: 抢在 C++ 动画前面落地、落错位置。
#:
#: 注意 ``ela_ghost_box.py`` **本身**是合法引用动效策略的（箭头旋转是真动效）——
#: 所以这条守卫的粒度必须落到**那一次 ``.start()`` 的实参**上，不能按文件扫。
_UPSTREAM_COUPLED = {"ela_ghost_box.py": ("_footer_retry",)}

#: **功能契约**而非动效：进度环是用户唯一的计时反馈，接上策略会让控件行为不可预测。
#:
#: ``ela_long_press_button.setDuration(ms)`` 的语义就是「按这么久才触发」：
#: Reduced 下 min(ms, 50) → 800ms 长按变 50ms、一碰就触发；Disabled 下直接落终值
#: → 长按按钮退化成单击按钮。两者都是 bug 而不是无障碍。
_ESSENTIAL_GESTURE = {
    "ela_long_press_button.py": ("_mouse_pressed_timer", "_go_backwards_timer"),
}


def _start_call_args(path: pathlib.Path, timer: str) -> list[list[ast.AST]]:
    """抽出 ``<timer>.start(<实参>)`` 的全部实参子树。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[list[ast.AST]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "start"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == timer
        ):
            found.append(list(node.args) + [kw.value for kw in node.keywords])
    return found


def _policy_call_args(path: pathlib.Path, helpers: set[str]) -> list[str]:
    """抽出所有 ``<helper>(...)`` 调用（桶 A2 的实参不挂在 ``.start()`` 上）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        f"{node.func.id}(...)"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in helpers
    ]


def _symbols_in(nodes: list[ast.AST]) -> set[str]:
    names: set[str] = set()
    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
    return names


def _file_symbols(path: pathlib.Path) -> set[str]:
    return _symbols_in(
        [ast.parse(path.read_text(encoding="utf-8"), filename=str(path))]
    )


@pytest.mark.parametrize("relpath,timers", sorted(_BLACKLIST.items()))
def test_coalescing_timers_are_never_policy_scaled(relpath, timers):
    """合帧/调度计时器的 ``.start()`` 实参不许依赖动效策略。"""
    path = _PKG / relpath
    assert path.is_file(), f"黑名单指向的文件不存在：{relpath}"
    file_symbols = _file_symbols(path)
    for timer in timers:
        assert timer in file_symbols, (
            f"{relpath} 里的 {timer} 改名或移走了，请更新黑名单"
        )
        for args in _start_call_args(path, timer):
            leaked = _symbols_in(args) & _MOTION_SYMBOLS
            assert not leaked, (
                f"{relpath}: {timer}.start() 的实参引用了动效策略 {sorted(leaked)} —— "
                f"这是合帧/调度路径，缩放它改的是行为不是观感"
            )


@pytest.mark.parametrize("relpath,timers", sorted(_UPSTREAM_COUPLED.items()))
def test_upstream_coupled_wait_is_never_policy_scaled(relpath, timers):
    """等上游 C++ 动画的等待不许被策略缩放。"""
    path = _PKG / relpath
    file_symbols = _file_symbols(path)
    for timer in timers:
        assert timer in file_symbols
        calls = _start_call_args(path, timer)
        assert calls, f"{relpath}: 找不到 {timer}.start(...) 调用，守卫已失效"
        for args in calls:
            leaked = _symbols_in(args) & _MOTION_SYMBOLS
            assert not leaked, (
                f"{relpath}: {timer}.start() 等的是上游 C++ showPopup 动画，"
                f"不受动效策略管，却引用了 {sorted(leaked)}"
            )


@pytest.mark.parametrize("relpath,timers", sorted(_ESSENTIAL_GESTURE.items()))
def test_essential_gesture_not_scaled(relpath, timers):
    """功能契约（长按进度环）不许被策略缩放。

    缩了会让控件行为不可预测：``setDuration(800)`` 在 Reduced 下变成 50ms
    （一碰就触发）、在 Disabled 下退化成单击按钮。那是 bug 不是无障碍。
    """
    path = _PKG / relpath
    file_symbols = _file_symbols(path)
    for timer in timers:
        assert timer in file_symbols, f"{relpath} 的 {timer} 已消失，请更新黑名单"
        calls = _start_call_args(path, timer)
        assert calls, f"{relpath}: 找不到 {timer}.start(...) 调用，守卫已失效"
        for args in calls:
            leaked = _symbols_in(args) & _MOTION_SYMBOLS
            assert not leaked, (
                f"{relpath}: {timer}.start() 是功能计时不是动效，不该引用 {sorted(leaked)}"
            )
    hooked = _policy_call_args(path, {"start_transition_timer", "start_transition"})
    assert not hooked, f"{relpath} 是功能契约（长按时长），不该接动效策略：{hooked}"


def test_blacklist_files_all_exist():
    """守卫自身：黑名单里写了不存在的文件就等于没在守。"""
    for relpath in {**_BLACKLIST, **_UPSTREAM_COUPLED, **_ESSENTIAL_GESTURE}:
        assert (_PKG / relpath).is_file(), f"黑名单里的 {relpath} 不存在"


def test_blacklist_timers_still_exist():
    """守卫自身：黑名单里的计时器符号必须真的还在用。"""
    for relpath, timers in {
        **_BLACKLIST,
        **_UPSTREAM_COUPLED,
        **_ESSENTIAL_GESTURE,
    }.items():
        symbols = _file_symbols(_PKG / relpath)
        for timer in timers:
            assert timer in symbols, f"{relpath} 的 {timer} 已消失，请更新黑名单"


# ── 4. 系统动效探测（SPI 常量守卫）────────────────────────────


def test_spi_getclientareaanimation_is_read_only_constant():
    """``SPI_GETCLIENTAREAANIMATION`` 必须是只读项 ``0x1042``。

    ``0x0049`` 是 ``SPI_SETANIMATION``（写操作，期望 ``ANIMATIONINFO``）、
    ``0x004B`` 是另一个 SET 项：拿 SET 常量当 GET 调用会让探测恒假
    （「跟随系统关闭动画」的无障碍默认失效），且参数一旦恰好满足校验就会
    改写用户的系统设置。常量写错时本用例立刻失败 —— 比真机验证便宜。
    """
    from pyqt6_ela_pro._motion import _SPI_GETCLIENTAREAANIMATION

    assert _SPI_GETCLIENTAREAANIMATION == 0x1042
    assert _SPI_GETCLIENTAREAANIMATION not in (0x0049, 0x004B)
