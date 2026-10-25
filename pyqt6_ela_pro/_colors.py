"""
共享颜色面板，供 ElaButton / ElaChip 等组件使用。

每个命名颜色定义 ``accent`` / ``accentHover`` / ``accentActive`` / ``accentBg`` /
``accentBgHover`` / ``textColor``。``get_color_scheme`` 额外派生实心按钮专用色
``solid`` / ``solidHover`` / ``solidActive`` / ``solidText``，保证文字对比度 ≥ 4.5:1。
"""

from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType

#: CSS ``rgb()`` / ``rgba()``（ECharts / 网页里最常见的颜色写法；``QColor`` 不解析）
_RGB_FUNC_RE = re.compile(
    r"rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)"
    r"\s*(?:,\s*([0-9.]+)\s*)?\)",
    re.IGNORECASE,
)


def parse_color(value) -> QColor:
    """颜色字符串 → QColor（支持 ``#rgb`` / ``#rrggbb`` / 具名色 /
    ``rgb(r,g,b)`` / ``rgba(r,g,b,a)``）。非法值返回无效 QColor。

    十六进制 / 具名色直接交给 ``QColor``，只有 ``rgb`` 前缀才走正则 ——
    这个函数在逐项绘制路径上被调用，别让正则成为常态开销。

    ``QColor`` 不认 ``rgb()`` / ``rgba()``：直接用 ``QColor(text)`` 会得到
    无效色（绘制出来是黑色，且零报错），所以**凡是颜色字符串都过这里**
    （charts 的 option 颜色、宿主传入的强调色 / 文本色等）。
    """
    if isinstance(value, QColor):
        return QColor(value)
    if not isinstance(value, str):
        return QColor()
    text = value.strip()
    if text[:3].lower() != "rgb":
        return QColor(text)
    match = _RGB_FUNC_RE.fullmatch(text)
    if match is None:
        return QColor(text)
    try:
        red, green, blue = (int(float(match.group(i))) for i in (1, 2, 3))
        alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    except (TypeError, ValueError, OverflowError):
        return QColor()
    return QColor(
        max(0, min(255, red)),
        max(0, min(255, green)),
        max(0, min(255, blue)),
        int(round(max(0.0, min(1.0, alpha)) * 255)),
    )


_COLOR_PALETTE: dict[str, dict[str, dict[str, str]]] = {
    "default": {
        "light": {
            "accent": "#4f5459",
            "accentHover": "#6a7075",
            "accentActive": "#3a3f44",
            "accentBg": "#f2f3f4",
            "accentBgHover": "#e4e6e8",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#5a5f63",
            "accentHover": "#6e747a",
            "accentActive": "#45494d",
            "accentBg": "#2c2e30",
            "accentBgHover": "#3a3d40",
            "textColor": "#ffffff",
        },
    },
    "blue": {
        "light": {
            "accent": "#0067c0",
            "accentHover": "#2680ce",
            "accentActive": "#004fa0",
            "accentBg": "#e5eff9",
            "accentBgHover": "#c8dcf0",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#4cc2ff",
            "accentHover": "#70cfff",
            "accentActive": "#38ade8",
            "accentBg": "#142a38",
            "accentBgHover": "#1e4059",
            "textColor": "#ffffff",
        },
    },
    "danger": {
        "light": {
            "accent": "#ff4d4f",
            "accentHover": "#ff7875",
            "accentActive": "#d9363e",
            "accentBg": "#fff2f0",
            "accentBgHover": "#ffd8d2",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#dc4446",
            "accentHover": "#e86a6b",
            "accentActive": "#ad393a",
            "accentBg": "#2c1415",
            "accentBgHover": "#4a1f20",
            "textColor": "#ffffff",
        },
    },
    "purple": {
        "light": {
            "accent": "#722ed1",
            "accentHover": "#9254de",
            "accentActive": "#531dab",
            "accentBg": "#f9f0ff",
            "accentBgHover": "#efdbff",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#642ab8",
            "accentHover": "#854eca",
            "accentActive": "#51219a",
            "accentBg": "#1e1330",
            "accentBgHover": "#2e1c4a",
            "textColor": "#ffffff",
        },
    },
    "cyan": {
        "light": {
            "accent": "#13c2c2",
            "accentHover": "#36cfc9",
            "accentActive": "#08979c",
            "accentBg": "#e6fffb",
            "accentBgHover": "#b5f5ec",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#10adad",
            "accentHover": "#2fc7c7",
            "accentActive": "#0c8a8a",
            "accentBg": "#112828",
            "accentBgHover": "#1a3d3d",
            "textColor": "#ffffff",
        },
    },
    "green": {
        "light": {
            "accent": "#52c41a",
            "accentHover": "#73d13d",
            "accentActive": "#389e0d",
            "accentBg": "#f6ffed",
            "accentBgHover": "#e8fcd9",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#49aa17",
            "accentHover": "#66c430",
            "accentActive": "#3a8c12",
            "accentBg": "#16280e",
            "accentBgHover": "#243d16",
            "textColor": "#ffffff",
        },
    },
    "magenta": {
        "light": {
            "accent": "#eb2f96",
            "accentHover": "#f06292",
            "accentActive": "#c41d7f",
            "accentBg": "#fff0f6",
            "accentBgHover": "#ffd6e7",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#c92980",
            "accentHover": "#dd5099",
            "accentActive": "#a81e6b",
            "accentBg": "#2c1120",
            "accentBgHover": "#421a31",
            "textColor": "#ffffff",
        },
    },
    "pink": {
        "light": {
            "accent": "#f759ab",
            "accentHover": "#ff85c0",
            "accentActive": "#c41d7f",
            "accentBg": "#fff0f6",
            "accentBgHover": "#ffd6e7",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#c95a91",
            "accentHover": "#d97cab",
            "accentActive": "#a14473",
            "accentBg": "#2c1120",
            "accentBgHover": "#421a31",
            "textColor": "#ffffff",
        },
    },
    "red": {
        "light": {
            "accent": "#e81123",
            "accentHover": "#eb424f",
            "accentActive": "#c40d1c",
            "accentBg": "#fde6e8",
            "accentBgHover": "#facacd",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#e81123",
            "accentHover": "#eb424f",
            "accentActive": "#c40d1c",
            "accentBg": "#2c1114",
            "accentBgHover": "#451a1e",
            "textColor": "#ffffff",
        },
    },
    "orange": {
        "light": {
            "accent": "#fa8c16",
            "accentHover": "#ffa940",
            "accentActive": "#d46b08",
            "accentBg": "#fff7e6",
            "accentBgHover": "#ffe7ba",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#d97a13",
            "accentHover": "#e8993a",
            "accentActive": "#b0640e",
            "accentBg": "#2c1c0e",
            "accentBgHover": "#452b14",
            "textColor": "#ffffff",
        },
    },
    "yellow": {
        "light": {
            "accent": "#fadb14",
            "accentHover": "#ffec3d",
            "accentActive": "#d4b106",
            "accentBg": "#feffe6",
            "accentBgHover": "#ffffb8",
            "textColor": "#000000",
        },
        "dark": {
            "accent": "#d9bd12",
            "accentHover": "#e8d13a",
            "accentActive": "#b09e0a",
            "accentBg": "#2c280e",
            "accentBgHover": "#453e14",
            "textColor": "#000000",
        },
    },
    "volcano": {
        "light": {
            "accent": "#fa541c",
            "accentHover": "#ff7a45",
            "accentActive": "#d4380d",
            "accentBg": "#fff2e8",
            "accentBgHover": "#ffd8bf",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#d94818",
            "accentHover": "#e86e3a",
            "accentActive": "#b03810",
            "accentBg": "#2c1610",
            "accentBgHover": "#452214",
            "textColor": "#ffffff",
        },
    },
    "geekblue": {
        "light": {
            "accent": "#2f54eb",
            "accentHover": "#597ef7",
            "accentActive": "#1d39c4",
            "accentBg": "#f0f5ff",
            "accentBgHover": "#d6e4ff",
            "textColor": "#ffffff",
        },
        "dark": {
            "accent": "#2a47cc",
            "accentHover": "#4d68e0",
            "accentActive": "#2038a8",
            "accentBg": "#12182c",
            "accentBgHover": "#1c2645",
            "textColor": "#ffffff",
        },
    },
    "lime": {
        "light": {
            "accent": "#a0d911",
            "accentHover": "#bae637",
            "accentActive": "#7cb305",
            "accentBg": "#fcffe6",
            "accentBgHover": "#f4ffb8",
            "textColor": "#000000",
        },
        "dark": {
            "accent": "#8cbd0e",
            "accentHover": "#a3d430",
            "accentActive": "#729b0a",
            "accentBg": "#1c280e",
            "accentBgHover": "#2b3d14",
            "textColor": "#000000",
        },
    },
    "gold": {
        "light": {
            "accent": "#faad14",
            "accentHover": "#ffd666",
            "accentActive": "#d48806",
            "accentBg": "#fffbe6",
            "accentBgHover": "#fff1b8",
            "textColor": "#000000",
        },
        "dark": {
            "accent": "#d99612",
            "accentHover": "#e8b43a",
            "accentActive": "#b07c0a",
            "accentBg": "#2c220e",
            "accentBgHover": "#453414",
            "textColor": "#000000",
        },
    },
}

_COLOR_ALIAS: dict[str, str] = {
    "primary": "blue",
}


def _resolve_color(name: str) -> str:
    return _COLOR_ALIAS.get(name, name)


def _mode_key(mode: ElaThemeType.ThemeMode) -> str:
    return "light" if mode == ElaThemeType.ThemeMode.Light else "dark"


def _relative_luminance(color: QColor) -> float:
    """WCAG 相对亮度。"""

    def channel(value: int) -> float:
        v = value / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def _contrast_ratio(a: QColor, b: QColor) -> float:
    """WCAG 对比度（1~21）。"""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    high, low = max(la, lb), min(la, lb)
    return (high + 0.05) / (low + 0.05)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() * (1 - t) + b.red() * t),
        int(a.green() * (1 - t) + b.green() * t),
        int(a.blue() * (1 - t) + b.blue() * t),
    )


#: 实心背景使用黑字的色系（亮黄色系，白字天然不达标）
_BLACK_TEXT_COLORS = {"yellow", "lime", "gold"}


def _solid_palette(accent: QColor, color_name: str) -> dict[str, QColor]:
    """派生实心按钮配色：保证 ``solidText`` 与 ``solid`` 对比度 ≥ 4.5:1。

    亮黄色系固定黑字且不压暗；其余颜色统一白字并按需逐步加深底色直到达标。
    """
    white, black = QColor("#ffffff"), QColor("#000000")
    if color_name in _BLACK_TEXT_COLORS:
        text, solid = black, QColor(accent)
    else:
        text, solid = white, QColor(accent)
        for _ in range(32):
            if _contrast_ratio(solid, text) >= 4.5:
                break
            solid = _mix(solid, black, 0.06)
    hover = _mix(solid, white, 0.08)
    if _contrast_ratio(hover, text) < 4.0:
        hover = _mix(solid, black, 0.08)
    active = _mix(solid, black, 0.12)
    return {
        "solid": solid,
        "solidHover": hover,
        "solidActive": active,
        "solidText": text,
    }


def get_color_scheme(
    color_name: str, mode: ElaThemeType.ThemeMode
) -> dict[str, QColor]:
    """获取指定颜色名称在当前主题下的完整色板（QColor 对象）。

    在原始 6 个键之外，额外包含：
    - ``accentText``：浅底（``accentBg``）上的**可读彩字**，对比度 ≥ 4.5；
    - 实心按钮色 ``solid`` / ``solidHover`` / ``solidActive`` / ``solidText``。
    """
    resolved = _resolve_color(color_name)
    if resolved not in _COLOR_PALETTE:
        resolved = "blue"
    raw = _COLOR_PALETTE[resolved][_mode_key(mode)]
    scheme = {k: QColor(v) for k, v in raw.items()}
    scheme["accentText"] = accent_text(resolved, mode, scheme["accentBg"])
    scheme.update(_solid_palette(scheme["accent"], resolved))
    return scheme


def get_accent_color(color_name: str, mode: ElaThemeType.ThemeMode) -> QColor:
    resolved = _resolve_color(color_name)
    if resolved not in _COLOR_PALETTE:
        resolved = "blue"
    return QColor(_COLOR_PALETTE[resolved][_mode_key(mode)]["accent"])


def accent_text(
    color_name: str,
    mode: ElaThemeType.ThemeMode,
    background: Optional[QColor] = None,
    target: float = 4.5,
) -> QColor:
    """浅底上的**可读彩字**（与实心按钮 ``solidText`` 同一套保证）。

    原始 ``accent`` 是按「填充色」设计的（配白字），直接拿来当浅底上的彩字，
    yellow / lime / cyan / green / geekblue / purple 等色系对比度只有 1.3~2.4。
    这里从本档 ``accent`` 出发，朝本档文字色（暗色→白 / 亮色→黑）逐步混合，
    直到与 ``background`` 的 WCAG 对比度 ≥ ``target``。

    :param background: 文字所在底色；缺省用本色的 ``accentBg``。
    """
    resolved = _resolve_color(color_name)
    if resolved not in _COLOR_PALETTE:
        resolved = "blue"
    raw = _COLOR_PALETTE[resolved][_mode_key(mode)]
    accent = QColor(raw["accent"])
    bg = QColor(background) if background is not None else QColor(raw["accentBg"])
    toward = (
        QColor("#ffffff") if mode != ElaThemeType.ThemeMode.Light else QColor("#000000")
    )
    if _contrast_ratio(accent, bg) >= target:
        return accent
    # 二分找「刚好达标」的最小混合量。**不能按固定步长循环有限次** ——
    # 6% × 40 步只到 #efefe3（离白还差 8%），低对比底色（暗色 yellow）永远
    # 收敛不到 4.5，最后静默返回一个不达标的值。
    low, high = 0.0, 1.0
    for _ in range(12):
        mid = (low + high) / 2.0
        if _contrast_ratio(_mix(accent, toward, mid), bg) >= target:
            high = mid
        else:
            low = mid
    return _mix(accent, toward, high)


# ── 状态层（透明底控件的悬浮 / 按下反馈）───────────────────────

#: 通用状态层透明度：hover ≈ 8% / press ≈ 12%（不换色相，只叠一层）。
STATE_HOVER_ALPHA = 20
STATE_PRESS_ALPHA = 31


def state_tint(mode: ElaThemeType.ThemeMode, *, pressed: bool = False) -> QColor:
    """通用状态层色：hover ≈ 8% / press ≈ 12%（**暗色叠白 / 亮色叠黑**）。

    透明底控件（``ElaButton`` 的 text / outlined 变体、下拉按钮族）共用；
    只负责颜色，形状与圆角由调用方画（``_styles.paintRoundedCard``）。
    """
    alpha = STATE_PRESS_ALPHA if pressed else STATE_HOVER_ALPHA
    if mode == ElaThemeType.ThemeMode.Dark:
        return QColor(255, 255, 255, alpha)
    return QColor(0, 0, 0, alpha)
