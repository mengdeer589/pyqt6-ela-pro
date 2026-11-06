"""``terminal_view`` 包结构守卫：拆分后公开路径与测试用私有符号都必须可达。"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PACKAGE = "pyqt6_ela_pro.terminal_view"
SUBMODULES = ("theme", "ansi", "view")
PUBLIC = (
    "AnsiColor",
    "AnsiParser",
    "ElaTerminalView",
    "TerminalLine",
    "TerminalSpan",
    "TerminalStyle",
    "defaultTerminalTheme",
    "registerTerminalTheme",
    "setDefaultTerminalTheme",
    "terminalThemes",
    "unregisterTerminalTheme",
)
PRIVATE = ("_HIGHLIGHT", "_HIGHLIGHT_RATIO", "_blend")


def test_package_directory_replaces_module():
    pkg = importlib.import_module(PACKAGE)
    assert hasattr(pkg, "__path__")
    init = Path(pkg.__file__)
    assert init.name == "__init__.py"
    assert not init.parent.with_suffix(".py").exists()


@pytest.mark.parametrize("name", SUBMODULES)
def test_submodule_importable(name):
    module = importlib.import_module(f"{PACKAGE}.{name}")
    assert module.__name__ == f"{PACKAGE}.{name}"


@pytest.mark.parametrize("name", PUBLIC)
def test_public_names(name):
    pkg = importlib.import_module(PACKAGE)
    assert name in pkg.__all__
    assert getattr(pkg, name) is not None


def test_star_import_matches_all():
    pkg = importlib.import_module(PACKAGE)
    namespace: dict = {}
    exec(f"from {PACKAGE} import *", namespace)  # noqa: S102
    exported = {key for key in namespace if key != "__builtins__"}
    assert exported == set(pkg.__all__)


@pytest.mark.parametrize("name", PRIVATE)
def test_private_symbols_still_reachable(name):
    assert getattr(importlib.import_module(PACKAGE), name) is not None
