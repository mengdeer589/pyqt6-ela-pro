"""LaTeX 数学公式轻量渲染（纯 QPainter，无 matplotlib 依赖）。

支持的语法子集与缓存策略见 ``docs/math.md``。
"""

from __future__ import annotations

from . import layout as _layout
from . import parser as _parser
from . import preprocess as _preprocess
from . import render as _render
from . import tables as _tables
from .render import clear_cache, extract_math, render_formula, set_cache_capacity
from .tables import MATH_ENVS

__all__ = [
    "extract_math",
    "render_formula",
    "clear_cache",
    "set_cache_capacity",
    "MATH_ENVS",
]

_MODULES = (_render, _layout, _parser, _preprocess, _tables)


def __getattr__(name: str):
    """私有符号仍可从 ``pyqt6_ela_pro.math_lite`` 直接取。"""
    for module in _MODULES:
        try:
            return getattr(module, name)
        except AttributeError:
            continue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
