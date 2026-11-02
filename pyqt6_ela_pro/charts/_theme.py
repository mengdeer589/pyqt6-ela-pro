"""图表配色主题注册表（私有）。

主题 = 分类色板 + 一组语义颜色槽位（``color.bg.base`` / ``color.text.primary`` …）。
槽位键与 ``_tokens.T()`` 的键一一对应；未写的槽位回退到 ``ela``（即 eTheme
语义令牌），**不跨明暗档借用** —— 自定义主题只写色板也能在明暗两档下保持可读。

公开入口在 :mod:`pyqt6_ela_pro.charts`：``chartThemes`` / ``registerChartTheme`` /
``setDefaultChartTheme`` 等。主题只提供默认值，option 里的显式颜色始终优先。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType

from .._colors import parse_color

# ---------------------------------------------------------------------------
# 色板（内置主题）
# ---------------------------------------------------------------------------

#: ECharts 5 默认 9 色（``ela`` / ``echarts`` 共用）
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

#: MATLAB R2014b+ 默认 color order
MATLAB_PALETTE = [
    "#0072bd",
    "#d95319",
    "#edb120",
    "#7e2f8e",
    "#77ac30",
    "#4dbeee",
    "#a2142f",
]

#: Plotly 默认 qualitative colorway
PLOTLY_PALETTE = [
    "#636efa",
    "#ef553b",
    "#00cc96",
    "#ab63fa",
    "#ffa15a",
    "#19d3f3",
    "#ff6692",
    "#b6e880",
    "#ff97ff",
    "#fecb52",
]

#: ggplot2 ``hue_pal()`` 10 色
GGPLOT2_PALETTE = [
    "#f8766d",
    "#d89000",
    "#a3a500",
    "#39b600",
    "#00ba38",
    "#00bfc4",
    "#00b0f6",
    "#619cff",
    "#c77cff",
    "#f564e3",
]

#: seaborn ``deep`` 10 色
SEABORN_PALETTE = [
    "#4c72b0",
    "#dd8452",
    "#55a868",
    "#c44e52",
    "#8172b3",
    "#937860",
    "#da8bc3",
    "#8c8c8c",
    "#ccb974",
    "#64b5cd",
]

#: Tableau 10
TABLEAU_PALETTE = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
]

#: MATLAB parula 色带（visualMap / heatmap / map 默认）
MATLAB_RAMP = [
    "#352a87",
    "#0f5cdd",
    "#1481c3",
    "#0f9ac4",
    "#1ac2a6",
    "#8bd16b",
    "#d9d94a",
    "#f4b73f",
    "#f78b2a",
    "#f4262b",
]

#: Plotly 默认连续色带 viridis
PLOTLY_RAMP = ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"]

#: 主题可写的全部颜色槽位（``color.ramp`` 是颜色列表，其余是单色）
COLOR_KEYS = frozenset(
    {
        "color.bg.base",
        "color.bg.elevated",
        "color.bg.muted",
        "color.border",
        "color.border.strong",
        "color.text.primary",
        "color.text.secondary",
        "color.text.tertiary",
        "color.text.disabled",
        "color.primary",
        "color.primary.hover",
        "color.primary.pressed",
        "color.primary.subtle",
        "color.success",
        "color.success.hover",
        "color.warning",
        "color.warning.hover",
        "color.danger",
        "color.on.primary",
        "color.ramp",
    }
)


def _dark_chrome(
    *,
    bg: str = "#1e1e1e",
    elevated: str = "#262626",
    muted: str = "#2d2d2d",
    border: str = "#3a3a3a",
    border_strong: str = "#b0b0b0",
    text: str = "#e8e8e8",
    secondary: str = "#c0c0c0",
    tertiary: str = "#909090",
    disabled: str = "#5a5a5a",
    primary: str,
    success: str,
    warning: str,
    danger: str,
    ramp: list,
) -> dict:
    """中性深色外观的公共骨架（各主题只换强调色与色带）。"""
    return {
        "color.bg.base": bg,
        "color.bg.elevated": elevated,
        "color.bg.muted": muted,
        "color.border": border,
        "color.border.strong": border_strong,
        "color.text.primary": text,
        "color.text.secondary": secondary,
        "color.text.tertiary": tertiary,
        "color.text.disabled": disabled,
        "color.primary": primary,
        "color.success": success,
        "color.warning": warning,
        "color.danger": danger,
        "color.ramp": list(ramp),
    }


# ---------------------------------------------------------------------------
# 内置主题
# ---------------------------------------------------------------------------

_CHART_THEMES: dict[str, dict] = {
    # 默认：完全跟随 Ela 明暗主题 + ECharts 色板（保持既有观感）
    "ela": {
        "palette": list(ECHARTS_PALETTE),
        "light": {},
        "dark": {},
    },
    # ECharts 5 官方默认 / dark 主题
    "echarts": {
        "palette": list(ECHARTS_PALETTE),
        "light": {
            "color.bg.base": "#ffffff",
            "color.bg.elevated": "#ffffff",
            "color.bg.muted": "#f5f7fa",
            "color.border": "#e0e6f1",
            "color.border.strong": "#6e7079",
            "color.text.primary": "#333333",
            "color.text.secondary": "#6e7079",
            "color.text.tertiary": "#6e7079",
            "color.text.disabled": "#a0a6b0",
            "color.primary": "#5470c6",
            "color.success": "#91cc75",
            "color.warning": "#fac858",
            "color.danger": "#ee6666",
            "color.ramp": ["#50a3ba", "#eac736", "#d94e5d"],
        },
        "dark": {
            "color.bg.base": "#100c2a",
            "color.bg.elevated": "#1b1735",
            "color.bg.muted": "#242043",
            "color.border": "#484753",
            "color.border.strong": "#6e7079",
            "color.text.primary": "#b9b8ce",
            "color.text.secondary": "#b9b8ce",
            "color.text.tertiary": "#8a86a8",
            "color.text.disabled": "#5c5875",
            "color.primary": "#5470c6",
            "color.success": "#91cc75",
            "color.warning": "#fac858",
            "color.danger": "#ee6666",
            "color.ramp": ["#50a3ba", "#eac736", "#d94e5d"],
        },
    },
    # MATLAB：白底 / 深灰底 + parula 色带
    "matlab": {
        "palette": list(MATLAB_PALETTE),
        "light": {
            "color.bg.base": "#ffffff",
            "color.bg.elevated": "#ffffff",
            "color.bg.muted": "#f2f2f2",
            "color.border": "#e6e6e6",
            "color.border.strong": "#262626",
            "color.text.primary": "#262626",
            "color.text.secondary": "#404040",
            "color.text.tertiary": "#666666",
            "color.text.disabled": "#a6a6a6",
            "color.primary": "#0072bd",
            "color.success": "#77ac30",
            "color.warning": "#edb120",
            "color.danger": "#d95319",
            "color.ramp": list(MATLAB_RAMP),
        },
        "dark": _dark_chrome(
            primary="#4dbeee",
            success="#77ac30",
            warning="#edb120",
            danger="#d95319",
            ramp=MATLAB_RAMP,
        ),
    },
    # Plotly：白底 / #111 + viridis 色带
    "plotly": {
        "palette": list(PLOTLY_PALETTE),
        "light": {
            "color.bg.base": "#ffffff",
            "color.bg.elevated": "#ffffff",
            "color.bg.muted": "#e5ecf6",
            "color.border": "#e5ecf6",
            "color.border.strong": "#2a3f5f",
            "color.text.primary": "#2a3f5f",
            "color.text.secondary": "#2a3f5f",
            "color.text.tertiary": "#4b5c7a",
            "color.text.disabled": "#a3b1c6",
            "color.primary": "#636efa",
            "color.success": "#00cc96",
            "color.warning": "#ffa15a",
            "color.danger": "#ef553b",
            "color.ramp": list(PLOTLY_RAMP),
        },
        "dark": {
            "color.bg.base": "#111111",
            "color.bg.elevated": "#1a1a1a",
            "color.bg.muted": "#222222",
            "color.border": "#2b2b2b",
            "color.border.strong": "#bdbdbd",
            "color.text.primary": "#f2f2f2",
            "color.text.secondary": "#bdbdbd",
            "color.text.tertiary": "#8a8a8a",
            "color.text.disabled": "#5a5a5a",
            "color.primary": "#636efa",
            "color.success": "#00cc96",
            "color.warning": "#ffa15a",
            "color.danger": "#ef553b",
            "color.ramp": list(PLOTLY_RAMP),
        },
    },
    # ggplot2：白底 / 深灰底 + 蓝渐变
    "ggplot2": {
        "palette": list(GGPLOT2_PALETTE),
        "light": {
            "color.bg.base": "#ffffff",
            "color.bg.elevated": "#ffffff",
            "color.bg.muted": "#ebebeb",
            "color.border": "#ebebeb",
            "color.border.strong": "#333333",
            "color.text.primary": "#333333",
            "color.text.secondary": "#4d4d4d",
            "color.text.tertiary": "#666666",
            "color.text.disabled": "#b3b3b3",
            "color.primary": "#619cff",
            "color.success": "#00ba38",
            "color.warning": "#d89000",
            "color.danger": "#f8766d",
            "color.ramp": ["#132b43", "#56b1f7"],
        },
        "dark": _dark_chrome(
            primary="#619cff",
            success="#00ba38",
            warning="#d89000",
            danger="#f8766d",
            ramp=["#132b43", "#56b1f7"],
            border_strong="#cccccc",
            text="#f0f0f0",
        ),
    },
    # seaborn deep
    "seaborn": {
        "palette": list(SEABORN_PALETTE),
        "light": {
            "color.bg.base": "#ffffff",
            "color.bg.elevated": "#ffffff",
            "color.bg.muted": "#eaeaf2",
            "color.border": "#eaeaf2",
            "color.border.strong": "#262626",
            "color.text.primary": "#262626",
            "color.text.secondary": "#4c4c4c",
            "color.text.tertiary": "#6b6b6b",
            "color.text.disabled": "#b0b0b0",
            "color.primary": "#4c72b0",
            "color.success": "#55a868",
            "color.warning": "#ccb974",
            "color.danger": "#c44e52",
            "color.ramp": ["#4c72b0", "#dd8452"],
        },
        "dark": _dark_chrome(
            primary="#64b5cd",
            success="#55a868",
            warning="#ccb974",
            danger="#c44e52",
            ramp=["#4c72b0", "#dd8452"],
            muted="#2a2a2a",
        ),
    },
    # Tableau 10
    "tableau": {
        "palette": list(TABLEAU_PALETTE),
        "light": {
            "color.bg.base": "#ffffff",
            "color.bg.elevated": "#ffffff",
            "color.bg.muted": "#f2f2f2",
            "color.border": "#e0e0e0",
            "color.border.strong": "#4d4d4d",
            "color.text.primary": "#333333",
            "color.text.secondary": "#4d4d4d",
            "color.text.tertiary": "#6b6b6b",
            "color.text.disabled": "#b3b3b3",
            "color.primary": "#4e79a7",
            "color.success": "#59a14f",
            "color.warning": "#edc948",
            "color.danger": "#e15759",
            "color.ramp": ["#c6dbef", "#4e79a7", "#08306b"],
        },
        "dark": _dark_chrome(
            primary="#4e79a7",
            success="#59a14f",
            warning="#edc948",
            danger="#e15759",
            ramp=["#c6dbef", "#4e79a7", "#08306b"],
            muted="#2a2a2a",
        ),
    },
}

#: 默认主题（``ela`` = 跟随 eTheme）
_DEFAULT_CHART_THEME = "ela"

#: 主题注册代次：重新注册 / 注销同名主题时递增，进缓存键
_THEME_EPOCH = 0


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def _theme_name(chart=None) -> str:
    """图表实例的主题名；``None`` / 未设置 → 全局默认主题。"""
    if chart is not None:
        name = getattr(chart, "_chart_theme", "")
        if isinstance(name, str) and name:
            return name
    return _DEFAULT_CHART_THEME


def _theme_spec(chart=None) -> dict:
    """取图表生效的主题定义；名称已注销时回退默认主题。"""
    name = _theme_name(chart)
    spec = _CHART_THEMES.get(name)
    if spec is None:
        spec = _CHART_THEMES.get(_DEFAULT_CHART_THEME) or _CHART_THEMES["ela"]
    return spec


def _variant_key(mode) -> str:
    return "dark" if mode == ElaThemeType.ThemeMode.Dark else "light"


def chart_theme_key(chart=None) -> tuple:
    """缓存键里的主题身份：``(主题名, 注册代次)``。"""
    return (_theme_name(chart), _THEME_EPOCH)


def theme_override(chart, mode, key):
    """主题对单个槽位的覆盖；未写返回 ``None``（调用方回退 eTheme）。"""
    if key == "color.ramp":
        return None
    spec = _theme_spec(chart)
    value = (spec.get(_variant_key(mode)) or {}).get(key)
    if value is None:
        return None
    return parse_color(value)


def theme_ramp_override(chart, mode):
    """主题定义的多色带（``list[QColor]``）；未写返回 ``None``。"""
    spec = _theme_spec(chart)
    colors = (spec.get(_variant_key(mode)) or {}).get("color.ramp")
    if not colors:
        return None
    return [parse_color(c) for c in colors]


def theme_palette_colors(chart=None) -> list:
    """主题的分类色板（hex 字符串列表；未写 → ECharts 默认）。"""
    spec = _theme_spec(chart)
    palette = spec.get("palette")
    if palette:
        return list(palette)
    return list(ECHARTS_PALETTE)


def chartThemeSpec(name: str) -> Optional[dict]:
    """返回主题定义的深拷贝；未知名称返回 ``None``。"""
    spec = _CHART_THEMES.get(str(name))
    if spec is None:
        return None
    return {
        "palette": list(spec.get("palette") or ECHARTS_PALETTE),
        "light": _copy_variant(spec.get("light")),
        "dark": _copy_variant(spec.get("dark")),
    }


def _copy_variant(variant) -> dict:
    out = {}
    for key, value in (variant or {}).items():
        out[key] = list(value) if isinstance(value, list) else value
    return out


def chartThemes() -> list:
    """全部内置 / 已注册主题名（按注册顺序）。"""
    return list(_CHART_THEMES)


def defaultChartTheme() -> str:
    """新建图表使用的默认主题名。"""
    return _DEFAULT_CHART_THEME


def setDefaultChartTheme(name: str) -> bool:
    """设置默认主题（只影响之后新建的图表）；主题存在才返回 ``True``。"""
    global _DEFAULT_CHART_THEME
    if name not in _CHART_THEMES:
        return False
    _DEFAULT_CHART_THEME = str(name)
    return True


def theme_exists(name: str) -> bool:
    """主题名是否已注册。"""
    return str(name) in _CHART_THEMES


# ---------------------------------------------------------------------------
# 注册 / 注销
# ---------------------------------------------------------------------------


def _normalize_color(value, where: str) -> str:
    color = parse_color(value)
    if not color.isValid():
        raise ValueError(f"{where}: 非法颜色 {value!r}")
    if isinstance(value, QColor):
        fmt = (
            QColor.NameFormat.HexArgb
            if color.alpha() < 255
            else QColor.NameFormat.HexRgb
        )
        return color.name(fmt)
    return str(value).strip()


def _validate_variant(patch, where: str) -> dict:
    if patch is None:
        return {}
    if not isinstance(patch, dict):
        raise ValueError(f"{where}: 必须是 dict，实际是 {type(patch).__name__}")
    out = {}
    for key, value in patch.items():
        if key not in COLOR_KEYS:
            allowed = ", ".join(sorted(COLOR_KEYS))
            raise ValueError(f"{where}: 未知颜色槽位 {key!r}（可用：{allowed}）")
        if key == "color.ramp":
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                raise ValueError(f"{where}.{key}: 至少需要 2 个颜色")
            out[key] = [
                _normalize_color(item, f"{where}.{key}[{index}]")
                for index, item in enumerate(value)
            ]
        else:
            out[key] = _normalize_color(value, f"{where}.{key}")
    return out


def _validate_palette(palette) -> list:
    if not isinstance(palette, (list, tuple)) or not palette:
        raise ValueError("registerChartTheme: palette 必须是非空颜色列表")
    return [
        _normalize_color(item, f"palette[{index}]")
        for index, item in enumerate(palette)
    ]


def registerChartTheme(
    name: str,
    palette=None,
    light: Optional[dict] = None,
    dark: Optional[dict] = None,
) -> None:
    """注册 / 覆盖一套图表主题（同名即覆盖，未给的段沿用原定义）。

    :param name: 主题名（不能为空）
    :param palette: 分类系列色板（省略 = 沿用同名主题原色板，新主题用 ECharts 9 色）
    :param light: 浅色槽位（``color.bg.base`` / ``color.text.primary`` /
        ``color.ramp`` …；未写的槽位回退 eTheme）
    :param dark: 深色槽位（同上）
    """
    global _THEME_EPOCH
    if not isinstance(name, str) or not name.strip():
        raise ValueError("registerChartTheme: 主题名不能为空")
    key = name.strip()
    base = _CHART_THEMES.get(key) or {}
    next_palette = (
        _validate_palette(palette)
        if palette is not None
        else list(base.get("palette") or ECHARTS_PALETTE)
    )
    light_merged = dict(base.get("light") or {})
    light_merged.update(_validate_variant(light, f"{key}.light"))
    dark_merged = dict(base.get("dark") or {})
    dark_merged.update(_validate_variant(dark, f"{key}.dark"))
    _CHART_THEMES[key] = {
        "palette": next_palette,
        "light": light_merged,
        "dark": dark_merged,
    }
    _THEME_EPOCH += 1


def unregisterChartTheme(name: str) -> bool:
    """移除已注册主题（``"ela"`` 不可移除）；返回是否移除成功。"""
    global _DEFAULT_CHART_THEME, _THEME_EPOCH
    key = str(name)
    if key == "ela" or key not in _CHART_THEMES:
        return False
    _CHART_THEMES.pop(key, None)
    if _DEFAULT_CHART_THEME == key:
        _DEFAULT_CHART_THEME = "ela"
    _THEME_EPOCH += 1
    return True
