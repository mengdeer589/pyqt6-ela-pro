"""charts 包主题令牌适配层（私有）：``T("...")`` 映射到图表主题 / ``eTheme``。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEasingCurve
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from .._colors import mixColor, parse_color
from .._theme import surfaceRaised
from ._style import TITLE_SIZE
from ._theme import (
    ECHARTS_PALETTE,
    theme_override,
    theme_palette_colors,
    theme_ramp_override,
)

# 固定令牌（与主题无关）

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
FONT_TITLE_MD = int(TITLE_SIZE)
FONT_WEIGHT_SEMIBOLD = 600
RADIUS_MD = 6.0

#: 入场 / 数据过渡动画时长（ms）与缓动（对齐源库 DURATION.slow / EASING.standard）
ANIM_DURATION = 320
ANIM_EASING = QEasingCurve.Type.OutCubic
#: loading 遮罩 spinner 的推进间隔（ms）。持续动效，Reduced/Disabled 下冻结角度。
SPINNER_TICK_MS = 40
#: 折线 ``effect.show`` 流动高亮的推进间隔（ms）。持续动效，Reduced/Disabled 下冻结。
EFFECT_TICK_MS = 40

# Ela 语义色映射（eTheme 实时取色，主题切换自动跟随）

#: 源令牌键 -> ElaThemeType.ThemeColor 成员名
_ELA_COLOR_KEYS = {
    "color.bg.base": "BasicBase",  # 画布底色（Ela 窗口基础色）
    "color.bg.elevated": "PopupBase",  # 浮层 / 数据点内芯底色
    "color.bg.muted": "BasicHoverAlpha",  # 次级填充背景
    "color.border": "BasicBorder",  # 网格线
    "color.border.strong": "BasicBorderDeep",  # 轴线 / 引线
    "color.text.primary": "BasicText",  # 主文本
    "color.text.secondary": "BasicTextNoFocus",  # 次级文本（V3.0 起与弱文本同源）
    "color.text.tertiary": "BasicTextNoFocus",  # 弱文本（轴名）
    "color.text.disabled": "BasicTextDisable",  # 禁用态文本（图例隐藏项）
    "color.primary": "PrimaryNormal",  # 主题主色
    "color.primary.hover": "PrimaryHover",
    "color.primary.pressed": "PrimaryPress",
    "color.success": "StatusSuccess",  # 成功状态
    "color.warning": "StatusWarning",  # 警告状态
    "color.danger": "StatusDanger",  # 危险色
}

#: 上游没有对应槽位的语义色：key -> (light_hex, dark_hex)
_STATIC_COLORS = {
    "color.on.primary": ("#FFFFFF", "#15181E"),
}

#: 上游没有 success / warning hover 槽位：从基础状态色派生
_STATUS_HOVER_KEYS = {
    "color.success.hover": "color.success",
    "color.warning.hover": "color.warning",
}


def _ela_color(mode, member_name: str) -> QColor:
    return QColor(
        eTheme.getThemeColor(mode, getattr(ElaThemeType.ThemeColor, member_name))
    )


def _subtle_primary(mode, chart=None) -> QColor:
    """color.primary.subtle：主色与不透明画布底的 12% 混合色（主题感知）。"""
    bg = theme_override(chart, mode, "color.bg.base")
    if bg is None:
        # BasicBase 是白色 alpha 叠色：直混得到近白，暗色热力图 / graphic 会过曝
        bg = surfaceRaised(mode)
    primary = theme_override(chart, mode, "color.primary")
    if primary is None:
        primary = _ela_color(mode, "PrimaryNormal")
    return mixColor(bg, primary, 0.12)


def _derived_accent(mode, key: str, chart=None) -> Optional[QColor]:
    """主题只给了 ``color.primary`` 时派生 hover / pressed，避免跳回 Ela 蓝。"""
    if key not in ("color.primary.hover", "color.primary.pressed"):
        return None
    primary = theme_override(chart, mode, "color.primary")
    if primary is None:
        return None
    target = QColor("#ffffff") if key == "color.primary.hover" else QColor("#000000")
    return mixColor(primary, target, 0.12)


def _derived_status_hover(mode, key: str, chart=None) -> Optional[QColor]:
    """上游没有 success / warning hover 槽位：按基础色 12% 压暗 / 提亮派生。"""
    base_key = _STATUS_HOVER_KEYS.get(key)
    if base_key is None:
        return None
    base = chart_token(mode, base_key, chart)
    target = (
        QColor("#000000") if mode == ElaThemeType.ThemeMode.Light else QColor("#ffffff")
    )
    return mixColor(base, target, 0.12)


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
    status_hover = _derived_status_hover(mode, key, chart)
    if status_hover is not None:
        return status_hover
    if key == "color.primary.subtle":
        return _subtle_primary(mode, chart)
    if key == "color.bg.base":
        # V3.0 的 BasicBase 是 alpha 叠色：画布底必须不透明，否则导出图/抓图半透明
        return surfaceRaised(mode)
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


# 系列默认调色板 / 色带


def palette_for_mode(mode, chart=None) -> list:
    """当前主题的数据系列调色板（``chart=None`` = 全局默认主题）。
    必须每次新建 list：调用方会就地 ``setAlphaF`` 改元素，共享实例会让一次
    绘制污染全局调色板。
    """
    return [parse_color(c) for c in theme_palette_colors(chart, mode)]


def theme_ramp(chart=None) -> list:
    """当前主题的多色带（``visualMap`` / ``heatmap`` / ``map`` 默认用）。"""
    mode = eTheme.getThemeMode()
    colors = theme_ramp_override(chart, mode)
    if colors:
        ramp = [QColor(c) for c in colors]
    else:
        ramp = [
            QColor(chart_token(mode, "color.primary.subtle", chart)),
            QColor(chart_token(mode, "color.primary", chart)),
        ]
    # 渐变 / 热力图要的是实色；主题色板和 fallback 的 alpha 都必须压掉。
    for color in ramp:
        color.setAlpha(255)
    return ramp


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
