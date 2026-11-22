"""聊天组件主题工具：颜色混合与语义色派生（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

# ``blend`` 复用共享层 ``pyqt6_ela_pro._theme``，chat 内部的语义色统一从本模块取。
from .._internal import system_cjk_font_family
from .._theme import blend, surfaceRaised

__all__ = [
    "MONO_FONT_STACK",
    "accent_color",
    "base_color",
    "blend",
    "border_color",
    "card_border_color",
    "card_color",
    "mono_font",
    "muted_color",
    "surface_color",
    "text_color",
]

#: 等宽字体栈（非中文系统默认；中文系统收成单族 CJK 字体，见 ``mono_font``）
MONO_FONT_STACK = ("Consolas", "Cascadia Mono", "Courier New")


def mono_font(size_px: int = 11) -> QFont:
    """等宽标签字体（库内禁 QSS，字体直接给 ``QFont``）。
    中文系统收成单族雅黑：多族列表在 Win7 上是慢 shaping 路径且进程级毒化，
    代价是丢掉等宽观感。
    """
    font = QFont()
    cjk_family = system_cjk_font_family()
    font.setFamilies([cjk_family] if cjk_family else list(MONO_FONT_STACK))
    font.setPixelSize(int(size_px))
    return font


def base_color(mode) -> QColor:
    """基础背景色（卡片 / 气泡表面）。

    V3.0 的 ``BasicPress`` 是 alpha 叠色，不能直接当底色；用读取层合成的
    不透明卡片表面（``BasicBase`` 叠 ``WindowBase``）。
    """
    return surfaceRaised(mode)


def text_color(mode) -> QColor:
    """主文本色（``BasicText`` 令牌）。"""
    return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)


def accent_color(mode) -> QColor:
    """强调色（``PrimaryNormal`` 令牌）。"""
    return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PrimaryNormal)


def muted_color(mode, ratio: float = 0.45) -> QColor:
    """弱化文本色（基础底与主文本按比例混合）。"""
    return blend(base_color(mode), text_color(mode), ratio)


def border_color(mode, ratio: float = 0.12) -> QColor:
    """分隔线 / 边框色。"""
    return blend(base_color(mode), text_color(mode), ratio)


def surface_color(mode, ratio: float = 0.035) -> QColor:
    """卡片 / 气泡底色（相对基础底轻微偏向主文本）。"""
    return blend(base_color(mode), text_color(mode), ratio)


def card_color(mode) -> QColor:
    """输入卡片底色（``BasicBaseAlpha`` 令牌，与 Ela 原生输入框一致）。"""
    return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBaseAlpha)


def card_border_color(mode) -> QColor:
    """输入卡片边框色（``BasicBorder`` 令牌，原生输入框同款）。"""
    return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBorder)
