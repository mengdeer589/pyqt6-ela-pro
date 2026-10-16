"""
聊天组件主题工具（``pyqt6_ela_pro.chat`` 内部模块）。

集中提供颜色混合与语义色派生，供输入区、工具栏、消息气泡共享，
避免包内互相导入私有实现（如 ``from .bubble import _blend``）。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

# ``blend`` 原为本模块私有，现已提到共享层 ``pyqt6_ela_pro._theme``（Shimmer 的
# 骨架底色、Avatar 的派生底色都要用同一套插值）。这里再导入一次是因为 chat 内部
# 有 6 处按 ``from ._theme import blend`` 取它 —— 那不是兼容别名，是 chat 的
# 语义色都集中在本模块的既有约定。
from .._theme import blend

__all__ = ["MONO_FONT_STACK", "blend", "mono_font"]

#: 等宽字体栈（数字 / 耗时 / 统计 / 工具参数的“代理轨迹”质感；
#: 中文自动回退系统字体，无需 HTML 混排）
MONO_FONT_STACK = ("Consolas", "Cascadia Mono", "Courier New")


def mono_font(size_px: int = 11) -> QFont:
    """等宽标签字体（替代 ``mono_css``：库内禁 QSS，字体直接给 ``QFont``）。"""
    font = QFont()
    font.setFamilies(list(MONO_FONT_STACK))
    font.setPixelSize(int(size_px))
    return font


def base_color(mode) -> QColor:
    """基础背景色（``BasicPress`` 令牌）。"""
    return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)


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


def role_accent(role: str, mode) -> QColor:
    """按消息角色派生强调色（用户=主色，助手=中性）。"""
    if role == "user":
        return blend(base_color(mode), accent_color(mode), 0.16)
    return blend(base_color(mode), text_color(mode), 0.10)
