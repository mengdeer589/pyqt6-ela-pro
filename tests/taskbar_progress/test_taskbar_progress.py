"""Tests for taskbar_progress module: ElaTaskbarProgress（comtypes ITaskbarList3 实现）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro import taskbar_progress as tp
from pyqt6_ela_pro.taskbar_progress import (
    _TBPF_ERROR,
    _TBPF_NOPROGRESS,
    _TBPF_NORMAL,
    _TBPF_PAUSED,
    ElaTaskbarProgress,
)

NOOP_METHODS = [
    "setRange",
    "setValue",
    "show",
    "pause",
    "resume",
    "stop",
    "reset",
    "hide",
]


class FakeTaskbar:
    """记录 ``SetProgressState`` / ``SetProgressValue`` 调用。"""

    def __init__(self, fail: bool = False) -> None:
        self.states: list = []
        self.values: list = []
        self.fail = fail

    def SetProgressState(self, hwnd, state):  # noqa: N802 - COM 命名
        if self.fail:
            raise OSError("taskbar gone")
        self.states.append((hwnd, state))

    def SetProgressValue(self, hwnd, completed, total):  # noqa: N802 - COM 命名
        if self.fail:
            raise OSError("taskbar gone")
        self.values.append((hwnd, completed, total))


class FakeHandle:
    def __init__(self, win_id: int = 4242) -> None:
        self._win_id = win_id

    def winId(self) -> int:  # noqa: N802 - Qt 命名
        return self._win_id


def _collect(signal) -> list:
    got: list = []
    signal.connect(got.append)
    return got


@pytest.fixture
def window(make):
    return make(QWidget)


@pytest.fixture
def unavailable():
    """模拟「没有 comtypes / COM 创建失败」：不建对象、不挂接。"""
    with patch.object(tp, "_create_taskbar", return_value=(None, "测试不可用")):
        yield


@pytest.fixture
def attached(make, window):
    """已挂接状态：COM 层替换为 FakeTaskbar，hwnd 固定为 4242。"""
    fake = FakeTaskbar()
    with patch.object(tp, "_create_taskbar", return_value=(fake, "")):
        tb = make(ElaTaskbarProgress, window)
        tb._ensure_attached()
        tb._attach_handle(FakeHandle())
    return tb, fake


def test_module_imports():
    assert ElaTaskbarProgress is not None
    assert tp._TBPF_NORMAL == 0x2


@pytest.mark.parametrize(
    "signal_name",
    ["valueChanged", "pausedChanged", "stoppedChanged", "visibilityChanged"],
)
def test_declares_signal(signal_name):
    assert isinstance(getattr(ElaTaskbarProgress, signal_name), pyqtSignal)


def test_has_on_window_handle_created_method():
    assert hasattr(ElaTaskbarProgress, "_on_window_handle_created")


def test_initialization_stores_window(attached, window):
    tb, _ = attached
    assert tb._window is window


@pytest.mark.parametrize(
    ("attr", "expected"),
    [
        ("_taskbar", None),
        ("_hwnd", None),
        ("_attach_timer", None),
        ("_unavailable", False),
        ("_visible", False),
    ],
)
def test_initial_state_before_attachment(make, window, attr, expected):
    tb = make(ElaTaskbarProgress, window)
    assert getattr(tb, attr) == expected


@pytest.mark.parametrize(
    ("prop", "expected"),
    [
        ("value", 0),
        ("minimum", 0),
        ("maximum", 0),
        ("isPaused", False),
        ("isVisible", False),
        ("isStopped", False),
    ],
)
def test_property_defaults(make, window, prop, expected):
    tb = make(ElaTaskbarProgress, window)
    assert getattr(tb, prop) == expected


@pytest.mark.parametrize("method", NOOP_METHODS)
def test_public_methods_create_nothing_when_unavailable(
    make, window, unavailable, method
):
    """COM 不可用时不建对象、不起轮询定时器（空操作可断言）。

    「未改动状态就不碰 COM」的早退路径（同值 setValue / 未暂停 resume / 已隐藏
    hide）连 ``_ensure_attached`` 都不会进 —— 所以这里只钉「什么都没创建」。
    """
    tb = make(ElaTaskbarProgress, window)
    if method == "setRange":
        tb.setRange(0, 100)
    elif method == "setValue":
        tb.setValue(50)
    else:
        getattr(tb, method)()

    assert tb._taskbar is None
    assert tb._hwnd is None
    assert tb._attach_timer is None


@pytest.mark.parametrize("method", ["setRange", "show", "stop"])
def test_attach_methods_mark_unavailable(make, window, unavailable, method):
    """真正需要挂接的入口在 COM 创建失败后要记住「不可用」，避免每次重试。"""
    tb = make(ElaTaskbarProgress, window)
    if method == "setRange":
        tb.setRange(0, 100)
    else:
        getattr(tb, method)()

    assert tb._unavailable is True
    assert tb._taskbar is None


def test_ensure_attached_noop_when_window_is_none(make, unavailable):
    tb = make(ElaTaskbarProgress, None)
    tb._ensure_attached()
    assert tb._taskbar is None
    assert tb._attach_timer is None


def test_ensure_attached_without_handle_starts_polling(make, window):
    """回归：QWidget 没有 windowHandleChanged 信号。

    窗口 show() 之前调 setter 不能抛 AttributeError，改用轮询重试挂接。
    """
    with patch.object(tp, "_create_taskbar", return_value=(FakeTaskbar(), "")):
        tb = make(ElaTaskbarProgress, window)
        tb.setRange(0, 100)
        tb.setValue(5)

        assert tb._hwnd is None
        assert tb._attach_timer is not None
        assert tb._attach_timer.isActive() is True

        tb.deleteLater()


def test_on_window_handle_created_attaches_and_stops_polling(make, window):
    with patch.object(tp, "_create_taskbar", return_value=(FakeTaskbar(), "")):
        tb = make(ElaTaskbarProgress, window)
        tb.setRange(0, 100)
        tb.setValue(5)
        window.windowHandle = lambda: FakeHandle()

        tb._on_window_handle_created()

        assert tb._hwnd == 4242
        assert tb._attach_timer.isActive() is False

        tb.deleteLater()


def test_attach_handle_pushes_current_state(attached, window):
    tb, fake = attached
    tb.setRange(0, 100)
    tb.setValue(30)
    tb.show()

    assert fake.states[0] == (4242, _TBPF_NOPROGRESS) or fake.states
    assert (4242, _TBPF_NORMAL) in fake.states
    assert (4242, 30, 100) in fake.values


def test_set_value_emits_and_clamps(attached):
    tb, fake = attached
    tb.setRange(0, 100)
    tb.show()  # 进度值只在可见时推给任务栏

    changes = _collect(tb.valueChanged)
    tb.setValue(50)
    tb.setValue(50)  # 同值不重复发
    tb.setValue(999)  # 夹到 max
    tb.setValue(-5)  # 夹到 min

    assert changes == [50, 100, 0]
    assert (4242, 50, 100) in fake.values


def test_set_range_normalizes_reversed_bounds(attached):
    tb, _ = attached
    tb.setRange(100, 10)
    assert tb.minimum == 10
    assert tb.maximum == 10


def test_set_range_keeps_value_in_bounds(attached):
    tb, _ = attached
    tb.setRange(0, 100)
    tb.setValue(80)
    tb.setRange(0, 50)
    assert tb.value == 50


def test_show_hide_visibility_signal(attached):
    tb, fake = attached
    visible = _collect(tb.visibilityChanged)

    tb.show()
    tb.hide()
    tb.hide()  # 重复隐藏不重复发

    assert visible == [True, False]
    assert tb.isVisible is False
    assert fake.states[-1] == (4242, _TBPF_NOPROGRESS)


def test_pause_resume(attached):
    tb, fake = attached
    paused = _collect(tb.pausedChanged)

    tb.pause()
    tb.pause()  # 重复暂停不重复发
    assert tb.isPaused is True
    assert (4242, _TBPF_PAUSED) in fake.states

    tb.resume()
    tb.resume()  # 未暂停时 resume 不重复发
    assert tb.isPaused is False
    assert paused == [True, False]


def test_stop(attached):
    tb, fake = attached
    stopped = _collect(tb.stoppedChanged)

    tb.stop()
    tb.stop()

    assert tb.isStopped is True
    assert (4242, _TBPF_ERROR) in fake.states
    assert stopped == [True]


def test_reset(attached):
    tb, _ = attached
    tb.setRange(0, 100)
    tb.setValue(60)
    tb.show()

    changes = _collect(tb.valueChanged)
    tb.reset()

    assert tb.value == 0
    assert tb.isVisible is False
    assert changes == [0]


def test_push_errors_are_swallowed(attached):
    tb, _ = attached
    tb._taskbar.fail = True

    tb.setRange(0, 100)
    tb.setValue(10)
    tb.show()  # 不得抛
    assert tb.isVisible is True


def test_delete_later_stops_timer(make, window):
    with patch.object(tp, "_create_taskbar", return_value=(FakeTaskbar(), "")):
        tb = make(ElaTaskbarProgress, window)
        tb.setRange(0, 100)
        tb.setValue(5)
        assert tb._attach_timer is not None

        tb.deleteLater()

        assert tb._attach_timer is None


class TestAvailability:
    """「静默失效」是历史 bug：不可用必须能查、能收信号、能打日志。"""

    def test_available_true_when_taskbar_created(self, make, window):
        with patch.object(tp, "_create_taskbar", return_value=(FakeTaskbar(), "")):
            tb = make(ElaTaskbarProgress, window)
            assert tb.available() is True
            assert tb.initialize() is True
            assert tb.unavailableReason() == ""
            assert tb.isUnavailable() is False

    def test_available_false_reports_reason_once(self, make, window):
        with patch.object(tp, "_create_taskbar", return_value=(None, "no comtypes")):
            tb = make(ElaTaskbarProgress, window)
            seen = []
            tb.unavailable.connect(seen.append)
            assert tb.available() is False
            assert tb.available() is False  # 第二次不再重复上报
        assert tb.unavailableReason() == "no comtypes"
        assert tb.isUnavailable() is True
        assert seen == ["no comtypes"]

    def test_unavailable_signal_is_pyqt_signal(self):
        assert isinstance(ElaTaskbarProgress.unavailable, pyqtSignal)

    def test_noop_methods_still_work_when_unavailable(self, make, window):
        with patch.object(tp, "_create_taskbar", return_value=(None, "nope")):
            tb = make(ElaTaskbarProgress, window)
            tb.setRange(0, 100)
            tb.setValue(50)
            tb.show()
            tb.pause()
            tb.resume()
            tb.stop()
            tb.reset()
            tb.hide()
        assert tb.isVisible is False


class TestAttachContract:
    """挂接的目标必须是**顶层窗口**的真实 HWND，且在窗口重建后重挂。"""

    def test_child_widget_resolves_top_level(self, make):
        parent = make(QWidget)
        child = make(QWidget, parent)
        parent.windowHandle = lambda: FakeHandle(777)
        with patch.object(tp, "_create_taskbar", return_value=(FakeTaskbar(), "")):
            tb = make(ElaTaskbarProgress, child)
            tb.setRange(0, 100)
        assert tb._hwnd == 777

    def test_reattach_when_hwnd_changes(self, make):
        window = make(QWidget)
        handle = FakeHandle(100)
        window.windowHandle = lambda: handle
        fake = FakeTaskbar()
        with patch.object(tp, "_create_taskbar", return_value=(fake, "")):
            tb = make(ElaTaskbarProgress, window)
            tb.setRange(0, 100)
            tb.show()
            assert tb._hwnd == 100

            handle._win_id = 200  # 窗口重建后 HWND 变了
            tb.setValue(10)

        assert tb._hwnd == 200
        assert fake.values[-1][0] == 200
        assert fake.states[-1] == (200, _TBPF_NORMAL)


@pytest.mark.skipif(not tp._COMTYPES_AVAILABLE, reason="comtypes 未安装（可选依赖）")
class TestInterfaceFallback:
    """先要 ITaskbarList4，失败再回退 ITaskbarList3（有的系统只认 v4 的 IID）。"""

    class _FakeCom:
        def HrInit(self) -> int:  # noqa: N802
            return 0

    def test_prefers_v4(self, monkeypatch):
        calls = []

        def fake_create(clsid, interface=None, clsctx=None):
            calls.append(interface.__name__)
            return self._FakeCom()

        monkeypatch.setattr(tp.comtypes, "CoCreateInstance", fake_create)
        taskbar, reason = tp._create_taskbar()
        assert taskbar is not None
        assert reason == ""
        assert calls == ["_ITaskbarList4"]

    def test_falls_back_to_v3(self, monkeypatch):
        calls = []

        def fake_create(clsid, interface=None, clsctx=None):
            calls.append(interface.__name__)
            if interface.__name__ == "_ITaskbarList4":
                raise OSError(0x80004002, "no interface")
            return self._FakeCom()

        monkeypatch.setattr(tp.comtypes, "CoCreateInstance", fake_create)
        taskbar, reason = tp._create_taskbar()
        assert taskbar is not None
        assert reason == ""
        assert calls == ["_ITaskbarList4", "_ITaskbarList3"]

    def test_all_fail_returns_reason(self, monkeypatch):
        def fake_create(clsid, interface=None, clsctx=None):
            exc = OSError("no interface")
            exc.winerror = 0x80004002
            raise exc

        monkeypatch.setattr(tp.comtypes, "CoCreateInstance", fake_create)
        taskbar, reason = tp._create_taskbar()
        assert taskbar is None
        assert "ITaskbarList4" in reason
        assert "ITaskbarList3" in reason
        assert "0x80004002" in reason
