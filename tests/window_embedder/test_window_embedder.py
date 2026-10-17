from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import pyqt6_ela_pro.window_embedder as we


class TestElaWindowEmbedderInit:
    @patch("pyqt6_ela_pro.window_embedder.win32gui", None)
    def test_check_dependencies_raises_when_no_win32(self):

        with pytest.raises(ImportError, match="pywin32"):
            we.ElaWindowEmbedder._checkDependencies()

    def test_has_required_signals(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            embedder = ElaWindowEmbedder()
            assert hasattr(embedder, "windowEmbedded")
            assert hasattr(embedder, "windowReleased")
            assert hasattr(embedder, "windowNotFound")
            assert hasattr(embedder, "embedError")
            assert hasattr(embedder, "embedTimeout")
            embedder.deleteLater()


class TestElaWindowEmbedderFindWindow:
    def test_find_window_by_title_empty(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            assert e.findWindowByTitle("") == 0
            e.deleteLater()

    def test_find_window_by_class_empty(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            assert e.findWindowByClass("") == 0
            e.deleteLater()


class TestElaWindowEmbedderIsWindowValid:
    def test_is_window_valid_zero(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            assert e.isWindowValid(0) is False
            e.deleteLater()


class TestElaWindowEmbedderGetWindowInfo:
    def test_get_window_info_invalid_hwnd(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            e.isWindowValid = MagicMock(return_value=False)
            assert e.getWindowInfo(12345) is None
            e.deleteLater()


class TestElaWindowEmbedderEmbedByHwnd:
    def test_embed_by_hwnd_starts_retry_timer_on_failure(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            e._tryEmbedOnce = MagicMock(return_value=False)
            result = e.embedByHwnd(12345)
            assert result is True
            assert e._embedTimer.isActive() is True
            e._embedTimer.stop()
            e.deleteLater()


class TestElaWindowEmbedderRelease:
    def test_release_when_not_embedded(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            assert e.release() is True
            e.deleteLater()


class TestElaWindowEmbedderProperties:
    def test_has_embedded_window_false_initially(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            assert e.hasEmbeddedWindow is False
            e.deleteLater()

    def test_embedded_window_info_none_initially(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            assert e.embeddedWindowInfo is None
            e.deleteLater()


class TestNativeClientSize:
    """外部窗口尺寸取父窗口客户区（高 DPI 缩放下逻辑尺寸会小一圈）。"""

    def test_uses_native_client_rect(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            we.win32gui.GetClientRect.return_value = (0, 0, 1200, 900)
            assert e._native_client_size() == (1200, 900)
            e.deleteLater()

    def test_falls_back_to_widget_size(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            e.resize(320, 240)
            we.win32gui.GetClientRect.side_effect = RuntimeError("boom")
            assert e._native_client_size() == (320, 240)
            e.deleteLater()

    def test_empty_rect_falls_back(self):
        with patch.multiple(
            "pyqt6_ela_pro.window_embedder",
            win32gui=MagicMock(),
            win32api=MagicMock(),
            win32con=MagicMock(),
        ):
            from pyqt6_ela_pro.window_embedder import ElaWindowEmbedder

            e = ElaWindowEmbedder()
            e.resize(320, 240)
            we.win32gui.GetClientRect.return_value = (0, 0, 0, 0)
            assert e._native_client_size() == (320, 240)
            e.deleteLater()
