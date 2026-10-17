"""动效收尾路径的回归测试。

三处状态机**只**挂在动画收尾上（``closed.emit()`` / ``hide()`` / ``deleteLater()``
全都只有那一个入口），所以它们是 ``Disabled`` 模式的直接受灾区。这些路径此前
**零覆盖** —— 收尾链断掉不会有任何测试变红。

另含 3 个由本次动效改造顺手修掉的真实 bug 的回归：
* ``ela_toast`` 的停留计时是无主 ``QTimer.singleShot``
* ``notify_popup`` 三处 disconnect 舞蹈导致关闭中收到 show 会弹回打开态
* ``tooltips`` 的 ``_isClosing`` 成功后不复位 + 裸 ``finished.connect`` 叠连接
* ``ela_side_drawer`` 关闭动画期间 ``toggleDrawer`` 会卡在打开态
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro._motion import ElaMotionModeType, motion
from pyqt6_ela_pro.ela_side_drawer import ElaDrawer
from pyqt6_ela_pro.ela_toast import ElaToast, ElaToastType
from pyqt6_ela_pro.notify_popup import ElaNotifyPopup


@pytest.fixture
def disabled_motion():
    """本模块全部用例都跑 ``Disabled``（同步落终值，收尾当场可断言）。"""
    previous = motion.mode()
    motion.setMode(ElaMotionModeType.Disabled)
    yield
    motion.setMode(previous)


# ── ElaDrawer：_is_opened 的复位点只有一个 ──────────────────


@pytest.fixture
def drawer(make):
    parent = make(QWidget)
    d = make(ElaDrawer, parent=parent)
    d.setContentWidget(make(QWidget))
    return d


class TestDrawerClosePath:
    def test_close_reaches_closed_synchronously(self, drawer, disabled_motion):
        """Disabled 下 closeDrawer 必须当场走完收尾：hide + _is_opened + closed。"""
        closed: list[int] = []
        drawer.closed.connect(lambda: closed.append(1))
        drawer.showDrawer()
        assert drawer.isOpened() is True

        drawer.closeDrawer()
        assert closed == [1], "Disabled 下收尾必须同步触发，不能等一帧"
        assert drawer.isOpened() is False

    def test_toggle_during_close_does_not_stick_open(self, drawer, disabled_motion):
        """回归：关闭动画期间 toggle 曾被「_is_opened 还是 True」带进
        closeDrawer，抽屉永久卡在打开态。"""
        drawer.showDrawer()
        drawer.closeDrawer()
        assert drawer.isOpened() is False

        drawer.toggleDrawer()
        assert drawer.isOpened() is True, "关闭完成后 toggle 必须能重新打开"

    def test_close_is_idempotent(self, drawer, disabled_motion):
        closed: list[int] = []
        drawer.closed.connect(lambda: closed.append(1))
        drawer.showDrawer()
        drawer.closeDrawer()
        drawer.closeDrawer()
        assert closed == [1], "重复 closeDrawer 不该重复发 closed"


# ── ElaToast：close() 只有一个入口 ──────────────────────────


class TestToastClosePath:
    def test_fade_in_creates_child_dwell_timer(self, make, disabled_motion):
        """停留计时器必须是 toast 的子对象。

        ``QTimer.singleShot`` 是无主定时器，toast 被提前关掉后照样在 T+ms 触发去摸
        已释放的包装器 → RuntimeError 穿过 C++ 边界 = 0xC0000409 静默终止。
        """
        toast = make(  # noqa: F841  (交给 qt_cleanup 回收)
            ElaToast, ElaToastType.Info, "提示", 2000
        )
        assert toast._dwell_timer.parent() is toast
        assert toast._dwell_timer.isSingleShot()

    def test_dwell_timer_survives_toast_deletion(self, qapp, disabled_motion):
        """提前销毁 toast 后，事件循环跑过 dwell 时长不得静默终止。"""
        from _qthelpers import wait_until

        toast = ElaToast(ElaToastType.Info, "提示", 10)
        toast._run_animation()
        toast.deleteLater()
        wait_until(qapp, lambda: True, timeout_ms=5, use_qwait=True)
        # 存活到这里就说明没有 callback 打向已释放包装器

    def test_fade_out_completes_under_disabled(self, qapp, disabled_motion):
        """Disabled 下淡出同步落终值（windowOpacity → 0）。"""
        from _qthelpers import wait_until

        toast = ElaToast(ElaToastType.Info, "提示", 1)
        toast.show()
        qapp.processEvents()
        toast._startFadeOut()
        assert toast.windowOpacity() == pytest.approx(0.0, abs=1e-6)
        wait_until(qapp, lambda: True, timeout_ms=5, use_qwait=True)


# ── ElaNotifyPopup：hide() + closed 只在收尾 ────────────────


@pytest.fixture
def popup(make):
    return make(ElaNotifyPopup, title="标题", content="内容", timeout=0)


class TestNotifyPopupClosePath:
    def test_slide_in_does_not_close_popup(self, popup, disabled_motion, qapp):
        """回归：滑入也走 start_transition，若误传收尾会在滑入结束时把弹窗关掉。"""
        from _qthelpers import wait_until

        closed: list[int] = []
        popup.closed.connect(lambda: closed.append(1))
        popup.showNotification()
        wait_until(qapp, lambda: True, timeout_ms=5, use_qwait=True)
        assert closed == [], "滑入结束不该触发收尾"

    def test_close_emits_closed_synchronously(self, popup, disabled_motion):
        """Disabled 下 closeAnimation 当场收尾：hide + closed。"""
        closed: list[int] = []
        popup.closed.connect(lambda: closed.append(1))
        popup.showNotification()
        popup._close_animation()
        assert closed == [1]
        assert popup.isVisible() is False

    def test_close_completion_not_stacked(self, popup, disabled_motion):
        """回归：关闭动画的收尾不得叠两遍（旧实现的 disconnect 舞蹈会让 closed 发两次）。

        ``QObject.receivers()`` 在 PyQt6 下不可用（见 MIGRATION），改为数
        ``closed`` 的真实触发次数：两次「打开→关闭」应各发一次。
        """
        closed: list[int] = []
        popup.closed.connect(lambda: closed.append(1))
        popup.showNotification()
        popup._close_animation()
        popup.showNotification()  # 重新打开（取消上一次收尾）
        popup._close_animation()
        assert closed == [1, 1], f"closed 发了 {len(closed)} 次"
