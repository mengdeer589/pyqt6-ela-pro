"""划词助手对用户正常 Ctrl+C / Ctrl+V 的影响：注入闸门与剪贴板恢复。

背景（2026-10 审查实测）：取词只能靠**向前台窗口注入 ``Ctrl+C``**
（``_native.send_copy``）。拖选与「拖窗口 / 拖滚动条 / 拖文件」在鼠标层面
无法区分，于是：

1. 默认放行拖选 → 终端 / 控制台里拖一下 scrollbar，注入的 Ctrl+C 就是
   **中断信号**，正在跑的命令被 SIGINT 掉；
2. 恢复剪贴板只看文本 → 注入撞上用户自己按的 Ctrl+C 时（抓到的是用户
   那份），恢复期会把**用户刚复制的内容**覆盖回旧值；
3. 基准剪贴板含图片 / 文件时恢复走 ``clear()`` → 用户复制的东西直接消失，
   Ctrl+V 粘不出来。

本文件钉住修复后的行为。**绝不真注入按键**：``_native._send_key`` 在每个
用例里都被替换掉（``test_injection_never_reaches_the_foreground`` 反过来
断言替换确实拦住了）。
"""

from __future__ import annotations

import pytest
from _qthelpers import wait_for_clipboard
from PyQt6.QtCore import QCoreApplication, QObject, pyqtSignal

from pyqt6_ela_pro import ElaSelectionAssistant
from pyqt6_ela_pro.selection_assistant import _native
from pyqt6_ela_pro.selection_assistant import assistant as assistant_module


@pytest.fixture
def no_injection(monkeypatch):
    """把真实的按键注入替换掉，并记录注入次数。

    单测里**绝不能**真往前台窗口发 Ctrl+C（会污染用户剪贴板）。
    """
    sent: list[tuple] = []
    monkeypatch.setattr(
        _native, "_send_key", lambda vk, flags=0: sent.append((vk, flags))
    )
    monkeypatch.setattr(_native, "_last_inject_at", 0.0, raising=False)
    return sent


class _FakeMonitor(QObject):
    leftPressed = pyqtSignal(object)
    leftReleased = pyqtSignal(object, object)
    otherPressed = pyqtSignal(object)
    wheelScrolled = pyqtSignal()

    def start(self) -> bool:
        return True

    def stop(self) -> None:
        pass


class _FakeCapture(QObject):
    captured = pyqtSignal(str)
    failed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def capture(self) -> None:
        self.count += 1

    def cancel(self) -> None:
        pass


def _assistant(qapp, monitor=None, capture=None):
    return ElaSelectionAssistant(
        None, monitor=monitor or _FakeMonitor(), capture=capture or _FakeCapture()
    )


def _drag(monitor, down=(100, 100), up=(160, 130)):
    monitor.leftReleased.emit(down, up)


def _double_click(monitor, at=(100, 100)):
    monitor.leftReleased.emit(at, at)
    monitor.leftReleased.emit(at, at)


# ============================================================ 注入侧闸门
class TestInjectionGates:
    def test_modifier_down_blocks_injection(self, no_injection, monkeypatch):
        """用户正按着修饰键时不注入 —— 否则发出去的是 Ctrl+Shift+C 之类。"""
        monkeypatch.setattr(_native, "any_modifier_down", lambda: True)
        assert _native.send_copy() is False
        assert no_injection == [], "闸门命中时一个键都不许发"

    def test_recent_injection_blocks_injection(self, no_injection, monkeypatch):
        """距上次注入不足间隔时不连发。"""
        import time

        monkeypatch.setattr(_native, "any_modifier_down", lambda: False)
        monkeypatch.setattr(_native, "_last_inject_at", time.monotonic(), raising=False)
        assert _native.send_copy() is False
        assert no_injection == []

    def test_gates_open_injects_and_returns_true(self, no_injection, monkeypatch):
        monkeypatch.setattr(_native, "any_modifier_down", lambda: False)
        monkeypatch.setattr(_native, "_last_inject_at", 0.0, raising=False)
        assert _native.send_copy() is True
        assert [vk for vk, _ in no_injection] == [
            _native._VK_CONTROL,
            _native._VK_C,
            _native._VK_C,
            _native._VK_CONTROL,
        ], "序列应是 Ctrl↓ C↓ C↑ Ctrl↑"

    def test_force_bypasses_both_gates(self, no_injection, monkeypatch):
        """``force=True`` 供明确知道自己在做什么的调用方使用。"""
        import time

        monkeypatch.setattr(_native, "any_modifier_down", lambda: True)
        monkeypatch.setattr(_native, "_last_inject_at", time.monotonic(), raising=False)
        assert _native.send_copy(force=True) is True
        assert len(no_injection) == 4

    def test_injection_never_reaches_the_foreground(self, no_injection, monkeypatch):
        """回归护栏：本文件所有用例都靠这个替换挡住真实注入。"""
        monkeypatch.setattr(_native, "any_modifier_down", lambda: False)
        monkeypatch.setattr(_native, "_last_inject_at", 0.0, raising=False)
        before = len(no_injection)
        _native.send_copy()
        assert len(no_injection) - before == 4, "注入仍走 _send_key（本文件已替换它）"

    def test_any_modifier_down_checks_three_keys(self, monkeypatch):
        seen: list[int] = []
        monkeypatch.setattr(
            _native, "_async_key_down", lambda vk: seen.append(vk) or False
        )
        assert _native.any_modifier_down() is False
        assert seen == [_native._VK_SHIFT, _native._VK_CONTROL, _native._VK_MENU]


# ============================================================ 默认取词闸门
class TestDefaultDragGate:
    def test_drag_blocked_without_filter(self, qapp):
        """未设过滤器时拖选**不取词**（终端里拖一下 = SIGINT）。"""
        monitor = _FakeMonitor()
        capture = _FakeCapture()
        assistant = _assistant(qapp, monitor, capture)
        assistant.setEnabled(True)
        _drag(monitor)
        assert capture.count == 0
        assistant.setEnabled(False)

    def test_blocked_drag_emits_signal(self, qapp):
        monitor = _FakeMonitor()
        assistant = _assistant(qapp, monitor)
        reasons: list[str] = []
        assistant.captureBlocked.connect(reasons.append)
        assistant.setEnabled(True)
        _drag(monitor)
        assert reasons == ["drag-without-filter"]
        assistant.setEnabled(False)

    def test_double_click_still_works_without_filter(self, qapp):
        monitor = _FakeMonitor()
        capture = _FakeCapture()
        assistant = _assistant(qapp, monitor, capture)
        assistant.setEnabled(True)
        _double_click(monitor)
        assert capture.count == 1, "双击选词不该被拖选闸门拦下（它不会拖走窗口）"
        assistant.setEnabled(False)

    def test_explicit_opt_in_restores_drag(self, qapp):
        monitor = _FakeMonitor()
        capture = _FakeCapture()
        assistant = _assistant(qapp, monitor, capture)
        assistant.setRequireFilterForDrag(False)
        assert assistant.requireFilterForDrag() is False
        assistant.setEnabled(True)
        _drag(monitor)
        assert capture.count == 1
        assistant.setEnabled(False)

    def test_default_flag_is_true(self, qapp):
        assistant = _assistant(qapp)
        assert assistant.requireFilterForDrag() is True
        assistant.setRequireFilterForDrag(False)
        assert assistant.requireFilterForDrag() is False

    def test_filter_takes_precedence_over_default(self, qapp):
        monitor = _FakeMonitor()
        capture = _FakeCapture()
        assistant = _assistant(qapp, monitor, capture)
        assistant.setCaptureFilter(lambda down, up: False)
        assistant.setEnabled(True)
        _drag(monitor)
        assert capture.count == 0, "宿主过滤器拒绝时不该注入"
        assistant.setEnabled(False)


# ============================================================ 内置启发式过滤器
class TestBuiltinDragFilter:
    def test_same_window_normal_drag_allowed(self, monkeypatch):
        monkeypatch.setattr(assistant_module, "window_pid_at", lambda x, y: 4242)
        monkeypatch.setattr(
            assistant_module,
            "window_rect_at",
            lambda x, y: (0, 0, 1000, 800),
        )
        f = ElaSelectionAssistant.builtinDragFilter()
        assert f((100, 100), (160, 130)) is True

    def test_cross_window_drag_denied(self, monkeypatch):
        """跨窗口拖拽多半是拖文件 / 拖到别的应用。"""
        pids = {(100, 100): 111, (160, 130): 222}
        monkeypatch.setattr(
            assistant_module, "window_pid_at", lambda x, y: pids[(x, y)]
        )
        f = ElaSelectionAssistant.builtinDragFilter()
        assert f((100, 100), (160, 130)) is False

    def test_unknown_window_denied(self, monkeypatch):
        monkeypatch.setattr(assistant_module, "window_pid_at", lambda x, y: 0)
        f = ElaSelectionAssistant.builtinDragFilter()
        assert f((100, 100), (160, 130)) is False

    def test_window_border_drag_denied(self, monkeypatch):
        """按在窗口边框上是在调窗口大小，不是在划词。"""
        monkeypatch.setattr(assistant_module, "window_pid_at", lambda x, y: 4242)
        monkeypatch.setattr(
            assistant_module, "window_rect_at", lambda x, y: (0, 0, 1000, 800)
        )
        f = ElaSelectionAssistant.builtinDragFilter(borderPx=6)
        assert f((2, 100), (60, 130)) is False, "左边缘 2px 处按下的拖拽应被拒"
        assert f((500, 400), (560, 430)) is True, "窗口正中不受影响"

    def test_too_long_drag_denied(self, monkeypatch):
        """超长位移更像拖滑块 / 拖滚动条 / 拖窗口。"""
        monkeypatch.setattr(assistant_module, "window_pid_at", lambda x, y: 4242)
        monkeypatch.setattr(
            assistant_module, "window_rect_at", lambda x, y: (0, 0, 5000, 2000)
        )
        f = ElaSelectionAssistant.builtinDragFilter(maxDragPx=200)
        assert f((100, 100), (400, 130)) is False
        assert f((100, 100), (250, 130)) is True

    def test_filter_failure_denies(self, monkeypatch):
        def boom(x, y):
            raise OSError("Win32 查询失败")

        monkeypatch.setattr(assistant_module, "window_pid_at", boom)
        f = ElaSelectionAssistant.builtinDragFilter()
        assert f((100, 100), (160, 130)) is False

    def test_usable_as_assistant_filter(self, qapp, monkeypatch):
        """串起来用：内置过滤器 + 限定前台进程。"""
        monkeypatch.setattr(assistant_module, "window_pid_at", lambda x, y: 4242)
        monkeypatch.setattr(
            assistant_module, "window_rect_at", lambda x, y: (0, 0, 1000, 800)
        )
        monitor = _FakeMonitor()
        capture = _FakeCapture()
        assistant = _assistant(qapp, monitor, capture)
        assistant.setCaptureFilter(ElaSelectionAssistant.builtinDragFilter())
        assistant.setEnabled(True)
        _drag(monitor)
        assert capture.count == 1
        assistant.setEnabled(False)


# ============================================================ 剪贴板恢复
@pytest.fixture
def clipboard(requires_clipboard):
    class _Clipboard:
        def __init__(self):
            self._cb = QCoreApplication.instance().clipboard()

        def setText(self, text: str) -> None:
            self._cb.setText(text)
            for _ in range(5):
                QCoreApplication.processEvents()

        def text(self) -> str:
            return self._cb.text()

    return _Clipboard()


class TestRestoreKeepsUserCopy:
    """恢复期不得覆盖用户自己的复制 —— P0-2 / P0-3 的回归。"""

    @staticmethod
    def _capture(capture_mod, captured: str) -> None:
        capture_mod._active = True
        capture_mod._finish(captured, ok=True)

    def test_same_text_newer_sequence_is_not_overwritten(
        self, qapp, clipboard, monkeypatch
    ):
        """文本相同但序列号变了 = 用户又复制了一遍同样的内容。

        原实现只看文本，会把用户这次复制覆盖回旧值（用户 Ctrl+V 拿到旧内容）。
        """
        from pyqt6_ela_pro.selection_assistant import capture as capture_mod

        cap = capture_mod.ElaClipboardCapture()
        cap._old_text = "旧内容"
        # 先确认哨兵落盘（Windows 单次写会被静默丢弃）；再快照序列号
        assert (
            wait_for_clipboard(
                qapp, "同样的文本", write=lambda: clipboard.setText("同样的文本")
            )
            == "同样的文本"
        )
        self._capture(cap, "同样的文本")
        # 模拟：用户又复制了一次同样的文本（文本没变，序列号变了）
        seq = capture_mod.clipboard_sequence_number()
        monkeypatch.setattr(capture_mod, "clipboard_sequence_number", lambda: seq + 7)
        cap._restore_clipboard()
        assert cap.lastRestoreSkipReason() == "clipboard-changed"

    def test_non_text_baseline_is_never_cleared(self, qapp, clipboard):
        """基准含图片等非文本内容 → 跳过恢复，**绝不 clear()**。

        否则用户复制的图片被清空，Ctrl+V 直接粘不出来（静默数据丢失）。
        """
        from pyqt6_ela_pro.selection_assistant import capture as capture_mod

        cap = capture_mod.ElaClipboardCapture()
        cap._old_text = ""
        cap._baseline_non_text = True
        # 先确认哨兵真的落盘（Windows 单次写会被静默丢弃）；再走取词流程 ——
        # ``_finish`` 在此快照序列号，晚写会推进序列号、被误判成「用户改过剪贴板」
        assert (
            wait_for_clipboard(qapp, "TAKEN", write=lambda: clipboard.setText("TAKEN"))
            == "TAKEN"
        )
        self._capture(cap, "TAKEN")
        cap._restore_clipboard()
        assert cap.lastRestoreSkipReason() == "non-text-baseline"
        # 只轮询不重发：重发等于覆盖证据
        assert (
            wait_for_clipboard(qapp, "TAKEN") == "TAKEN"
        ), "注入进来的文本应留着"

    def test_non_text_probe_detects_image(self, qapp):
        """``_has_non_text_format`` 能认出图片剪贴板。"""
        from PyQt6.QtGui import QImage
        from pyqt6_ela_pro.selection_assistant.capture import _has_non_text_format

        cb = qapp.clipboard()
        cb.setImage(QImage(4, 4, QImage.Format.Format_RGB32))
        for _ in range(5):
            QCoreApplication.processEvents()
        assert _has_non_text_format(cb) is True
        cb.setText("纯文本")
        for _ in range(5):
            QCoreApplication.processEvents()
        assert _has_non_text_format(cb) is False, "纯文本剪贴板不该被误判成含非文本"

    def test_plain_restore_still_works(self, qapp, clipboard):
        """对照组：没人动过剪贴板时仍然正常还原。"""
        from pyqt6_ela_pro.selection_assistant import capture as capture_mod

        cap = capture_mod.ElaClipboardCapture()
        cap._old_text = "用户原本的内容"
        # 先确认哨兵落盘（Windows 单次写会被静默丢弃），再快照序列号
        assert (
            wait_for_clipboard(
                qapp, "取词拿到的文本", write=lambda: clipboard.setText("取词拿到的文本")
            )
            == "取词拿到的文本"
        )
        self._capture(cap, "取词拿到的文本")
        # 还原写入同样可能被丢弃：重发同一个动作（不然永远读不回旧值）
        assert (
            wait_for_clipboard(qapp, "用户原本的内容", write=cap._restore_clipboard)
            == "用户原本的内容"
        )
        assert cap.lastRestoreSkipReason() == ""


# ============================================================ 不影响键盘本身
class TestNoKeyboardHook:
    """助手**不得**安装键盘钩子 / 改键鼠映射 —— 否则用户自己的 Ctrl+C/V 会被吞。"""

    def test_no_hooks_installed(self):
        import inspect

        for module in (_native, assistant_module):
            source = inspect.getsource(module)
            for forbidden in (
                "SetWindowsHookEx",
                "CallNextHookEx",
                "MapVirtualKey",
                "SetWindowsHookExW",
            ):
                assert forbidden not in source, (
                    f"{module.__name__} 出现了 {forbidden}：会全局拦截键盘"
                )

    def test_only_mouse_keys_are_polled(self):
        """键盘状态只以 ``GetAsyncKeyState`` 读取（只读），不做任何拦截。"""
        import inspect

        source = inspect.getsource(_native)
        assert "GetAsyncKeyState" in source
        assert "GetKeyState" not in source.replace("GetAsyncKeyState", "")
