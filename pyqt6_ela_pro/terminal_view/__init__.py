"""终端输出展示组件（只读）：接收原始文本 / ANSI，按模型重建渲染。

``_lines`` 是唯一真相，``QTextDocument`` 只是派生视图；细节见 ``docs/terminal.md``。
"""

from __future__ import annotations

from . import ansi as _ansi
from . import theme as _theme
from . import view as _view
from .ansi import AnsiColor, AnsiParser, TerminalLine, TerminalSpan, TerminalStyle
from .theme import (
    defaultTerminalTheme,
    registerTerminalTheme,
    setDefaultTerminalTheme,
    terminalThemes,
    unregisterTerminalTheme,
)
from .view import ElaTerminalView

__all__ = [
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
]

_MODULES = (_view, _ansi, _theme)


def __getattr__(name: str):
    """私有符号仍可从 ``pyqt6_ela_pro.terminal_view`` 直接取。"""
    for module in _MODULES:
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
