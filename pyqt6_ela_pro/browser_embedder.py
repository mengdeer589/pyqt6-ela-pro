"""
浏览器嵌入组件 (Windows + PyQt6)

继承自 ElaWindowEmbedder，添加浏览器启动和管理功能。

使用示例:
    from pyqt6_ela_pro.browser_embedder import ElaBrowserEmbedder
    browser = ElaBrowserEmbedder(
        webview_path=Path("chrome.exe"),
        port=9023,
        debug_port=9222,
        parent=self
    )
    browser.embed("http://example.com", window_title="MyBrowser")
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import functools
import json
import subprocess
import tempfile
import time
import weakref
from ctypes import (
    POINTER,
    byref,
    c_uint32,
    c_void_p,
    cast,
    create_unicode_buffer,
)
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Callable, Optional, Union
from urllib.parse import unquote, urlparse

from ._internal import is_deleted
from PyQt6.QtCore import (
    QAbstractNativeEventFilter,
    QObject,
    QProcess,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtWidgets import QApplication, QWidget

from ._internal import safe_call, to_logical_pos
from .window_embedder import ElaWindowEmbedder

try:
    import win32api  # type: ignore[attr-defined]
    import win32con  # type: ignore[attr-defined]
    import win32gui  # type: ignore[attr-defined]
except ImportError:
    win32api = None
    win32con = None
    win32gui = None
try:
    import win32process  # type: ignore[attr-defined]
except ImportError:
    win32process = None

try:
    from comtypes import (
        COMMETHOD,
        GUID,  # type: ignore[attr-defined]
        HRESULT,
        COMObject,
        IUnknown,
    )

    _COM_AVAILABLE = True
except ImportError:
    _COM_AVAILABLE = False


def _normalize_url(url: str) -> str:
    """CDP target 匹配用的 URL 归一化（scheme / host 大小写、末尾斜杠、fragment）。"""
    try:
        parsed = urlparse(url)
        path = (parsed.path or "").rstrip("/")
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"
    except Exception:  # noqa
        return url


def _parse_target_id(debugger_url: str) -> str:
    """从 ``ws://host/devtools/page/<targetId>`` 提取 target id。"""
    try:
        path = urlparse(debugger_url).path
        marker = "/devtools/page/"
        if marker in path:
            return path.split(marker, 1)[1].strip("/")
    except Exception:  # noqa
        pass
    return ""


def _trim_mapping(mapping: dict, limit: int = 2048) -> None:
    """限制 requestId 映射规模（dict 保持插入序，淘汰最早的条目）。"""
    while len(mapping) > limit:
        mapping.pop(next(iter(mapping)), None)


# 当前处于嵌入状态的浏览器窗口句柄集合：为空时 IME 过滤器直接绕行，
# 避免库被引入后每条原生消息都进一次 Python。
_active_chrome_hwnds: set[int] = set()


class _BrowserController(QObject):
    """CDP WebSocket 客户端（内部类）- 信号驱动版本"""

    cdpReady = pyqtSignal()
    errorOccurred = pyqtSignal(str)
    consoleMessage = pyqtSignal(str, str)
    domContentReady = pyqtSignal()
    pageError = pyqtSignal(str, str)
    networkRequest = pyqtSignal(str, str, str)
    networkResponse = pyqtSignal(str, int, str)
    cookieSent = pyqtSignal(str, str)
    cookieReceived = pyqtSignal(str, str)
    credentialDetected = pyqtSignal(str, str, str)

    def __init__(
        self,
        debugger_url: str,
        timeout: float = 5.0,
        log_func: Optional[Callable[[str, int], None]] = None,
        target_id: str = "",
        parent: Optional[QObject] = None,
    ):
        # **parent 必填**：controller 与 WebSocket 原来都没有 parent，唯一的
        # 引用链是 ``embedder._controller -> controller._ws``。embedder 一旦走
        # C++ 析构路径被删（child 控件被父窗口连带销毁就是这条），``_cleanup_browser()``
        # 不会被调用，controller 与 WebSocket 存活下来继续收 CDP 消息 ->
        # ``_log_func``（宿主 embedder 的直接 Python 引用）抛 RuntimeError。
        # 挂上 parent 后 Qt 会连带断开并销毁，整条链断掉。
        super().__init__(parent)
        self._debugger_url = debugger_url
        self._timeout = timeout
        self._log_func = log_func
        self._target_id = target_id or ""
        self._ws: Optional[QWebSocket] = None
        self._message_id: int = 0
        self._callbacks: dict[int, Callable] = {}
        self._result_timers: dict[int, QTimer] = {}
        self._connect_timer: Optional[QTimer] = None
        self._running: bool = False
        self._loadStarted_callback: Optional[Callable] = None
        self._loadFinished_callback: Optional[Callable] = None
        self._dropped_file_callback: Optional[Callable[[str], None]] = None
        self._pending_request_urls: dict[str, str] = {}
        self._pending_response_urls: dict[str, str] = {}

    def _log(self, message: str, level: int = 30) -> None:
        if self._log_func:
            self._log_func(message, level)

    def connect(self) -> None:
        """启动 WebSocket 连接（非阻塞）"""
        # **QWebSocket 的签名是 (origin, version, parent)** ——
        # ``QWebSocket(self)`` 会把 controller 当 origin 字符串塞进去 ->
        # ``TypeError: argument 1 has unexpected type '_BrowserController'``。
        # 用关键字参数才是「挂 parent」的意思。
        self._ws = QWebSocket(parent=self)
        self._ws.error.connect(self._on_error)
        self._ws.textMessageReceived.connect(self._on_text_message)
        self._ws.connected.connect(self._on_connected)

        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self._on_connect_timeout)
        self._connect_timer.start(10000)

        self._ws.open(QUrl(self._debugger_url))

    def _on_connected(self) -> None:
        self._log("CDP WebSocket 已连接", 20)
        self._connect_timer.stop()
        self._running = True
        self.sendCommand("Page.enable")
        self.sendCommand("Runtime.enable")
        self.sendCommand("Network.enable")
        self.sendCommand("Log.enable")
        self.sendCommand(
            "Browser.setDownloadBehavior",
            {
                "behavior": "deny",
            },
        )
        self.sendCommand(
            "Target.setAutoAttach",
            {
                "autoAttach": True,
                "waitForDebuggerOnStart": False,
                "flatten": True,
            },
        )
        self.cdpReady.emit()

    def _on_connect_timeout(self) -> None:
        self._log("CDP WebSocket 连接超时", 30)
        self.errorOccurred.emit("WebSocket 连接超时")
        self._running = False
        if self._ws:
            self._ws.close()
            self._ws = None

    def _on_error(self, error) -> None:
        try:
            self._log(f"WebSocket 错误: {error}", 30)
        except RuntimeError:
            return
        self.errorOccurred.emit(str(error))
        if self._connect_timer:
            self._connect_timer.stop()

    def _on_text_message(self, message: str) -> None:
        """``QWebSocket.textMessageReceived`` 槽 —— **整段必须兜底**。

        这是**外部输入**入口：``--remote-debugging-port`` 绑127.0.0.1，
        任何本地进程都能连上发任意 JSON，所以「格式合法」不等于「类型合法」。
        两处原缺口：

        ① ``msg_id`` 未做类型校验就当 dict key 用（``_callbacks`` /
           ``_result_timers`` 都是 dict）-> ``{"id": []}`` 抛
           ``TypeError: unhashable type: 'list'``，**穿出 Qt 槽** =
           进程 0xC0000409 零 traceback 终止（实测复现）；
        ② ``self._log(...)`` 没护 —— 它是宿主 embedder 的**直接 Python
           引用**（不是信号），embedder 被删后抛
           ``RuntimeError: wrapped C/C++ object ... has been deleted``。
           对照：``_on_error`` 明确写了 ``except RuntimeError: return``。
        """
        try:
            self._dispatch_text_message(message)
        except Exception as e:  # noqa: BLE001
            # 兜底本身不能再抛（_log 也可能因宿主已销毁而 RuntimeError）
            try:
                self._log(f"CDP message dispatch failed: {e}", 30)
            except Exception:  # noqa: BLE001
                pass

    def _dispatch_text_message(self, message: str) -> None:
        try:
            data = json.loads(message)
        except Exception as e:
            self._log(f"CDP 消息解析失败: {e}", 30)
            return
        if not isinstance(data, dict):
            return

        if "id" in data:
            msg_id = data["id"]
            # **必须是 int**：dict 的 key 要求可哈希，而 JSON 能送来 list/dict。
            # bool 是 int 的子类，要显式拒（True 会被当成 id 1 误匹配）。
            if isinstance(msg_id, bool) or not isinstance(msg_id, int):
                self._log(f"CDP 响应 id 类型非法（已忽略）: {msg_id!r}", 30)
                return
            result = data.get("result")
            error = data.get("error")
            if error:
                self._log(f"CDP 命令 {msg_id} 返回错误: {error}", 40)
            if msg_id in self._callbacks:
                cb = self._callbacks.pop(msg_id)
                # 宿主回调异常不能穿过 Qt 信号边界（PyQt6 直接 abort）
                safe_call(cb, result)
            if msg_id in self._result_timers:
                self._result_timers[msg_id].stop()
                self._result_timers[msg_id].deleteLater()
                del self._result_timers[msg_id]
        else:
            method = data.get("method")
            params = data.get("params", {})
            try:
                self._handle_event(method, params)
            except Exception as e:
                self._log(f"CDP 事件处理失败 ({method}): {e}", 30)

    def _handle_event(self, method: Optional[str], params: dict) -> None:
        if method == "Page.frameStartedLoading":
            safe_call(self._loadStarted_callback)
        elif method in ("Page.loadEventFired", "Page.frameStoppedLoading"):
            safe_call(self._loadFinished_callback)
        elif method == "Runtime.consoleAPICalled":
            msg_type = params.get("type", "log")
            args = params.get("args", [])
            texts = []
            for arg in args:
                value = arg.get("value", "")
                texts.append(str(value))
            text = " ".join(texts)
            self.consoleMessage.emit(msg_type, text)
        elif method in (
            "Target.targetCreated",
            "Target.attachedToTarget",
            "Target.targetInfoChanged",
        ):
            self._close_target_page(params)
        elif method == "Page.frameRequestedNavigation":
            url = params.get("url", "")
            if url.startswith("file:///"):
                path = self._parse_file_url_path(url)
                safe_call(self._dropped_file_callback, path)
                self.sendCommand("Page.stopLoading", {})
        elif method == "Page.downloadWillBegin":
            url = params.get("url", "")
            if url.startswith("file:///"):
                path = self._parse_file_url_path(url)
                safe_call(self._dropped_file_callback, path)
        elif method == "Page.domContentEventFired":
            self.domContentReady.emit()
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            exception_text = details.get("text", "")
            url = details.get("url", "")
            self.pageError.emit(url, exception_text)
        elif method == "Network.requestWillBeSent":
            request = params.get("request", {})
            req_url = request.get("url", "")
            req_method = request.get("method", "GET")
            req_type = params.get("type", "")
            self.networkRequest.emit(req_url, req_method, req_type)
            self._pending_request_urls[params.get("requestId", "")] = req_url
            _trim_mapping(self._pending_request_urls)
            headers = request.get("headers") or {}
            cookie = headers.get("cookie", "")
            if cookie:
                self.cookieSent.emit(req_url, cookie)
            for hdr_name in ("authorization", "x-api-key", "proxy-authorization"):
                val = headers.get(hdr_name, "")
                if val:
                    self.credentialDetected.emit(req_url, hdr_name, val)
        elif method == "Network.requestWillBeSentExtraInfo":
            headers = params.get("headers") or {}
            cookie = headers.get("cookie", "")
            if cookie:
                req_url = self._pending_request_urls.get(
                    params.get("requestId", ""), ""
                )
                self.cookieSent.emit(req_url, cookie)
            for hdr_name in ("authorization", "x-api-key", "proxy-authorization"):
                val = headers.get(hdr_name, "")
                if val:
                    req_url = self._pending_request_urls.get(
                        params.get("requestId", ""), ""
                    )
                    self.credentialDetected.emit(req_url, hdr_name, val)
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            resp_url = response.get("url", "")
            status = response.get("status", 0)
            resp_type = params.get("type", "")
            self.networkResponse.emit(resp_url, status, resp_type)
            self._pending_response_urls[params.get("requestId", "")] = resp_url
            _trim_mapping(self._pending_response_urls)
            headers = response.get("headers") or {}
            set_cookie = headers.get("set-cookie", "")
            if isinstance(set_cookie, list):
                for sc in set_cookie:
                    if sc:
                        self.cookieReceived.emit(resp_url, sc)
            elif set_cookie:
                self.cookieReceived.emit(resp_url, set_cookie)
        elif method == "Network.responseReceivedExtraInfo":
            headers = params.get("headers") or {}
            set_cookie = headers.get("set-cookie", "")
            if set_cookie:
                resp_url = self._pending_response_urls.get(
                    params.get("requestId", ""), ""
                )
                if isinstance(set_cookie, list):
                    for sc in set_cookie:
                        if sc:
                            self.cookieReceived.emit(resp_url, sc)
                else:
                    self.cookieReceived.emit(resp_url, set_cookie)
        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            # 请求结束即回收映射，避免长会话下无限增长
            request_id = params.get("requestId", "")
            self._pending_request_urls.pop(request_id, None)
            self._pending_response_urls.pop(request_id, None)
        elif method == "Inspector.targetCrashed":
            self._log("浏览器标签页崩溃", 40)
        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            log_level = entry.get("level", "log")
            log_text = entry.get("text", "")
            self.consoleMessage.emit(log_level, log_text)
        elif method == "Page.javascriptDialogOpening":
            self.sendCommand("Page.handleJavaScriptDialog", {"accept": True})

    @staticmethod
    def _parse_file_url_path(url: str) -> str:
        path = unquote(urlparse(url).path)
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return path

    def _close_target_page(self, params: dict) -> None:
        """关闭由本页面（window.open / target=_blank）打开的弹窗。

        共享浏览器进程下 ``Target.*`` 事件可能混入其它实例的页面，因此只处理
        ``openerId`` 明确指向本页面的 target；``openerId`` 缺失时同样不关
        （宁可漏放一个弹窗，也不能误关别的实例的窗口）。
        """
        target = params.get("targetInfo", {})
        if not isinstance(target, dict) or target.get("type") != "page":
            return
        target_id = target.get("targetId", "")
        if not target_id or target_id == self._target_id:
            return
        opener_id = target.get("openerId", "")
        if not opener_id or opener_id != self._target_id:
            self._log(f"忽略非本页面的 page target: {target_id}", 10)
            return
        url = target.get("url", "")
        if url.startswith("file:///"):
            path = self._parse_file_url_path(url)
            safe_call(self._dropped_file_callback, path)
        self.sendCommand("Target.closeTarget", {"targetId": target_id})

    def set_loadStarted_callback(self, callback: Callable) -> None:
        """设置页面开始加载的回调。"""
        self._loadStarted_callback = callback

    def set_loadFinished_callback(self, callback: Callable) -> None:
        """设置页面加载完成的回调。"""
        self._loadFinished_callback = callback

    def sendCommand(
        self,
        method: str,
        params: Optional[dict] = None,
        callback: Optional[Callable[[Any], None]] = None,
    ) -> int:
        """发送 CDP 命令（非阻塞），返回消息 ID（未连接时返回 ``-1``）。"""
        # 未连接时直接返回，不登记回调 / 定时器（否则会留下等超时才清掉的幽灵条目）
        if self._ws is None:
            return -1

        msg_id = self._message_id
        self._message_id += 1

        cmd: dict = {"id": msg_id, "method": method}
        if params:
            cmd["params"] = params

        if callback:
            self._callbacks[msg_id] = callback

        if callback and self._timeout > 0:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._on_command_timeout(msg_id))
            timer.start(int(self._timeout * 1000))
            self._result_timers[msg_id] = timer

        self._ws.sendTextMessage(json.dumps(cmd))
        return msg_id

    def _on_command_timeout(self, msg_id: int) -> None:
        self._log(f"命令 {msg_id} 超时", 30)
        self._callbacks.pop(msg_id, None)
        timer = self._result_timers.pop(msg_id, None)
        if timer:
            timer.deleteLater()

    def runJS(
        self, script: str, callback: Optional[Callable[[Any], None]] = None
    ) -> int:
        """执行 JavaScript 代码（非阻塞），返回消息 ID。"""
        return self.sendCommand(
            "Runtime.evaluate",
            {"expression": script, "returnByValue": True},
            callback=callback,
        )

    def navigate(
        self, url: str, callback: Optional[Callable[[Any], None]] = None
    ) -> int:
        """导航到指定 URL（非阻塞），返回消息 ID。"""
        return self.sendCommand("Page.navigate", {"url": url}, callback=callback)

    def reload(self, callback: Optional[Callable[[Any], None]] = None) -> int:
        """刷新页面（非阻塞），返回消息 ID。"""
        return self.sendCommand("Page.reload", callback=callback)

    def close(self) -> None:
        self._running = False
        if self._connect_timer:
            self._connect_timer.stop()
            self._connect_timer = None
        for timer in self._result_timers.values():
            timer.stop()
            timer.deleteLater()
        self._result_timers.clear()
        self._callbacks.clear()
        if self._ws:
            self._ws.close()
            self._ws = None


# ── IME 转发过滤器（浏览器专用）──────────────────────────────


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint32),
        (
            "wParam",
            ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32,
        ),
        (
            "lParam",
            ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32,
        ),
        ("time", ctypes.c_uint32),
        ("pt", ctypes.c_uint64),
    ]


class _ImeForwardFilter(QAbstractNativeEventFilter):
    """Qt 原生事件过滤器：光标在嵌入浏览器上时转发 IME 并切换焦点。

    只在**交互类消息**（键盘 / IME / 鼠标按键 / 激活 / 滚轮）上参与：纯鼠标
    移动等高频消息既不触发焦点切换（否则鼠标划过浏览器就会改写键盘焦点），
    也不需要进 Python，避免给整个应用的消息循环加开销。
    """

    # 参与焦点判断的消息
    _INTERACTION_MESSAGES = frozenset(
        {
            0x0007,  # WM_SETFOCUS
            0x0021,  # WM_MOUSEACTIVATE
            0x0051,  # WM_INPUTLANGCHANGE
            0x0100,  # WM_KEYDOWN
            0x0101,  # WM_KEYUP
            0x0102,  # WM_CHAR
            0x0104,  # WM_SYSKEYDOWN
            0x0105,  # WM_SYSKEYUP
            0x010D,  # WM_IME_STARTCOMPOSITION
            0x010E,  # WM_IME_ENDCOMPOSITION
            0x010F,  # WM_IME_COMPOSITION
            0x0201,  # WM_LBUTTONDOWN
            0x0204,  # WM_RBUTTONDOWN
            0x0207,  # WM_MBUTTONDOWN
            0x020A,  # WM_MOUSEWHEEL
            0x020E,  # WM_MOUSEHWHEEL
            0x0281,  # WM_IME_SETCONTEXT
            0x0282,  # WM_IME_NOTIFY
            0x0286,  # WM_IME_CHAR
        }
    )
    # 需要转投给嵌入浏览器窗口的 IME / 输入法消息
    _IME_MESSAGES = frozenset({0x0051, 0x010D, 0x010E, 0x010F, 0x0281, 0x0282, 0x0286})

    def __init__(self):
        super().__init__()
        self._last_cursor_pos: Optional[tuple[int, int]] = None
        self._last_cursor_hwnd: Optional[int] = None
        self._last_chrome_hwnd: Optional[int] = None
        self._qt_focus_widget: Optional[QWidget] = None

    def reset(self) -> None:
        """清空位置 / 焦点缓存（最后一个浏览器窗口释放时调用）。"""
        self._last_cursor_pos = None
        self._last_cursor_hwnd = None
        self._last_chrome_hwnd = None
        self._qt_focus_widget = None

    @staticmethod
    def _chrome_hwnd_usable(hwnd: Optional[int]) -> bool:
        """缓存的 hwnd 是否仍可用：**仍登记为嵌入中，且句柄未被系统回收**。

        hwnd 会被系统复用：浏览器窗口关闭后若光标没动，``_last_cursor_pos``
        命中就会直接返回旧 hwnd，而 ``PostMessageW`` 会把输入法消息投给
        「碰巧复用了这个句柄的任意窗口」。
        """
        if hwnd is None or hwnd not in _active_chrome_hwnds:
            return False
        if win32gui is None:
            return False
        try:
            return bool(win32gui.IsWindow(hwnd))
        except Exception:  # noqa
            return False

    def _find_at_cursor(self) -> Optional[int]:
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        pos = (pt.x, pt.y)
        if pos == self._last_cursor_pos and self._chrome_hwnd_usable(
            self._last_cursor_hwnd
        ):
            return self._last_cursor_hwnd
        self._last_cursor_pos = pos

        # GetCursorPos 给物理像素，widgetAt 要逻辑坐标（高 DPI 缩放必须换算）
        w = QApplication.widgetAt(to_logical_pos(pt.x, pt.y))
        hwnd = getattr(w, "_chrome_hwnd", None)
        self._last_cursor_hwnd = hwnd
        return hwnd

    def _remember_qt_focus(self) -> None:
        try:
            w = QApplication.focusWidget()
        except Exception:  # noqa
            w = None
        if w is not None and not is_deleted(w):
            self._qt_focus_widget = w

    def _restore_qt_focus(self) -> None:
        w = self._qt_focus_widget
        self._qt_focus_widget = None
        try:
            if w is not None and not is_deleted(w):
                ctypes.windll.user32.SetFocus(int(w.winId()))
                return
        except Exception:  # noqa
            pass
        # 兜底：切回光标下的 Qt 控件
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        w = QApplication.widgetAt(to_logical_pos(pt.x, pt.y))
        try:
            if w is not None and not is_deleted(w):
                ctypes.windll.user32.SetFocus(int(w.winId()))
        except Exception:  # noqa
            pass

    def nativeEventFilter(self, eventType, message):
        if eventType != "windows_generic_MSG" or not _active_chrome_hwnds:
            return False, 0
        try:
            msg = _MSG.from_address(message.__int__())
            if msg.message not in self._INTERACTION_MESSAGES:
                return False, 0

            hwnd = self._find_at_cursor() or None
            # 首行的 ``_active_chrome_hwnds`` 非空判断只说明「**还有**浏览器在
            # 嵌入」，不代表「光标下这个」还活着 —— 多实例共享浏览器会话时，
            # A 实例释放后B 实例仍让过滤器工作，而缓存里的 hwnd 属于 A。
            if not self._chrome_hwnd_usable(hwnd):
                hwnd = None

            # 焦点切换：Chrome ↔ Qt，仅在状态真正变化时动作
            if hwnd != self._last_chrome_hwnd:
                if hwnd:
                    self._last_chrome_hwnd = hwnd
                    self._remember_qt_focus()
                    ctypes.windll.user32.SetFocus(hwnd)
                else:
                    self._last_chrome_hwnd = None
                    self._restore_qt_focus()

            # IME 转发：光标在浏览器上时把输入法消息转投给浏览器窗口
            if hwnd and msg.message in self._IME_MESSAGES:
                ctypes.windll.user32.PostMessageW(
                    hwnd, msg.message, msg.wParam, msg.lParam
                )
        except Exception:  # noqa
            pass
        return False, 0


_ime_filter = _ImeForwardFilter()
_ime_installed = False


def _register_chrome_hwnd(hwnd: int) -> None:
    """登记处于嵌入状态的浏览器窗口（IME 过滤器据此判断是否需要工作）。"""
    _active_chrome_hwnds.add(hwnd)


def _unregister_chrome_hwnd(hwnd: Optional[int]) -> None:
    if hwnd:
        _active_chrome_hwnds.discard(hwnd)
    if not _active_chrome_hwnds:
        _ime_filter.reset()


def _ensure_ime_filter() -> None:
    global _ime_installed
    if not _ime_installed:
        try:
            QApplication.instance().installNativeEventFilter(_ime_filter)
            _ime_installed = True
        except Exception:
            pass


# ── 共享 Browser 进程管理器 ─────────────────────────────────


class _BrowserSession:
    """共享 Chrome Browser 进程单例，支持多 --app 窗口共享一个进程。

    多个 ``--app`` 窗口共用同一个浏览器进程 / 调试端口，因此窗口认领必须
    **按启动顺序串行化**（同一时刻只允许一个「已启动、未认领」的窗口在途），
    否则各实例轮询时可能抢到别的实例刚创建出来的窗口。
    """

    _instance: Optional[Any] = None  # type: ignore[name-defined]
    _refcount: int = 0

    def __init__(
        self,
        webview_path: Path,
        debug_port: int,
        profile_dir: Path,
        browser_args: Optional[list[str]] = None,
    ) -> None:
        self._webview_path = webview_path
        self._debug_port = debug_port
        self._profile_dir = profile_dir
        self._process: Optional[QProcess] = None
        self._known_hwnds: set[int] = set()
        self._foreign_hwnds: set[int] = set()
        self._browser_pid: int = 0
        self._browser_args = browser_args or []
        self._launch_queue: list[tuple[Any, Callable[[], None]]] = []
        self._launch_in_flight: Any = None
        # 已被各实例认领的 CDP page target（多窗口下用于区分“哪一页是自己的”）
        self.claimed_target_ids: set[str] = set()

    @classmethod
    def acquire(
        cls,
        webview_path: Path,
        debug_port: int,
        profile_dir: Path,
        browser_args: Optional[list[str]] = None,
    ) -> _BrowserSession:
        if cls._instance is not None:
            cls._refcount += 1
            return cls._instance
        cls._instance = cls(webview_path, debug_port, profile_dir, browser_args)
        cls._refcount = 1
        return cls._instance

    def conflicts(
        self,
        webview_path: Path,
        debug_port: int,
        browser_args: Optional[list[str]] = None,
    ) -> list[str]:
        """本实例与共享会话首个实例的配置差异（复用会话时这些配置会被忽略）。"""
        items: list[str] = []
        if str(webview_path) != str(self._webview_path):
            items.append(f"浏览器路径 {webview_path} ≠ {self._webview_path}")
        if debug_port != self._debug_port:
            items.append(f"调试端口 {debug_port} ≠ {self._debug_port}")
        if list(browser_args or []) != list(self._browser_args):
            items.append("browser_args 与首个实例不同")
        return items

    def release(self) -> None:
        _BrowserSession._refcount -= 1
        if _BrowserSession._refcount <= 0:
            self._terminate()
            _BrowserSession._instance = None
            _BrowserSession._refcount = 0

    # ---- 启动串行化（窗口 ↔ 实例一一对应） ----

    def request_launch(self, token: Any, launch: Callable[[], None]) -> None:
        """排队启动窗口：前一个实例认领（或超时 / 释放）后才轮到下一个。"""
        self._launch_queue.append((token, launch))
        self._pump_launch()

    def finish_launch(self, token: Any) -> None:
        """实例认领窗口（含超时 / 释放路径）后放行下一个排队者。"""
        if self._launch_in_flight is token:
            self._launch_in_flight = None
            self._pump_launch()
        else:
            self._launch_queue = [
                item for item in self._launch_queue if item[0] is not token
            ]

    def _pump_launch(self) -> None:
        if self._launch_in_flight is not None or not self._launch_queue:
            return
        token, launch = self._launch_queue.pop(0)
        self._launch_in_flight = token
        try:
            launch()
        except Exception:  # noqa - 启动失败不能卡住队列
            self._launch_in_flight = None
            self._pump_launch()

    def launch_start(self, url: str, _window_title: str, on_error=None) -> None:
        self._snapshot_foreign_hwnds()
        args = [
            f"--app={url}",
            "--incognito",
            "--no-first-run",
            "--disable-sync",
            "--disable-session-crashed-bubble",
            "--suppress-message-center-popups",
            f"--user-data-dir={self._profile_dir}",
            f"--remote-debugging-port={self._debug_port}",
            "--remote-allow-origins=*",
            "--window-position=-9999,-9999",
        ]
        args.extend(self._browser_args)

        if self._process is None:
            self._process = QProcess()
            self._process.setProgram(str(self._webview_path))
            self._process.setArguments(args)
            self._process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
            # **QProcess 启动失败不抛异常**，只发 ``errorOccurred``；只接信号
            # 不够，浏览器路径写错时「等窗口」会空转满 30 秒零反馈
            # （详见 AGENTS.md）。
            if on_error is not None:
                self._process.errorOccurred.connect(on_error)
            self._process.start()
            if self._process.state() == QProcess.ProcessState.NotRunning:
                # 同步就失败（路径不存在 / 无权限）—— 抛出去复用 ``_launch``
                # 已有的 embedError 收尾，而不是干等 30 秒
                detail = self._process.errorString() or "浏览器进程未能启动"
                self._process = None
                raise RuntimeError(detail)
        else:
            subprocess.Popen(
                [str(self._webview_path), *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS,
            )

    def _snapshot_foreign_hwnds(self) -> None:
        """快照启动前已存在的 Chrome 窗口，避免认领用户自己的浏览器窗口。

        （浏览器进程可能因 ``--user-data-dir`` 路由而提前退出，此时拿不到
        可靠的 pid，只能靠这份快照排除。）
        """
        found: list[int] = []

        def _cb(hwnd, _):
            try:
                if (
                    win32gui.IsWindow(hwnd)
                    and win32gui.IsWindowVisible(hwnd)
                    and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1"
                ):
                    found.append(hwnd)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_cb, None)
            self._foreign_hwnds.update(found)
        except Exception:
            pass

    def poll_hwnd(self) -> Optional[int]:
        # 句柄会被系统复用，两个集合都先剪掉已销毁的，否则新窗口可能永远
        # 认不出来：``_known_hwnds`` 命中会让认到的窗口被当成「旧的」，
        # ``_foreign_hwnds`` 命中会让新窗口被当成「用户自己的」。
        for bucket in (self._known_hwnds, self._foreign_hwnds):
            if bucket:
                try:
                    pruned = {h for h in bucket if win32gui.IsWindow(h)}
                except Exception:
                    continue
                if pruned != bucket:
                    bucket.clear()
                    bucket.update(pruned)

        process_pid = self._process.processId() if self._process else 0
        browser_pid = process_pid or self._browser_pid
        hwnds: list[int] = []

        def _cb(hwnd, _):
            try:
                if (
                    win32gui.IsWindow(hwnd)
                    and win32gui.IsWindowVisible(hwnd)
                    and win32gui.GetClassName(hwnd) == "Chrome_WidgetWin_1"
                    and hwnd not in self._known_hwnds
                    and hwnd not in self._foreign_hwnds
                    and win32gui.GetWindowText(hwnd)
                ):
                    if browser_pid:
                        _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                        if wpid != browser_pid:
                            return True
                    hwnds.append(hwnd)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_cb, None)

        for hwnd in hwnds:
            self._known_hwnds.add(hwnd)
            self._remember_browser_pid(hwnd)
            return hwnd
        return None

    def _remember_browser_pid(self, hwnd: int) -> None:
        if self._browser_pid or win32process is None:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                self._browser_pid = int(pid)
        except Exception:
            pass

    def _terminate(self) -> None:
        handled = False
        if self._process:
            try:
                if self._process.state() == QProcess.ProcessState.Running:
                    self._process.terminate()
                    self._process.waitForFinished(3000)
                    if self._process.state() == QProcess.ProcessState.Running:
                        self._process.kill()
                    handled = True
            except Exception:
                pass
            self._process = None
        # 首发进程可能因路由到已存在实例而提前退出（拿不到 QProcess），
        # 用认领窗口时记下的 pid 兜底结束浏览器进程。
        if not handled and self._browser_pid:
            self._kill_process(self._browser_pid)
        self._browser_pid = 0

    @staticmethod
    def _kill_process(pid: int) -> None:
        if win32api is None or win32con is None:
            return
        try:
            handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
            win32api.TerminateProcess(handle, 0)
        except Exception:
            pass


def _release_browser_on_destroy(embedder) -> None:
    """``destroyed`` 收尾：释放共享浏览器会话的引用并拆掉 Win32 钩子。

    原先清理只挂在 ``closeEvent`` 与Python 的 ``deleteLater()`` 覆写上，而两者
    在**标准用法下都是死的**：``QWidget::close()`` 对非窗口 widget 直接 return
    true、**不发 QCloseEvent**，而示例用的正是
    ``ElaBrowserEmbedder(..., parent=self)``（child）；父控件析构走
    ``deleteChildren()`` → 直接 ``~QWidget``，**不会**回调Python 覆写。

    后果：``_BrowserSession._refcount`` 永不减→ **浏览器进程永不休**；
    ``_active_chrome_hwnds`` 留下死 hwnd → IME 过滤器**永久不再绕行**
    （全应用每条交互类原生消息都进 Python）；OLE drop target 永不 revoke。

    ``weakref.proxy`` 是必须的：``destroyed`` 发出时 C++ 对象正在析构，
    这里只能碰纯 Python 属性与 Win32 API。
    """
    try:
        release = getattr(embedder, "release", None)
    except ReferenceError:
        return
    if release is None:
        return
    try:
        release()
    except Exception:  # noqa: BLE001
        pass


class ElaBrowserEmbedder(ElaWindowEmbedder):
    """浏览器嵌入组件

    继承自 ElaWindowEmbedder，添加浏览器启动和管理功能。

    信号（继承自 ElaWindowEmbedder）:
        windowEmbedded(int): 窗口嵌入成功
        windowReleased(int): 窗口释放成功
        windowNotFound(str): 等待窗口时未找到
        embedError(str): 嵌入出错
        embedTimeout(): 等待窗口嵌入超时

    新增信号:
        loadStarted(): 页面开始加载
        loadFinished(): 页面加载完成

    使用示例:
        browser = ElaBrowserEmbedder(
            webview_path=Path("chrome.exe"),
            port=9023,
            debug_port=9222,
            parent=self
        )
        browser.embed("http://example.com", window_title="MyBrowser")
    """

    loadStarted = pyqtSignal()
    loadFinished = pyqtSignal()
    domContentReady = pyqtSignal()
    pageError = pyqtSignal(str, str)
    networkRequest = pyqtSignal(str, str, str)
    networkResponse = pyqtSignal(str, int, str)
    logMessage = pyqtSignal(str, int)
    embedCompleted = pyqtSignal(bool)
    consoleMessage = pyqtSignal(str, str)
    fileDropped = pyqtSignal(str)
    cookieSent = pyqtSignal(str, str)
    cookieReceived = pyqtSignal(str, str)
    credentialDetected = pyqtSignal(str, str, str)

    _instances: weakref.WeakSet = weakref.WeakSet()
    _default_debug_port: int = 9222

    @classmethod
    def getAllInstances(cls) -> list:
        """返回所有活跃实例"""
        return list(cls._instances)

    @classmethod
    def closeAllInstances(cls) -> None:
        """关闭所有活跃实例"""
        for instance in list(cls._instances):
            instance.release()

    @staticmethod
    def _checkDependencies() -> None:
        if win32gui is None:
            raise ImportError(
                "ElaBrowserEmbedder 需要 pywin32，请运行: uv pip install pywin32"
            )
        if not _COM_AVAILABLE:
            raise ImportError(
                "ElaBrowserEmbedder 需要 comtypes，请运行: uv pip install comtypes"
            )

    def __init__(
        self,
        webview_path: Path,
        debug_port: Optional[int] = None,
        browser_args: Optional[list[str]] = None,
        parent: Optional[QWidget] = None,
    ):
        self._checkDependencies()
        super().__init__(parent)
        _ensure_ime_filter()
        ElaBrowserEmbedder._instances.add(self)

        self._webview_path = webview_path
        self._debug_port = debug_port or ElaBrowserEmbedder._default_debug_port
        self._session: Optional[_BrowserSession] = None
        self._browser_args = browser_args or []
        self._browser_process: Optional[QProcess] = None
        self._controller: Optional[_BrowserController] = None
        self._target_hwnd: Optional[int] = None
        self._original_parent: Optional[int] = None
        self._original_style: Optional[int] = None
        self._original_ex_style: Optional[int] = None
        self._original_rect: Optional[tuple] = None
        self._pending_window_title: Optional[str] = None
        self._pending_connect_cdp: bool = False
        self._launch_pending: bool = False
        self._hwnd_timer: Optional[QTimer] = None
        self._hwnd_retries: int = 0
        self._browser_embedTimer: Optional[QTimer] = None
        self._network_mgr: Optional[QNetworkAccessManager] = None
        self._debug_url_timer: Optional[QTimer] = None
        self._debug_url_retries: int = 0
        self._debug_url_max_retries: int = 0
        self._debug_url_callback: Optional[Callable] = None
        self._last_dropped_file_path: Optional[str] = None
        self._last_dropped_file_time: float = 0
        self._ole_drop_target: Any = None
        self._ole_target_hwnd: Optional[int] = None
        self._embedded_url: Optional[str] = None
        self._enable_cookie_jar: bool = False
        self._cookie_store: dict[str, dict[str, str]] = {}
        self._cookie_expiry: dict[tuple[str, str], Optional[float]] = {}
        # 补上析构收尾：child 控件被父窗口连带销毁时 closeEvent /
        # deleteLater() 都不触发（见 _release_browser_on_destroy）
        self.destroyed.connect(
            functools.partial(_release_browser_on_destroy, weakref.proxy(self))
        )

    def _log(self, message: str, level: int = 30) -> None:
        self.logMessage.emit(message, level)

    def embed(
        self,
        url: Union[str, Path],
        window_title: Optional[str] = None,
        connect_cdp: bool = True,
    ) -> None:
        if isinstance(url, Path):
            url = url.as_uri()
        if self._embeddedInfo is not None:
            self._log("已有嵌入窗口，请先调用 release()", 30)
            return
        if self._launch_pending or self._hwnd_timer is not None:
            self._log("嵌入流程正在进行中", 30)
            return

        profile_dir = Path(tempfile.gettempdir()) / "pyqt5_ela_browser_profile"
        profile_dir.mkdir(exist_ok=True)

        # 每个实例只 acquire 一次（重复会漏减引用计数 → 进程永不回收）
        if self._session is None or self._session is not _BrowserSession._instance:
            self._session = _BrowserSession.acquire(
                self._webview_path, self._debug_port, profile_dir, self._browser_args
            )
            conflicts = self._session.conflicts(
                self._webview_path, self._debug_port, self._browser_args
            )
            if conflicts:
                self._log(
                    "共享浏览器会话已存在，以下实例配置被忽略: " + "; ".join(conflicts),
                    20,
                )

        self._embedded_url = url
        self._pending_window_title = window_title or url
        self._pending_connect_cdp = connect_cdp
        self._launch_pending = True

        session = self._session

        def _launch() -> None:
            self._launch_pending = False
            if session is not self._session:
                # 排队期间已被 release() 取消
                return
            try:
                session.launch_start(
                    url, window_title or url, self._on_browser_process_error
                )
            except Exception as e:  # noqa
                self._log(f"启动浏览器失败: {e}", 40)
                self.embedError.emit(f"启动浏览器失败: {e}")
                session.finish_launch(self)
                return
            self._start_hwnd_polling()

        # 串行启动：等前一个实例认领窗口后再启动，避免互相抢窗口
        session.request_launch(self, _launch)

    def _on_browser_process_error(self, error) -> None:
        """浏览器进程启动 / 运行失败：**立刻**中止窗口轮询。

        没有它，失败的表现是「30 秒后弹一句『等待窗口超时』」—— 与「浏览器
        慢慢启动不出来」完全无法区分，而后者其实在正常工作。

        ``self._hwnd_timer is None`` 表示**已不在启动阶段**（窗口已认领、或
        已经在收尾），此时不打扰宿主 —— 共享会话下浏览器进程归先启动的那个
        实例所有，它后来退出不该给当前实例报错。
        """
        if self._hwnd_timer is None:
            return
        self._cleanup_hwnd_polling()
        code = getattr(error, "name", None) or str(error)
        msg = f"浏览器进程异常（{code}）"
        self._log(msg, 40)
        self.embedError.emit(msg)
        self.embedCompleted.emit(False)
        if self._session is not None:
            self._session.finish_launch(self)

    def _start_hwnd_polling(self) -> None:
        self._hwnd_retries = 0
        self._hwnd_timer = QTimer(self)
        self._hwnd_timer.setSingleShot(True)
        self._hwnd_timer.timeout.connect(self._poll_hwnd)
        self._hwnd_timer.start(0)

    def _poll_hwnd(self) -> None:
        if not self._session:
            self._cleanup_hwnd_polling()
            return

        try:
            hwnd = self._session.poll_hwnd()
        except Exception as e:  # noqa - QTimer 回调里不能抛异常
            self._log(f"轮询浏览器窗口失败: {e}", 30)
            hwnd = None

        if hwnd:
            self._cleanup_hwnd_polling()
            # 认领成功立刻放行下一个排队实例的启动
            self._session.finish_launch(self)
            self._embedHwnd(hwnd)
            if self._pending_connect_cdp:
                self._pending_connect_cdp = False
                self._start_cdp_connection()
            return

        self._hwnd_retries += 1
        if self._hwnd_retries >= 60:
            self._cleanup_hwnd_polling()
            title = self._pending_window_title
            self._log(f"等待窗口超时: {title}", 40)
            # **必须发对外信号**：只 log 的话，只监听 ``embedCompleted`` 的
            # 宿主会**永久等待**
            self.embedTimeout.emit()
            self.embedError.emit(f"等待浏览器窗口超时: {title}")
            self.embedCompleted.emit(False)
            self._session.finish_launch(self)
            return

        self._hwnd_timer.start(500)

    def _cleanup_hwnd_polling(self) -> None:
        if self._hwnd_timer:
            self._hwnd_timer.stop()
            self._hwnd_timer.deleteLater()
            self._hwnd_timer = None
        self._hwnd_retries = 0

    def _cleanup_browser(self) -> None:
        """清理 CDP 连接"""
        if self._controller:
            try:
                                self._controller.cdpReady.disconnect(self._cdpReadySlot)
            except (TypeError, RuntimeError):
                pass
            try:
                                self._controller.errorOccurred.disconnect(self._cdpErrorSlot)
            except (TypeError, RuntimeError):
                pass
            try:
                self._controller.consoleMessage.disconnect(self.consoleMessage)
            except (TypeError, RuntimeError):
                pass
            try:
                self._controller.domContentReady.disconnect(self.domContentReady)
            except (TypeError, RuntimeError):
                pass
            try:
                self._controller.pageError.disconnect(self.pageError)
            except (TypeError, RuntimeError):
                pass
            try:
                self._controller.networkRequest.disconnect(self.networkRequest)
            except (TypeError, RuntimeError):
                pass
            try:
                self._controller.networkResponse.disconnect(self.networkResponse)
            except (TypeError, RuntimeError):
                pass
            try:
                self._controller.cookieSent.disconnect(self.cookieSent)
            except (TypeError, RuntimeError):
                pass
            try:
                self._controller.cookieReceived.disconnect(self.cookieReceived)
            except (TypeError, RuntimeError):
                pass
            try:
                self._controller.credentialDetected.disconnect(self.credentialDetected)
            except (TypeError, RuntimeError):
                pass
            self._controller.close()
            self._controller = None

    # ---- 公共 API（CDP 操控） ----

    def reload(self, callback: Optional[Callable[[Any], None]] = None) -> None:
        """刷新当前页面（非阻塞）"""
        if self._controller:
            self._controller.reload(callback=callback)

    def navigate(
        self, url: str, callback: Optional[Callable[[Any], None]] = None
    ) -> None:
        """导航到指定 URL（非阻塞）"""
        if self._controller:
            self._controller.navigate(url, callback=callback)

    def load_url(
        self, url: Union[str, Path], callback: Optional[Callable[[Any], None]] = None
    ) -> Optional[int]:
        """加载指定 URL 或本地文件（非阻塞）"""
        if isinstance(url, Path):
            url = url.as_uri()
        if self._controller:
            return self._controller.navigate(url, callback=callback)
        return None

    def runJS(
        self, script: str, callback: Optional[Callable[[Any], None]] = None
    ) -> Optional[int]:
        """执行 JavaScript 代码（非阻塞）"""
        if self._controller:
            return self._controller.runJS(script, callback=callback)
        return None

    # ---- 异步 CDP 连接 ----

    def _start_cdp_connection(self) -> None:
        """启动 CDP 连接流程（非阻塞）"""
        self._start_debug_url_polling(self._on_debugger_url_obtained)

    def _start_debug_url_polling(
        self, callback: Callable[[str], None], timeout: float = 15
    ) -> None:
        """通过 QTimer + QNetworkAccessManager 异步轮询调试 URL"""
        self._debug_url_callback = callback
        self._debug_url_retries = 0
        self._debug_url_max_retries = int(timeout / 0.5)

        self._network_mgr = QNetworkAccessManager(self)
        self._debugUrlSlot = self._on_debug_url_response  # 断连要同一对象（lambda / partial 必须存引用）
        self._network_mgr.finished.connect(self._debugUrlSlot)

        self._debug_url_timer = QTimer(self)
        self._debug_url_timer.setSingleShot(True)
        self._debug_url_timer.timeout.connect(self._do_debug_url_request)

        self._do_debug_url_request()

    def _do_debug_url_request(self) -> None:
        port = self._session._debug_port if self._session else self._debug_port
        if self._debug_url_retries >= self._debug_url_max_retries:
            self._log("获取调试 URL 超时", 40)
            self.embedCompleted.emit(False)
            self._cleanup_debug_url_polling()
            return

        url = QUrl(f"http://127.0.0.1:{port}/json")
        self._network_mgr.get(QNetworkRequest(url))
        self._debug_url_retries += 1

    def _pick_debugger_url(self, data: list) -> Optional[str]:
        """从 ``/json`` 结果中挑出属于本实例的 page target。

        匹配顺序：① URL 归一化后相等；② 排除已被其它实例认领的 target 后
        恰好只剩一个候选。多窗口共享浏览器进程时**不再**退回“第一个 page
        target”，否则会把 controller 附到别的实例的页面上。
        """
        pages = [t for t in data if isinstance(t, dict) and t.get("type") == "page"]
        if not pages:
            return None

        claimed = self._session.claimed_target_ids if self._session else set()
        embedded = _normalize_url(self._embedded_url or "")
        if embedded:
            for target in pages:
                if target.get("id", "") in claimed:
                    continue
                if _normalize_url(target.get("url", "")) == embedded:
                    return target.get("webSocketDebuggerUrl")

        candidates = [t for t in pages if t.get("id", "") not in claimed]
        if len(candidates) == 1:
            target = candidates[0]
            self._log(
                f"CDP 目标未按 URL 匹配，回退到唯一候选: {target.get('url', '')}", 20
            )
            return target.get("webSocketDebuggerUrl")
        if len(candidates) > 1:
            self._log(
                f"CDP 目标不明确（{len(candidates)} 个候选，期望 {self._embedded_url}），继续等待",
                20,
            )
        return None

    def _on_debug_url_response(self, reply) -> None:
        # PyQt6 的 ``reply.error()`` 返回 **枚举成员**（``NoError`` 也是 truthy），
        # 直接 ``if reply.error():`` 会把每个成功响应都当失败（CDP 永远连不上）。
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._log(f"CDP 调试端口尚未就绪: {reply.errorString()}", 10)
            self._debug_url_timer.start(500)
            reply.deleteLater()
            return

        try:
            data = json.loads(bytes(reply.readAll()).decode())
            debugger_url = (
                self._pick_debugger_url(data) if isinstance(data, list) else None
            )
            if debugger_url:
                cb = self._debug_url_callback
                self._cleanup_debug_url_polling()
                if cb:
                    cb(debugger_url)
                reply.deleteLater()
                return
        except Exception as e:
            self._log(f"CDP 调试端口响应解析失败: {e}", 20)

        self._debug_url_timer.start(500)
        reply.deleteLater()

    def _cleanup_debug_url_polling(self) -> None:
        if self._debug_url_timer:
            self._debug_url_timer.stop()
            self._debug_url_timer.deleteLater()
            self._debug_url_timer = None
        if self._network_mgr:
            try:
                                self._network_mgr.finished.disconnect(self._debugUrlSlot)
            except (TypeError, RuntimeError):
                pass
            self._network_mgr.deleteLater()
            self._network_mgr = None
        self._debug_url_callback = None

    def _on_debugger_url_obtained(self, debugger_url: str) -> None:
        # 记下自己的 target id：既用于标记“本实例已认领”（避免其它实例选中），
        # 也让 controller 能分辨哪些 page target 不是自己的（不误关窗口）。
        target_id = _parse_target_id(debugger_url)
        if target_id and self._session:
            self._session.claimed_target_ids.add(target_id)
        self._controller = _BrowserController(
            debugger_url=debugger_url,
            log_func=self._log,
            target_id=target_id,
            parent=self,
        )
        self._controller.set_loadStarted_callback(self.loadStarted.emit)
        self._controller.set_loadFinished_callback(self.loadFinished.emit)
        self._cdpReadySlot = self._on_cdpReady  # 断连要同一对象（lambda / partial 必须存引用）
        self._controller.cdpReady.connect(self._cdpReadySlot)
        self._cdpErrorSlot = self._onCdpError  # 断连要同一对象（lambda / partial 必须存引用）
        self._controller.errorOccurred.connect(self._cdpErrorSlot)
        self._controller.consoleMessage.connect(self.consoleMessage)
        self._controller.domContentReady.connect(self.domContentReady)
        self._controller.pageError.connect(self.pageError)
        self._controller.networkRequest.connect(self.networkRequest)
        self._controller.networkResponse.connect(self.networkResponse)
        self._controller.cookieSent.connect(self.cookieSent)
        self._controller.cookieReceived.connect(self.cookieReceived)
        self._controller.credentialDetected.connect(self.credentialDetected)
        if self._enable_cookie_jar:
            self._controller.cookieReceived.connect(self._jar_on_set_cookie)
            self._controller.cookieSent.connect(self._jar_on_cookie_sent)
        self._controller.connect()

    def _on_dropped_file(self, path: str) -> None:
        if is_deleted(self):
            # OLE / CDP 的迟到回调可能落在已销毁实例上
            return
        now = time.time()
        if (
            path == self._last_dropped_file_path
            and now - self._last_dropped_file_time < 0.5
        ):
            return
        self._last_dropped_file_path = path
        self._last_dropped_file_time = now
        self.fileDropped.emit(path)

    def _on_cdpReady(self) -> None:
        self._log("CDP 连接就绪", 20)
        self._controller._dropped_file_callback = self._on_dropped_file
        self._inject_block_new_window()
        self.embedCompleted.emit(True)

    def _inject_block_new_window(self) -> None:
        """注入脚本，防止网站通过 window.open 或 target=_blank 创建新窗口。"""
        script = """
(function() {
    var origOpen = window.open;
    window.open = function(url) {
        if (url) window.location.href = url;
        return window;
    };
    document.addEventListener('click', function(e) {
        var a = e.target.closest('a');
        if (a && a.target === '_blank') {
            e.preventDefault();
            if (a.href) window.location.href = a.href;
        }
    }, true);
    document.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
    }, true);
})();
"""
        self._controller.sendCommand(
            "Page.addScriptToEvaluateOnNewDocument", {"source": script}
        )
        self._controller.sendCommand(
            "Runtime.evaluate", {"expression": script, "returnByValue": False}
        )
        self._log("已注入新窗口拦截脚本", 20)

    def _onCdpError(self, error: str) -> None:
        self._log(f"CDP 连接失败: {error}", 40)
        self.embedCompleted.emit(False)

    def _embedHwnd(self, hwnd: int) -> None:
        # 先快照原状态：失败时不能留下“已 SetParent 但没记录”的孤儿窗口
        try:
            original_parent = win32gui.GetParent(hwnd)
            original_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            original_ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            original_rect = win32gui.GetWindowRect(hwnd)
        except Exception as e:  # noqa - 窗口可能在轮询间隙被销毁
            self._log(f"读取浏览器窗口状态失败: {e}", 40)
            self.embedError.emit(f"读取浏览器窗口状态失败: {e}")
            return

        self._target_hwnd = hwnd
        self._original_parent = original_parent
        self._original_style = original_style
        self._original_ex_style = original_ex_style
        self._original_rect = original_rect

        try:
            if self._embeddedInfo:
                ElaWindowEmbedder.release(self)

            self._tryEmbedOnce(hwnd)
            if original_rect and original_rect[0] < -5000:
                w = original_rect[2] - original_rect[0]
                h = original_rect[3] - original_rect[1]
                screen = win32gui.GetWindowRect(win32gui.GetDesktopWindow())
                cx = screen[0] + (screen[2] - screen[0] - w) // 2
                cy = screen[1] + (screen[3] - screen[1] - h) // 2
                self._original_rect = (cx, cy, cx + w, cy + h)
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            ctypes.windll.user32.SetFocus(hwnd)
        except Exception as e:  # noqa
            self._log(f"嵌入浏览器窗口失败: {e}", 40)
            self.embedError.emit(f"嵌入浏览器窗口失败: {e}")
            return

        if self._embeddedInfo is not None:
            _register_chrome_hwnd(hwnd)
        try:
            self._install_drop_interceptor(hwnd)
        except Exception as e:  # noqa
            self._log(f"安装拖放拦截器失败: {e}", 20)

    def _install_drop_interceptor(self, hwnd: int) -> None:
        """通过 COM IDropTarget 在浏览器 HWND 上拦截 OLE 拖放。"""
        if not _COM_AVAILABLE:
            return
        try:
            OLE32 = ctypes.windll.ole32
            try:
                OLE32.OleInitialize(None)
            except Exception:
                pass
            SHELL32 = ctypes.windll.shell32

            # 定义 IDropTarget COM 接口
            class _IDropTarget(IUnknown):
                _iid_ = GUID("{00000122-0000-0000-C000-000000000046}")
                _methods_ = [
                    COMMETHOD(
                        [],
                        HRESULT,
                        "DragEnter",
                        (["in"], c_void_p, "pDataObj"),
                        (["in"], c_uint32, "grfKeyState"),
                        (["in"], c_void_p, "pt"),
                        (["in", "out"], POINTER(c_uint32), "pdwEffect"),
                    ),
                    COMMETHOD(
                        [],
                        HRESULT,
                        "DragOver",
                        (["in"], c_uint32, "grfKeyState"),
                        (["in"], c_void_p, "pt"),
                        (["in", "out"], POINTER(c_uint32), "pdwEffect"),
                    ),
                    COMMETHOD([], HRESULT, "DragLeave"),
                    COMMETHOD(
                        [],
                        HRESULT,
                        "Drop",
                        (["in"], c_void_p, "pDataObj"),
                        (["in"], c_uint32, "grfKeyState"),
                        (["in"], c_void_p, "pt"),
                        (["in", "out"], POINTER(c_uint32), "pdwEffect"),
                    ),
                ]

            class _ChromeDropTarget(COMObject):
                _com_interfaces_ = [_IDropTarget]

                def __init__(self, embedder):
                    super().__init__()
                    self._embedder = embedder
                    self._cached_path = ""

                @staticmethod
                def _normalize_drop_effect(pdwEffect):
                    allowed = pdwEffect[0]
                    if allowed & 1:
                        pdwEffect[0] = 1
                    elif allowed & 2:
                        pdwEffect[0] = 2
                    elif allowed & 4:
                        pdwEffect[0] = 4
                    else:
                        pdwEffect[0] = 0

                def _emit_dropped(self, path: str) -> None:
                    """回调宿主：embedder 可能已被 release()（OLE 迟到回调）。"""
                    try:
                        embedder = self._embedder
                        if embedder is None or is_deleted(embedder):
                            return
                        embedder._on_dropped_file(path)
                    except Exception:  # noqa - COM 回调内异常会 abort 进程
                        pass

                def DragEnter(self, pDataObj, _grfKeyState, _pt, pdwEffect):
                    try:
                        self._normalize_drop_effect(pdwEffect)
                        self._cached_path = self._extract_h_drop(pDataObj)
                    except Exception:  # noqa
                        self._cached_path = ""
                    return 0

                def DragOver(self, _grfKeyState, _pt, pdwEffect):
                    try:
                        self._normalize_drop_effect(pdwEffect)
                    except Exception:  # noqa
                        pass
                    return 0

                def DragLeave(self):
                    if self._cached_path:
                        self._emit_dropped(self._cached_path)
                    self._cached_path = ""

                def Drop(self, pDataObj, _grfKeyState, _pt, pdwEffect):
                    try:
                        if self._cached_path:
                            self._emit_dropped(self._cached_path)
                        else:
                            path = self._extract_h_drop(pDataObj)
                            if path:
                                self._emit_dropped(path)
                        pdwEffect[0] = 0
                    except Exception:  # noqa
                        pass
                    self._cached_path = ""
                    return 0

                def _extract_h_drop(self, pDataObj) -> str:
                    try:
                        vtable = c_void_p.from_address(pDataObj).value
                        slot3_addr = vtable + 3 * ctypes.sizeof(c_void_p)
                        func_ptr = c_void_p.from_address(slot3_addr).value
                        GETDATA = ctypes.WINFUNCTYPE(
                            ctypes.c_long, c_void_p, c_void_p, c_void_p
                        )
                        GetData = GETDATA(func_ptr)

                        class _FormatEtc(ctypes.Structure):
                            _fields_ = [
                                ("cfFormat", ctypes.c_uint16),
                                ("_pad1", ctypes.c_uint16),
                                ("ptd", c_void_p),
                                ("dwAspect", c_uint32),
                                ("lindex", ctypes.c_int32),
                                ("tymed", c_uint32),
                            ]

                        class _StgMedium(ctypes.Structure):
                            _fields_ = [
                                ("tymed", c_uint32),
                                ("_pad1", c_uint32),
                                ("hGlobal", c_void_p),
                                ("pUnkForRelease", c_void_p),
                            ]

                        fmt = _FormatEtc()
                        fmt.cfFormat = 15
                        fmt.ptd = None
                        fmt.dwAspect = 1
                        fmt.lindex = -1
                        fmt.tymed = 1

                        stg = _StgMedium()
                        hr = GetData(pDataObj, byref(fmt), byref(stg))
                        if hr != 0:
                            return ""
                        if not stg.hGlobal:
                            OLE32.ReleaseStgMedium(byref(stg))
                            return ""
                        p = ctypes.windll.kernel32.GlobalLock(stg.hGlobal)
                        if not p:
                            OLE32.ReleaseStgMedium(byref(stg))
                            return ""
                        buf = create_unicode_buffer(260)
                        SHELL32.DragQueryFileW(c_void_p(p), 0, buf, 260)
                        result = buf.value
                        ctypes.windll.kernel32.GlobalUnlock(stg.hGlobal)
                        OLE32.ReleaseStgMedium(byref(stg))
                        return result
                    except Exception:  # noqa
                        return ""

            self._ole_drop_target = _ChromeDropTarget(self)
            pdt = cast(
                self._ole_drop_target._com_pointers_[_IDropTarget._iid_], c_void_p
            )
            OLE32.RevokeDragDrop(hwnd)
            hr = OLE32.RegisterDragDrop(hwnd, pdt)
            if hr == 0:
                self._ole_target_hwnd = hwnd
            else:
                self._ole_drop_target = None
        except Exception:  # noqa
            pass

    def _remove_drop_interceptor(self) -> None:
        if hasattr(self, "_ole_target_hwnd") and self._ole_target_hwnd:
            try:
                ctypes.windll.ole32.RevokeDragDrop(self._ole_target_hwnd)
            except Exception:  # noqa
                pass
            self._ole_target_hwnd = None
        self._ole_drop_target = None

    def release(self, destroy: bool = True) -> None:
        """释放浏览器窗口并终止浏览器进程。

        ``destroy`` 用于与基类 :class:`ElaWindowEmbedder` 签名保持一致 ——
        基类 ``_tryEmbedOnce`` 会调用 ``self.release(destroy=True)``，若本方法
        不接受该关键字就会抛 ``TypeError`` 并被外层 ``except Exception`` 吞掉，
        结果是 HWND 已经被 ``SetParent`` 挂到 Qt 父窗口上却没人还原（孤儿窗口）。

        **两步会话级副作用必须无条件执行**，本方法因此拆成三段：
        ``finish_launch``（放行共享启动队列）在最前且自带兜底，
        ``session.release()``（``_refcount`` 递减 / 终止进程）收在
        ``_finish_release`` 里且同样自带兜底。中间那 5 个局部清理步骤逐一
        兜底 —— 漏掉前者会让**之后所有实例永久排队、永远不启动**，漏掉后者
        会让**浏览器进程永不休**（实测：任一局部清理抛异常即可复现两条）。
        """
        session = self._session

        # ① 先放行共享启动队列，且不受后续异常影响
        if session is not None:
            try:
                session.finish_launch(self)
            except Exception:  # noqa: BLE001 - 队列放行失败也不能连累下面
                pass

        # ② 局部清理：逐步兜底，任一步失败只丢那一步
        for step in (
            self._stop_browser_embed_timer,
            self._cleanup_hwnd_polling,
            self._cleanup_debug_url_polling,
            self._restore_window_state,
            self._remove_drop_interceptor,
        ):
            try:
                step()
            except Exception:  # noqa: BLE001
                pass
        self._pending_window_title = None
        self._launch_pending = False

        # ③ 拆控制器 + 归还会话引用（无条件）
        self._finish_release(session)

    def _stop_browser_embed_timer(self) -> None:
        if self._browser_embedTimer:
            self._browser_embedTimer.stop()
            self._browser_embedTimer = None

    def _restore_window_state(self) -> None:
        """把浏览器窗口还原成认领前的父窗口 / 样式 / 位置。"""
        _unregister_chrome_hwnd(self._target_hwnd)
        if self._target_hwnd:
            try:
                win32gui.ShowWindow(self._target_hwnd, win32con.SW_HIDE)
                win32gui.SetParent(self._target_hwnd, self._original_parent)
                if self._original_style is not None:
                    style_no_visible = self._original_style & ~win32con.WS_VISIBLE
                    win32gui.SetWindowLong(
                        self._target_hwnd, win32con.GWL_STYLE, style_no_visible
                    )
                if self._original_ex_style is not None:
                    win32gui.SetWindowLong(
                        self._target_hwnd, win32con.GWL_EXSTYLE, self._original_ex_style
                    )
                if self._original_rect:
                    win32gui.SetWindowPos(
                        self._target_hwnd,
                        0,
                        self._original_rect[0],
                        self._original_rect[1],
                        self._original_rect[2] - self._original_rect[0],
                        self._original_rect[3] - self._original_rect[1],
                        win32con.SWP_HIDEWINDOW
                        | win32con.SWP_NOACTIVATE
                        | win32con.SWP_NOZORDER,
                    )
            except Exception as e:
                self._log(f"还原窗口状态失败: {e}", 30)

        self._target_hwnd = None
        self._original_parent = None
        self._original_style = None
        self._original_ex_style = None
        self._original_rect = None

    def _finish_release(self, session) -> None:
        """``release()`` 的收尾：拆控制器 + 归还会话引用，**无条件执行**。

        基类 ``release`` 与 ``_cleanup_browser`` 各自都会碰已销毁的 Qt 对象
        （CDP 断连 / 宿主先销毁），必须互不连累 —— 否则 ``_refcount`` 不减，
        浏览器进程永不休。
        """
        try:
            ElaWindowEmbedder.release(self, destroy=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._cleanup_browser()
        except Exception:  # noqa: BLE001
            pass
        if session is not None:
            self._session = None
            session.release()

    def enable_cookie_jar(self) -> None:
        """启用内部 cookie jar，记录所有 cookie。

        需在调用 embed() 之前调用。启用后可通过 get_cookie_header()
        或 get_cookies() 获取收集到的 cookie。
        """
        self._enable_cookie_jar = True

    def _jar_on_set_cookie(self, url: str, set_cookie_str: str) -> None:
        """从 Set-Cookie 响应头解析并存入 cookie store（含过期时间）。"""
        try:
            domain = urlparse(url).hostname or ""
            c = SimpleCookie()
            c.load(set_cookie_str)
            now = time.time()
            for name, morsel in c.items():
                morsel_domain = morsel.get("domain", "").lstrip(".")
                store_domain = morsel_domain or domain
                expires = self._parse_cookie_expiry(morsel, now)
                if expires is not None and expires <= now:
                    # Max-Age<=0 / 已过期 → 视为删除
                    self._cookie_store.get(store_domain, {}).pop(name, None)
                    self._cookie_expiry.pop((store_domain, name), None)
                    continue
                self._cookie_store.setdefault(store_domain, {})[name] = morsel.value
                self._cookie_expiry[(store_domain, name)] = expires
        except Exception:
            pass

    @staticmethod
    def _parse_cookie_expiry(morsel, now: float) -> Optional[float]:
        """解析 Max-Age / Expires，返回绝对时间戳（会话 cookie 返回 None）。"""
        max_age = morsel.get("max-age", "")
        if max_age:
            try:
                return now + float(max_age)
            except ValueError:
                pass
        expires = morsel.get("expires", "")
        if expires:
            try:
                return parsedate_to_datetime(expires).timestamp()
            except Exception:  # noqa
                pass
        return None

    def _jar_on_cookie_sent(self, url: str, cookie_str: str) -> None:
        """从请求 Cookie 头提取键值，补全 cookie store。"""
        try:
            domain = urlparse(url).hostname or ""
            for pair in cookie_str.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    name, val = pair.split("=", 1)
                    name = name.strip()
                    self._cookie_store.setdefault(domain, {})[name] = val.strip()
                    self._cookie_expiry.setdefault((domain, name), None)
        except Exception:
            pass

    def _iter_live_cookies(self):
        """遍历未过期的 ``(域, 名, 值)``，顺带剔除已过期条目。"""
        now = time.time()
        for store_domain, cookies in self._cookie_store.items():
            for name, val in list(cookies.items()):
                expires = self._cookie_expiry.get((store_domain, name))
                if expires is not None and expires <= now:
                    cookies.pop(name, None)
                    self._cookie_expiry.pop((store_domain, name), None)
                    continue
                yield store_domain, name, val

    def get_cookie_header(self, domain: str = "") -> str:
        """返回 Cookie 请求头字符串，例如 ``name1=value1; name2=value2``。

        便捷方法：所有域名的 cookie 会被合并成一条头，且不做 Secure / Path /
        SameSite 过滤；跨站复用时请自行按域名筛选。已过期的 cookie 会被剔除。

        :param domain: 可选，过滤指定域名（子串匹配）
        """
        parts: list[str] = []
        seen: set[str] = set()
        for store_domain, name, val in self._iter_live_cookies():
            if domain and domain not in store_domain:
                continue
            if name not in seen:
                seen.add(name)
                parts.append(f"{name}={val}")
        return "; ".join(parts)

    def get_cookies(self):
        """返回 ``httpx.Cookies`` 对象，可直接传给 httpx 请求。

        需要安装 httpx，否则抛出 ImportError。
        """
        try:
            import httpx
        except ImportError:
            raise ImportError("需要 httpx 库，请运行: uv pip install httpx")
        cookies = httpx.Cookies()
        for store_domain, name, val in self._iter_live_cookies():
            cookies.set(name, val, domain=store_domain)
        return cookies

    def closeEvent(self, event) -> None:
        """窗口关闭时释放资源。"""
        self.release()
        super().closeEvent(event)

    def deleteLater(self) -> None:
        self.release()
        super().deleteLater()
