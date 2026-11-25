"""``_clipboard.set_clipboard_text``：首写 / 异步重试 / 请求取代。"""

from __future__ import annotations

import sys

import pytest
from _qthelpers import wait_until
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro import _clipboard


@pytest.fixture
def fast_retry(monkeypatch):
    """把重试间隔压到 0，测试不依赖真实时钟。"""
    monkeypatch.setattr(_clipboard, "_RETRY_DELAYS_MS", (0, 0, 0))


@pytest.fixture
def writes(monkeypatch):
    """替换真实写入；``script`` 按顺序决定每次写入的成败。"""
    state = {"script": [], "texts": []}

    def fake_write(text: str) -> bool:
        state["texts"].append(text)
        return state["script"].pop(0) if state["script"] else True

    monkeypatch.setattr(_clipboard, "_write_text", fake_write)
    return state


class TestSetClipboardText:
    def test_first_write_calls_done_synchronously(self, make, fast_retry, writes):
        ctx = make(QWidget)
        results = []
        assert _clipboard.set_clipboard_text("hi", ctx, results.append) is True
        assert results == [True]
        assert writes["texts"] == ["hi"]

    def test_retries_until_write_succeeds(self, qapp, make, fast_retry, writes):
        writes["script"] = [False, False]
        ctx = make(QWidget)
        results = []
        assert _clipboard.set_clipboard_text("retry", ctx, results.append) is False
        assert results == []
        assert wait_until(qapp, lambda: results == [True])
        assert writes["texts"] == ["retry", "retry", "retry"]

    def test_gives_up_after_retry_budget(self, qapp, make, fast_retry, writes):
        writes["script"] = [False] * 10
        ctx = make(QWidget)
        results = []
        assert _clipboard.set_clipboard_text("fail", ctx, results.append) is False
        assert wait_until(qapp, lambda: results == [False])
        # 首写 + 3 个重试间隔
        assert len(writes["texts"]) == 4

    def test_newer_request_supersedes_old_retry(self, qapp, make, fast_retry, writes):
        writes["script"] = [False]
        ctx = make(QWidget)
        results = []
        _clipboard.set_clipboard_text("old", ctx, results.append)
        assert results == []
        _clipboard.set_clipboard_text("new", ctx, results.append)
        assert results == [True]
        # 让旧请求的 0ms 重试跑完：必须被新请求 token 拦下
        assert not wait_until(qapp, lambda: False, timeout_ms=30)
        assert writes["texts"] == ["old", "new"]
        assert results == [True]

    def test_empty_text_writes_empty(self, make, fast_retry, writes):
        ctx = make(QWidget)
        results = []
        assert _clipboard.set_clipboard_text("", ctx, results.append) is True
        assert results == [True]
        assert writes["texts"] == [""]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("a\nb", "a\r\nb"),
        ("a\r\nb", "a\r\nb"),
        ("a\rb", "a\r\nb"),
    ],
)
def test_windows_text_normalizes_crlf(source, expected):
    assert _clipboard._to_windows_text(source) == expected


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 剪贴板路径")
def test_native_write_is_visible_to_qt(qapp, make):
    """原生写入不依赖 Qt 的 OLE 剪贴板，写完 Qt 侧必须能读回。"""
    ctx = make(QWidget)
    clipboard = qapp.clipboard()
    old = clipboard.text()
    token = "__ela_clipboard_native_test__"
    results = []
    try:
        assert _clipboard.set_clipboard_text(token, ctx, results.append) is True
        assert results == [True]
        assert wait_until(qapp, lambda: clipboard.text() == token)
    finally:
        if old:
            _clipboard.set_clipboard_text(old, ctx)
        else:
            clipboard.clear()
