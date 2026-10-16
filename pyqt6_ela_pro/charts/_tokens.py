"""
charts 包主题令牌适配层（私有）。

将源引擎（InstructionX_UIKit.charts，PyQt6 + 自建令牌）对 ``T("...")``
的读取，映射到本库 ``eTheme`` / ``ElaThemeType`` 语义令牌：颜色一律
实时取 ``eTheme.getThemeColor(mode, ...)``，深浅色主题切换后重绘即生效，
观感与当前 Ela 组件库保持一致。

Ela 主题色中没有的语义色（success / warning / 主色上的浮层文字等）使用
静态双主题色表（light / dark），并集中在本模块以便审计。字体字号 / 圆角
/ 动效时长为固定常量（源令牌值）。

对外仅暴露 ``chart_token(mode, key)`` 与 ``T(key)``（实时模式）及少量常量。
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import eTheme, ElaThemeType

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


def _subtle_primary(mode) -> QColor:
    """color.primary.subtle：主色与画布底的 12% 混合浅色（主题感知）。"""
    bg = _ela_color(mode, "BasicBase")
    p = _ela_color(mode, "PrimaryNormal")
    return QColor(
        int(bg.red() * 0.88 + p.red() * 0.12),
        int(bg.green() * 0.88 + p.green() * 0.12),
        int(bg.blue() * 0.88 + p.blue() * 0.12),
    )


def chart_token(mode, key):
    """读取单个令牌值：颜色返回 ``QColor``（实时主题），数值返回 int/float。

    ``mode`` 是主题模式（``eTheme.getThemeMode()`` 返回值），``key`` 是令牌键
    （如 ``"color.bg.base"`` / ``"font.xs"``）。
    """
    if key == "color.primary.subtle":
        return _subtle_primary(mode)
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


def T(key):
    """按当前主题模式读取令牌（对齐源库 T() 调用面）。"""
    return chart_token(eTheme.getThemeMode(), key)


#: 公开入口：按当前主题读取令牌（第三方扩展自定义系列 / 组件时取主题色）
chartToken = T


# ---------------------------------------------------------------------------
# 系列默认调色板（ECharts 默认 9 色：light / dark 共用，保证跨主题一致观感）
# ---------------------------------------------------------------------------

#: ECharts 默认数据系列调色板
ECHARTS_PALETTE = [
    "#5470c6",
    "#91cc75",
    "#fac858",
    "#ee6666",
    "#73c0de",
    "#3ba272",
    "#fc8452",
    "#9a60b4",
    "#ea7ccc",
]


def palette_for_mode(mode) -> list:
    """当前主题的数据系列调色板（ECharts 默认 9 色，主题无关）。

    **必须每次新建 list**：调用方会 ``setAlphaF`` 改单个元素的 alpha
    （bar / scatter 逐图元调透明度），返回共享实例会让一次绘制污染全局
    调色板 —— 表现为「悬浮过某根柱之后所有系列颜色都变了」。而 bar /
    scatter 的绘制路径逐图元取色，本函数单帧被调上万次，每次新建 9 个
    QColor 是绘制路径最大的 Python 开销（profiling 占 tottime 16%）。
    """
    return [QColor(c) for c in ECHARTS_PALETTE]
