"""语义令牌层：把上游颜色槽位翻译成可读角色，并补齐 Success / Warning 等缺项。

公开入口见 ``docs/core.md`` 与模块导出。"""

from __future__ import annotations

from enum import IntEnum
from typing import List, Optional

from PyQt6.QtGui import QColor

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._colors import parse_color

__all__ = [
    "ElaSeverity",
    "ElaStatusRoleType",
    "accent",
    "blend",
    "border",
    "borderStrong",
    "chartPalette",
    "currentMode",
    "relativeLuminance",
    "resetAccentColor",
    "setAccentColor",
    "severityColor",
    "statusColor",
    "surface",
    "surfaceDialog",
    "surfacePopup",
    "surfaceRaised",
    "text",
    "textDisabled",
    "textMuted",
    "textOnAccent",
]


_TC = ElaThemeType.ThemeColor
_TM = ElaThemeType.ThemeMode


def currentMode() -> int:  # noqa: N802 (与 Qt 命名一致)
    """当前主题模式（``Light`` / ``Dark``）。

    自绘控件在 ``paintEvent`` 开头调一次即可；缓存颜色的控件（``ColorText`` 等）
    仍应走 ``_apply_theme`` 重算。

    ``eTheme.getThemeColor`` 的 ``mode`` 不接受 ``None``（直接 ``TypeError``），
    本层访问器统一包了一层，``mode=None`` 即当前模式。
    """
    return eTheme.getThemeMode()


def blend(base: QColor, other: QColor, t: float) -> QColor:
    """按比例混合两种颜色，``t`` 是**第二个参数（前景）**的占比（0-1，含 alpha）。
    **参数序易搞反**：``blend(白底, 黑, 0.075)`` 才是「浅底叠 7.5% 黑」，
    反过来会算成近黑。alpha 一起插值，半透明叠色才与两次绘制等价（否则边界出硬环）。
    """
    t = max(0.0, min(1.0, float(t)))
    return QColor(
        round(base.red() + (other.red() - base.red()) * t),
        round(base.green() + (other.green() - base.green()) * t),
        round(base.blue() + (other.blue() - base.blue()) * t),
        round(base.alpha() + (other.alpha() - base.alpha()) * t),
    )


def relativeLuminance(color: QColor) -> float:  # noqa: N802 (与数学名一致)
    """**Rec.709** 相对亮度（0-1），直接对 0-1 通道值线性加权，不做 sRGB 线性化。

    阈值由它决定（``ela_avatar`` 的对比度），别按 WCAG 公式去「修正」。
    """
    return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()


def _color(mode, token) -> QColor:
    """读一个上游槽位并**拷贝**成新的 QColor。``mode=None`` = 当前模式。"""
    if mode is None:
        mode = currentMode()
    return QColor(eTheme.getThemeColor(mode, token))


# ── 表面 ──────────────────────────────────────────────────────


def surface(mode) -> QColor:
    """最底层表面（窗口 / 画布）。``WindowBase``"""
    return _color(mode, _TC.WindowBase)


def surfaceRaised(mode) -> QColor:
    """抬起一层的表面（卡片 / 输入框）。``BasicBase``"""
    return _color(mode, _TC.BasicBase)


def surfacePopup(mode) -> QColor:
    """弹层表面（菜单 / 气泡 / 下拉）。``PopupBase``"""
    return _color(mode, _TC.PopupBase)


def surfaceDialog(mode) -> QColor:
    """对话框表面。``DialogBase``"""
    return _color(mode, _TC.DialogBase)


# ── 边 ────────────────────────────────────────────────────────


def border(mode) -> QColor:
    """常规描边。``BasicBorder``"""
    return _color(mode, _TC.BasicBorder)


def borderStrong(mode) -> QColor:
    """强调描边（聚焦态外圈等）。``BasicBorderDeep``"""
    return _color(mode, _TC.BasicBorderDeep)


# ── 文字 ──────────────────────────────────────────────────────


def text(mode) -> QColor:
    """正文主色。``BasicText``"""
    return _color(mode, _TC.BasicText)


def textMuted(mode) -> QColor:
    """次要 / 说明文字。``BasicDetailsText``"""
    return _color(mode, _TC.BasicDetailsText)


def textDisabled(mode) -> QColor:
    """禁用文字。``BasicTextDisable``"""
    return _color(mode, _TC.BasicTextDisable)


def accent(mode) -> QColor:
    """强调色（基础档）。``PrimaryNormal``"""
    return _color(mode, _TC.PrimaryNormal)


# ── 语义状态色 ────────────────────────────────────────────────


class ElaStatusRoleType(IntEnum):
    """校验 / 提示的语义档位。
    刻意**不叫** ``None``：那是 Python 关键字，当不了枚举成员名（``None = 0`` 是
    SyntaxError）。用 ``Neutral`` 表达「无状态」。
    """

    Neutral = 0
    """无状态：不显示图标，文字用次要色。"""

    Error = 1
    Warning = 2
    Success = 3


class ElaSeverity(IntEnum):
    """消息提示的严重等级（toast / 通知弹窗共用）。"""

    Info = 0
    Success = 1
    Warning = 2
    Error = 3


#: ``Warning`` / ``Success`` 的定值，**刻意不从强调色派生**：状态语义来自色相
#: （琥珀 / 绿），换强调色不该把它染成同色；色值取 Fluent 对比度调校过的一组。
_STATUS_COLORS = {
    _TM.Light: {
        ElaStatusRoleType.Warning: QColor("#9D5D00"),
        ElaStatusRoleType.Success: QColor("#0F7B0F"),
    },
    _TM.Dark: {
        ElaStatusRoleType.Warning: QColor("#FCE100"),
        ElaStatusRoleType.Success: QColor("#6CCB5F"),
    },
}


def _shift(base: QColor, d_s: float, d_l: float) -> QColor:
    """保持色相与 alpha，按 HSL 偏移饱和度 / 亮度。
    ``QColor.getHslF()`` 返回 **4 元组**（含 alpha），写成 3 元组会
    ``ValueError``。
    """
    hue, sat, light, alpha = base.getHslF()
    out = QColor()
    out.setHslF(
        hue,
        min(max(sat + d_s, 0.0), 1.0),
        min(max(light + d_l, 0.0), 1.0),
        alpha,
    )
    return out


def statusColor(mode, role: ElaStatusRoleType) -> QColor:
    """校验 / 提示状态的文字与图标色。

    ``Error`` 用上游 ``StatusDanger``；``Warning`` / ``Success`` 取
    :data:`_STATUS_COLORS` 定值；``Neutral`` 回落次要文字色。

    :param mode: ``None`` = 当前模式；定值色表也按它取，否则暗色下会拿到浅色主题的色。
    :param role: 也接受裸 int；非法值按 ``Neutral`` 处理。
    """
    if mode is None:
        mode = currentMode()
    try:
        role = ElaStatusRoleType(role)
    except ValueError:
        role = ElaStatusRoleType.Neutral
    if role == ElaStatusRoleType.Neutral:
        return textMuted(mode)
    if role == ElaStatusRoleType.Error:
        return _color(mode, _TC.StatusDanger)
    table = _STATUS_COLORS.get(mode) or _STATUS_COLORS[_TM.Light]
    return QColor(table.get(role, table[ElaStatusRoleType.Warning]))


#: 消息等级 → 状态角色。``Info`` 没有对应状态色，单独走强调色。
_SEVERITY_ROLE = {
    ElaSeverity.Success: ElaStatusRoleType.Success,
    ElaSeverity.Warning: ElaStatusRoleType.Warning,
    ElaSeverity.Error: ElaStatusRoleType.Error,
}


def severityColor(mode, severity: ElaSeverity) -> QColor:
    """消息等级的图标 / 指示色：``Info`` 用强调色，其余走状态色。

    :param mode: ``None`` = 当前模式。
    :param severity: 也接受裸 int；非法值按 ``Info`` 处理。
    """
    if mode is None:
        mode = currentMode()
    try:
        severity = ElaSeverity(severity)
    except (TypeError, ValueError):
        severity = ElaSeverity.Info
    if severity == ElaSeverity.Info:
        return accent(mode)
    return statusColor(mode, _SEVERITY_ROLE[severity])


# ── 分类调色板（头像兜底色等） ────────────────────────────────


def chartPalette(mode=None) -> List[QColor]:
    """一组彼此可区分的分类色，用于「按名字稳定取色」的场景（头像兜底底色等）。
    复用 ``charts._tokens.ECHARTS_PALETTE``，不另维护一份；**每次返回新 list**，
    调用方常对单个元素 ``setAlpha``，共享实例会污染全局。
    """
    from .charts._tokens import ECHARTS_PALETTE

    return [QColor(c) for c in ECHARTS_PALETTE]


# ── 强调色换色 ────────────────────────────────────────────────


#: 强调色 hover / press 的 HSL 偏移 ``(ΔS, ΔL)``，从上游出厂值反解；默认色经
#: :func:`setAccentColor` → :func:`resetAccentColor` 必须逐值还原（``tests/theme/`` 钉住）。
_ACCENT_STEPS = {
    _TM.Light: {"hover": (-0.225, +0.059), "press": (-0.390, +0.116)},
    _TM.Dark: {"hover": (-0.1376, -0.0353), "press": (-0.2999, -0.0883)},
}

#: ``ToggleSwitchNoToggledCenter``（开关未激活的圆点）跟随强调色。它在上游是中性灰，
#: 不跟着走就会出现「强调色换了、开关圆点还是灰的」。
_SWITCH_CENTER_DS = -0.55

#: 上游出厂强调色，供 :func:`resetAccentColor` 还原。
_DEFAULT_ACCENT = {
    _TM.Light: QColor("#0067c0"),
    _TM.Dark: QColor("#4abcf7"),
}

#: 上游出厂的开关圆点色（还原用）。
_DEFAULT_SWITCH_CENTER = {
    _TM.Light: QColor("#6a6a6a"),
    _TM.Dark: QColor("#d0d0d0"),
}


def setAccentColor(color, modes=None) -> None:
    """换强调色，**并一并派生写入 hover / press / 开关圆点**（换色后不自动重绘，见模块 docstring）。

    ``color`` 收 ``QColor`` / hex / ``rgb()`` / ``rgba()``；非法值忽略。
    """
    value = parse_color(color)
    if not value.isValid():
        return
    targets = list(modes) if modes else [_TM.Light, _TM.Dark]
    for mode in targets:
        steps = _ACCENT_STEPS.get(mode, _ACCENT_STEPS[_TM.Light])
        eTheme.setThemeColor(mode, _TC.PrimaryNormal, QColor(value))
        for slot, key in (
            (_TC.PrimaryHover, "hover"),
            (_TC.PrimaryPress, "press"),
        ):
            d_s, d_l = steps[key]
            eTheme.setThemeColor(mode, slot, _shift(value, d_s, d_l))
        eTheme.setThemeColor(
            mode, _TC.ToggleSwitchNoToggledCenter, _shift(value, _SWITCH_CENTER_DS, 0.0)
        )


def resetAccentColor(modes=None) -> None:
    """还原成上游出厂强调色（并按出厂值写回开关圆点，不重新派生）。"""
    targets = list(modes) if modes else [_TM.Light, _TM.Dark]
    for mode in targets:
        base = _DEFAULT_ACCENT.get(mode)
        if base is None:
            continue
        eTheme.setThemeColor(mode, _TC.PrimaryNormal, QColor(base))
        eTheme.setThemeColor(
            mode, _TC.ToggleSwitchNoToggledCenter, QColor(_DEFAULT_SWITCH_CENTER[mode])
        )
        # hover / press 一并回到出厂值，换回后视觉与「从未换过色」完全相同
        steps = _ACCENT_STEPS.get(mode, _ACCENT_STEPS[_TM.Light])
        for slot, key in ((_TC.PrimaryHover, "hover"), (_TC.PrimaryPress, "press")):
            d_s, d_l = steps[key]
            eTheme.setThemeColor(mode, slot, _shift(base, d_s, d_l))


def textOnAccent(color: Optional[QColor] = None) -> QColor:
    """强调色上的前景色（按亮度自动黑 / 白，分界取 0.6，与上游按钮一致）。
    ``color=None`` 取**当前模式**的强调色 —— 用 Light 档算会在暗色下给出反的
    答案（暗色强调色是亮青，该给黑字却给了白字）。
    """
    base = accent(currentMode()) if color is None else color
    if base.lightnessF() > 0.6:
        return QColor(0, 0, 0)
    return QColor(255, 255, 255)
