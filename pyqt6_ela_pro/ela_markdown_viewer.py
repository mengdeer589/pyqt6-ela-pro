"""兼容入口：实现位于 :mod:`pyqt6_ela_pro.markdown_viewer`。"""

from .markdown_viewer import (
    ElaMarkdownViewer,
    defaultMarkdownBodyFontFamily,
    defaultMarkdownTheme,
    isFontFamilyAvailable,
    markdownThemes,
    registerMarkdownTheme,
    setDefaultMarkdownBodyFontFamily,
    setDefaultMarkdownTheme,
    unregisterMarkdownTheme,
)
from .markdown_viewer import appearance as _appearance
from .markdown_viewer import code as _code
from .markdown_viewer import export as _export
from .markdown_viewer import fonts as _fonts
from .markdown_viewer import interaction as _interaction
from .markdown_viewer import media as _media
from .markdown_viewer import mermaid as _mermaid
from .markdown_viewer import preprocess as _preprocess
from .markdown_viewer import render as _render
from .markdown_viewer import selection as _selection
from .markdown_viewer import stream as _stream
from .markdown_viewer import syntax as _syntax
from .markdown_viewer import text_browser as _text_browser
from .markdown_viewer import themes as _themes
from .markdown_viewer import tokens as _tokens
from .markdown_viewer import viewer as _viewer

_MODULES = (
    _viewer,
    _appearance,
    _stream,
    _mermaid,
    _media,
    _interaction,
    _preprocess,
    _render,
    _selection,
    _syntax,
    _text_browser,
    _themes,
    _code,
    _fonts,
    _tokens,
    _export,
)

__all__ = [
    "ElaMarkdownViewer",
    "defaultMarkdownBodyFontFamily",
    "defaultMarkdownTheme",
    "isFontFamilyAvailable",
    "markdownThemes",
    "registerMarkdownTheme",
    "setDefaultMarkdownBodyFontFamily",
    "setDefaultMarkdownTheme",
    "unregisterMarkdownTheme",
]


def __getattr__(name: str):
    """测试 / 工具链仍可从旧路径取私有符号。"""
    for module in _MODULES:
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
