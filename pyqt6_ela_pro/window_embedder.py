"""
外部窗口嵌入器 (Windows + PyQt6)

可将指定的外部窗口嵌入到 QWidget 中，支持窗口查找、嵌入、释放等操作。
针对 Windows 7/10/11 做了兼容性优化。

使用示例:
    embedder = ElaWindowEmbedder(parent_widget)
    embedder.embedByHwnd(hwnd)
"""

from __future__ import annotations

import functools
import logging
import weakref
from typing import Optional, Any

try:
    import win32process  # type: ignore[attr-defined]
except ImportError:
    win32process = None

try:
    import win32api  # type: ignore[attr-defined]
    import win32con  # type: ignore[attr-defined]
    import win32gui  # type: ignore[attr-defined]
except ImportError:
    win32api = None
    win32con = None
    win32gui = None
from ._internal import is_deleted
from PyQt6.QtCore import pyqtSignal, QTimer
from PyQt6.QtWidgets import QWidget

from ._internal import catch_error
from PyQt6.QtGui import QWindow

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def _release_on_destroy(embedder) -> None:
    """``destroyed`` 收尾：把外部窗口从 Qt 父 HWND 上摘下来并恢复原状。

    ``weakref.proxy`` 是必须的：``destroyed`` 发出时 C++ 对象**正在析构**，
    这里只能碰纯 Python 属性（``_embeddedInfo`` / ``_attached_tid``）与
    Win32 API，绝不能再调任何 Qt 方法。
    """
    try:
        info = embedder._embeddedInfo
    except ReferenceError:
        return  # proxy 已失效
    if not info:
        return
    try:
        embedder._embeddedInfo = None
        embedder._isEmbedded = False
        hwnd = info.get("hwnd")
        if hwnd and win32gui.IsWindow(hwnd):
            # 关键：解除 SetParent，否则外部窗口随 Qt 父 HWND 一起销毁
            win32gui.SetParent(hwnd, 0)
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, info.get("style", 0))
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, info.get("exstyle", 0))
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        tid = getattr(embedder, "_attached_tid", None)
        if tid:
            try:
                win32api.GetCurrentThreadId()
                win32gui.AttachThreadInput(tid, win32api.GetCurrentThreadId(), False)
            except Exception:  # noqa: BLE001
                pass
            embedder._attached_tid = None
    except Exception:  # noqa: BLE001
        pass


class ElaWindowEmbedder(QWidget):
    """外部窗口嵌入器：把外部窗口 ``SetParent`` 到本控件，支持嵌入 / 释放 / 目标窗口轮询等待。

    信号：``windowEmbedded(hwnd)`` / ``windowReleased(hwnd)`` / ``windowNotFound(msg)``
    / ``embedError(msg)`` / ``embedTimeout()`` / ``fileDropped(path)``。
    """

    windowEmbedded = pyqtSignal(int)
    windowReleased = pyqtSignal(int)
    windowNotFound = pyqtSignal(str)
    embedError = pyqtSignal(str)
    embedTimeout = pyqtSignal()
    fileDropped = pyqtSignal(str)

    @staticmethod
    def _checkDependencies() -> None:
        if win32gui is None:
            raise ImportError(
                "ElaWindowEmbedder 需要 pywin32，请运行: uv pip install pywin32"
            )

    def __init__(self, parent: Optional[QWidget] = None):
        self._checkDependencies()
        super().__init__(parent=parent)

        self.setAcceptDrops(True)

        self._embeddedInfo: Optional[dict] = None
        self._embeddedWidget: Optional[QWidget] = None
        self._isEmbedded: bool = False
        self._resize_debounce: Optional[QTimer] = None
        self._resize_debounce_enabled: bool = True

        self._embedTimer = QTimer(self)
        self._embedTimer.timeout.connect(self._onEmbedTimerTimeout)
        self._findTimer = QTimer(self)
        self._findTimer.timeout.connect(self._onFindTimerTimeout)
        self._embedPendingHwnd: Optional[int] = None
        self._embedPendingTitle: Optional[str] = None
        self._embedPendingClassName: Optional[str] = None
        self._embedRetryCount: int = 0
        self._embedMaxRetries: int = 30
        self._attached_tid: Optional[int] = None
        self._install_destroy_hook()

    def _startEmbedTimer(self, hwnd: int) -> None:
        self._embedPendingHwnd = hwnd
        self._embedRetryCount = 0
        self._embedTimer.start(1000)

    def _stopEmbedTimer(self) -> None:
        self._embedTimer.stop()
        self._embedPendingHwnd = None
        self._embedRetryCount = 0

    def _onEmbedTimerTimeout(self) -> None:
        if self._embedPendingHwnd is None:
            self._stopEmbedTimer()
            return

        self._embedRetryCount += 1

        if self._embedRetryCount >= self._embedMaxRetries:
            self._stopEmbedTimer()
            self.embedTimeout.emit()
            return

        if self._tryEmbedOnce(self._embedPendingHwnd):
            self._stopEmbedTimer()

    def _startFindTimer(
        self, title: Optional[str] = None, class_name: Optional[str] = None
    ) -> None:
        self._embedPendingTitle = title
        self._embedPendingClassName = class_name
        self._embedRetryCount = 0
        self._findTimer.start(1000)

    def _stopFindTimer(self) -> None:
        self._findTimer.stop()
        self._embedPendingTitle = None
        self._embedPendingClassName = None

    def _onFindTimerTimeout(self) -> None:
        self._embedRetryCount += 1

        if self._embedRetryCount >= self._embedMaxRetries:
            self._stopFindTimer()
            self.embedTimeout.emit()
            return

        hwnd = 0
        if self._embedPendingTitle:
            hwnd = self.findWindowByTitle(
                self._embedPendingTitle, self._embedPendingClassName
            )
        elif self._embedPendingClassName:
            hwnd = self.findWindowByClass(self._embedPendingClassName)

        if hwnd:
            self._stopFindTimer()
            self.embedByHwnd(hwnd)
        else:
            self.windowNotFound.emit(f"等待窗口中... ({self._embedRetryCount}s)")

    @staticmethod
    def isWindowValid(hwnd: int) -> bool:
        """检查窗口句柄是否有效"""
        if not hwnd:
            return False
        try:
            return bool(win32gui.IsWindow(hwnd) and win32gui.IsWindowEnabled(hwnd))
        except Exception:  # noqa
            return False

    def _tryEmbedOnce(self, hwnd: int) -> bool:
        """尝试嵌入单个窗口"""
        if not self.isWindowValid(hwnd):
            return False

        window_info = self.getWindowInfo(hwnd)
        if not window_info:
            return False

        if self._embeddedInfo:
            # **显式基类实现，不是虚分派**：对 ``ElaBrowserEmbedder`` 而言
            # ``self.release(destroy=True)`` 会终止整个共享浏览器进程
            # （那是它的语义，不是「回滚一次部分嵌入」）。这里只回滚本次。
            ElaWindowEmbedder.release(self, destroy=True)

        # **两个都必须在 try 之前预置**：
        # ① ``orig_style`` 原先在下面那个**嵌套 try** 里才赋值，而它在
        #    外层 ``except`` 里被使用 —— 182~191 之间任何一步抛异常
        #    （``QWindow.fromWinId`` 对已销毁窗口返回 None、
        #    ``createWindowContainer`` 对非顶层 HWND 返回 nullptr、
        #    ``window_info`` 缺键）就变成 ``UnboundLocalError``，
        #    而它是从 ``except`` 块里抛出的 -> 直接逃出整个函数。
        #    两条入口都在 Qt 回调链上（``_onEmbedTimerTimeout`` 的
        #    ``QTimer.timeout``、``embedByHwnd``）= 进程 0xC0000409 静默终止。
        # ② ``widget`` 同理：183 行创建的容器若在 194 行之后失败，
        #    原补偿路径只把 ``self._embeddedWidget`` 置 None、**从不
        #    deleteLater 它** —— 每次失败泄漏一个容器（重试循环最多 30 个），
        #    且它们继续参与 resize 布局。
        orig_style: Optional[int] = None
        orig_exstyle: Optional[int] = None
        widget = None
        try:
            q_window = QWindow.fromWinId(hwnd)
            if q_window is None:
                raise RuntimeError(f"invalid window handle: {hwnd}")
            widget = QWidget.createWindowContainer(q_window, self)
            if widget is None:
                raise RuntimeError(
                    f"createWindowContainer returned null (not a top-level window?): {hwnd}"
                )
            widget.setObjectName("embedded_window")
            widget._chrome_hwnd = hwnd

            widget.hwnd = hwnd
            widget.phwnd = window_info["phwnd"]
            # 别叫 ``style``/``exstyle``：那会**遮蔽 ``QWidget.style()`` 方法**，
            # 宿主（或 Ela 的 C++ 绑定层）任何 ``container.style()`` 都变TypeError。
            # 改成 win_style / win_exstyle。
            widget.win_style = window_info["style"]
            widget.win_exstyle = window_info["exstyle"]
            widget.wrect = window_info["wrect"]

            # 先快照原样式：失败回滚时要靠它把外部窗口恢复原状
            try:
                orig_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                orig_exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            except Exception:  # noqa: BLE001
                orig_style = orig_exstyle = None

            win32gui.SetParent(hwnd, int(self.winId()))

            # ── 修复 IME 输入法无法激活的问题 ──

            # SetParent 后嵌入窗口的线程与 Qt 线程的输入状态不再共享，
            # 通过 AttachThreadInput 使两线程共享 IME 上下文和焦点状态。
            try:
                target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
                current_tid = win32api.GetCurrentThreadId()
                if target_tid != current_tid:
                    win32gui.AttachThreadInput(target_tid, current_tid, True)
                    self._attached_tid = target_tid
            except Exception:  # noqa
                pass

            current_style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            new_style = current_style | win32con.WS_CLIPSIBLINGS
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, new_style)

            current_exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            new_exstyle = current_exstyle | win32con.WS_EX_NOPARENTNOTIFY
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, new_exstyle)

            widget.setGeometry(0, 0, self.width(), self.height())
            widget.show()

            self._embeddedInfo = window_info.copy()
            self._embeddedWidget = widget
            self._isEmbedded = True

            self._showEmbeddedWindow()
            self.windowEmbedded.emit(hwnd)
            return True

        except Exception as e:
            logger.warning(f"嵌入窗口失败: {e}")
            # 回收半成品容器：它还是 self 的 child，不删就每次失败泄漏一个
            if widget is not None:
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except RuntimeError:
                    pass
            # 回滚：SetParent 之后的任何一步失败都不能留下孤儿 HWND。
            # 此时 _embeddedInfo 还没赋值，release() 会在开头直接 return，
            # 于是外部窗口会一直挂在 Qt 父窗口上（父窗口销毁时连带销毁别人的
            # 窗口），_attached_tid 也永远 detach 不掉。
            self._rollbackPartialEmbed(hwnd, orig_style, orig_exstyle)
            return False

    def _rollbackPartialEmbed(
        self, hwnd: int, orig_style: Optional[int], orig_exstyle: Optional[int]
    ) -> None:
        """``SetParent`` 之后失败的补偿：还原父子关系、窗口样式与线程输入绑定。"""
        if self._attached_tid:
            try:
                current_tid = win32api.GetCurrentThreadId()
                if self._attached_tid != current_tid:
                    win32gui.AttachThreadInput(self._attached_tid, current_tid, False)
            except Exception:  # noqa: BLE001 - 补偿路径不允许再抛
                pass
            self._attached_tid = 0
        try:
            win32gui.SetParent(hwnd, 0)
            if orig_style is not None:
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, orig_style)
            if orig_exstyle is not None:
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, orig_exstyle)
        except Exception:  # noqa: BLE001
            pass
        self._embeddedInfo = None
        self._embeddedWidget = None
        self._isEmbedded = False

    def _native_client_size(self) -> tuple[int, int]:
        """外部窗口应使用的**原生**客户区尺寸。

        ``SetParent`` 后外部窗口的父级是本控件的 HWND，其坐标系是 Win32 原生
        坐标；高 DPI 缩放（``AA_EnableHighDpiScaling``）下 ``self.width()`` /
        ``self.height()`` 是逻辑值，直接拿去 ``SetWindowPos`` 会让嵌入窗口小一圈。
        取父窗口客户区即可自动适配（100% 缩放下与控件尺寸一致）。
        """
        try:
            rect = win32gui.GetClientRect(int(self.winId()))
            width = int(rect[2] - rect[0])
            height = int(rect[3] - rect[1])
            if width > 0 and height > 0:
                return width, height
        except Exception:  # noqa
            pass
        return self.width(), self.height()

    def _showEmbeddedWindow(self) -> None:
        """显示已嵌入的窗口"""
        if self._embeddedInfo:
            hwnd = self._embeddedInfo.get("hwnd")
            if hwnd:
                try:
                    width, height = self._native_client_size()
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                    win32gui.SetWindowPos(
                        hwnd,
                        0,
                        0,
                        0,
                        width,
                        height,
                        win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
                    )
                except Exception as e:
                    logger.warning(f"显示嵌入窗口失败: {e}")

    def findWindowByTitle(self, title: str, class_name: Optional[str] = None) -> int:
        """按标题（包含匹配，可选类名精确匹配）找句柄，未找到返回 0。"""
        if not title:
            return 0

        results: list[int] = []

        def enum_callback(hwnd: int, _: Any) -> bool:
            if win32gui.IsWindow(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if title in window_title:
                    if class_name:
                        if win32gui.GetClassName(hwnd) == class_name:
                            results.append(hwnd)
                    else:
                        results.append(hwnd)
            return True

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as e:
            self.embedError.emit(f"查找窗口时出错: {str(e)}")
            return 0

        return results[0] if results else 0

    def findWindowByClass(self, class_name: str) -> int:
        """按窗口类名（精确匹配）找句柄，未找到返回 0。"""
        if not class_name:
            return 0

        try:
            return win32gui.FindWindow(class_name, None)
        except Exception as e:
            self.embedError.emit(f"查找窗口时出错: {str(e)}")
            return 0

    def getWindowInfo(self, hwnd: int) -> Optional[dict]:
        """窗口详情（``hwnd`` / ``phwnd`` / ``title`` / ``class_name`` / ``style`` /
        ``exstyle`` / ``wrect``），句柄无效时返回 ``None``。"""
        if not self.isWindowValid(hwnd):
            return None

        try:
            phwnd = win32gui.GetParent(hwnd)
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            wr = win32gui.GetWindowRect(hwnd)
            wrect = (wr[0], wr[1], wr[2] - wr[0], wr[3] - wr[1])

            return {
                "hwnd": hwnd,
                "phwnd": phwnd,
                "title": title,
                "class_name": class_name,
                "style": style,
                "exstyle": exstyle,
                "wrect": wrect,
            }
        except Exception as e:
            self.embedError.emit(f"获取窗口信息失败: {str(e)}")
            return None

    def embedByHwnd(self, hwnd: int) -> bool:
        """按句柄嵌入；先试一次，失败就转入等待窗口的轮询。"""
        if self._embeddedInfo:
            self.release()

        self._stopFindTimer()

        if self._tryEmbedOnce(hwnd):
            return True

        self._startEmbedTimer(hwnd)
        return True

    def embedByTitle(self, title: str, class_name: Optional[str] = None) -> bool:
        """按标题嵌入；找不到就发 ``windowNotFound`` 并转入等待。"""
        hwnd = self.findWindowByTitle(title, class_name)

        if not hwnd:
            self.windowNotFound.emit(f"未找到标题包含 '{title}' 的窗口，正在等待...")
            self._startFindTimer(title=title, class_name=class_name)
            return True

        return self.embedByHwnd(hwnd)

    def embedByClass(self, class_name: str) -> bool:
        """按类名嵌入；找不到就发 ``windowNotFound`` 并转入等待。"""
        hwnd = self.findWindowByClass(class_name)

        if not hwnd:
            self.windowNotFound.emit(f"未找到类名为 '{class_name}' 的窗口，正在等待...")
            self._startFindTimer(class_name=class_name)
            return True

        return self.embedByHwnd(hwnd)

    def release(self, destroy: bool = False) -> bool:
        """释放已嵌入的窗口（``destroy=True`` 时不恢复原状态直接销毁）。"""
        self._stopEmbedTimer()
        self._stopFindTimer()

        if not self._embeddedInfo:
            return True

        try:
            # 分离之前 AttachThreadInput 附加的线程输入状态
            if self._attached_tid:
                try:
                    current_tid = win32api.GetCurrentThreadId()
                    win32gui.AttachThreadInput(self._attached_tid, current_tid, False)
                except Exception:
                    pass
                self._attached_tid = None

            info = self._embeddedInfo
            hwnd = info["hwnd"]

            if self._embeddedWidget:
                self._embeddedWidget.close()
                self._embeddedWidget.deleteLater()
                self._embeddedWidget = None

            if destroy:
                released_hwnd = hwnd
                self._embeddedInfo = None
                self._isEmbedded = False
                self.windowReleased.emit(released_hwnd)
                return True

            phwnd = info["phwnd"]
            style = info["style"]
            exstyle = info["exstyle"]
            wrect = info["wrect"]

            win32gui.SetParent(hwnd, phwnd)

            win32gui.SetWindowLong(
                hwnd, win32con.GWL_STYLE, style | win32con.WS_VISIBLE
            )
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, exstyle)

            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.SetWindowPos(
                hwnd, 0, wrect[0], wrect[1], wrect[2], wrect[3], win32con.SWP_NOACTIVATE
            )

            released_hwnd = hwnd
            self._embeddedInfo = None
            self._isEmbedded = False

            self.windowReleased.emit(released_hwnd)
            return True

        except Exception as e:  # noqa
            error_msg = f"嵌入窗口失败: {str(e)}"
            self.embedError.emit(error_msg)
            return False

    @catch_error
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._isEmbedded or not self._embeddedWidget or not self._embeddedInfo:
            return
        if self._resize_debounce_enabled:
            if self._resize_debounce is None:
                self._resize_debounce = QTimer(self)
                self._resize_debounce.setSingleShot(True)
                self._resize_debounce.timeout.connect(self._apply_debounced_resize)
            self._resize_debounce.start(150)
        else:
            self._apply_debounced_resize()

    def setResizeDebounceEnabled(self, enabled: bool) -> None:
        """resize 节流开关（默认启用，150ms；关闭时立即响应）。"""
        self._resize_debounce_enabled = enabled
        if not enabled and self._resize_debounce:
            self._resize_debounce.stop()

    @catch_error
    def _apply_debounced_resize(self) -> None:
        """把嵌入容器与外部窗口调到新尺寸（``resizeEvent`` 的节流落点）。

        **必须有兜底**：``resizeEvent`` 上的 ``@catch_error`` 护不住这条 ——
        默认开启 150ms 节流时resizeEvent 只 ``start()`` 定时器，真正干活的是
        这里的 ``QTimer.timeout`` 槽。而外部窗口（Chrome）崩溃 / 被杀 /
        被别的代码关掉之后 hwnd 失效，``SetWindowPos`` 抛
        ``pywintypes.error(1400, 'Invalid window handle')``；包装器被删时
        ``setGeometry`` 抛 ``RuntimeError``。两者都会**穿过 Qt 回调链** =
        进程 0xC0000409 零 traceback 终止。
        """
        if not self._embeddedInfo or not self._embeddedWidget:
            return
        if is_deleted(self._embeddedWidget):
            return
        width = self.width()
        height = self.height()
        self._embeddedWidget.setGeometry(0, 0, width, height)
        hwnd = self._embeddedInfo.get("hwnd")
        if hwnd and not win32gui.IsWindow(hwnd):
            # 外部窗口已经没了：别再对着死 hwnd 发消息
            return
        if hwnd:
            # Qt 容器用逻辑尺寸，外部窗口用原生客户区尺寸（高 DPI 下不一致）
            native_width, native_height = self._native_client_size()
            win32gui.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                native_width,
                native_height,
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
            )

    def deleteLater(self) -> None:
        if self._embeddedInfo:
            self.release()
        super().deleteLater()

    def closeEvent(self, event) -> None:
        if self._embeddedInfo:
            self.release()
        super().closeEvent(event)

    def _install_destroy_hook(self) -> None:
        """挂上 ``destroyed`` 收尾（构造末尾调一次）。

        **必须是模块级函数 + ``functools.partial``**：PyQt6 不会调用「绑定到
        自身」的 ``destroyed`` 槽（实测 ``sip.delete()`` 下绑方法触发 0 次，
        ``self.destroyed.connect(self._x)`` 等于清理从来没发生过），而这正好是
        这个仓库反复踩到的形状。
        """
        self.destroyed.connect(
            functools.partial(_release_on_destroy, weakref.proxy(self))
        )

    @property
    def embeddedWindowInfo(self) -> Optional[dict]:
        """返回已嵌入窗口的信息副本"""
        return self._embeddedInfo.copy() if self._embeddedInfo else None

    @property
    def hasEmbeddedWindow(self) -> bool:
        """当前是否已有嵌入的窗口"""
        return self._embeddedInfo is not None
