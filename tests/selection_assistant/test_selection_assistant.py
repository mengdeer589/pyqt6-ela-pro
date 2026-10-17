"""ElaSelectionAssistant 测试：手势识别、取词链路与动作信号（注入假后端）。"""

from __future__ import annotations

import time

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QPoint, pyqtSignal

from pyqt6_ela_pro import ElaMenuItem, ElaSelectionAssistant
from pyqt6_ela_pro.selection_assistant import assistant as assistant_module
from PyQt6 import sip

#: 测试用宿主自定义动作（组件本身不内置任何动作）
_HOST_ACTIONS = (
    ElaMenuItem(id="copy", label="复制"),
    ElaMenuItem(id="search", label="搜索"),
)


class _FakeMonitor(QObject):
    leftPressed = pyqtSignal(object)
    leftReleased = pyqtSignal(object, object)
    otherPressed = pyqtSignal(object)
    wheelScrolled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.stopped = False

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.stopped = True


class _FakeCapture(QObject):
    captured = pyqtSignal(str)
    failed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.count = 0
        self.cancelled = 0

    def capture(self) -> None:
        self.count += 1

    def cancel(self) -> None:
        self.cancelled += 1


class _ConfigurableCapture(_FakeCapture):
    """带配置方法的自定义取词后端（验证 capture() 句柄不再 isinstance 失效）。"""

    def __init__(self) -> None:
        super().__init__()
        self.restore = True
        self.capture_delay_ms = 0
        self.restore_delay_ms = 0

    def setRestoreClipboard(self, on: bool) -> None:  # noqa: N802 (Qt 命名)
        self.restore = bool(on)

    def setCaptureDelayMs(self, ms: int) -> None:  # noqa: N802 (Qt 命名)
        self.capture_delay_ms = int(ms)

    def setRestoreDelayMs(self, ms: int) -> None:  # noqa: N802 (Qt 命名)
        self.restore_delay_ms = int(ms)


def _make(qapp):
    monitor = _FakeMonitor()
    capture = _FakeCapture()
    assistant = ElaSelectionAssistant(monitor=monitor, capture=capture)
    qapp.processEvents()
    return assistant, monitor, capture


def _dispose(qapp, assistant):
    assistant.hide()
    assistant.deleteLater()
    qapp.processEvents()


class TestEnable:
    def test_enable_starts_monitor_and_disable_stops(self, qapp):
        assistant, monitor, _ = _make(qapp)
        changes = []
        assistant.enabledChanged.connect(changes.append)
        assert assistant.setEnabled(True) is True
        assert assistant.isEnabled() is True
        assert monitor.started is True
        assert assistant.setEnabled(False) is False
        assert monitor.stopped is True
        assert changes == [True, False]
        _dispose(qapp, assistant)

    def test_monitor_failure_emits_error(self, qapp):
        class _BadMonitor(_FakeMonitor):
            def start(self):
                raise RuntimeError("钩子安装失败")

        monitor = _BadMonitor()
        assistant = ElaSelectionAssistant(monitor=monitor, capture=_FakeCapture())
        errors = []
        assistant.errorOccurred.connect(errors.append)
        assert assistant.setEnabled(True) is False
        assert assistant.isEnabled() is False
        assert errors == ["钩子安装失败"]
        _dispose(qapp, assistant)

    def test_disabled_ignores_gestures(self, qapp):
        assistant, monitor, capture = _make(qapp)
        monitor.leftReleased.emit((0, 0), (50, 50))
        assert capture.count == 0
        monitor.leftPressed.emit((0, 0))
        _dispose(qapp, assistant)

    def test_disable_cancels_inflight_capture(self, qapp):
        """取词是异步的（延迟+轮询共 100~350ms），停用必须取消在途取词，
        否则已发出的 Ctrl+C 仍会在几十毫秒后带回结果。"""
        assistant, monitor, capture = _make(qapp)
        assistant.setCaptureFilter(lambda down, up: True)
        assistant.setEnabled(True)
        monitor.leftReleased.emit((0, 0), (50, 50))
        assert capture.count == 1
        assistant.setEnabled(False)
        assert capture.cancelled == 1
        _dispose(qapp, assistant)

    def test_capture_result_after_disable_does_not_popup(self, qapp):
        """异步结果到达时若已停用，不得弹出动作条。"""
        assistant, monitor, capture = _make(qapp)
        assistant.setActions(_HOST_ACTIONS)
        assistant.setCaptureFilter(lambda down, up: True)
        assistant.setEnabled(True)
        monitor.leftReleased.emit((0, 0), (50, 50))
        assistant.setEnabled(False)
        captured = []
        assistant.selectionCaptured.connect(lambda t, p: captured.append(t))
        capture.captured.emit("late result")  # 结果迟到
        qapp.processEvents()
        assert captured == []
        assert assistant.popup().isVisible() is False
        _dispose(qapp, assistant)

    def test_capture_result_while_enabled_still_pops(self, qapp):
        """对照组：未停用时结果照常弹出（别把上一个用例写成假阳性）。"""
        assistant, monitor, capture = _make(qapp)
        assistant.setActions(_HOST_ACTIONS)
        assistant.setEnabled(True)
        capture.captured.emit("fresh result")
        qapp.processEvents()
        assert assistant.popup().isVisible() is True
        _dispose(qapp, assistant)

    def test_destroy_with_lazy_monitor_does_not_touch_dead_child(self, qapp):
        """懒创建的 monitor 是 self 的子对象：Qt 先 deleteChildren() 再 emit
        destroyed()，所以清理逻辑必须先 sip.isdeleted 判存活。"""

        from pyqt6_ela_pro.selection_assistant._native import ElaMouseMonitor

        assistant = ElaSelectionAssistant(capture=_FakeCapture())
        assistant._monitor = ElaMouseMonitor(assistant)  # 同 _ensure_monitor
        assistant._enabled = True
        sip.delete(assistant)  # 走真实的析构顺序（不给 deleteLater 缓冲）
        assert sip.isdeleted(assistant._monitor)

    def test_destroy_stops_injected_monitor(self, qapp):
        """注入的 monitor 不是 self 的子对象，仍必须被停掉。"""

        monitor = _FakeMonitor()
        assistant = ElaSelectionAssistant(monitor=monitor, capture=_FakeCapture())
        sip.delete(assistant)
        assert monitor.stopped is True

    def test_destroy_reclaims_popup(self, qapp):
        """popup 是**无父的顶层窗**，助手销毁后必须自己把它收掉。

        历史 bug：``self.destroyed.connect(self._on_destroyed)`` 里 PyQt5 根本
        不调用绑定到自身的槽（实测 lambda/functools.partial 才会触发），于是
        这段清理从未执行 —— 助手销毁后动作条永久留在屏幕上，宿主也再也拿不到
        它去关。"""

        assistant, _, _ = _make(qapp)
        assistant.setActions(_HOST_ACTIONS)
        assistant.setEnabled(True)
        assistant.showFor("选中文本", QPoint(200, 200))
        qapp.processEvents()
        popup = assistant.popup()
        assert popup.isVisible() is True

        sip.delete(assistant)
        # 用户可见的结果：动作条从屏幕上消失
        assert popup.isVisible() is False
        # 再确认 deleteLater 真的排上了。
        # 注意：``QApplication.processEvents()`` **不处理 DeferredDelete 事件**
        # （它只在事件循环回到更低层级时才派发），所以无父顶层窗要用
        # ``sendPostedEvents`` 显式冲刷，否则连裸 QWidget 都测不出删除。
        QCoreApplication.sendPostedEvents(popup, QEvent.Type.DeferredDelete)
        assert sip.isdeleted(popup) is True


class TestGestures:
    def _enabled(self, qapp, allowDrag: bool = True):
        assistant, monitor, capture = _make(qapp)
        # 拖选取词要向前台注入 Ctrl+C，默认闸门不放行。绝大多数手势用例要的是
        # 「手势识别本身对不对」，所以这里统一显式放行拖选（默认闸门另有专测）。
        if allowDrag:
            assistant.setCaptureFilter(lambda down, up: True)
        assistant.setEnabled(True)
        return assistant, monitor, capture

    def test_drag_release_triggers_capture(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        monitor.leftReleased.emit((100, 100), (160, 130))
        assert capture.count == 1
        _dispose(qapp, assistant)

    def test_click_without_drag_ignored(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        monitor.leftReleased.emit((100, 100), (101, 100))
        assert capture.count == 0
        _dispose(qapp, assistant)

    def test_double_click_triggers_capture(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        monitor.leftReleased.emit((100, 100), (100, 100))
        assert capture.count == 0
        monitor.leftReleased.emit((100, 100), (100, 100))
        assert capture.count == 1
        _dispose(qapp, assistant)

    def test_two_slow_clicks_ignored(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        monitor.leftReleased.emit((100, 100), (100, 100))
        time.sleep(0.45)
        monitor.leftReleased.emit((100, 100), (100, 100))
        assert capture.count == 0
        _dispose(qapp, assistant)

    def test_drag_threshold_configurable(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        assistant.setDragThreshold(50)
        assert assistant.dragThreshold() == 50
        monitor.leftReleased.emit((100, 100), (120, 100))
        assert capture.count == 0
        _dispose(qapp, assistant)

    def test_drag_then_click_same_spot_captures_once(self, qapp):
        """拖选释放后在同一点马上点一下（收起选区）不该被误判成双击。"""
        assistant, monitor, capture = self._enabled(qapp)
        monitor.leftReleased.emit((100, 100), (160, 130))  # 拖选 → 取词 1
        assert capture.count == 1
        monitor.leftPressed.emit((160, 130))
        monitor.leftReleased.emit((160, 130), (160, 130))  # 同点单击
        assert capture.count == 1, "拖拽释放被记成了「点击」，导致误判双击"
        _dispose(qapp, assistant)

    def test_drag_breaks_double_click_sequence(self, qapp):
        """单击 → 拖拽 → 再单击同一点：两次点击不该跨拖拽配成双击。"""
        assistant, monitor, capture = self._enabled(qapp)
        monitor.leftReleased.emit((100, 100), (100, 100))  # 点击 1（只记录）
        assert capture.count == 0
        monitor.leftReleased.emit((100, 100), (140, 100))  # 拖拽 → 取词 1
        assert capture.count == 1
        monitor.leftPressed.emit((100, 100))
        monitor.leftReleased.emit((100, 100), (100, 100))  # 点击 2
        assert capture.count == 1, "拖拽没有打断双击序列"
        _dispose(qapp, assistant)


class TestCaptureFilter:
    """``setCaptureFilter``：在注入 Ctrl+C 之前给宿主一个闸门。"""

    def _enabled(self, qapp):
        assistant, monitor, capture = _make(qapp)
        assistant.setEnabled(True)
        return assistant, monitor, capture

    def test_filter_blocks_capture(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        assistant.setCaptureFilter(lambda down, up: False)
        assert assistant.captureFilter() is not None
        monitor.leftReleased.emit((100, 100), (160, 130))
        assert capture.count == 0, "过滤器返回 False 时不该注入 Ctrl+C"
        _dispose(qapp, assistant)

    def test_filter_allows_capture(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        assistant.setCaptureFilter(lambda down, up: True)
        monitor.leftReleased.emit((100, 100), (160, 130))
        assert capture.count == 1
        _dispose(qapp, assistant)

    def test_filter_receives_physical_points(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        seen = []
        assistant.setCaptureFilter(lambda down, up: seen.append((down, up)) or True)
        monitor.leftReleased.emit((100, 100), (160, 130))
        assert seen == [((100, 100), (160, 130))]
        _dispose(qapp, assistant)

    def test_filter_exception_denies_capture(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)

        def bad(down, up):
            raise ValueError("host filter bug")

        assistant.setCaptureFilter(bad)
        with pytest.warns(RuntimeWarning):
            monitor.leftReleased.emit((100, 100), (160, 130))
        assert capture.count == 0, "过滤器异常应拦截（宁可少取一次词）"
        _dispose(qapp, assistant)

    def test_filter_also_gates_double_click(self, qapp):
        assistant, monitor, capture = self._enabled(qapp)
        assistant.setCaptureFilter(lambda down, up: False)
        monitor.leftReleased.emit((100, 100), (100, 100))
        monitor.leftReleased.emit((100, 100), (100, 100))
        assert capture.count == 0
        _dispose(qapp, assistant)

    def test_double_click_survives_clearing_the_filter(self, qapp):
        """双击选词不受过滤器开关影响（它不会拖走窗口 / 滚动条）。"""
        assistant, monitor, capture = self._enabled(qapp)
        assistant.setCaptureFilter(None)
        monitor.leftReleased.emit((100, 100), (100, 100))
        monitor.leftReleased.emit((100, 100), (100, 100))
        assert capture.count == 1
        _dispose(qapp, assistant)

    def test_filter_can_be_cleared(self, qapp):
        """清空过滤器后拖选取词**回到默认闸门**（不放行）。

        「清掉过滤器」不等于「打开拖选取词」—— 那要用
        ``setRequireFilterForDrag(True)`` 显式表达。
        """
        assistant, monitor, capture = self._enabled(qapp)
        assistant.setCaptureFilter(lambda down, up: False)
        assistant.setCaptureFilter(None)
        assert assistant.captureFilter() is None
        monitor.leftReleased.emit((100, 100), (160, 130))
        assert capture.count == 0, "清空过滤器不该顺带打开拖选取词"
        _dispose(qapp, assistant)


class TestCaptureFlow:
    def _flow(self, qapp, monkeypatch):
        monkeypatch.setattr(
            assistant_module, "to_logical_pos", lambda x, y: QPoint(x, y)
        )
        assistant, monitor, capture = _make(qapp)
        # 这组用例测的是「取到词之后」的展示链路，用双击手势避开默认的拖选闸门
        assistant.setEnabled(True)
        assistant.setActions(_HOST_ACTIONS)
        captured = []
        shown = []
        assistant.selectionCaptured.connect(
            lambda text, pos: captured.append((text, pos))
        )
        assistant.popupShown.connect(lambda text, pos: shown.append((text, pos)))
        return assistant, monitor, capture, captured, shown

    @staticmethod
    def _double_click(monitor):
        """双击选词（默认闸门只拦拖选，双击不需要过滤器）。"""
        monitor.leftReleased.emit((100, 100), (100, 100))
        monitor.leftReleased.emit((100, 100), (100, 100))

    def test_captured_shows_popup_and_emits(self, qapp, monkeypatch):
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        self._double_click(monitor)
        capture.captured.emit("  选中的文本  ")
        qapp.processEvents()
        assert assistant.popup().isVisible() is True
        assert [text for text, _ in captured] == ["  选中的文本  "]
        assert [text for text, _ in shown] == ["  选中的文本  "]
        assert captured[0][1] == QPoint(100, 100)
        assert assistant.selectedText() == "  选中的文本  "
        _dispose(qapp, assistant)

    def test_capture_without_actions_emits_signal_only(self, qapp, monkeypatch):
        monkeypatch.setattr(
            assistant_module, "to_logical_pos", lambda x, y: QPoint(x, y)
        )
        assistant, monitor, capture = _make(qapp)
        assistant.setEnabled(True)
        captured = []
        shown = []
        assistant.selectionCaptured.connect(
            lambda text, pos: captured.append((text, pos))
        )
        assistant.popupShown.connect(lambda text, pos: shown.append((text, pos)))
        self._double_click(monitor)
        capture.captured.emit("无动作文本")
        qapp.processEvents()
        assert captured == [("无动作文本", QPoint(100, 100))]
        assert shown == []
        assert assistant.popup().isVisible() is False
        _dispose(qapp, assistant)

    def test_short_text_does_not_show_popup(self, qapp, monkeypatch):
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        assistant.setMinSelectionLength(3)
        monitor.leftReleased.emit((100, 100), (160, 130))
        capture.captured.emit("ab")
        qapp.processEvents()
        assert assistant.popup().isVisible() is False
        assert captured == []
        _dispose(qapp, assistant)

    def test_capture_failure_hides_popup(self, qapp, monkeypatch):
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        assistant.showFor("先显示的文本", QPoint(300, 300))
        qapp.processEvents()
        assert assistant.popup().isVisible() is True
        capture.failed.emit()
        qapp.processEvents()
        assert assistant.popup().isVisible() is False
        _dispose(qapp, assistant)

    def test_buttons_are_reused_across_shows(self, qapp, monkeypatch):
        """showFor 不该重建按钮：动作列表早已推给 popup，每次重建等于
        销毁+重建全部按钮（连带重建每个 tooltip），连续划词时是纯浪费+闪烁。"""
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        assistant.showFor("第一次", QPoint(300, 300))
        qapp.processEvents()
        first = assistant.popup().button("copy")
        assistant.showFor("第二次", QPoint(300, 300))
        qapp.processEvents()
        assert assistant.popup().button("copy") is first
        _dispose(qapp, assistant)

    def test_set_actions_still_rebuilds_buttons(self, qapp, monkeypatch):
        """对照组：setActions 仍要重建（动作列表真的变了）。"""
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        assistant.showFor("文本", QPoint(300, 300))
        qapp.processEvents()
        first = assistant.popup().button("copy")
        assistant.setActions(_HOST_ACTIONS)
        assert assistant.popup().button("copy") is not first
        _dispose(qapp, assistant)

    def test_action_click_emits_payload(self, qapp, monkeypatch):
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        assistant.showFor("选中文本", QPoint(320, 240))
        qapp.processEvents()
        events = []
        assistant.actionTriggered.connect(
            lambda actionId, text, pos: events.append((actionId, text, pos))
        )
        button = assistant.popup().button("copy")
        assert button is not None
        button.click()
        assert events == [("copy", "选中文本", QPoint(320, 240))]
        assert assistant.popup().isVisible() is False
        _dispose(qapp, assistant)

    def test_hidden_signal_on_popup_dismiss(self, qapp, monkeypatch):
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        hidden = []
        assistant.popupHidden.connect(lambda: hidden.append(True))
        assistant.showFor("文本", QPoint(200, 200))
        qapp.processEvents()
        monitor.otherPressed.emit((0, 0))
        qapp.processEvents()
        assert hidden == [True]
        _dispose(qapp, assistant)

    def test_wheel_hides_popup(self, qapp, monkeypatch):
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        assistant.showFor("文本", QPoint(200, 200))
        qapp.processEvents()
        monitor.wheelScrolled.emit()
        qapp.processEvents()
        assert assistant.popup().isVisible() is False
        _dispose(qapp, assistant)

    def test_press_outside_hides_popup(self, qapp, monkeypatch):
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        assistant.showFor("文本", QPoint(200, 200))
        qapp.processEvents()
        monitor.leftPressed.emit((0, 0))
        qapp.processEvents()
        assert assistant.popup().isVisible() is False
        _dispose(qapp, assistant)

    def test_press_inside_popup_keeps_it_and_skips_capture(self, qapp, monkeypatch):
        assistant, monitor, capture, captured, shown = self._flow(qapp, monkeypatch)
        assistant.showFor("文本", QPoint(200, 200))
        qapp.processEvents()
        center = assistant.popup().frameGeometry().center()
        point = (center.x(), center.y())
        monitor.leftPressed.emit(point)
        monitor.leftReleased.emit(point, point)
        qapp.processEvents()
        assert assistant.popup().isVisible() is True
        assert capture.count == 0
        _dispose(qapp, assistant)


class TestActionsConfig:
    def test_default_actions_empty(self, qapp):
        assistant, monitor, capture = _make(qapp)
        assert assistant.actions() == []
        assert assistant.popup().hasActions() is False
        _dispose(qapp, assistant)

    def test_actions_replace_and_dict_coerce(self, qapp):
        assistant, monitor, capture = _make(qapp)
        assistant.setActions(
            [
                ElaMenuItem(id="a", label="动作 A"),
                {"id": "b", "label": "动作 B", "enabled": False},
            ]
        )
        assert [item.id for item in assistant.actions()] == ["a", "b"]
        assert assistant.popup().button("b") is None
        # 清空后不再弹窗
        assistant.setActions([])
        assert assistant.actions() == []
        assert assistant.popup().hasActions() is False
        _dispose(qapp, assistant)

    def test_compact_mode_via_popup(self, qapp):
        """外观配置走 popup() 句柄，助手不再做同名转发。"""
        assistant, monitor, capture = _make(qapp)
        assistant.popup().setCompactMode(True)
        assert assistant.popup().compactMode() is True
        _dispose(qapp, assistant)

    def test_capture_config_via_capture_accessor(self, qapp):
        """取词参数走 capture() 句柄（注入的自定义后端同样可配）。"""
        capture = _ConfigurableCapture()
        assistant = ElaSelectionAssistant(monitor=_FakeMonitor(), capture=capture)
        assistant.capture().setRestoreClipboard(False)
        assistant.capture().setCaptureDelayMs(10)
        assistant.capture().setRestoreDelayMs(20)
        assert capture.restore is False
        assert capture.capture_delay_ms == 10
        assert capture.restore_delay_ms == 20
        _dispose(qapp, assistant)

    def test_no_forwarding_shims_left(self, qapp):
        """转发层已删除，不留兼容桩。"""
        assistant, _, _ = _make(qapp)
        for gone in (
            "setCompactMode",
            "compactMode",
            "setOffset",
            "setRestoreClipboard",
            "setCaptureDelayMs",
            "setRestoreDelayMs",
        ):
            assert not hasattr(assistant, gone), f"legacy forwarder: {gone}"
        _dispose(qapp, assistant)
