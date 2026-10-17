from __future__ import annotations

import ctypes

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from PyQt6.QtCore import QUrl

import pyqt6_ela_pro.browser_embedder as browser_embedder_mod

from pyqt6_ela_pro.browser_embedder import (
    _BrowserController,
    _BrowserSession,
    _normalize_url,
    _parse_target_id,
    ElaBrowserEmbedder,
)


def _make_embedder() -> ElaBrowserEmbedder:
    """构造一个不依赖真实 pywin32 的实例（win32 全部替换为 mock）。"""
    with patch.multiple(
        "pyqt6_ela_pro.browser_embedder",
        win32gui=MagicMock(),
        win32con=MagicMock(),
        win32process=MagicMock(),
    ):
        return ElaBrowserEmbedder(webview_path=Path("chrome.exe"))


class TestBrowserControllerInit:
    def test_initialization(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222", timeout=5.0)
        assert ctrl._debugger_url == "ws://127.0.0.1:9222"
        assert ctrl._timeout == 5.0
        assert ctrl._running is False
        assert ctrl._message_id == 0
        assert ctrl._callbacks == {}
        ctrl.close()

    def test_has_signals(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        assert hasattr(ctrl, "cdpReady")
        assert hasattr(ctrl, "errorOccurred")
        assert hasattr(ctrl, "consoleMessage")
        ctrl.close()


class TestBrowserControllerConnection:
    def test_connect_creates_websocket(self):
        with patch("pyqt6_ela_pro.browser_embedder.QWebSocket") as mock_ws:
            ctrl = _BrowserController("ws://127.0.0.1:9222")
            ctrl.connect()
            mock_ws_instance = mock_ws.return_value
            mock_ws_instance.open.assert_called_with(QUrl("ws://127.0.0.1:9222"))
            ctrl.close()

    def test_close_cleans_up(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        ctrl._ws = MagicMock()
        ctrl.close()
        assert ctrl._running is False
        assert ctrl._ws is None

    def test_send_command_returns_id(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        ctrl._ws = MagicMock()
        mid = ctrl.sendCommand("Page.enable")
        assert mid == 0
        ctrl.close()

    def test_runJS_calls_send_command(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        ctrl._ws = MagicMock()
        mid = ctrl.runJS("1+1")
        assert mid >= 0
        ctrl.close()

    def test_navigate_calls_send_command(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        ctrl._ws = MagicMock()
        mid = ctrl.navigate("http://example.com")
        assert mid >= 0
        ctrl.close()

    def test_reload_calls_send_command(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        ctrl._ws = MagicMock()
        mid = ctrl.reload()
        assert mid >= 0
        ctrl.close()


class TestBrowserControllerCallbacks:
    def test_set_load_started_callback(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        cb = MagicMock()
        ctrl.set_loadStarted_callback(cb)
        assert ctrl._loadStarted_callback is cb
        ctrl.close()

    def test_set_load_finished_callback(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        cb = MagicMock()
        ctrl.set_loadFinished_callback(cb)
        assert ctrl._loadFinished_callback is cb
        ctrl.close()

    def test_handle_event_frame_started_loading(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        cb = MagicMock()
        ctrl.set_loadStarted_callback(cb)
        ctrl._handle_event("Page.frameStartedLoading", {})
        cb.assert_called_once()
        ctrl.close()

    def test_handle_event_load_event_fired(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        cb = MagicMock()
        ctrl.set_loadFinished_callback(cb)
        ctrl._handle_event("Page.loadEventFired", {})
        cb.assert_called_once()
        ctrl.close()


class TestElaBrowserEmbedderInit:
    def test_check_dependencies_raises_without_win32(self):
        with patch("pyqt6_ela_pro.browser_embedder.win32gui", None):
            with patch("pyqt6_ela_pro.browser_embedder.win32con", None):
                import pyqt6_ela_pro.browser_embedder as be

                with pytest.raises(ImportError, match="pywin32"):
                    be.ElaBrowserEmbedder._checkDependencies()

    def test_has_signals(self):
        with patch.multiple(
            "pyqt6_ela_pro.browser_embedder",
            win32gui=MagicMock(),
            win32con=MagicMock(),
            win32process=MagicMock(),
        ):
            embedder = ElaBrowserEmbedder(webview_path=Path("chrome.exe"))
            assert hasattr(embedder, "loadStarted")
            assert hasattr(embedder, "loadFinished")
            assert hasattr(embedder, "logMessage")
            assert hasattr(embedder, "embedCompleted")
            assert hasattr(embedder, "consoleMessage")
            embedder.deleteLater()


class TestElaBrowserEmbedderStatic:
    def test_get_all_instances_returns_list(self):
        instances = ElaBrowserEmbedder.getAllInstances()
        assert isinstance(instances, list)


class TestElaBrowserEmbedderNavigateRunJS:
    def test_navigate_returns_none_when_no_controller(self):
        with patch.multiple(
            "pyqt6_ela_pro.browser_embedder",
            win32gui=MagicMock(),
            win32con=MagicMock(),
            win32process=MagicMock(),
        ):
            embedder = ElaBrowserEmbedder(webview_path=Path("chrome.exe"))
            result = embedder.navigate("http://example.com")
            assert result is None
            embedder.deleteLater()

    def test_runJS_returns_none_when_no_controller(self):
        with patch.multiple(
            "pyqt6_ela_pro.browser_embedder",
            win32gui=MagicMock(),
            win32con=MagicMock(),
            win32process=MagicMock(),
        ):
            embedder = ElaBrowserEmbedder(webview_path=Path("chrome.exe"))
            result = embedder.runJS("1+1")
            assert result is None
            embedder.deleteLater()

    def test_load_url_path_conversion(self):
        with patch.multiple(
            "pyqt6_ela_pro.browser_embedder",
            win32gui=MagicMock(),
            win32con=MagicMock(),
            win32process=MagicMock(),
        ):
            embedder = ElaBrowserEmbedder(webview_path=Path("chrome.exe"))
            result = embedder.load_url(Path("C:\\page.html"))
            assert result is None
            embedder.deleteLater()

    def test_load_url_string(self):
        with patch.multiple(
            "pyqt6_ela_pro.browser_embedder",
            win32gui=MagicMock(),
            win32con=MagicMock(),
            win32process=MagicMock(),
        ):
            embedder = ElaBrowserEmbedder(webview_path=Path("chrome.exe"))
            result = embedder.load_url("http://example.com")
            assert result is None
            embedder.deleteLater()


class TestUrlHelpers:
    def test_normalize_url_trims_slash_and_case(self):
        assert _normalize_url("HTTPS://Example.com/a/") == "https://example.com/a"
        assert _normalize_url("http://example.com/#frag") == "http://example.com"
        assert _normalize_url("http://example.com") == "http://example.com"

    def test_parse_target_id(self):
        url = "ws://127.0.0.1:9222/devtools/page/ABC123"
        assert _parse_target_id(url) == "ABC123"
        assert _parse_target_id("ws://127.0.0.1:9222/devtools/browser/x") == ""
        assert _parse_target_id("") == ""


class TestPickDebuggerUrl:
    @staticmethod
    def _embedder(url, claimed=None):
        embedder = _make_embedder()
        embedder._embedded_url = url
        session = MagicMock()
        session.claimed_target_ids = set(claimed or [])
        embedder._session = session
        return embedder

    def test_url_match_wins(self):
        embedder = self._embedder("https://www.bilibili.com")
        data = [
            {
                "type": "page",
                "id": "a",
                "url": "https://www.baidu.com",
                "webSocketDebuggerUrl": "ws://x/1",
            },
            {
                "type": "page",
                "id": "b",
                "url": "https://www.bilibili.com/",
                "webSocketDebuggerUrl": "ws://x/2",
            },
        ]
        assert embedder._pick_debugger_url(data) == "ws://x/2"
        embedder.deleteLater()

    def test_unique_unclaimed_candidate_is_used(self):
        embedder = self._embedder("https://www.bilibili.com/?spm=1")
        data = [
            {
                "type": "page",
                "id": "a",
                "url": "https://www.baidu.com",
                "webSocketDebuggerUrl": "ws://x/1",
            },
            {
                "type": "page",
                "id": "b",
                "url": "https://www.bilibili.com/?redirected=1",
                "webSocketDebuggerUrl": "ws://x/2",
            },
        ]
        assert embedder._pick_debugger_url(data) == "ws://x/2"
        embedder.deleteLater()

    def test_multiple_candidates_refuse_to_guess(self):
        embedder = self._embedder("https://www.bilibili.com/?spm=1")
        data = [
            {
                "type": "page",
                "id": "a",
                "url": "https://a.com",
                "webSocketDebuggerUrl": "ws://x/1",
            },
            {
                "type": "page",
                "id": "b",
                "url": "https://b.com",
                "webSocketDebuggerUrl": "ws://x/2",
            },
        ]
        assert embedder._pick_debugger_url(data) is None
        embedder.deleteLater()

    def test_claimed_target_is_skipped(self):
        embedder = self._embedder("https://x.com", claimed=["a"])
        data = [
            {
                "type": "page",
                "id": "a",
                "url": "https://x.com",
                "webSocketDebuggerUrl": "ws://x/1",
            }
        ]
        assert embedder._pick_debugger_url(data) is None
        embedder.deleteLater()


class TestCloseTargetPage:
    def test_ignores_foreign_page_target(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222", target_id="mine")
        ctrl.sendCommand = MagicMock(return_value=1)
        ctrl._close_target_page(
            {"targetInfo": {"type": "page", "targetId": "other", "url": "https://a"}}
        )
        ctrl.sendCommand.assert_not_called()
        ctrl.close()

    def test_closes_popup_opened_by_self(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222", target_id="mine")
        ctrl.sendCommand = MagicMock(return_value=1)
        ctrl._close_target_page(
            {
                "targetInfo": {
                    "type": "page",
                    "targetId": "popup",
                    "url": "https://a",
                    "openerId": "mine",
                }
            }
        )
        ctrl.sendCommand.assert_called_once_with(
            "Target.closeTarget", {"targetId": "popup"}
        )
        ctrl.close()


class TestControllerStateCleanup:
    def test_loading_finished_pops_pending_maps(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        ctrl._pending_request_urls["1"] = "http://a"
        ctrl._pending_response_urls["1"] = "http://b"
        ctrl._handle_event("Network.loadingFinished", {"requestId": "1"})
        assert ctrl._pending_request_urls == {}
        assert ctrl._pending_response_urls == {}
        ctrl.close()

    def test_pending_maps_are_bounded(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        for i in range(2100):
            ctrl._handle_event(
                "Network.requestWillBeSent",
                {"requestId": str(i), "request": {"url": f"http://a/{i}"}},
            )
        assert len(ctrl._pending_request_urls) <= 2048
        ctrl.close()

    def test_send_command_disconnected_keeps_no_callback(self):
        ctrl = _BrowserController("ws://127.0.0.1:9222")
        cb = MagicMock()
        assert ctrl.sendCommand("Page.enable", callback=cb) == -1
        assert ctrl._callbacks == {}
        assert ctrl._result_timers == {}
        ctrl.close()


class TestBrowserSessionLaunchQueue:
    def test_launch_is_serialized(self):
        session = _BrowserSession(Path("chrome.exe"), 9222, Path("tmp"))
        calls = []
        session.request_launch("a", lambda: calls.append("a"))
        session.request_launch("b", lambda: calls.append("b"))
        assert calls == ["a"]
        session.finish_launch("a")
        assert calls == ["a", "b"]

    def test_finish_launch_removes_queued_token(self):
        session = _BrowserSession(Path("chrome.exe"), 9222, Path("tmp"))
        calls = []
        session.request_launch("a", lambda: calls.append("a"))
        session.request_launch("b", lambda: calls.append("b"))
        session.finish_launch("b")  # b 还没轮到 → 仅出队
        session.finish_launch("a")
        assert calls == ["a"]

    def test_conflicts_reports_diff(self):
        session = _BrowserSession(Path("chrome.exe"), 9222, Path("tmp"))
        assert session.conflicts(Path("chrome.exe"), 9222, None) == []
        items = session.conflicts(Path("other.exe"), 9333, ["--foo"])
        assert len(items) == 3


class TestEmbedSessionAcquire:
    def test_embed_acquires_shared_session_once_and_releases(self):
        embedder = _make_embedder()
        try:
            with (
                patch.multiple(
                    "pyqt6_ela_pro.browser_embedder",
                    win32gui=MagicMock(),
                    win32con=MagicMock(),
                    win32process=MagicMock(),
                ),
                patch.object(_BrowserSession, "launch_start", MagicMock()),
                patch.object(ElaBrowserEmbedder, "_start_hwnd_polling", MagicMock()),
            ):
                embedder.embed("http://example.com")
                session = embedder._session
                assert session is not None
                assert session is _BrowserSession._instance
                # 再 embed 一次不应重复 acquire（引用计数泄漏）
                embedder._embeddedInfo = None
                embedder.embed("http://example.com")
                assert embedder._session is session
            embedder.release()
            assert embedder._session is None
            assert _BrowserSession._instance is None
        finally:
            _BrowserSession._instance = None
            _BrowserSession._refcount = 0
            embedder.deleteLater()


class TestImeFilterMessageGating:
    """IME 过滤器只在交互类消息上工作，且无活跃浏览器窗口时完全绕行。"""

    @staticmethod
    def _msg_addr(message: int) -> int:
        msg = browser_embedder_mod._MSG()
        msg.message = message
        return ctypes.addressof(msg)

    def test_mouse_move_is_not_processed(self, qapp):
        be = browser_embedder_mod
        be._ime_filter.reset()
        be._register_chrome_hwnd(0xBEEF)
        try:
            with patch.object(
                be.QApplication, "widgetAt", MagicMock(return_value=None)
            ) as widget_at:
                result = be._ime_filter.nativeEventFilter(
                    "windows_generic_MSG", self._msg_addr(0x0200)
                )
            assert result == (False, 0)
            widget_at.assert_not_called()
        finally:
            be._unregister_chrome_hwnd(0xBEEF)

    def test_keyboard_message_triggers_cursor_lookup(self, qapp):
        be = browser_embedder_mod
        be._ime_filter.reset()
        be._register_chrome_hwnd(0xBEEF)
        try:
            with patch.object(
                be.QApplication, "widgetAt", MagicMock(return_value=None)
            ) as widget_at:
                be._ime_filter.nativeEventFilter(
                    "windows_generic_MSG", self._msg_addr(0x0100)
                )
            assert widget_at.called
        finally:
            be._unregister_chrome_hwnd(0xBEEF)

    def test_skips_work_when_no_active_browser(self, qapp):
        be = browser_embedder_mod
        be._ime_filter.reset()
        saved = set(be._active_chrome_hwnds)
        be._active_chrome_hwnds.clear()
        try:
            with patch.object(
                be.QApplication, "widgetAt", MagicMock(return_value=None)
            ) as widget_at:
                result = be._ime_filter.nativeEventFilter(
                    "windows_generic_MSG", self._msg_addr(0x0100)
                )
            assert result == (False, 0)
            widget_at.assert_not_called()
        finally:
            be._active_chrome_hwnds.update(saved)


class TestCookieJarExpiry:
    def test_max_age_zero_removes_cookie(self):
        embedder = _make_embedder()
        embedder._jar_on_set_cookie("http://a.com", "k=v")
        assert embedder.get_cookie_header() == "k=v"
        embedder._jar_on_set_cookie("http://a.com", "k=; Max-Age=0")
        assert embedder.get_cookie_header() == ""
        embedder.deleteLater()

    def test_expired_cookie_is_pruned_on_read(self):
        embedder = _make_embedder()
        embedder._jar_on_set_cookie("http://a.com", "k=v; Max-Age=-1")
        assert embedder.get_cookie_header() == ""
        assert embedder._cookie_store == {}
        embedder.deleteLater()

    def test_session_cookie_survives(self):
        embedder = _make_embedder()
        embedder._jar_on_set_cookie(
            "http://a.com", "k=v; Expires=Wed, 21 Oct 2099 07:28:00 GMT"
        )
        assert embedder.get_cookie_header() == "k=v"
        embedder.deleteLater()
