"""桶 B（持续动效）与桶 A2（手搓过渡）在 Reduced/Disabled 下的行为。

核心不变量：**「停掉」不等于「不画」**。

* 旋转 / 流动类：角度或相位冻结在当前值 —— 冻结即静态态，不需要额外摆姿态。
* **相位类必须显式摆好**，否则会停在「不可见」上：流式光标停在 phase 0 等于
  光标凭空消失（用户以为流式卡住）；呼吸状态点停在低相位是个若隐若现的灰点。
  这两条靠 ``start_id_loop(on_stop=...)`` 钩子保证。
* 桶 A2 的手搓过渡（``QTimer`` 驱动、没走 ``QAbstractAnimation``）被 snap 时
  **收尾不能丢** —— splash 的「关自己 + 激活主窗口」、gauge 的「落到目标值」。
"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget

import pyqt6_ela_pro._motion as _motion

from pyqt6_ela_pro._motion import (
    ElaMotionKindType,
    ElaMotionModeType,
    idle_loop_running,
    motion,
    start_idle_loop,
    start_transition_timer,
)


@pytest.fixture
def reduced_motion():
    previous = motion.mode()
    motion.setMode(ElaMotionModeType.Reduced)
    yield
    motion.setMode(previous)


@pytest.fixture
def disabled_motion():
    previous = motion.mode()
    motion.setMode(ElaMotionModeType.Disabled)
    yield
    motion.setMode(previous)


def _timer(qapp) -> QTimer:
    t = QTimer()
    t.setInterval(16)
    return t


# ── start_idle_loop ─────────────────────────────────────────


class TestStartIdleLoop:
    def test_full_starts(self, qapp, motion_full):
        t = _timer(qapp)
        assert start_idle_loop(t, 50) is True
        assert t.isActive()
        assert t.interval() == 50

    @pytest.mark.parametrize("mode", [ElaMotionModeType.Reduced, ElaMotionModeType.Disabled])
    def test_reduced_and_disabled_stop(self, qapp, mode):
        previous = motion.mode()
        motion.setMode(mode)
        try:
            t = _timer(qapp)
            assert start_idle_loop(t, 50) is False
            assert t.isActive() is False
        finally:
            motion.setMode(previous)

    def test_local_disabled_stops_even_in_full(self, qapp, motion_full):
        t = _timer(qapp)
        assert start_idle_loop(t, 50, local_enabled=False) is False
        assert t.isActive() is False

    def test_stops_rather_than_slows(self, qapp, reduced_motion):
        """Reduced 下持续动效是**停掉**，不是放慢 —— 转得更慢的圈看起来像卡住。"""
        t = _timer(qapp)
        start_idle_loop(t, 600)
        assert t.isActive() is False
        # 用 600ms 才能与 Reduced 的 50ms 上限区分开：间隔保持原值（没被缩放），
        # 该做的是不启动。
        assert t.interval() == 600

    def test_interval_is_written_even_when_stopped(self, qapp, reduced_motion):
        """停掉时也必须写入间隔。

        少了这步，间隔会停在 0，之后任何一处直接 ``timer.start()`` 就是 0ms 空转。
        """
        t = _timer(qapp)
        assert t.interval() == 16
        start_idle_loop(t, 500)
        assert t.interval() == 500

    def test_on_stop_called_when_blocked(self, qapp, reduced_motion):
        hits: list[int] = []
        t = _timer(qapp)
        start_idle_loop(t, 50, on_stop=lambda: hits.append(1))
        assert hits == [1], "该停时必须调用摆静态基态的钩子"

    def test_on_stop_called_when_was_running(self, qapp, motion_full):
        """运行中切到 Reduced：停循环 + 调 on_stop。"""
        hits: list[int] = []
        t = _timer(qapp)
        start_idle_loop(t, 50, on_stop=lambda: hits.append(1))
        assert hits == []
        motion.setMode(ElaMotionModeType.Reduced)
        try:
            assert t.isActive() is False
            assert hits == [1]
        finally:
            motion.setMode(ElaMotionModeType.Full)

    def test_on_stop_not_called_when_never_running(self, qapp, reduced_motion):
        """本来就没在跑 → 无需重画，不该调 on_stop。"""
        hits: list[int] = []
        t = _timer(qapp)
        start_idle_loop(t, 50, on_stop=lambda: hits.append(1))
        assert hits == [1], "启动时该停会调一次"
        hits.clear()
        motion.setMode(ElaMotionModeType.Disabled)
        try:
            assert hits == [], "本来没在跑，切策略不该再触发重画"
        finally:
            motion.setMode(ElaMotionModeType.Full)

    def test_on_stop_exception_does_not_escape(self, qapp, reduced_motion):
        """on_stop 跑在 modeChanged 的 Qt 回调链上，抛异常就是 0xC0000409。"""

        def boom() -> None:
            raise RuntimeError("boom")

        t = _timer(qapp)
        start_idle_loop(t, 50, on_stop=boom)  # 不应抛出

    def test_mode_change_does_not_crash_on_deleted_timer(self, qapp, motion_full):
        """控件析构后定时器的 C++ 对象可能已没了 —— modeChanged 不能踩它。"""

        host = QWidget()
        t = QTimer(host)
        t.timeout.connect(lambda: None)
        start_idle_loop(t, 50)
        host.deleteLater()
        from PyQt6 import sip  # noqa: F401

        from _qthelpers import wait_until

        wait_until(qapp, lambda: sip.isdeleted(host), timeout_ms=500, use_qwait=True)
        motion.setMode(ElaMotionModeType.Reduced)  # 不应抛出
        motion.setMode(ElaMotionModeType.Full)

    def test_idle_loop_running_handles_deleted(self, qapp):

        host = QWidget()
        t = QTimer(host)
        start_idle_loop(t, 50)
        assert idle_loop_running(t) is True
        host.deleteLater()
        from _qthelpers import wait_until

        wait_until(qapp, lambda: sip.isdeleted(host), timeout_ms=500, use_qwait=True)
        assert idle_loop_running(t) is False

    def test_repeated_registration_does_not_duplicate(self, qapp, motion_full):
        """同一个定时器重复 start_idle_loop 只登记一次（否则 on_stop 会跑多遍）。"""
        hits: list[int] = []
        t = _timer(qapp)
        for _ in range(4):
            start_idle_loop(t, 50, on_stop=lambda: hits.append(1))
        motion.setMode(ElaMotionModeType.Reduced)
        try:
            assert len(hits) == 1
        finally:
            motion.setMode(ElaMotionModeType.Full)

    def test_registry_does_not_pin_owner(self, qapp, motion_full):
        """登记表**不能**强引用住 ``on_stop`` 的宿主（bound method 会钉住整个控件）。

        这是一条真实泄漏：``on_stop`` 存进模块级 ``_IDLE_LOOPS`` 时形成
        ``全局 → bound method → 控件 → _caret_timer → weakref 的 target 活着
        → 永不剪枝`` 的闭环。实测 20 个跑过 ``beginStream()`` 的
        ``ElaMarkdownViewer`` 在正常销毁路径后 20/20 全被钉住、Python 堆多出
        约 18.9 MB；聊天里每条助手消息都会 ``beginStream()``，所以无界增长。
        """
        import gc
        import weakref

        from PyQt6.QtCore import QCoreApplication, QEvent

        class Owner(QWidget):
            def __init__(self):
                super().__init__()
                self.timer = QTimer(self)
                self.timer.timeout.connect(self._tick)
                # 够大，让「被钉住」在存活判定之外也肉眼可见
                self.payload = ["x" * 2000] * 20

            def _tick(self):
                pass

            def on_stop(self):
                self.payload.clear()

        refs = []
        for _ in range(20):
            owner = Owner()
            owner.show()
            qapp.processEvents()
            start_idle_loop(owner.timer, 50, on_stop=owner.on_stop)
            owner.timer.start()
            refs.append(weakref.ref(owner))
            owner.close()
            owner.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            qapp.processEvents()
        del owner
        gc.collect()
        gc.collect()

        retained = [r for r in refs if r() is not None]
        assert not retained, f"{len(retained)}/20 个宿主被 _IDLE_LOOPS 钉住，未被回收"

    def test_pruned_entries_release_on_stop_hook(self, qapp, motion_full):
        """死条目被剪掉时，它挂的 ``on_stop`` 也随之释放（不留悬挂引用）。"""
        import gc
        import weakref

        from PyQt6.QtCore import QCoreApplication, QEvent

        class Owner(QWidget):
            def __init__(self):
                super().__init__()
                self.timer = QTimer(self)
                self.timer.timeout.connect(lambda: None)

            def on_stop(self):
                pass

        owner = Owner()
        start_idle_loop(owner.timer, 50, on_stop=owner.on_stop)
        ref = weakref.ref(owner)
        owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        del owner
        gc.collect()
        assert ref() is None
        # 再登记一次会顺带剪枝；剪完后不得还挂着任何 dead 条目
        other = _timer(qapp)
        start_idle_loop(other, 50)
        live = [entry for entry in _motion._IDLE_LOOPS if entry[0]() is not None]
        assert len(live) == len(_motion._IDLE_LOOPS)


# ── start_transition_timer（桶 A2） ──────────────────────────


class TestStartTransitionTimer:
    def test_full_starts(self, qapp, motion_full):
        t = _timer(qapp)
        assert start_transition_timer(t) is True
        assert t.isActive()

    def test_disabled_stops_and_caller_must_settle(self, qapp, disabled_motion):
        """Disabled：返回 False，**调用方负责自己落终值**（QTimer 不会替它判断跑完）。"""
        t = _timer(qapp)
        assert start_transition_timer(t) is False
        assert t.isActive() is False

    def test_reduced_still_runs_transition(self, qapp, reduced_motion):
        """Reduced 保留过渡（只是短）—— 这正是双轴的分野：过渡压时长、持续动效停止。"""
        t = _timer(qapp)
        assert start_transition_timer(t) is True
        assert t.isActive() is True

    def test_rejects_non_timer(self, qapp, motion_full):
        with pytest.raises(TypeError):
            start_transition_timer(object())

    def test_transition_kind_is_preserved_under_reduced(self, qapp, reduced_motion):
        """过渡与持续动效的分野：Reduced 压过渡但杀持续动效。"""
        assert motion.shouldAnimate(ElaMotionKindType.Transition) is True
        assert motion.shouldAnimate(ElaMotionKindType.Continuous) is False


# ── 真实组件的静态基态 ──────────────────────────────────────


class TestRealIdleLoops:
    def test_status_dot_stops_but_stays_visible(self, qapp, reduced_motion):
        """呼吸点停掉后必须画**满不透明度**的静态点。

        停在低相位就是个若隐若现的灰点，用户看不出「正在生成」。
        """
        from pyqt6_ela_pro.chat.blocks import _StatusDot

        dot = _StatusDot()
        dot.setActive(True)
        assert dot._timer.isActive() is False, "Reduced 下不该启动呼吸循环"
        assert dot._phase is False, "静态基态 = 亮着"

    def test_spinner_arc_freezes_rather_than_disappears(self, qapp, reduced_motion):
        """旋转类：角度冻结即静态基态（仍是一段可见的弧）。"""
        from pyqt6_ela_pro.blueprint._spinner import SpinnerArc

        arc = SpinnerArc(size=24)
        assert arc.isRunning() is False
        assert arc._angle == 0.0, "冻结在起始角度，仍会被画出来"

    def test_stream_caret_stays_visible(self, qapp, reduced_motion):
        """回归：光标闪烁停掉后必须**留在可见态**。

        停在 phase 0 等于把光标删掉，用户会以为流式卡住了。这是「停掉 ≠ 不画」
        最容易踩的一条。
        """
        from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

        viewer = ElaMarkdownViewer()
        try:
            viewer.beginStream()
            assert viewer._caret_timer.isActive() is False, "Reduced 下不该闪"
            assert viewer._caret_visible is True, "静态基态必须是亮着的光标"
        finally:
            viewer.deleteLater()
            qapp.processEvents()

    def test_tooltip_spinner_stops(self, qapp, reduced_motion):
        from pyqt6_ela_pro.tooltips import (
            TOOLTIP_ROTATE_TIMER_INTERVAL,
            ElaStateToolTip,
        )

        tip = ElaStateToolTip("加载中")
        try:
            tip.show()
            qapp.processEvents()
            assert tip._rotateTimer.isActive() is False
            assert tip._rotateTimer.interval() == TOOLTIP_ROTATE_TIMER_INTERVAL
        finally:
            tip.deleteLater()
            qapp.processEvents()

    def test_chart_loading_spinner_stops(self, qapp, reduced_motion):
        from pyqt6_ela_pro.charts.core import ElaChartWidget

        chart = ElaChartWidget()
        try:
            chart.showLoading()
            assert chart._spinner_timer.isActive() is False
            assert chart._loading is True, "遮罩与文字照常显示，只是不再转"
        finally:
            chart.hideLoading()
            chart.deleteLater()
            qapp.processEvents()


class TestHandRolledTransitions:
    def test_gauge_settles_to_target_under_disabled(self, qapp, disabled_motion):
        """桶 A2：gauge 的插值被 snap 时必须**直接落到目标值**。"""
        from pyqt6_ela_pro.ela_dashboard_gauge import ElaDashboardGauge

        gauge = ElaDashboardGauge()
        try:
            gauge.setMinimum(0)
            gauge.setMaximum(100)
            gauge.setValue(0)
            gauge.setValue(80)
            assert gauge._anim_timer.isActive() is False
            assert gauge._animated_value == pytest.approx(80)
        finally:
            gauge.deleteLater()
            qapp.processEvents()

    def test_spotlight_fade_in_lands_at_one(self, qapp, disabled_motion):
        from pyqt6_ela_pro.ela_spotlight import ElaSpotlight

        spot = ElaSpotlight()
        try:
            spot._startFadeIn()
            assert spot._fade_timer.isActive() is False
            assert spot._opacity == 1.0
        finally:
            spot.deleteLater()
            qapp.processEvents()

    def test_splash_finish_still_hands_over_to_main_window(self, qapp, disabled_motion):
        """桶 A2 最关键的一条：snap 后**收尾不能丢**。

        splash 的收尾是「关自己 + show/raise/activate 主窗口」—— 这是一条完整的
        应用交接流程，丢了就等于应用永远停在启动屏。
        """
        from pyqt6_ela_pro.splash_screen import ElaSplashScreen

        closed: list[int] = []
        main = QWidget()
        splash = ElaSplashScreen()
        splash.closed.connect(lambda: closed.append(1))
        splash.show()
        qapp.processEvents()
        splash.finish(main)
        assert closed == [1], "收尾必须同步发生"
        assert splash._fade_timer.isActive() is False
        assert main.isVisible() is True, "主窗口必须被顶到前台"
        for w in (splash, main):
            w.deleteLater()
        qapp.processEvents()
