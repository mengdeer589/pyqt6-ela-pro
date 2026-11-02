"""charts 包主题令牌适配层（私有）：``T("...")`` 映射到图表主题 / ``eTheme``。

颜色实时取图表主题（:mod:`._theme`），未写的槽位回退 ``eTheme.getThemeColor``；
主题切换后重绘即生效。Ela 主题没有的语义色用本模块的静态双主题色表。

**颜色调用必须带图表上下文**：``T("color.text.primary", self.chart)`` —— 每个
图表实例可以有不同主题；不传 ``chart`` 只用于公开的 ``chartToken`` / 模块级
辅助函数，取全局默认主题。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEasingCurve
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from .._colors import parse_color
from ._theme import (
    ECHARTS_PALETTE,
    theme_override,
    theme_palette_colors,
    theme_ramp_override,
)

# ---------------------------------------------------------------------------
# 固定令牌（与主题无关）
# ---------------------------------------------------------------------------

#: 图表用字族（首个为 Windows 主推中文字体）
FONT_FAMILIES = [
    "Microsoft YaHei",
    "Segoe UI",
    "PingFang SC",
    "Noto Sans CJK SC",
    "WenQuanYi Micro Hei",
]

#: 字号 / 字重 / 圆角（px）
FONT_XS = 11
FONT_SM = 12
FONT_TITLE_MD = 17
FONT_WEIGHT_SEMIBOLD = 600
RADIUS_MD = 6.0

#: 入场 / 数据过渡动画时长（ms）与缓动（对齐源库 DURATION.slow / EASING.standard）
ANIM_DURATION = 320
ANIM_EASING = QEasingCurve.Type.OutCubic
#: loading 遮罩 spinner 的推进间隔（ms）。持续动效，Reduced/Disabled 下冻结角度。
SPINNER_TICK_MS = 40
#: 折线 ``effect.show`` 流动高亮的推进间隔（ms）。持续动效，Reduced/Disabled 下冻结。
EFFECT_TICK_MS = 40

# ---------------------------------------------------------------------------
# Ela 语义色映射（eTheme 实时取色，主题切换自动跟随）
# ---------------------------------------------------------------------------

#: 源令牌键 -> ElaThemeType.ThemeColor 成员名
_ELA_COLOR_KEYS = {
    "color.bg.base": "BasicBase",  # 画布底色（Ela 窗口基础色）
    "color.bg.elevated": "PopupBase",  # 浮层 / 数据点内芯底色
    "color.bg.muted": "BasicHoverAlpha",  # 次级填充背景
    "color.border": "BasicBorder",  # 网格线
    "color.border.strong": "BasicBorderDeep",  # 轴线 / 引线
    "color.text.primary": "BasicText",  # 主文本
    "color.text.secondary": "BasicDetailsText",  # 次级文本（刻度标签）
    "color.text.tertiary": "BasicTextNoFocus",  # 弱文本（轴名）
    "color.text.disabled": "BasicTextDisable",  # 禁用态文本（图例隐藏项）
    "color.primary": "PrimaryNormal",  # 主题主色
    "color.primary.hover": "PrimaryHover",
    "color.primary.pressed": "PrimaryPress",
    "color.danger": "StatusDanger",  # 危险色
}

#: Ela 主题色中没有的语义色：key -> (light_hex, dark_hex)
_STATIC_COLORS = {
    "color.success": ("#3E7E5F", "#6BA98A"),
    "color.success.hover": ("#34684F", "#55D0A0"),
    "color.warning": ("#C08A3E", "#D2A668"),
    "color.warning.hover": ("#A97A35", "#C08A3E"),
    "color.on.primary": ("#FFFFFF", "#15181E"),
}


def _ela_color(mode, member_name: str) -> QColor:
    return QColor(
        eTheme.getThemeColor(mode, getattr(ElaThemeType.ThemeColor, member_name))
    )


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() * (1 - t) + b.red() * t),
        int(a.green() * (1 - t) + b.green() * t),
        int(a.blue() * (1 - t) + b.blue() * t),
        int(a.alpha() * (1 - t) + b.alpha() * t),
    )


def _subtle_primary(mode, chart=None) -> QColor:
    """color.primary.subtle：主色与画布底的 12% 混合浅色（主题感知）。"""
    bg = theme_override(chart, mode, "color.bg.base")
    if bg is None:
        bg = _ela_color(mode, "BasicBase")
    primary = theme_override(chart, mode, "color.primary")
    if primary is None:
        primary = _ela_color(mode, "PrimaryNormal")
    return _mix(bg, primary, 0.12)


def _derived_accent(mode, key: str, chart=None) -> Optional[QColor]:
    """主题只给了 ``color.primary`` 时派生 hover / pressed，避免跳回 Ela 蓝。"""
    if key not in ("color.primary.hover", "color.primary.pressed"):
        return None
    primary = theme_override(chart, mode, "color.primary")
    if primary is None:
        return None
    target = QColor("#ffffff") if key == "color.primary.hover" else QColor("#000000")
    return _mix(primary, target, 0.12)


def chart_token(mode, key, chart=None):
    """读取单个令牌值：颜色返回 ``QColor``（实时主题），数值返回 int/float。

    :param chart: 图表实例；``None`` = 全局默认主题（仅公开 ``chartToken`` 用）
    """
    if key == "color.ramp":
        raise KeyError("color.ramp 是多色带，请用 theme_ramp(chart) 读取")
    override = (
        theme_override(chart, mode, key)
        if isinstance(key, str) and key.startswith("color.")
        else None
    )
    if override is not None:
        return override
    derived = _derived_accent(mode, key, chart)
    if derived is not None:
        return derived
    if key == "color.primary.subtle":
        return _subtle_primary(mode, chart)
    member = _ELA_COLOR_KEYS.get(key)
    if member is not None:
        return _ela_color(mode, member)
    static = _STATIC_COLORS.get(key)
    if static is not None:
        dark = mode == ElaThemeType.ThemeMode.Dark
        return QColor(static[1] if dark else static[0])
    ints = {
        "font.xs": FONT_XS,
        "font.sm": FONT_SM,
        "font.title.md": FONT_TITLE_MD,
        "font.weight.semibold": FONT_WEIGHT_SEMIBOLD,
        "radius.md": RADIUS_MD,
    }
    if key in ints:
        return ints[key]
    raise KeyError(f"未知图表令牌: {key!r}")


def T(key, chart=None):
    """按当前主题模式读取令牌（对齐源库 T() 调用面）。

    颜色调用一律传图表上下文：``T("color.text.primary", self.chart)``。
    """
    return chart_token(eTheme.getThemeMode(), key, chart)


#: 公开入口：按当前主题读取令牌（第三方扩展自定义系列 / 组件时取主题色）
chartToken = T


# ---------------------------------------------------------------------------
# 系列默认调色板 / 色带
# ---------------------------------------------------------------------------


def palette_for_mode(mode, chart=None) -> list:
    """当前主题的数据系列调色板（``chart=None`` = 全局默认主题）。

    必须每次新建 list：调用方会就地 ``setAlphaF`` 改元素，共享实例会让一次
    绘制污染全局调色板。
    """
    return [parse_color(c) for c in theme_palette_colors(chart)]


def theme_ramp(chart=None) -> list:
    """当前主题的多色带（``visualMap`` / ``heatmap`` / ``map`` 默认用）。"""
    mode = eTheme.getThemeMode()
    colors = theme_ramp_override(chart, mode)
    if colors:
        return colors
    return [
        QColor(chart_token(mode, "color.primary.subtle", chart)),
        QColor(chart_token(mode, "color.primary", chart)),
    ]


__all__ = [
    "ANIM_DURATION",
    "ANIM_EASING",
    "ECHARTS_PALETTE",
    "EFFECT_TICK_MS",
    "FONT_FAMILIES",
    "FONT_SM",
    "FONT_TITLE_MD",
    "FONT_WEIGHT_SEMIBOLD",
    "FONT_XS",
    "RADIUS_MD",
    "SPINNER_TICK_MS",
    "T",
    "chartToken",
    "palette_for_mode",
    "theme_ramp",
]
