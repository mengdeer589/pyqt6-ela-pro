"""Windows 任务栏进度条组件。

Qt6 里没有 ``QtWinExtras``（``QWinTaskbarButton`` / ``QWinTaskbarProgress`` 已随
Qt5 退役），本组件改为直接调 COM 的 ``ITaskbarList3`` / ``ITaskbarList4``，在任务栏
图标上展示进度条（正常 / 暂停 / 错误 / 不确定 / 隐藏）。

**接口按版本回退**：先要 ``ITaskbarList4``（Win8+），失败再要 ``ITaskbarList3``
（Win7）。两者的进度方法在 vtable 里位置相同（v4 是 v3 的超集），所以共用同一张
方法表。实测有系统（Win11 26H2 / build 26300）只接受 v4 的 IID、对 v3 返回
``E_NOINTERFACE`` —— 只请求 v3 会让整个组件静默失效。

非 Windows 或缺少 ``comtypes``（``[all] extra``）时所有方法为空操作；可用性可以
通过 :meth:`ElaTaskbarProgress.available` / :meth:`~ElaTaskbarProgress.unavailableReason`
查询，首次判定不可用时会发 :attr:`ElaTaskbarProgress.unavailable` 并打一条 warning
（以前是**静默**什么都不做，排查成本很高）。

用法::

    from pyqt6_ela_pro import ElaTaskbarProgress

    tb = ElaTaskbarProgress(my_window)
    if not tb.available():
        print("任务栏进度不可用:", tb.unavailableReason())
    tb.setRange(0, 100)
    tb.setValue(0)
    tb.show()
    for i in range(100):
        tb.setValue(i)
        # ...
    tb.hide()

:param window: 要关联进度的窗口控件（传子控件也行，会自动上溯到顶层窗口）
:type window: QWidget
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

try:  # comtypes 是可选依赖（[all] extra），缺失时整组件退化为空操作
    import comtypes
    import comtypes.client
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
    from ctypes import c_int, c_ulonglong, c_void_p

    def _taskbar_methods() -> list:
        """``ITaskbarList`` → ``ITaskbarList3`` 的 vtable 前缀（按顺序绑定）。

        前面用不到的方法也必须照样声明；``SetProgressValue`` / ``SetProgressState``
        是 ``ITaskbarList3`` 的第 7、8 个方法（v4 位置相同）。
        """
        return [
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

    class _ITaskbarList4(IUnknown):
        """``ITaskbarList4``（Win8+）。"""

        _iid_ = GUID("{C43DC798-95D1-4BEA-9030-BB99E2983A1A}")
        _methods_ = _taskbar_methods()

    class _ITaskbarList3(IUnknown):
        """``ITaskbarList3``（Win7）。"""

        _iid_ = GUID("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEA84}")
        _methods_ = _taskbar_methods()

    #: 按优先级排列的候选接口（v4 是 v3 的超集，老系统才回退到 v3）
    _TASKBAR_INTERFACES = (
        ("ITaskbarList4", _ITaskbarList4),
        ("ITaskbarList3", _ITaskbarList3),
    )
    _COMTYPES_AVAILABLE = True
except ImportError:  # pragma: no cover - 非 Windows / 未装 comtypes
    comtypes = None  # type: ignore[assignment]
    _TASKBAR_INTERFACES = ()
    _COMTYPES_AVAILABLE = False


#: ``TBPFLAG``（``shellapi.h``）
_TBPF_NOPROGRESS = 0x0
_TBPF_INDETERMINATE = 0x1
_TBPF_NORMAL = 0x2
_TBPF_ERROR = 0x4
_TBPF_PAUSED = 0x8

_CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"


def _create_taskbar():
    """创建并初始化任务栏对象，返回 ``(taskbar, reason)``。

    成功时 ``reason`` 是空串；失败时 ``taskbar`` 为 ``None``，``reason`` 是**能
    直接给用户看**的原因（含各接口的 HRESULT）。不抛异常 —— 它跑在 Qt 回调链上。
    """
    if not _COMTYPES_AVAILABLE:
        return None, "未安装 comtypes（pip install comtypes，或安装 [all] extra）"
    if sys.platform != "win32":
        return None, f"仅 Windows 支持任务栏进度（当前平台：{sys.platform}）"
    try:
        comtypes.CoInitialize()
    except OSError:  # pragma: no cover - 已初始化 / 其它 apartment
        pass
    reasons: list[str] = []
    for label, interface in _TASKBAR_INTERFACES:
        try:
            taskbar = comtypes.CoCreateInstance(
                GUID(_CLSID_TASKBAR_LIST),
                interface=interface,
                clsctx=comtypes.CLSCTX_INPROC_SERVER,
            )
            taskbar.HrInit()
            return taskbar, ""
        except OSError as exc:  # E_NOINTERFACE / REGDB_E_CLASSNOTREG
            code = getattr(exc, "winerror", None)
            if code is None:
                code = exc.errno
            detail = "?" if not code else f"{code & 0xFFFFFFFF:#010x}"
            reasons.append(f"{label}: HRESULT {detail}")
        except Exception as exc:  # noqa: BLE001 - COM 失败不能冒泡进 Qt 回调
            reasons.append(f"{label}: {type(exc).__name__} {exc}")
    return None, "任务栏接口不可用（" + "；".join(reasons) + "）"


class ElaTaskbarProgress(QObject):
    """Windows 任务栏进度条组件。

    在 Windows 任务栏图标上展示进度条，支持暂停 / 恢复 / 停止 / 隐藏。

    传**子控件**也行：内部会上溯到 ``window()``（子控件没有自己的原生窗口句柄）。
    窗口重建（``winId`` 变化）会自动重新挂接，不会把进度推到旧句柄上。
    """

    valueChanged = pyqtSignal(int)
    pausedChanged = pyqtSignal(bool)
    stoppedChanged = pyqtSignal(bool)
    visibilityChanged = pyqtSignal(bool)
    #: 组件不可用（参数是原因，直接展示给用户）。只在**首次判定**时发一次。
    unavailable = pyqtSignal(str)

    def __init__(self, window: Optional[QWidget] = None) -> None:
        super().__init__(window)
        self._window = window
        self._taskbar = None
        self._hwnd: Optional[int] = None
        self._unavailable = False
        self._unavailable_reason = ""
        self._visible = False
        self._state = _TBPF_NOPROGRESS
        self._value = 0
        self._minimum = 0
        self._maximum = 0
        self._attach_timer: Optional[QTimer] = None

    # ── 可用性 ────────────────────────────────────────────────────────

    def available(self) -> bool:
        """组件是否可用（惰性创建任务栏对象，失败时记住原因并上报一次）。"""
        self._ensure_attached()
        return self._taskbar is not None

    #: 与 :meth:`available` 同义（显式初始化入口，语义更直白）。
    def initialize(self) -> bool:
        """立即尝试创建任务栏对象，返回是否可用。"""
        return self.available()

    def unavailableReason(self) -> str:  # noqa: N802 (Qt 命名)
        """不可用原因（可用 / 尚未判定时为 ``""``）。"""
        return self._unavailable_reason

    def isUnavailable(self) -> bool:  # noqa: N802 (Qt 命名)
        """是否已判定不可用。"""
        return self._unavailable

    def _mark_unavailable(self, reason: str) -> None:
        if self._unavailable:
            return
        self._unavailable = True
        self._unavailable_reason = reason
        self._stop_polling()
        logger.warning("ElaTaskbarProgress 不可用：%s", reason)
        self.unavailable.emit(reason)

    # ── 挂接 ──────────────────────────────────────────────────────────

    def _top_level_window(self) -> Optional[QWidget]:
        """取顶层窗口：子控件没有自己的 ``QWindow``，挂到它上面永远等不到句柄。"""
        window = self._window
        if window is None:
            return None
        try:
            top = window.window()
        except RuntimeError:  # 已销毁
            return None
        return top if top is not None else window

    def _current_hwnd(self) -> int:
        window = self._top_level_window()
        if window is None:
            return 0
        try:
            handle = window.windowHandle()
            if handle is None:
                return 0
            return int(handle.winId())
        except (RuntimeError, TypeError, ValueError):  # 窗口正在销毁
            return 0

    def _ensure_attached(self) -> None:
        """懒挂接：第一次需要用时才建 COM 对象、等 windowHandle 就绪。"""
        if self._window is None or self._unavailable:
            return
        if self._taskbar is None:
            taskbar, reason = _create_taskbar()
            if taskbar is None:
                self._mark_unavailable(reason)
                return
            self._taskbar = taskbar
        hwnd = self._current_hwnd()
        if not hwnd:
            self._start_polling()
            return
        self._stop_polling()
        if hwnd != self._hwnd:
            # 窗口重建（改窗口标志 / 换顶层）后旧句柄已经无效，必须重挂
            self._hwnd = hwnd
            self._push()

    def _start_polling(self) -> None:
        if self._attach_timer is None:
            # QWidget 没有 windowHandleChanged 信号：轮询等 show()/create()
            self._attach_timer = QTimer(self)
            self._attach_timer.setInterval(50)
            self._attach_timer.timeout.connect(self._on_window_handle_created)
        self._attach_timer.start()

    def _stop_polling(self) -> None:
        if self._attach_timer is not None:
            self._attach_timer.stop()

    def _attach_handle(self, handle) -> None:
        hwnd = 0 if handle is None else int(handle.winId())
        if not hwnd:
            return
        self._stop_polling()
        self._hwnd = hwnd
        self._push()

    def _on_window_handle_created(self) -> None:
        if self._window is None:
            self._stop_polling()
            return
        window = self._top_level_window()
        if window is None:
            self._stop_polling()
            return
        handle = window.windowHandle()
        if handle is None:
            return
        self._attach_handle(handle)

    def _push(self) -> None:
        """把当前状态推给任务栏（COM 调用失败静默忽略）。"""
        if self._taskbar is None:
            return
        # 每次都核对句柄：窗口重建后旧 HWND 会被复用，进度会跑到别的窗口上
        hwnd = self._current_hwnd() or self._hwnd
        if not hwnd:
            return
        self._hwnd = hwnd
        try:
            if not self._visible:
                self._taskbar.SetProgressState(hwnd, _TBPF_NOPROGRESS)
                return
            self._taskbar.SetProgressState(hwnd, self._state)
            total = self._maximum - self._minimum
            if total > 0 and self._state != _TBPF_INDETERMINATE:
                self._taskbar.SetProgressValue(hwnd, self._value - self._minimum, total)
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
        self._stop_polling()
        self._attach_timer = None
        super().deleteLater()
