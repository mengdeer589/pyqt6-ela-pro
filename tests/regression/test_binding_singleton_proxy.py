"""``__wrapsingleton`` 的缓存契约（bug #19 的防御性收口）。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

WHEEL_INIT = (
    Path(__file__).resolve().parents[2]
    / "PyElaWidgetTools"
    / "scripts"
    / "wheel"
    / "__init__.py"
)


class _Theme:
    def getThemeMode(self):
        return "light"

    def getThemeColor(self, mode, color):
        return f"{mode}:{color}"


class _App:
    def getFontPixelSize(self):
        return 13

    def init(self):
        return "inited"


class _FakeTheme:
    calls = 0

    @classmethod
    def getInstance(cls):
        cls.calls += 1
        return _THEME


class _FakeApplication:
    calls = 0

    @classmethod
    def getInstance(cls):
        cls.calls += 1
        return _APP


class _FakeThemeType:
    ThemeMode = str
    ThemeColor = str


_THEME = _Theme()
_APP = _App()


def _load_proxy_module():
    package = "_ela_wheel_init_probe"
    fake_package = types.ModuleType(package)
    fake_package.__path__ = [str(WHEEL_INIT.parent)]
    sys.modules[package] = fake_package

    upstream = types.ModuleType(f"{package}.ElaWidgetTools")
    upstream.ElaTheme = _FakeTheme
    upstream.ElaApplication = _FakeApplication
    upstream.ElaThemeType = _FakeThemeType
    sys.modules[f"{package}.ElaWidgetTools"] = upstream

    spec = importlib.util.spec_from_file_location(
        package,
        WHEEL_INIT,
        submodule_search_locations=[str(WHEEL_INIT.parent)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return module


def test_proxy_caches_instance_and_forwards_attributes():
    _FakeTheme.calls = 0
    _FakeApplication.calls = 0
    module = _load_proxy_module()
    try:
        assert module.eTheme.getThemeMode() == "light"
        assert _FakeTheme.calls == 1
        assert module.eTheme.getThemeColor("light", "accent") == "light:accent"
        assert module.ElaThemeColor("dark", "text") == "dark:text"
        assert _FakeTheme.calls == 1
        assert module.eTheme.__dict__["_instance"] is _THEME

        assert module.eApp.getFontPixelSize() == 13
        assert module.eApp.init() == "inited"
        assert _FakeApplication.calls == 1
        assert module.eApp.__dict__["_instance"] is _APP

        with pytest.raises(AttributeError):
            module.eTheme.missing
    finally:
        sys.modules.pop("_ela_wheel_init_probe.ElaWidgetTools", None)
        sys.modules.pop("_ela_wheel_init_probe", None)
