"""剪贴板纯文本写入（全库唯一入口）。

Windows 上 ``QClipboard.setText`` 遇到其他进程占着剪贴板时会静默失败并刷
``qt.qpa.mime``；这里改用原生 ``SetClipboardData``，被占用时异步重试。
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from ._internal import is_deleted, safe_call, single_shot_on

#: 失败后的重试间隔（毫秒）；首写之外最多再试 5 次
_RETRY_DELAYS_MS = (10, 20, 40, 80, 160)

#: 最新一次复制请求；旧请求的异步重试直接放弃，避免覆盖后来复制的内容
_latest_request = 0

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:  # pragma: no cover - 平台分支
    import ctypes
    from ctypes import wintypes

    _CF_UNICODETEXT = 13
    _GMEM_MOVEABLE = 0x0002
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HANDLE
    _kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    _kernel32.GlobalFree.argtypes = [wintypes.HANDLE]


def _to_windows_text(text: str) -> str:
    """按 Windows 剪贴板约定统一 CRLF（Win7 记事本不认单独的 LF）。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def _win32_write(text: str) -> bool:
    """原生写 ``CF_UNICODETEXT``；剪贴板被别的进程打开时返回 ``False``。"""
    if not _user32.OpenClipboard(None):
        return False
    try:
        if not _user32.EmptyClipboard():
            return False
        data = _to_windows_text(text).encode("utf-16-le") + b"\x00\x00"
        handle = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            _kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            _kernel32.GlobalUnlock(handle)
        if not _user32.SetClipboardData(_CF_UNICODETEXT, handle):
            _kernel32.GlobalFree(handle)
            return False
        # 成功后 HGLOBAL 归系统所有，不能 GlobalFree
        return True
    finally:
        _user32.CloseClipboard()


def _qt_write(text: str) -> bool:
    """非 Windows / 原生 API 不可用时的回退：写后读回校验。"""
    app = QApplication.instance()
    if app is None:
        return False
    clipboard = app.clipboard()
    if clipboard is None:
        return False
    clipboard.setText(text)
    return clipboard.text() == text


def _write_text(text: str) -> bool:
    try:
        if not _IS_WINDOWS:
            return _qt_write(text)
        return _win32_write(text)
    except Exception:  # noqa: BLE001 - 任何写入异常都按失败处理，交给重试
        if _IS_WINDOWS:
            try:
                return _qt_write(text)
            except Exception:  # noqa: BLE001 - 回退也失败就放弃这次
                return False
        return False


def set_clipboard_text(
    text: str,
    ctx: Optional[QObject] = None,
    done: Optional[Callable[[bool], None]] = None,
) -> bool:
    """把纯文本写入剪贴板；写入被占用时在 ``ctx`` 上异步重试。

    必须在 GUI 线程调用。空字符串会写成空剪贴板（与 ``QClipboard.setText("")``
    一致）。``done`` 在最终结果确定时调用一次：首写成功同步调用，重试成功后
    异步调用；被更新的复制请求取代时不调用。

    :returns: 首次写入是否成功（``False`` 时最终结果看 ``done``）
    """
    global _latest_request
    _latest_request += 1
    request = _latest_request

    value = str(text or "")
    owner = ctx if ctx is not None else QApplication.instance()

    def finish(ok: bool) -> None:
        safe_call(done, ok)

    def attempt(index: int) -> bool:
        if request != _latest_request:
            return False
        if _write_text(value):
            finish(True)
            return True
        if index >= len(_RETRY_DELAYS_MS):
            finish(False)
            return False
        if owner is None or is_deleted(owner):
            finish(False)
            return False
        single_shot_on(owner, _RETRY_DELAYS_MS[index], lambda: attempt(index + 1))
        return False

    return attempt(0)
