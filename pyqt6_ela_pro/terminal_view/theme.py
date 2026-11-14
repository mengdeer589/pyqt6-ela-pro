"""terminal_view.theme：终端主题注册表（每个主题含 Light/Dark ANSI 调色板）。"""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from .._internal import system_cjk_font_family


#: 无 CJK 系统时的默认等宽字体（中文系统走 ``_default_font_families()`` 的 CJK 字体）
_DEFAULT_FONT_FAMILY = "Consolas"

#: 8 基础色 / 8 亮色的调色板键
_BASIC_KEYS = (
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
)

_BRIGHT_KEYS = tuple(f"bright_{name}" for name in _BASIC_KEYS)

#: 调色板全部键
_PALETTE_KEYS = _BASIC_KEYS + _BRIGHT_KEYS + ("foreground", "background")


def _default_font_families() -> list[str]:
    """终端默认字体族（中文系统用**单族** CJK UI 字体，其它系统用 Consolas）。

    Consolas 渲染 CJK 走逐字形 fallback：Win7 上是慢 shaping 路径且进程级毒化
    后续文本；多族列表（等宽 + CJK 后备）同样慢，因此这里只返回单族。
    """
    cjk_family = system_cjk_font_family()
    if cjk_family:
        return [cjk_family]
    return [_DEFAULT_FONT_FAMILY]


#: 缺键回退（one-dark 暗色档），保证只定义部分键的调色板也能跑
_PALETTE_FALLBACK: dict[str, str] = {
    "black": "#3f4451",
    "red": "#e06c75",
    "green": "#98c379",
    "yellow": "#e5c07b",
    "blue": "#61afef",
    "magenta": "#c678dd",
    "cyan": "#56b6c2",
    "white": "#abb2bf",
    "bright_black": "#5a6374",
    "bright_red": "#e06c75",
    "bright_green": "#98c379",
    "bright_yellow": "#e5c07b",
    "bright_blue": "#61afef",
    "bright_magenta": "#c678dd",
    "bright_cyan": "#56b6c2",
    "bright_white": "#ffffff",
    "foreground": "#abb2bf",
    "background": "#282c34",
}

_TERMINAL_THEMES: dict[str, dict[str, dict[str, str]]] = {
    "one-dark": {
        "light": {
            "black": "#383a42",
            "red": "#e45649",
            "green": "#50a14f",
            "yellow": "#c18401",
            "blue": "#0184bc",
            "magenta": "#a626a4",
            "cyan": "#0997b3",
            "white": "#383a42",
            "bright_black": "#4f525e",
            "bright_red": "#f07171",
            "bright_green": "#4bbf73",
            "bright_yellow": "#c18401",
            "bright_blue": "#2a7ab9",
            "bright_magenta": "#d45ad0",
            "bright_cyan": "#1b9aaa",
            "bright_white": "#4f525e",
            "foreground": "#383a42",
            "background": "#fafafa",
        },
        "dark": dict(_PALETTE_FALLBACK),
    },
    "solarized": {
        "light": {
            "black": "#073642",
            "red": "#dc322f",
            "green": "#859900",
            "yellow": "#b58900",
            "blue": "#268bd2",
            "magenta": "#d33682",
            "cyan": "#2aa198",
            "white": "#eee8d5",
            "bright_black": "#002b36",
            "bright_red": "#cb4b16",
            "bright_green": "#586e75",
            "bright_yellow": "#657b83",
            "bright_blue": "#839496",
            "bright_magenta": "#6c71c4",
            "bright_cyan": "#93a1a1",
            "bright_white": "#fdf6e3",
            "foreground": "#657b83",
            "background": "#fdf6e3",
        },
        "dark": {
            "black": "#073642",
            "red": "#dc322f",
            "green": "#859900",
            "yellow": "#b58900",
            "blue": "#268bd2",
            "magenta": "#d33682",
            "cyan": "#2aa198",
            "white": "#eee8d5",
            "bright_black": "#002b36",
            "bright_red": "#cb4b16",
            "bright_green": "#586e75",
            "bright_yellow": "#657b83",
            "bright_blue": "#839496",
            "bright_magenta": "#6c71c4",
            "bright_cyan": "#93a1a1",
            "bright_white": "#fdf6e3",
            "foreground": "#839496",
            "background": "#002b36",
        },
    },
    "classic": {
        "light": {
            "black": "#000000",
            "red": "#cd3131",
            "green": "#0dbc79",
            "yellow": "#c4a000",
            "blue": "#2472c8",
            "magenta": "#bc3fbc",
            "cyan": "#11a8cd",
            "white": "#000000",
            "bright_black": "#767676",
            "bright_red": "#f14c4c",
            "bright_green": "#23d18b",
            "bright_yellow": "#f5f543",
            "bright_blue": "#3b8eea",
            "bright_magenta": "#d670d6",
            "bright_cyan": "#29b8db",
            "bright_white": "#767676",
            "foreground": "#000000",
            "background": "#ffffff",
        },
        "dark": {
            "black": "#000000",
            "red": "#cd3131",
            "green": "#0dbc79",
            "yellow": "#e5e510",
            "blue": "#2472c8",
            "magenta": "#bc3fbc",
            "cyan": "#11a8cd",
            "white": "#cccccc",
            "bright_black": "#767676",
            "bright_red": "#f14c4c",
            "bright_green": "#23d18b",
            "bright_yellow": "#f5f543",
            "bright_blue": "#3b8eea",
            "bright_magenta": "#d670d6",
            "bright_cyan": "#29b8db",
            "bright_white": "#ffffff",
            "foreground": "#cccccc",
            "background": "#0c0c0c",
        },
    },
}

_DEFAULT_THEME_NAME = "one-dark"

_BUILTIN_THEMES = ("one-dark", "solarized", "classic")


def terminalThemes() -> list:
    """列出已注册的终端主题名称。"""
    return list(_TERMINAL_THEMES)


def defaultTerminalTheme() -> str:
    """获取新建实例默认使用的终端主题名。"""
    return _DEFAULT_THEME_NAME


def setDefaultTerminalTheme(name: str) -> None:
    """设置新建 :class:`ElaTerminalView` 实例的默认主题。

    不影响已存在的实例（用 ``view.setTerminalTheme()`` 单独改）。

    :param name: 主题名，未注册时抛 ``KeyError``
    """
    global _DEFAULT_THEME_NAME
    if name not in _TERMINAL_THEMES:
        raise KeyError(f"未注册的终端主题 {name!r}，可用：{sorted(_TERMINAL_THEMES)}")
    _DEFAULT_THEME_NAME = name


def registerTerminalTheme(name: str, light: dict, dark: dict) -> None:
    """注册（或覆盖）一套终端主题。

    ``light`` / ``dark`` 是「调色板键 → 十六进制色串」的字典，键见
    ``_PALETTE_KEYS``（``black`` … ``bright_white`` / ``foreground`` /
    ``background``）。**允许只给部分键**，其余回退到 ``one-dark`` 暗色档。

    :param name: 主题名
    :param light: 亮色主题下的颜色
    :param dark: 暗色主题下的颜色
    """
    if not name:
        raise ValueError("主题名不能为空")
    _TERMINAL_THEMES[name] = {"light": dict(light), "dark": dict(dark)}


def unregisterTerminalTheme(name: str) -> None:
    """注销一套终端主题。
    内置三套、或正在作为默认的那套不可注销（抛 ``ValueError``）；名称未注册抛
    ``KeyError``。
    """
    if name in _BUILTIN_THEMES:
        raise ValueError(f"内置主题 {name!r} 不可注销")
    if name not in _TERMINAL_THEMES:
        raise KeyError(name)
    if _DEFAULT_THEME_NAME == name:
        raise ValueError(f"主题 {name!r} 正在作为默认，不可注销")
    del _TERMINAL_THEMES[name]


def _resolve_palette(name: str, light: bool) -> dict:
    """按名称 + 明暗解析出完整的 ``QColor`` 调色板（未注册名称回退到默认）。

    ``foreground`` / ``background`` 缺省时取 eTheme 令牌。
    """
    theme = _TERMINAL_THEMES.get(name) or _TERMINAL_THEMES[_DEFAULT_THEME_NAME]
    raw = theme["light" if light else "dark"]
    merged = {**_PALETTE_FALLBACK, **raw}
    mode = eTheme.getThemeMode()
    if not raw.get("foreground"):
        merged["foreground"] = eTheme.getThemeColor(
            mode, ElaThemeType.ThemeColor.BasicText
        )
    if not raw.get("background"):
        merged["background"] = eTheme.getThemeColor(
            mode, ElaThemeType.ThemeColor.BasicBaseAlpha
        )
    return {key: QColor(merged[key]) for key in _PALETTE_KEYS}
