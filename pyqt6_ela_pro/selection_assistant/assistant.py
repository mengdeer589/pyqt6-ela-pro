"""划词助手组件：监视全局划词手势，取词后在落点弹出动作条。

动作项由 ``setActions`` 定义，组件只发信号；用法见 ``docs/selection-assistant.md``。"""

from __future__ import annotations

import functools
import time
from typing import Iterable, List, Optional, Union

from .._internal import is_deleted
from PyQt6.QtCore import QObject, QPoint, pyqtSignal

from ..menu_item import ElaMenuItem
from ._native import (
    ElaMouseMonitor,
    _warn_once,
    safe_connect,
    to_logical_pos,
    window_pid_at,
    window_rect_at,
)
from .capture import ElaClipboardCapture
from .popup import ElaSelectionPopup

#: 触发拖选所需的最小位移（像素）
_DEFAULT_DRAG_THRESHOLD = 4
#: 双击选词判定的最大间隔（毫秒）
_DEFAULT_DOUBLE_CLICK_MS = 400
#: 双击选词判定的最大位移（像素）
_DOUBLE_CLICK_SLOP = 6


def _is_deleted(obj) -> bool:  # noqa: ANN001
    """C++ 对象是否已析构（``destroyed`` 槽里必须先问一句）。"""
    try:
        return bool(is_deleted(obj))
    except (RuntimeError, TypeError):
        return True


def _cleanup_on_destroy(assistant, _object=None) -> None:  # noqa: ANN001
    """助手析构时收尾：停监视器 + 回收无父的动作条浮窗。
    **必须是普通函数，不能是绑定方法**：PyQt6 不会调用绑定到发出信号的
    对象自身的 ``destroyed`` 槽。写成 ``self.destroyed.connect(self._on_destroyed)``
    """
    monitor = getattr(assistant, "_monitor", None)
    if monitor is not None and not _is_deleted(monitor):
        # 注入的 monitor 不是助手的子对象，必须显式停；懒创建的那个此时已被
        # Qt 先行 deleteChildren() 析构，判存活后才碰。
        try:
            monitor.stop()
        except Exception:  # noqa: BLE001 - 析构路径不允许异常逃逸
            pass
    popup = getattr(assistant, "_popup", None)
    if popup is None or _is_deleted(popup):
        return
    try:
        popup.hide()
        popup.deleteLater()
    except Exception:  # noqa: BLE001
        pass


class ElaSelectionAssistant(QObject):
    """全局划词助手：监视划词 → 取词 → 弹出动作条 → 发信号。

    :param parent: 父对象
    :param monitor: 鼠标监视后端（默认懒创建，测试可注入假实现）
    :param capture: 取词后端（默认 :class:`ElaClipboardCapture`，同上）

    取词会向前台窗口注入 Ctrl+C（没有别的通道读选区）；拖选与拖窗口 /
    滚动条 / 文件在鼠标层面无法区分，注入到终端里就是 SIGINT，因此未设
    :meth:`setCaptureFilter` 时拖选默认不取词（只保留双击选词），被拦截时
    发 :attr:`captureBlocked`。
    """

    #: 启用状态变化
    enabledChanged = pyqtSignal(bool)
    #: 捕获到选中文本（参数：文本、落点逻辑坐标）
    selectionCaptured = pyqtSignal(str, QPoint)
    #: 本次手势**没有向前台注入 Ctrl+C**（参数：原因，见
    #: :attr:`captureBlocked` 的取值说明）
    #: 点击动作（参数：动作 id、选中文本、落点逻辑坐标）
    actionTriggered = pyqtSignal(str, str, QPoint)
    #: 动作条弹出
    popupShown = pyqtSignal(str, QPoint)
    #: 动作条隐藏
    popupHidden = pyqtSignal()
    #: 本次手势**没有注入 Ctrl+C**（被取词闸门拦下），参数为原因：
    #: ``"drag-without-filter"``（默认闸门，未设过滤器）/ ``"filter-denied"``
    #: （宿主过滤器返回 False）/ ``"filter-error"``（过滤器抛异常）
    captureBlocked = pyqtSignal(str)
    #: 错误（监视启动失败 / 取词异常等）
    errorOccurred = pyqtSignal(str)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        monitor=None,
        capture=None,
    ) -> None:
        super().__init__(parent)
        self._enabled = False
        self._monitor = monitor
        self._capture = capture if capture is not None else ElaClipboardCapture(self)
        self._popup = ElaSelectionPopup()
        # 动作条菜单项完全由宿主定义（setActions），默认无动作
        self._actions: List[ElaMenuItem] = []
        self._capture_filter = None
        self._require_filter_for_drag = True
        self._min_length = 1
        self._drag_threshold = _DEFAULT_DRAG_THRESHOLD
        self._double_click_ms = _DEFAULT_DOUBLE_CLICK_MS

        self._text = ""
        self._pos = QPoint()
        self._capture_point = QPoint()
        self._down = None
        self._press_in_popup = False
        self._last_click_at = 0.0
        self._last_click_pos = None

        if self._monitor is not None:
            self._connect_monitor()
        self._popup.actionTriggered.connect(self._on_action)
        self._popup.hidden.connect(self.popupHidden)
        self._capture.captured.connect(self._on_captured)
        self._capture.failed.connect(self._on_capture_failed)
        # 只能用普通 callable 连接 destroyed：绑定方法形式的槽 PyQt6 不会调用
        # （见 _cleanup_on_destroy 的说明）
        self.destroyed.connect(functools.partial(_cleanup_on_destroy, self))

    def isEnabled(self) -> bool:
        """是否已启用（鼠标监视是否在运行）。"""
        return self._enabled

    def setEnabled(self, on: bool) -> bool:
        """启用 / 停用划词助手；返回操作后的启用状态。
        停用会顺带**取消在途取词** —— 取词是异步的（延迟 + 轮询，共
        100~350ms），若不取消，用户在这段时间内关掉助手，已经发出的
        """
        on = bool(on)
        if on == self._enabled:
            return self._enabled
        if on:
            if not self._ensure_monitor():
                return False
        else:
            if self._monitor is not None:
                self._monitor.stop()
            self._cancelCapture()
            self.hide()
        self._enabled = on
        self.enabledChanged.emit(on)
        return self._enabled

    def setActions(self, actions: Iterable[Union[ElaMenuItem, dict]]) -> None:
        """整体替换动作条菜单项（由宿主定义；支持 ``ElaMenuItem`` 或同名字典）。

        未设置动作时取词仍会发出 ``selectionCaptured``，但不弹出动作条。
        """
        self._actions = [self._coerce_action(item) for item in actions or []]
        self._popup.setActions(self._actions)

    def actions(self) -> List[ElaMenuItem]:
        """动作列表快照。"""
        return list(self._actions)

    def setMinSelectionLength(self, length: int) -> None:
        """设置触发弹窗的最小文本长度（默认 1）。"""
        self._min_length = max(1, int(length))

    def minSelectionLength(self) -> int:
        """触发弹窗的最小文本长度。"""
        return self._min_length

    def setDragThreshold(self, pixels: int) -> None:
        """设置拖选判定的最小位移像素数（默认 4）。"""
        self._drag_threshold = max(1, int(pixels))

    def dragThreshold(self) -> int:
        """拖选判定的最小位移像素数。"""
        return self._drag_threshold

    def setDoubleClickMs(self, ms: int) -> None:
        """设置双击选词判定的最大间隔毫秒数（默认 400）。"""
        self._double_click_ms = max(1, int(ms))

    def doubleClickMs(self) -> int:
        """双击选词判定的最大间隔毫秒数。"""
        return self._double_click_ms

    def setCaptureFilter(self, predicate) -> None:
        """设置取词过滤器：``predicate(down, up) -> bool``，返回 ``False`` 时
        本次手势**不取词**（不注入 Ctrl+C）；两个参数都是按下 / 抬起点的
        **物理像素**坐标。

        过滤器异常按**拦截**处理（宁可少取一次词，也不向未知应用注入
        Ctrl+C），并发 ``RuntimeWarning`` + ``captureBlocked("filter-error")``。

        典型用途是跳过拖窗口 / 拖滚动条 / 拖文件；不想自己写就用
        :meth:`builtinDragFilter`。传 ``None`` 清空过滤器。
        """
        self._capture_filter = predicate

    def captureFilter(self):  # noqa: ANN201
        """当前取词过滤器（未设置时为 ``None``）。"""
        return self._capture_filter

    def setRequireFilterForDrag(self, required: bool) -> None:
        """拖选取词是否必须先设过滤器（默认 ``True`` = 必须）。
        拖选与拖窗口 / 滚动条 / 文件在鼠标层面无法区分，而拖选取词要向前台
        窗口注入 Ctrl+C —— 在终端 / 控制台里就是中断信号。双击选词不受本
        """
        self._require_filter_for_drag = bool(required)

    def requireFilterForDrag(self) -> bool:
        """拖选取词当前是否要求先设过滤器（默认 ``True``）。"""
        return self._require_filter_for_drag

    @staticmethod
    def builtinDragFilter(maxDragPx: int = 600, borderPx: int = 6):
        """内置的启发式拖选过滤器（``predicate(down, up) -> bool``）。

        刻意只做**不依赖具体应用**的保守判断，宁可放过（少弹一次动作条）
        也不误伤正常操作：同一窗口内（``window_pid_at`` 相同且非 0）、位移
        不超过 ``maxDragPx`` 像素、按下点不在目标窗口边框 ``borderPx`` 内。

        仍会漏掉滚动区横向拖动等场景，建议再叠加宿主自己的规则（例如限定
        前台进程）。
        """

        def _filter(down, up) -> bool:
            try:
                dx = int(up[0]) - int(down[0])
                dy = int(up[1]) - int(down[1])
                if dx * dx + dy * dy > int(maxDragPx) ** 2:
                    return False
                down_pid = window_pid_at(int(down[0]), int(down[1]))
                if down_pid == 0 or down_pid != window_pid_at(int(up[0]), int(up[1])):
                    return False
                if borderPx > 0:
                    rect = window_rect_at(int(down[0]), int(down[1]))
                    if rect is not None:
                        left, top, right, bottom = rect
                        m = int(borderPx)
                        if (
                            int(down[0]) <= left + m
                            or int(down[1]) <= top + m
                            or int(down[0]) >= right - m
                            or int(down[1]) >= bottom - m
                        ):
                            return False
                return True
            except Exception as exc:  # noqa: BLE001 - Win32 查询不可信
                _warn_once("内置拖选过滤器查询失败，已拦截本次手势：", exc)
                return False

        return _filter

    def popup(self) -> ElaSelectionPopup:
        """获取动作条浮窗（紧凑模式 / 偏移等外观配置在这里做）。"""
        return self._popup

    def capture(self):  # noqa: ANN201
        """获取取词后端（剪贴板恢复 / 各类延迟等参数在这里配）。
        注入自定义后端时直接对它配置即可 —— 助手不再用 ``isinstance``
        判断具体类型（那样对注入的后端会**静默失效**）。
        """
        return self._capture

    def showFor(self, text: str, pos: QPoint) -> None:
        """对指定文本 / 落点弹出动作条（无动作时只发 ``selectionCaptured``）。

        始终发出 ``selectionCaptured``；有动作时弹出动作条并发 ``popupShown``。
        """
        self._text = text or ""
        self._pos = QPoint(pos)
        self.selectionCaptured.emit(self._text, QPoint(self._pos))
        # 不要在这里再 setActions()：动作列表在 setActions() 时已推给 popup，
        # 每弹一次就 _rebuild() 等于把全部按钮销毁重建（连带重建每个 tooltip），
        # 连续划词时是纯浪费 + 闪烁。
        if not self._popup.hasActions():
            return
        self._popup.popupAt(self._pos)
        self.popupShown.emit(self._text, QPoint(self._pos))

    def hide(self) -> None:
        """隐藏动作条（未显示时无动作）。"""
        if self._popup.isVisible():
            self._popup.hide()

    def selectedText(self) -> str:
        """最近一次捕获 / 手动显示时的文本。"""
        return self._text

    def _connect_monitor(self) -> None:
        # 走 safe_connect：PyQt6 中槽抛异常会直接 abort（0xC0000409），
        # 而这些槽会触发 capture() -> Win32 SendInput，宿主异常不能拖垮整个应用。
        safe_connect(
            self._monitor, "leftPressed", self._on_left_pressed, "on_left_pressed"
        )
        safe_connect(
            self._monitor, "leftReleased", self._on_left_released, "on_left_released"
        )
        safe_connect(
            self._monitor, "otherPressed", self._on_other_pressed, "on_other_pressed"
        )
        safe_connect(self._monitor, "wheelScrolled", self._on_wheel, "on_wheel")

    def _ensure_monitor(self) -> bool:
        if self._monitor is None:
            try:
                self._monitor = ElaMouseMonitor(self)
            except Exception as exc:  # noqa: BLE001 - 平台 / 导入兜底
                self.errorOccurred.emit(f"鼠标监视不可用：{exc}")
                return False
            self._connect_monitor()
        try:
            self._monitor.start()
        except Exception as exc:  # noqa: BLE001 - 监视启动兜底
            self.errorOccurred.emit(str(exc))
            return False
        return True

    def _on_left_pressed(self, point) -> None:
        self._down = point
        self._press_in_popup = False
        if self._popup.isVisible():
            logical = to_logical_pos(*point)
            if self._popup.frameGeometry().contains(logical):
                self._press_in_popup = True
            else:
                self.hide()

    def _on_left_released(self, down, up) -> None:
        if not self._enabled or up is None:
            return
        if self._press_in_popup:
            self._press_in_popup = False
            return
        if self._popup.isVisible() and self._popup.frameGeometry().contains(
            to_logical_pos(*up)
        ):
            return
        down = tuple(down or up)
        dx = int(up[0]) - int(down[0])
        dy = int(up[1]) - int(down[1])
        dragged = dx * dx + dy * dy >= self._drag_threshold**2

        if dragged:
            # 拖拽不算「点击」：不记录，且打断双击序列 —— 否则拖选后在同一
            # 点马上点一下会被误判成双击，多注入一次 Ctrl+C。
            self._last_click_at = 0.0
            self._last_click_pos = None
            if self._allow_capture(down, up, "drag"):
                self._start_capture(up)
            return

        now = time.monotonic()
        double = (
            self._last_click_pos is not None
            and (now - self._last_click_at) * 1000.0 <= self._double_click_ms
            and abs(int(up[0]) - self._last_click_pos[0]) <= _DOUBLE_CLICK_SLOP
            and abs(int(up[1]) - self._last_click_pos[1]) <= _DOUBLE_CLICK_SLOP
        )
        self._last_click_at = now
        self._last_click_pos = (int(up[0]), int(up[1]))
        if double and self._allow_capture(down, up, "double"):
            self._start_capture(up)

    def _allow_capture(self, down, up, kind: str = "drag") -> bool:
        """取词闸门（决定是否向前台窗口注入 Ctrl+C）。

        :param kind: ``"drag"`` / ``"double"``（双击选词）。

        判定顺序：① 宿主过滤器说话（异常按拦截）；② 无过滤器且是拖选时，
        受 :meth:`requireFilterForDrag` 约束（**默认拦截**，理由见那里）；
        ③ 其余情况放行。拦截时发 ``captureBlocked`` 并告警一次。
        """
        predicate = self._capture_filter
        if predicate is None:
            if kind == "drag" and self._require_filter_for_drag:
                _warn_once(
                    "拖选取词被默认闸门拦截（未设置取词过滤器）："
                    "拖选要向前台注入 Ctrl+C，终端里等于 SIGINT。"
                    "需要拖选取词请 setCaptureFilter("
                    "ElaSelectionAssistant.builtinDragFilter())，"
                    "或 setRequireFilterForDrag(True) 显式打开：",
                    RuntimeError("blocked"),
                )
                self.captureBlocked.emit("drag-without-filter")
                return False
            return True
        try:
            allowed = bool(predicate(tuple(down), tuple(up)))
        except Exception as exc:  # noqa: BLE001 - 宿主过滤器不可信
            _warn_once("取词过滤器异常，已拦截本次手势：", exc)
            self.captureBlocked.emit("filter-error")
            return False
        if not allowed:
            self.captureBlocked.emit("filter-denied")
        return allowed

    def _on_other_pressed(self, _point) -> None:
        self.hide()

    def _on_wheel(self) -> None:
        self.hide()

    def _start_capture(self, point) -> None:
        self._capture_point = to_logical_pos(*point)
        self._capture.capture()

    def _on_captured(self, text: str) -> None:
        # 取词是异步的（延迟 + 轮询）：结果到达时可能已经被关掉 / 换掉了，
        # 此时的 _enabled 才是决定要不要弹窗的依据（_on_left_released 里的
        # 检查只覆盖发起那一刻）。
        if not self._enabled:
            return
        text = text or ""
        if len(text.strip()) < self._min_length:
            return
        self.showFor(text, self._capture_point)

    def _on_capture_failed(self) -> None:
        self.hide()

    def _cancelCapture(self) -> None:  # noqa: N802 (Qt 命名)
        """取消在途取词（取词后端可选实现 ``cancel()``）。"""
        cancel = getattr(self._capture, "cancel", None)
        if cancel is None:
            return
        try:
            cancel()
        except Exception:  # noqa: BLE001 - 取词后端可能是宿主自定义实现
            pass

    def _on_action(self, actionId: str) -> None:
        self.actionTriggered.emit(actionId, self._text, QPoint(self._pos))

    @staticmethod
    def _coerce_action(item: Union[ElaMenuItem, dict]) -> ElaMenuItem:
        if isinstance(item, ElaMenuItem):
            return item
        if isinstance(item, dict):
            return ElaMenuItem(
                id=str(item.get("id") or ""),
                label=str(item.get("label") or item.get("id") or ""),
                icon=item.get("icon"),
                tooltip=str(item.get("tooltip") or ""),
                enabled=bool(item.get("enabled", True)),
            )
        raise TypeError(f"不支持的动作类型：{type(item)!r}")


__all__ = ["ElaSelectionAssistant"]
