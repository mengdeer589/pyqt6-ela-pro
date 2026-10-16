"""划词助手 Win32 原生层（``pyqt6_ela_pro.selection_assistant``）。

- :class:`ElaMouseMonitor`：**轮询式**全局鼠标监视（``GetAsyncKeyState`` +
  ``GetCursorPos``，QTimer 在主线程，默认 15ms 一次）。刻意不使用
  ``WH_MOUSE_LL`` 全局钩子：钩子回调运行在独立线程且需要抢 GIL，一旦回调
  阻塞会拖住整个系统的鼠标输入（表现为机器卡死），还受杀软 / Win7 钩子
  超时影响；
- :func:`send_copy`：``SendInput`` 向当前前台窗口发送 Ctrl+C —— **本模块
  是划词助手唯一会影响用户正常复制粘贴的地方**，所以它默认带两道闸门
  （修饰键按下不注入、距上次注入不足 ``_MIN_INJECT_INTERVAL_MS`` 不注入）；
- :func:`any_modifier_down` / :func:`clipboard_sequence_number` /
  :func:`window_rect_at`：上面三道闸门 / 恢复逻辑要用的 Win32 查询；
- :func:`to_logical_pos`：物理像素 → Qt 逻辑坐标（多屏 DPI 尽力而为）；
- :func:`window_pid_at` / :func:`foreground_pid`：窗口归属进程查询。

非 Windows 环境下 :meth:`ElaMouseMonitor.start` 抛 ``RuntimeError``，
由 :class:`~pyqt6_ela_pro.selection_assistant.assistant.ElaSelectionAssistant`
转换为 ``errorOccurred`` 信号。

命名规范与库内一致（``camelCase``）。
"""

from __future__ import annotations

import ctypes
import sys
import time
import warnings
from ctypes import wintypes
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .._internal import to_logical_pos  # noqa: F401  （重导出，实现见 _internal）

_IS_WINDOWS = sys.platform == "win32"

#: 轮询回调里已告警过的异常（同一异常只提示一次，避免每 15ms 刷屏）
_warned_poll_errors: set = set()


def safe_connect(obj, signal_name: str, slot, label: str = "") -> None:
    """连接一个**受保护**的槽：槽内异常被捕获并告警，不会杀掉进程。

    为什么要这个helper：PyQt6 里，槽（slot）抛出的 Python 异常**不会**
    传播给 ``signal.emit()`` 的调用方 —— PyQt6 打印 traceback 后直接
    ``abort()``（0xC0000409）。所以在 emit 外面包 ``try/except`` 是无效的，
    唯一的防线就在槽本身。

    划词助手的槽会走 ``capture()`` -> Win32 ``SendInput``，宿主一旦抛异常，
    整个应用连同助手一起消失。因此库内部一律用本helper连接。

    :param obj: 拥有信号的对象
    :param signal_name: 信号名
    :param slot: 槽（可调用）
    :param label: 告警标签
    """
    name = label or getattr(slot, "__name__", repr(slot))

    def _guarded(*args):
        try:
            return slot(*args)
        except Exception as exc:  # noqa: BLE001 - 槽内异常绝不能逃逸
            _warn_once("划词助手槽 %s 抛出异常，已忽略：" % name, exc)
            return None

    _guarded.__name__ = "guarded_%s" % name
    getattr(obj, signal_name).connect(_guarded)


def _warn_once(prefix: str, exc: BaseException) -> None:
    """同一个「来源 + 异常类型」只提示一次，避免 15ms 一次地刷屏。

    key 里带上 ``prefix``：不同槽 / 不同闸门各自去重、互不吞告警
    （曾只用 ``type(exc)``，一种类型先出现就会把别处的同类型异常静默）。
    """
    key = (prefix, type(exc))
    if key in _warned_poll_errors:
        return
    _warned_poll_errors.add(key)
    warnings.warn(f"{prefix} {type(exc).__name__}: {exc}", RuntimeWarning, stacklevel=3)


#: 默认轮询间隔（毫秒）
_DEFAULT_POLL_MS = 15
#: 两次 Ctrl+C 注入之间的最小间隔（毫秒）—— 防连发，也顺带限制
#: 「注入的那次 Ctrl+C 撞上用户自己按的 Ctrl+C」的窗口
MIN_INJECT_INTERVAL_MS = 200
#: 虚拟键
_VK_LBUTTON = 0x01
_VK_RBUTTON = 0x02
_VK_MBUTTON = 0x04
_VK_SHIFT = 0x10
_VK_MENU = 0x12
#: ``GetSystemMetrics``：系统是否交换了鼠标主 / 次键
_SM_SWAPBUTTON = 23

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_VK_CONTROL = 0x11
_VK_C = 0x43

#: 上次注入时刻（``time.monotonic()`` 秒）；模块级，节流闸门用
_last_inject_at = 0.0

_ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


if _IS_WINDOWS:  # pragma: no cover - 平台分支
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(_INPUT),
        ctypes.c_int,
    ]
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.WindowFromPoint.argtypes = [_POINT]
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.GetClipboardSequenceNumber.argtypes = []
    _user32.GetClipboardSequenceNumber.restype = wintypes.DWORD


def _swap_buttons() -> bool:
    """系统是否交换了鼠标主 / 次键（``SM_SWAPBUTTON``）。

    交换后物理右键才是「主键」，划词手势必须跟着换，否则这类用户完全用不了。
    """
    if not _IS_WINDOWS:  # pragma: no cover - 平台分支
        return False
    return bool(_user32.GetSystemMetrics(_SM_SWAPBUTTON))


def _async_key_down(vk: int) -> bool:
    """``GetAsyncKeyState`` 的高位置（只读全局键盘状态，无钩子）。"""
    if not _IS_WINDOWS:  # pragma: no cover - 平台分支
        return False
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


def any_modifier_down() -> bool:
    """Shift / Ctrl / Alt 中是否有任意一个正被按下。

    注入 Ctrl+C 前必须问一句：用户按着修饰键时，注入出去的其实是
    Ctrl+Shift+C / Ctrl+Alt+C —— 在不少终端里那恰好是「复制」绑定，
    语义完全跑偏。
    """
    return any(_async_key_down(vk) for vk in (_VK_SHIFT, _VK_CONTROL, _VK_MENU))


def clipboard_sequence_number() -> int:
    """Windows 剪贴板序列号（内容每变化一次递增）；不可用返回 ``0``。

    「文本相同」无法区分「用户又复制了一遍同样的内容」与「没人动过」，
    序列号可以 —— 恢复剪贴板前用它兜一道。取不到时调用方按「不可用」
    回退到纯文本比较（本模块的平台分支刻意不引 pywin32 / win32api）。
    """
    if not _IS_WINDOWS:  # pragma: no cover - 平台分支
        return 0
    try:
        return int(_user32.GetClipboardSequenceNumber())
    except Exception:  # noqa: BLE001 - 旧系统 / 导出缺失一律按不可用
        return 0


def window_rect_at(x: int, y: int):
    """该物理坐标处**顶层窗口**的矩形 ``(left, top, right, bottom)``。

    取不到（无窗口 / API 失败）返回 ``None``。内置拖选过滤器用它排除
    「按在窗口边框上」——那是在调窗口大小，不是在划词。
    """
    if not _IS_WINDOWS:  # pragma: no cover - 平台分支
        return None
    try:
        hwnd = _user32.WindowFromPoint(_POINT(int(x), int(y)))
        if not hwnd:
            return None
        rect = _RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:  # noqa: BLE001 - 查询失败按「无信息」处理
        return None


def _send_key(vk: int, flags: int = 0) -> None:
    """发一个按键事件（``SendInput``）。单独成函数是为了测试能替换它。"""
    if not _IS_WINDOWS:  # pragma: no cover - 平台分支
        raise RuntimeError("send_copy 仅支持 Windows")
    item = _INPUT(type=_INPUT_KEYBOARD)
    item.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    _user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT))


def send_copy(force: bool = False) -> bool:
    """向当前前台窗口发送 Ctrl+C；返回**是否真的注入**。

    默认两道闸门（任一命中就返回 ``False``，一个键都不发）：

    1. **任何修饰键正被按下** —— 否则注入出去的是 Ctrl+Shift+C /
       Ctrl+Alt+C 之类，在不少终端里语义直接跑偏；
    2. **距上次注入不足 :data:`MIN_INJECT_INTERVAL_MS`** —— 连续划词时
       不连发，也顺带收窄「注入的那次 Ctrl+C 撞上用户自己按的 Ctrl+C」
       的窗口（撞上了会让恢复逻辑把用户刚复制的内容覆盖回旧值）。

    ``force=True`` 跳过全部闸门，供明确知道自己在做什么的调用方使用。
    """
    global _last_inject_at
    if not _IS_WINDOWS:  # pragma: no cover - 平台分支
        raise RuntimeError("send_copy 仅支持 Windows")
    now = time.monotonic()
    if not force:
        if any_modifier_down():
            return False
        if (now - _last_inject_at) * 1000.0 < MIN_INJECT_INTERVAL_MS:
            return False
    _send_key(_VK_CONTROL)
    _send_key(_VK_C)
    _send_key(_VK_C, _KEYEVENTF_KEYUP)
    _send_key(_VK_CONTROL, _KEYEVENTF_KEYUP)
    _last_inject_at = now
    return True


def window_pid_at(x: int, y: int) -> int:
    """获取指定物理坐标处窗口的进程 id（无窗口返回 0）。"""
    if not _IS_WINDOWS:  # pragma: no cover - 平台分支
        return 0
    hwnd = _user32.WindowFromPoint(_POINT(int(x), int(y)))
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def foreground_pid() -> int:
    """获取前台窗口的进程 id（无窗口返回 0）。"""
    if not _IS_WINDOWS:  # pragma: no cover - 平台分支
        return 0
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


class ElaMouseMonitor(QObject):
    """轮询式全局鼠标监视（主线程 QTimer，无全局钩子、无额外线程）。

    「左键」指**系统主键**（尊重 Windows 主 / 次键互换设置；交换后物理右键
    即主键）。信号参数中的坐标一律为 Win32 物理像素 ``(x, y)``，宿主 / 组件
    负责换算为 Qt 逻辑坐标（见 :func:`to_logical_pos`）。

    已知限制：单次按下 / 抬起间隔短于轮询间隔（默认 15ms）的极快点击可能
    被漏检；滚轮事件无法轮询，``wheelScrolled`` 仅为契约保留（真实监视不会
    发射）。

    :param parent: 父对象
    :param pollMs: 轮询间隔毫秒数
    """

    #: 左键（系统主键）按下
    leftPressed = pyqtSignal(object)
    #: 左键抬起（参数：按下点、抬起点）
    leftReleased = pyqtSignal(object, object)
    #: 右键 / 中键按下
    otherPressed = pyqtSignal(object)
    #: 滚轮滚动（契约保留；轮询实现不发射）
    wheelScrolled = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QObject] = None,
        pollMs: int = _DEFAULT_POLL_MS,
    ) -> None:
        super().__init__(parent)
        self._down: Optional[tuple] = None
        self._left_last = False
        self._right_last = False
        self._middle_last = False
        self._primary_vk = _VK_LBUTTON
        self._secondary_vk = _VK_RBUTTON
        self._refresh_buttons()
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(pollMs)))
        self._timer.timeout.connect(self._poll)

    # -- 生命周期 ----------------------------------------------------------

    def start(self) -> bool:
        """开始轮询；失败抛 ``RuntimeError``（非 Windows）。"""
        if not _IS_WINDOWS:
            raise RuntimeError("划词助手仅支持 Windows")
        if self._timer.isActive():
            return True
        self._refresh_buttons()
        self._reset_state()
        self._timer.start()
        return True

    def stop(self) -> None:
        """停止轮询（幂等）。"""
        self._timer.stop()
        self._reset_state()

    def isRunning(self) -> bool:
        """是否正在轮询。"""
        return self._timer.isActive()

    def setPollMs(self, ms: int) -> None:
        """设置轮询间隔毫秒数。"""
        self._timer.setInterval(max(1, int(ms)))

    def pollMs(self) -> int:
        """轮询间隔毫秒数。"""
        return self._timer.interval()

    # -- 轮询 --------------------------------------------------------------

    def _refresh_buttons(self) -> None:
        """按系统「主 / 次键互换」设置决定哪个虚拟键算主键。"""
        if _swap_buttons():
            self._primary_vk = _VK_RBUTTON
            self._secondary_vk = _VK_LBUTTON
        else:
            self._primary_vk = _VK_LBUTTON
            self._secondary_vk = _VK_RBUTTON

    def _reset_state(self) -> None:
        self._down = None
        self._left_last = False
        self._right_last = False
        self._middle_last = False

    def _poll(self) -> None:
        """15ms 轮询：检测按下 / 抬起边沿并转发给宿主。

        保护范围说明（重要）：这个 ``try/except`` 只能兜住 **Win32 采样调用**
        （``_cursor_pos`` / ``_key_down``）自身抛出的异常。它**兜不住**信号槽
        里宿主的异常 —— PyQt6 中槽抛异常会直接 ``abort()``（0xC0000409），
        不经过 emit 调用方，那条路只能靠 :func:`safe_connect` 在槽侧拦住。

        状态推进放在 finally，保证一次异常不会把边沿检测卡死在同一状态。
        """
        left = right = middle = False
        sampled = False
        try:
            point = self._cursor_pos()
            left = self._key_down(self._primary_vk)
            right = self._key_down(self._secondary_vk)
            middle = self._key_down(_VK_MBUTTON)
            sampled = True

            if left and not self._left_last:
                self._down = point
                self.leftPressed.emit(point)
            elif not left and self._left_last:
                self.leftReleased.emit(self._down or point, point)
                self._down = None

            if (right and not self._right_last) or (middle and not self._middle_last):
                self.otherPressed.emit(point)
        except Exception as exc:  # noqa: BLE001 - Win32 采样异常不得逃逸
            _warn_once("划词轮询采样异常，已忽略：", exc)
        finally:
            # 只在采样成功时推进边沿状态：一次 GetCursorPos 失败就把 _left_last
            # 清零，会让下一轮把「仍按着」误判成新的按下沿，多发一次事件。
            if sampled:
                self._left_last = left
                self._right_last = right
                self._middle_last = middle

    @staticmethod
    def _key_down(vk: int) -> bool:
        return _async_key_down(vk)

    @staticmethod
    def _cursor_pos() -> tuple:
        point = _POINT()
        if not _user32.GetCursorPos(ctypes.byref(point)):
            return (0, 0)
        return (int(point.x), int(point.y))


__all__ = [
    "MIN_INJECT_INTERVAL_MS",
    "ElaMouseMonitor",
    "any_modifier_down",
    "clipboard_sequence_number",
    "foreground_pid",
    "safe_connect",
    "send_copy",
    "to_logical_pos",
    "window_pid_at",
    "window_rect_at",
]
