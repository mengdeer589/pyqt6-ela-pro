"""ElaClipboardCapture 测试：变化计数取词、超时失败与剪贴板恢复。"""

from __future__ import annotations

import time

from _qthelpers import wait_for_clipboard
from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro import ElaClipboardCapture
from pyqt6_ela_pro.selection_assistant import capture as capture_module


def _speed_up(capture: ElaClipboardCapture, timeout_ms: int = 120) -> None:
    capture.setCaptureDelayMs(1)
    capture.setPollMs(1)
    capture.setTimeoutMs(timeout_ms)
    capture.setRestoreDelayMs(1)


def _set_clipboard(qapp, text: str) -> str:
    """写入剪贴板并确认生效（Qt/Windows 下连续写入可能被静默丢弃）。"""
    clipboard = qapp.clipboard()
    for _ in range(10):
        clipboard.setText(text)
        qapp.processEvents()
        if clipboard.text() == text:
            return text
        time.sleep(0.01)
    return clipboard.text()


def _fake_send_copy(action):
    """替代 ``send_copy()`` 的假注入。

    **必须返回 True**：真实的 ``send_copy()`` 返回「是否真的注入了按键」，
    而取词链路把 False 当作「注入被闸门拦下」直接按无选区收尾
    （见 ``_on_send_copy``）。假实现不回 True 的话，用例测到的就不是
    取词链路而是闸门分支了。
    """

    def _send() -> bool:
        action()
        return True

    return _send


class TestCapture:
    def test_success_and_clipboard_restored(
        self, qapp, monkeypatch, requires_clipboard
    ):
        clipboard = qapp.clipboard()
        before = _set_clipboard(qapp, "旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture)
        results = []
        capture.captured.connect(results.append)
        monkeypatch.setattr(
            capture_module,
            "send_copy",
            _fake_send_copy(lambda: clipboard.setText("选中的文本")),
        )

        capture.capture()
        assert capture.isCapturing() is True
        assert _wait_until(qapp, lambda: bool(results))
        assert results == ["选中的文本"]
        # 恢复写入在 Windows 上可能被静默丢弃（只轮询永远等不来）——
        # 按 _qthelpers 的约定重发同一个动作。
        assert (
            wait_for_clipboard(qapp, before, write=capture._restore_clipboard) == before
        )
        capture.deleteLater()

    def test_timeout_fails_without_touching_clipboard(
        self, qapp, monkeypatch, requires_clipboard
    ):
        clipboard = qapp.clipboard()
        before = _set_clipboard(qapp, "旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture, timeout_ms=60)
        failures = []
        capture.failed.connect(lambda: failures.append(True))
        monkeypatch.setattr(capture_module, "send_copy", _fake_send_copy(lambda: None))

        capture.capture()
        assert _wait_until(qapp, lambda: bool(failures))
        assert capture.isCapturing() is False
        assert clipboard.text() == before
        capture.deleteLater()

    def test_restore_disabled_keeps_selection(
        self, qapp, monkeypatch, requires_clipboard
    ):
        clipboard = qapp.clipboard()
        _set_clipboard(qapp, "旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture)
        capture.setRestoreClipboard(False)
        assert capture.restoreClipboard() is False
        results = []
        capture.captured.connect(results.append)
        fake = _fake_send_copy(lambda: clipboard.setText("选中"))
        monkeypatch.setattr(capture_module, "send_copy", fake)

        capture.capture()
        assert _wait_until(qapp, lambda: bool(results))
        # 关闭恢复：剪贴板应停在「选中」（写入可能被静默丢弃 → 重发同一动作）
        assert wait_for_clipboard(qapp, "选中", write=fake) == "选中"
        capture.deleteLater()

    def test_blocked_injection_never_polls_or_captures(self, qapp, monkeypatch):
        """注入被 ``send_copy`` 的闸门拦下（返回 False）→ 直接判无选区。

        闸门是「修饰键按下 / 距上次注入过近」这类**不该发按键**的场合；此时
        绝不能继续轮询剪贴板，否则用户自己那次 Ctrl+C 会被误当成取词结果。
        """
        capture = ElaClipboardCapture()
        _speed_up(capture)
        results: list[str] = []
        failures: list[bool] = []
        capture.captured.connect(results.append)
        capture.failed.connect(lambda: failures.append(True))
        sent: list[int] = []
        monkeypatch.setattr(
            capture_module, "send_copy", lambda: (sent.append(1), False)[1]
        )

        capture.capture()
        assert _wait_until(qapp, lambda: bool(failures))
        assert results == [], "注入没发出去，不该出现取词结果"
        assert sent == [1], "闸门判定本身必须走过（只拦一次，不重试）"
        assert capture.isCapturing() is False
        capture.deleteLater()

    def test_empty_copy_is_failure(self, qapp, monkeypatch, requires_clipboard):
        clipboard = qapp.clipboard()
        _set_clipboard(qapp, "旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture, timeout_ms=60)
        failures = []
        capture.failed.connect(lambda: failures.append(True))
        monkeypatch.setattr(
            capture_module, "send_copy", _fake_send_copy(clipboard.clear)
        )

        capture.capture()
        assert _wait_until(qapp, lambda: bool(failures))
        capture.deleteLater()

    def test_cancel_keeps_clipboard(self, qapp, monkeypatch, requires_clipboard):
        clipboard = qapp.clipboard()
        before = _set_clipboard(qapp, "旧内容")
        capture = ElaClipboardCapture()
        capture.setCaptureDelayMs(1000)
        monkeypatch.setattr(capture_module, "send_copy", _fake_send_copy(lambda: None))

        capture.capture()
        assert capture.isCapturing() is True
        capture.cancel()
        assert capture.isCapturing() is False
        assert clipboard.text() == before
        capture.deleteLater()

    def test_config_roundtrip(self, qapp):
        capture = ElaClipboardCapture()
        capture.setCaptureDelayMs(50)
        capture.setPollMs(20)
        capture.setTimeoutMs(400)
        capture.setRestoreDelayMs(200)
        assert capture.captureDelayMs() == 50
        assert capture.pollMs() == 20
        assert capture.timeoutMs() == 400
        assert capture.restoreDelayMs() == 200
        assert capture.restoreClipboard() is True
        capture.deleteLater()
