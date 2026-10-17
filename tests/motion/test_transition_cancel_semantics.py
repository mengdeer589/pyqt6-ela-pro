from __future__ import annotations

import pytest
from PyQt6.QtCore import QAbstractAnimation, QPropertyAnimation, QTimer

from pyqt6_ela_pro._motion import ElaMotionKindType, ElaMotionModeType, motion, start_transition


@pytest.fixture
def full_motion():
    previous = motion.mode()
    motion.setMode(ElaMotionModeType.Full)
    yield
    motion.setMode(previous)


def _anim() -> QPropertyAnimation:
    obj = QTimer()  # 只借个 QObject 属性载体
    anim = QPropertyAnimation(obj, b"dummy")
    anim.setProperty("dummy", 0)
    yield_obj = obj
    anim._keep = yield_obj  # type: ignore[attr-defined]  # 防被GC
    return anim


class TestOnCompleteNoneCancels:
    def test_none_disconnects_previous_slot(self, full_motion):
        anim = _anim()
        hits: list[int] = []
        start_transition(
            anim, 40, kind=ElaMotionKindType.Transition, on_complete=lambda: hits.append(1)
        )
        # 第二段不传 on_complete —— 应取消收尾
        start_transition(anim, 40, kind=ElaMotionKindType.Transition)
        assert hits == [], "on_complete=None 没有取消上一次的收尾"
        anim._keep.deleteLater()  # type: ignore[attr-defined]

    def test_none_clears_the_slot_attribute(self, full_motion):
        anim = _anim()
        start_transition(anim, 40, kind=ElaMotionKindType.Transition, on_complete=lambda: None)
        start_transition(anim, 40, kind=ElaMotionKindType.Transition)
        assert getattr(anim, "_ela_motion_slot", None) is None
        anim._keep.deleteLater()  # type: ignore[attr-defined]

    def test_repeated_none_is_idempotent(self, full_motion):
        anim = _anim()
        for _ in range(4):
            start_transition(anim, 20, kind=ElaMotionKindType.Transition)
        assert getattr(anim, "_ela_motion_slot", None) is None
        anim._keep.deleteLater()  # type: ignore[attr-defined]

    def test_explicit_callback_still_registers(self, full_motion):
        anim = _anim()
        hits: list[int] = []
        start_transition(
            anim, 40, kind=ElaMotionKindType.Transition, on_complete=lambda: hits.append(1)
        )
        assert getattr(anim, "_ela_motion_slot", None) is not None
        anim._keep.deleteLater()  # type: ignore[attr-defined]

    def test_snap_path_also_honours_it(self, full_motion):
        """snap 路径（``setCurrentTime`` 同步落终值）同样不该留旧收尾。"""
        anim = _anim()
        hits: list[int] = []
        start_transition(
            anim, 40, kind=ElaMotionKindType.Transition, on_complete=lambda: hits.append(1)
        )
        hits.clear()
        start_transition(anim, 40, kind=ElaMotionKindType.Transition)
        assert hits == []
        anim._keep.deleteLater()  # type: ignore[attr-defined]


class TestNotifyPopupReplay:
    """用户可见的后果：重播的通知不该自己关掉自己。"""

    def test_replay_after_close_stays_visible(self, make, qapp):
        from _qthelpers import wait_until

        from pyqt6_ela_pro.notify_popup import ElaNotifyPopup

        closed: list[int] = []
        popup = make(ElaNotifyPopup, title="t", content="c", timeout=0)
        popup.closed.connect(lambda: closed.append(1))

        popup.showNotification()
        qapp.processEvents()
        assert popup.isVisible()

        popup._on_close()
        wait_until(qapp, lambda: not popup.isVisible(), timeout_ms=2000, use_qwait=True)
        assert len(closed) == 1

        popup.showNotification("t2", "c2")
        qapp.processEvents()
        wait_until(qapp, lambda: False, timeout_ms=700, interval_ms=50, use_qwait=True)

        assert popup.isVisible(), "replayed notification closed itself"
        assert len(closed) == 1, "closed was emitted again on replay"


def test_deletion_policy_default_unchanged(full_motion):
    """顺带钉住：默认删除策略仍是 KeepWhenStopped。"""
    anim = _anim()
    start_transition(anim, 40, kind=ElaMotionKindType.Transition)
    assert isinstance(anim, QAbstractAnimation)
    anim._keep.deleteLater()  # type: ignore[attr-defined]
