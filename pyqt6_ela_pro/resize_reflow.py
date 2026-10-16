"""交互 resize（侧边栏动画 / 拖动窗口边框）期间的「钉尺寸 + 防抖重排」。

连续 resize 时每一帧都会让整页 invalidated → 上百个子控件各自重排 / 重绘（实测单帧
8.6ms；慢机按 2–5× 放大，侧边栏收缩动画直接掉帧）。挂上本工具后：连续 resize 期间把
控件**钉在起始尺寸**（本页不再重排 / 重绘），停手 ``delayMs`` 毫秒后一次性放开，交给
父布局按当前尺寸重排。

只作用于**页面 / 面板这一级**（顶层窗口的尺寸归窗口管理器，挂上会被忽略并记 WARNING）。
``ElaChatView`` 自带同一口径的 ``setResizeReflowDeferred``（聊天场景另有会话级参数）；
本工具给其余宿主页面用。
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

#: 连续 resize 的判据：两次 resize 间隔小于它就算「同一串」（动画 / 拖动）
_RAPID_GAP_S = 0.06
#: 停手后统一重排的默认延迟（毫秒）
_DEFAULT_DELAY_MS = 120
#: 挂在目标控件上的守卫实例属性名
_GUARD_ATTR = "_ela_resize_reflow_guard"


class _ResizeReflowGuard(QObject):
    """挂在目标控件上的事件过滤器 + 防抖定时器（作为子对象随控件销毁）。"""

    def __init__(self, widget: QWidget, delay_ms: int) -> None:
        super().__init__(widget)
        self._widget = widget
        self._delay_ms = max(0, int(delay_ms))
        self._last_resize_at = 0.0
        self._frozen = False
        self._enabled = True
        self._restore: tuple[int, int, int, int] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._release)
        widget.installEventFilter(self)

    # ── 接口 ──────────────────────────────────────────────

    def setEnabled(self, on: bool) -> None:  # noqa: N802 (与 Qt 命名一致)
        """关掉时立刻放开（恢复原始 min/max），不再冻结。"""
        self._enabled = bool(on)
        if not on:
            self._release()

    def isEnabled(self) -> bool:  # noqa: N802 (与 Qt 命名一致)
        return self._enabled

    def setDelayMs(self, ms: int) -> None:  # noqa: N802 (与 Qt 命名一致)
        self._delay_ms = max(0, int(ms))

    def delayMs(self) -> int:  # noqa: N802 (与 Qt 命名一致)
        return self._delay_ms

    # ── 内部 ──────────────────────────────────────────────

    def eventFilter(self, obj, event):  # noqa: N802 (Qt 钩子)
        if obj is self._widget and event.type() == QEvent.Type.Resize:
            self._on_resize()
        return False

    def _on_resize(self) -> None:
        if not self._enabled:
            return
        if self._widget.isWindow():
            # 顶层窗口的尺寸由窗口管理器驱动，钉住它只会打架
            if not getattr(self, "_warned_window", False):
                self._warned_window = True
                logger.warning(
                    "setResizeReflowDeferred 只作用于页面 / 面板控件，顶层窗口已忽略"
                )
            return
        now = time.perf_counter()
        rapid = (now - self._last_resize_at) < _RAPID_GAP_S
        self._last_resize_at = now
        if not rapid:
            return
        if not self._frozen:
            self._frozen = True
            self._restore = (
                self._widget.minimumWidth(),
                self._widget.minimumHeight(),
                self._widget.maximumWidth(),
                self._widget.maximumHeight(),
            )
            self._widget.setFixedSize(self._widget.width(), self._widget.height())
        self._timer.start(self._delay_ms)

    def _release(self) -> None:
        if not self._frozen:
            return
        self._frozen = False
        widget = self._widget
        if self._restore is not None:
            min_w, min_h, max_w, max_h = self._restore
            self._restore = None
            widget.setMinimumSize(min_w, min_h)
            widget.setMaximumSize(max_w, max_h)
        # 放开后让父布局按当前尺寸重排一次：先 invalidate（页面的尺寸约束刚变过）再跑 ——
        # 隐藏控件不会自动跑布局，可见控件也要等下一个 LayoutRequest 才动。
        widget.updateGeometry()
        parent = widget.parentWidget()
        if parent is not None:
            layout = parent.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
        widget.update()


def setResizeReflowDeferred(
    widget: QWidget, on: bool = True, delayMs: int = _DEFAULT_DELAY_MS
) -> None:
    """开关「连续 resize 期间的钉尺寸 + 防抖重排」（幂等）。

    典型用法：宿主的大页面 / 面板在构造时挂一次，侧边栏收缩动画、拖动窗口边框期间
    就不会逐帧重排整页（实测单帧 8.6ms → 0.0ms）。

    :param widget: 目标控件（页面 / 面板这一级；顶层窗口会被忽略并记 WARNING）
    :param on: ``False`` 关闭（立刻放开并恢复原始 min/max 约束）
    :param delayMs: 停手后统一重排的延迟（毫秒，缺省 120）
    """
    if widget is None:
        return
    guard = getattr(widget, _GUARD_ATTR, None)
    if guard is None:
        guard = _ResizeReflowGuard(widget, delayMs)
        setattr(widget, _GUARD_ATTR, guard)
    else:
        guard.setDelayMs(delayMs)
    guard.setEnabled(on)
