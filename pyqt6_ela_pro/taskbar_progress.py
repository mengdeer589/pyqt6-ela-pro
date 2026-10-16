"""Windows 任务栏进度条组件。

Qt6 里没有 ``QtWinExtras``（``QWinTaskbarButton`` / ``QWinTaskbarProgress`` 已随
Qt5 退役），本组件改为直接调 COM 的 ``ITaskbarList3``，在任务栏图标上展示进度条
（正常 / 暂停 / 错误 / 不确定 / 隐藏）。

非 Windows 或缺少 ``comtypes``（``[all]`` extra）时所有方法为空操作。

用法::

    from pyqt6_ela_pro import ElaTaskbarProgress

    tb = ElaTaskbarProgress(my_window)
    tb.setRange(0, 100)
    tb.setValue(0)
    tb.show()
    for i in range(100):
        tb.setValue(i)
        # ...
    tb.hide()

:param window: 要关联进度的窗口控件
:type window: QWidget
"""

from __future__ import annotations

import sys
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

try:  # comtypes 是可选依赖（[all] extra），缺失时整组件退化为空操作
    import comtypes
    import comtypes.client
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
    from ctypes import c_int, c_ulonglong, c_void_p

    class _ITaskbarList3(IUnknown):
        """``ITaskbarList3`` 的最小 vtable（声明到 ``SetProgressState`` 为止）。

        COM 的 vtable 按顺序绑定，所以前面六个用不到的方法也必须照样声明。
        """

        _iid_ = GUID("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEA84}")
        _methods_ = [
            COMMETHOD([], HRESULT, "HrInit"),
            COMMETHOD([], HRESULT, "AddTab", (["in"], c_void_p, "hwnd")),
            COMMETHOD([], HRESULT, "DeleteTab", (["in"], c_void_p, "hwnd")),
            COMMETHOD([], HRESULT, "ActivateTab", (["in"], c_void_p, "hwnd")),
            COMMETHOD([], HRESULT, "SetActiveAlt", (["in"], c_void_p, "hwnd")),
            COMMETHOD(
                [],
                HRESULT,
                "MarkFullscreenWindow",
                (["in"], c_void_p, "hwnd"),
                (["in"], c_int, "fFullscreen"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "SetProgressValue",
                (["in"], c_void_p, "hwnd"),
                (["in"], c_ulonglong, "ullCompleted"),
                (["in"], c_ulonglong, "ullTotal"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "SetProgressState",
                (["in"], c_void_p, "hwnd"),
                (["in"], c_int, "tbpFlags"),
            ),
        ]

    _COMTYPES_AVAILABLE = True
except ImportError:  # pragma: no cover - 非 Windows / 未装 comtypes
    comtypes = None  # type: ignore[assignment]
    _COMTYPES_AVAILABLE = False


#: ``TBPFLAG``（``shellapi.h``）
_TBPF_NOPROGRESS = 0x0
_TBPF_INDETERMINATE = 0x1
_TBPF_NORMAL = 0x2
_TBPF_ERROR = 0x4
_TBPF_PAUSED = 0x8

_CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"


def _create_taskbar():
    """创建并初始化 ``ITaskbarList3``；不可用 / 失败返回 ``None``。"""
    if not _COMTYPES_AVAILABLE or sys.platform != "win32":
        return None
    try:
        comtypes.CoInitialize()
    except OSError:  # pragma: no cover - 已初始化
        pass
    try:
        taskbar = comtypes.client.CreateObject(
            _CLSID_TASKBAR_LIST, interface=_ITaskbarList3
        )
        taskbar.HrInit()
        return taskbar
    except Exception:  # noqa: BLE001 - COM 失败不能冒泡进 Qt 回调
        return None


class ElaTaskbarProgress(QObject):
    """Windows 任务栏进度条组件。

    在 Windows 任务栏图标上展示进度条，支持暂停 / 恢复 / 停止 / 隐藏。
    """

    valueChanged = pyqtSignal(int)
    pausedChanged = pyqtSignal(bool)
    stoppedChanged = pyqtSignal(bool)
    visibilityChanged = pyqtSignal(bool)

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._taskbar = None
        self._hwnd: Optional[int] = None
        self._unavailable = False
        self._visible = False
        self._state = _TBPF_NOPROGRESS
        self._value = 0
        self._minimum = 0
        self._maximum = 0
        self._attach_timer: Optional[QTimer] = None

    # ── 挂接 ──────────────────────────────────────────────────────────

    def _ensure_attached(self) -> None:
        """懒挂接：第一次需要用时才建 COM 对象、等 windowHandle 就绪。"""
        if self._unavailable or self._window is None:
            return
        if self._taskbar is None:
            self._taskbar = _create_taskbar()
            if self._taskbar is None:
                self._unavailable = True
                return
        if self._hwnd is not None:
            return
        handle = self._window.windowHandle()
        if handle is None:
            # QWidget 没有 windowHandleChanged 信号：轮询等 show()/create()
            if self._attach_timer is None:
                self._attach_timer = QTimer(self)
                self._attach_timer.setInterval(50)
                self._attach_timer.timeout.connect(self._on_window_handle_created)
            self._attach_timer.start()
            return
        self._attach_handle(handle)

    def _attach_handle(self, handle) -> None:
        if self._attach_timer is not None:
            self._attach_timer.stop()
        hwnd = int(handle.winId())
        if not hwnd:
            return
        self._hwnd = hwnd
        self._push()

    def _on_window_handle_created(self) -> None:
        if self._window is None:
            return
        handle = self._window.windowHandle()
        if handle is None:
            return
        self._attach_handle(handle)

    def _push(self) -> None:
        """把当前状态推给任务栏（COM 调用失败静默忽略）。"""
        if self._taskbar is None or self._hwnd is None:
            return
        try:
            if not self._visible:
                self._taskbar.SetProgressState(self._hwnd, _TBPF_NOPROGRESS)
                return
            self._taskbar.SetProgressState(self._hwnd, self._state)
            total = self._maximum - self._minimum
            if total > 0 and self._state != _TBPF_INDETERMINATE:
                self._taskbar.SetProgressValue(
                    self._hwnd, self._value - self._minimum, total
                )
        except Exception:  # noqa: BLE001 - 任务栏没了 / COM 出错都不该崩
            pass

    # ── 属性 ──────────────────────────────────────────────────────────

    @property
    def value(self) -> int:
        return self._value

    @property
    def minimum(self) -> int:
        return self._minimum

    @property
    def maximum(self) -> int:
        return self._maximum

    @property
    def isPaused(self) -> bool:
        return self._state == _TBPF_PAUSED

    @property
    def isVisible(self) -> bool:
        return self._visible

    @property
    def isStopped(self) -> bool:
        return self._state == _TBPF_ERROR

    # ── 公开操作 ──────────────────────────────────────────────────────

    def setRange(self, min_val: int, max_val: int) -> None:
        if max_val < min_val:
            min_val = max_val
        self._minimum = int(min_val)
        self._maximum = int(max_val)
        self._ensure_attached()
        if self._value < self._minimum:
            self.setValue(self._minimum)
        elif self._value > self._maximum:
            self.setValue(self._maximum)
        else:
            self._push()

    def setValue(self, value: int) -> None:
        value = int(value)
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        if value == self._value:
            return
        self._value = value
        self._ensure_attached()
        self._push()
        self.valueChanged.emit(value)

    def show(self) -> None:
        """显示任务栏进度条。"""
        self._ensure_attached()
        if self._visible and self._state == _TBPF_NORMAL:
            return
        self._visible = True
        self._state = _TBPF_NORMAL
        self._push()
        self.visibilityChanged.emit(True)

    def hide(self) -> None:
        """隐藏任务栏进度条。"""
        if not self._visible:
            return
        self._visible = False
        self._state = _TBPF_NOPROGRESS
        self._push()
        self.visibilityChanged.emit(False)

    def pause(self) -> None:
        """暂停进度条（黄色）。"""
        self._ensure_attached()
        if self._state == _TBPF_PAUSED:
            return
        self._visible = True
        self._state = _TBPF_PAUSED
        self._push()
        self.pausedChanged.emit(True)

    def resume(self) -> None:
        """恢复被暂停的进度条。"""
        if self._state != _TBPF_PAUSED:
            return
        self._state = _TBPF_NORMAL
        self._push()
        self.pausedChanged.emit(False)

    def stop(self) -> None:
        """以「错误」状态停止进度条（红色）。"""
        self._ensure_attached()
        if self._state == _TBPF_ERROR:
            return
        self._visible = True
        self._state = _TBPF_ERROR
        self._push()
        self.stoppedChanged.emit(True)

    def reset(self) -> None:
        """重置进度条（值归零并隐藏）。"""
        if self._value != 0:
            self._value = 0
            self.valueChanged.emit(0)
        self._visible = False
        self._state = _TBPF_NOPROGRESS
        self._push()

    def deleteLater(self) -> None:
        if self._attach_timer is not None:
            self._attach_timer.stop()
        self._attach_timer = None
        super().deleteLater()
