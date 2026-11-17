"""ElaMouseMonitor 轮询状态机测试（注入假键状态 / 坐标，不产生真实输入）。"""

from __future__ import annotations

import ctypes
import sys

import pytest

from pyqt6_ela_pro.selection_assistant import _native
from pyqt6_ela_pro.selection_assistant._native import (
    _VK_LBUTTON,
    _VK_MBUTTON,
    _VK_RBUTTON,
    ElaMouseMonitor,
)


class _FakeInput:
    """假的键状态 + 光标位置（替换 monitor 的静态探测方法）。"""

    def __init__(self) -> None:
        self.point = (10, 20)
        self.left = False
        self.right = False
        self.middle = False

    def install(self, monitor: ElaMouseMonitor) -> None:
        monitor._cursor_pos = lambda: self.point
        monitor._key_down = lambda vk: {
            _VK_LBUTTON: self.left,
            _VK_RBUTTON: self.right,
            _VK_MBUTTON: self.middle,
        }.get(vk, False)


def _monitor(qapp):
    monitor = ElaMouseMonitor()
    fake = _FakeInput()
    fake.install(monitor)
    events = []
    monitor.leftPressed.connect(lambda pt: events.append(("down", pt)))
    monitor.leftReleased.connect(lambda down, up: events.append(("up", down, up)))
    monitor.otherPressed.connect(lambda pt: events.append(("other", pt)))
    return monitor, fake, events


class TestPolling:
    def test_press_and_release(self, qapp):
        monitor, fake, events = _monitor(qapp)
        fake.left = True
        monitor._poll()
        assert events == [("down", (10, 20))]
        fake.point = (40, 60)
        fake.left = False
        monitor._poll()
        assert events == [
            ("down", (10, 20)),
            ("up", (10, 20), (40, 60)),
        ]
        monitor.deleteLater()

    def test_no_change_produces_no_events(self, qapp):
        monitor, fake, events = _monitor(qapp)
        for _ in range(5):
            monitor._poll()
        assert events == []
        fake.left = True
        monitor._poll()
        monitor._poll()
        monitor._poll()
        assert events == [("down", (10, 20))]
        monitor.deleteLater()

    def test_right_and_middle_press(self, qapp):
        monitor, fake, events = _monitor(qapp)
        fake.right = True
        monitor._poll()
        fake.right = False
        fake.middle = True
        monitor._poll()
        monitor._poll()
        assert events == [("other", (10, 20)), ("other", (10, 20))]
        monitor.deleteLater()

    def test_release_without_press_uses_cursor_point(self, qapp):
        monitor, fake, events = _monitor(qapp)
        fake.left = True
        monitor._poll()
        fake.left = False
        fake.point = (5, 6)
        monitor._poll()
        assert events[-1] == ("up", (10, 20), (5, 6))
        monitor.deleteLater()

    def test_stop_resets_state(self, qapp):
        monitor, fake, events = _monitor(qapp)
        fake.left = True
        monitor._poll()
        monitor.stop()
        fake.left = True
        monitor._poll()
        assert events == [("down", (10, 20)), ("down", (10, 20))]
        monitor.deleteLater()

    def test_swapped_buttons_use_primary(self, qapp, monkeypatch):
        """系统交换主 / 次键后，物理右键才是「左键」（主键）。"""
        from pyqt6_ela_pro.selection_assistant import _native

        monkeypatch.setattr(_native, "_swap_buttons", lambda: True)
        monitor = ElaMouseMonitor()
        fake = _FakeInput()
        fake.install(monitor)
        events = []
        monitor.leftPressed.connect(lambda pt: events.append(("down", pt)))
        fake.right = True  # 物理右键 = 主键
        monitor._poll()
        assert events == [("down", (10, 20))]
        monitor.deleteLater()


class TestWindowRect:
    def test_uses_top_level_rect_for_border_check(self, monkeypatch):
        """``WindowFromPoint`` 返回的是子窗口；边框判断必须换成顶层窗口矩形。"""
        if sys.platform != "win32":  # pragma: no cover - 平台分支
            pytest.skip("仅 Windows")

        calls = []

        class _FakeUser32:
            def WindowFromPoint(self, point):  # noqa: N802
                calls.append(("WindowFromPoint", point.x, point.y))
                return 111

            def GetAncestor(self, hwnd, flags):  # noqa: N802
                calls.append(("GetAncestor", hwnd, flags))
                return 222

            def GetWindowRect(self, hwnd, ptr):  # noqa: N802
                calls.append(("GetWindowRect", hwnd))
                rect = ctypes.cast(ptr, ctypes.POINTER(_native._RECT)).contents
                rect.left, rect.top, rect.right, rect.bottom = 10, 20, 30, 40
                return 1

        monkeypatch.setattr(_native, "_user32", _FakeUser32())
        assert _native.window_rect_at(5, 6) == (10, 20, 30, 40)
        assert ("GetAncestor", 111, _native._GA_ROOT) in calls
        assert ("GetWindowRect", 222) in calls


class TestLifecycle:
    def test_start_stop_and_interval(self, qapp):
        monitor = ElaMouseMonitor()
        assert monitor.isRunning() is False
        assert monitor.pollMs() == 15
        monitor.setPollMs(30)
        assert monitor.pollMs() == 30
        if sys.platform != "win32":  # pragma: no cover - 平台分支
            with pytest.raises(RuntimeError):
                monitor.start()
        else:
            assert monitor.start() is True
            assert monitor.isRunning() is True
            assert monitor.start() is True
            monitor.stop()
            assert monitor.isRunning() is False
            monitor.stop()
        monitor.deleteLater()
