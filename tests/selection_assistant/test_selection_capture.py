"""ElaClipboardCapture 测试：变化计数取词、超时失败与剪贴板恢复。"""

from __future__ import annotations

import time

import pytest
from PyQt6.QtCore import QByteArray, QMimeData, QTimer
from PyQt6.QtGui import QColor, QImage

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


@pytest.fixture
def fake_clipboard(monkeypatch):
    """确定性剪贴板桩：真实 ``QMimeData`` + 显式序列号，避免系统剪贴板抖动。"""
    state = {"seq": 1000, "mime": QMimeData()}

    class _FakeClipboard:
        def text(self) -> str:
            return state["mime"].text()

        def mimeData(self):  # noqa: N802
            return state["mime"]

        def setText(self, text: str) -> None:  # noqa: N802
            mime = QMimeData()
            mime.setText(text)
            state["mime"] = mime
            state["seq"] += 1

        def setMimeData(self, mime) -> None:  # noqa: N802
            state["mime"] = mime
            state["seq"] += 1

        def setImage(self, image) -> None:  # noqa: N802
            mime = QMimeData()
            mime.setImageData(image)
            state["mime"] = mime
            state["seq"] += 1

        def image(self):
            return state["mime"].imageData()

        def clear(self) -> None:
            state["mime"] = QMimeData()
            state["seq"] += 1

    cb = _FakeClipboard()

    class _FakeApp:
        @staticmethod
        def clipboard() -> _FakeClipboard:
            return cb

    monkeypatch.setattr(capture_module, "QApplication", _FakeApp)
    monkeypatch.setattr(capture_module, "clipboard_sequence_number", lambda: state["seq"])
    monkeypatch.setattr(capture_module, "any_modifier_down", lambda: False)
    return cb, state


class TestCapture:
    def test_success_and_clipboard_restored(
        self, qapp, monkeypatch, requires_clipboard
    ):
        before = _set_clipboard(qapp, "旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture)
        results = []
        capture.captured.connect(results.append)
        monkeypatch.setattr(
            capture_module,
            "send_copy",
            _fake_send_copy(lambda: _set_clipboard(qapp, "选中的文本")),
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
        _set_clipboard(qapp, "旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture)
        capture.setRestoreClipboard(False)
        assert capture.restoreClipboard() is False
        results = []
        capture.captured.connect(results.append)
        fake = _fake_send_copy(lambda: _set_clipboard(qapp, "选中"))
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
        # 本用例只验「空副本 = 失败」；停掉恢复定时器避免污染后续用例
        capture._restore_timer.stop()
        capture._need_restore = False
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


class TestRichTextAndImages:
    def test_html_only_selection_with_image_is_captured(
        self, qapp, fake_clipboard, monkeypatch
    ):
        """纯文本为空、文字在 HTML 里时也要取到词（图片忽略）。"""
        clipboard, _state = fake_clipboard
        clipboard.setText("旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture)
        results: list[str] = []
        capture.captured.connect(results.append)
        mime = QMimeData()
        mime.setHtml("<p>before <img src='x' width='10' height='10'> after</p>")
        monkeypatch.setattr(
            capture_module,
            "send_copy",
            _fake_send_copy(lambda: clipboard.setMimeData(mime)),
        )

        capture.capture()
        assert _wait_until(qapp, lambda: bool(results))
        assert "before" in results[0] and "after" in results[0]
        assert "\ufffc" not in results[0]
        assert _wait_until(qapp, lambda: clipboard.text() == "旧内容")
        capture.deleteLater()

    def test_markdown_only_selection_with_image_is_captured(
        self, qapp, fake_clipboard, monkeypatch
    ):
        clipboard, _state = fake_clipboard
        clipboard.setText("旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture)
        results: list[str] = []
        capture.captured.connect(results.append)
        mime = QMimeData()
        mime.setData(
            "text/markdown",
            QByteArray("before ![red](x.png) after".encode("utf-8")),
        )
        monkeypatch.setattr(
            capture_module,
            "send_copy",
            _fake_send_copy(lambda: clipboard.setMimeData(mime)),
        )

        capture.capture()
        assert _wait_until(qapp, lambda: bool(results))
        assert "before" in results[0] and "after" in results[0]
        assert "\ufffc" not in results[0]
        assert _wait_until(qapp, lambda: clipboard.text() == "旧内容")
        capture.deleteLater()

    def test_plain_text_image_placeholder_is_stripped(
        self, qapp, fake_clipboard, monkeypatch
    ):
        clipboard, _state = fake_clipboard
        clipboard.setText("旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture)
        results: list[str] = []
        capture.captured.connect(results.append)
        monkeypatch.setattr(
            capture_module,
            "send_copy",
            _fake_send_copy(lambda: clipboard.setText("before \ufffc after")),
        )

        capture.capture()
        assert _wait_until(qapp, lambda: bool(results))
        assert results == ["before  after"]
        assert _wait_until(qapp, lambda: clipboard.text() == "旧内容")
        capture.deleteLater()

    def test_same_text_new_sequence_is_captured(
        self, qapp, fake_clipboard, monkeypatch
    ):
        """文本与剪贴板原内容相同，但用户确实重新复制了一次。"""
        clipboard, _state = fake_clipboard
        clipboard.setText("同样的文本")
        capture = ElaClipboardCapture()
        _speed_up(capture)
        results: list[str] = []
        capture.captured.connect(results.append)
        monkeypatch.setattr(
            capture_module,
            "send_copy",
            _fake_send_copy(lambda: clipboard.setText("同样的文本")),
        )

        capture.capture()
        assert _wait_until(qapp, lambda: bool(results))
        assert results == ["同样的文本"]
        assert _wait_until(qapp, lambda: clipboard.text() == "同样的文本")
        capture.deleteLater()

    def test_image_only_selection_fails_and_restores_text(
        self, qapp, fake_clipboard, monkeypatch
    ):
        """纯图片选区不弹窗，但注入过的剪贴板要还原。"""
        clipboard, _state = fake_clipboard
        clipboard.setText("旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture, timeout_ms=40)
        monkeypatch.setattr(capture_module, "_IMAGE_TEXT_GRACE_MS", 60)
        failures: list[bool] = []
        results: list[str] = []
        capture.failed.connect(lambda: failures.append(True))
        capture.captured.connect(results.append)
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        capture_module.send_copy = _fake_send_copy(lambda: clipboard.setImage(image))

        capture.capture()
        assert _wait_until(qapp, lambda: bool(failures))
        assert results == []
        assert _wait_until(qapp, lambda: clipboard.text() == "旧内容")
        assert clipboard.mimeData().hasImage() is False
        capture.deleteLater()

    def test_success_restores_image_baseline(
        self, qapp, fake_clipboard, monkeypatch
    ):
        """基准是图片时，取词成功后也要把图片还回去。"""
        clipboard, _state = fake_clipboard
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))
        clipboard.setImage(image)
        capture = ElaClipboardCapture()
        _speed_up(capture)
        results: list[str] = []
        capture.captured.connect(results.append)
        monkeypatch.setattr(
            capture_module,
            "send_copy",
            _fake_send_copy(lambda: clipboard.setText("选中文本")),
        )

        capture.capture()
        assert _wait_until(qapp, lambda: bool(results))
        assert results == ["选中文本"]
        assert _wait_until(qapp, lambda: clipboard.mimeData().hasImage())
        assert clipboard.image().pixelColor(0, 0).name() == "#ff0000"
        assert clipboard.text() == ""
        capture.deleteLater()

    def test_delayed_text_after_image_is_captured(
        self, qapp, fake_clipboard, monkeypatch
    ):
        """图片先写入、文本稍后才到时，宽限窗口内仍能取词。"""
        clipboard, _state = fake_clipboard
        clipboard.setText("旧内容")
        capture = ElaClipboardCapture()
        _speed_up(capture, timeout_ms=50)
        monkeypatch.setattr(capture_module, "_IMAGE_TEXT_GRACE_MS", 400)
        results: list[str] = []
        capture.captured.connect(results.append)
        image = QImage(8, 8, QImage.Format.Format_ARGB32)
        image.fill(QColor("red"))

        def fake() -> bool:
            clipboard.setImage(image)
            timer = QTimer(capture)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: clipboard.setText("延迟文本"))
            timer.start(150)
            return True

        monkeypatch.setattr(capture_module, "send_copy", fake)
        capture.capture()
        assert _wait_until(qapp, lambda: bool(results))
        assert results == ["延迟文本"]
        assert _wait_until(qapp, lambda: clipboard.text() == "旧内容")
        capture.deleteLater()
