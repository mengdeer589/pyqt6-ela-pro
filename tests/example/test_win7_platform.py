"""示例启动的 Win7 QPA 平台选择契约。"""

from __future__ import annotations

import os
import types

from pyqt6_ela_pro.example import __main__ as example_main


class _FakeSys:
    def __init__(self, platform: str, version=None):
        self.platform = platform
        self._version = version

    def getwindowsversion(self):
        if self._version is None:
            raise OSError("no windows version")
        return self._version


class TestWin7QpaPlatform:
    def test_detects_windows_7(self, monkeypatch):
        monkeypatch.setattr(
            example_main,
            "sys",
            _FakeSys("win32", types.SimpleNamespace(major=6, minor=1)),
        )
        assert example_main._is_windows_7()

    def test_windows_10_is_not_windows_7(self, monkeypatch):
        monkeypatch.setattr(
            example_main,
            "sys",
            _FakeSys("win32", types.SimpleNamespace(major=10, minor=0)),
        )
        assert not example_main._is_windows_7()

    def test_non_windows_is_not_windows_7(self, monkeypatch):
        monkeypatch.setattr(example_main, "sys", _FakeSys("linux"))
        assert not example_main._is_windows_7()

    def test_win7_sets_gdi_platform_only_when_unset(self, monkeypatch):
        monkeypatch.setattr(example_main, "_is_windows_7", lambda: True)
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        example_main._prepare_qpa_platform()
        assert os.environ["QT_QPA_PLATFORM"] == "windows:nodirectwrite"

    def test_explicit_platform_is_not_overridden(self, monkeypatch):
        monkeypatch.setattr(example_main, "_is_windows_7", lambda: True)
        monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
        example_main._prepare_qpa_platform()
        assert os.environ["QT_QPA_PLATFORM"] == "windows"

    def test_non_win7_does_not_set_platform(self, monkeypatch):
        monkeypatch.setattr(example_main, "_is_windows_7", lambda: False)
        monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
        example_main._prepare_qpa_platform()
        assert "QT_QPA_PLATFORM" not in os.environ
