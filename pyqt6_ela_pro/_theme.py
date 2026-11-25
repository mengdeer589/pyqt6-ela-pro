"""语义令牌层：把上游颜色槽位翻译成可读角色，并补齐 Success / Warning 等缺项。

公开入口见 ``docs/core.md`` 与模块导出。"""

from __future__ import annotations

from enum import IntEnum
from typing import List, Optional

from PyQt6.QtGui import QColor

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ._colors import mixColor, parse_color

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
    "surfaceControl",
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
    return mixColor(base, other, t, rounding=True)


def relativeLuminance(color: QColor) -> float:  # noqa: N802 (与数学名一致)
    """**Rec.709** 相对亮度（0-1），直接对 0-1 通道值线性加权，不做 sRGB 线性化。

    阈值由它决定（``ela_avatar`` 的对比度），别按 WCAG 公式去「修正」。
    """
    return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()


def _composite(base: QColor, overlay: QColor) -> QColor:
    """把半透明 ``overlay`` 按 source-over 压到不透明 ``base`` 上，返回不透明色。

    V3.0 起 ``BasicBaseAlpha`` / ``BasicBorder`` / ``BasicText*`` 都是 alpha 叠色；
    读取层必须给不透明色 —— ``QTextDocument`` 的 CSS、matplotlib 的 ``.name()``
    等场景会直接丢弃 alpha，半透明色在那里会退化成纯白/纯黑。
    """
    a = overlay.alphaF()
    result = QColor(overlay)
    if a >= 1.0:
        result.setAlpha(255)
        return result
    base = QColor(base)
    base.setAlpha(255)
    return QColor(
        round(base.red() * (1 - a) + overlay.red() * a),
        round(base.green() * (1 - a) + overlay.green() * a),
        round(base.blue() * (1 - a) + overlay.blue() * a),
        255,
    )


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
    """卡片 / 内容层表面。``BasicBaseAlpha`` 叠在 ``WindowBase`` 上。"""
    return _composite(surface(mode), _color(mode, _TC.BasicBaseAlpha))


def surfaceControl(mode) -> QColor:
    """普通控件填充。``BasicBase`` 叠在卡片层上。"""
    return _composite(surfaceRaised(mode), _color(mode, _TC.BasicBase))


def surfacePopup(mode) -> QColor:
    """弹层表面（菜单 / 气泡 / 下拉）。``PopupBase``"""
    return _color(mode, _TC.PopupBase)


def surfaceDialog(mode) -> QColor:
    """对话框表面。``PopupBase``"""
    return _color(mode, _TC.PopupBase)


# ── 边 ────────────────────────────────────────────────────────


def border(mode) -> QColor:
    """常规描边。``BasicBorder`` 叠在卡片表面上。"""
    return _composite(surfaceRaised(mode), _color(mode, _TC.BasicBorder))


def borderStrong(mode) -> QColor:
    """强调描边（聚焦态外圈等）。``BasicBorderDeep`` 叠在卡片表面上。"""
    return _composite(surfaceRaised(mode), _color(mode, _TC.BasicBorderDeep))


# ── 文字 ──────────────────────────────────────────────────────


def text(mode) -> QColor:
    """正文主色。``BasicText`` 叠在卡片表面上。"""
    return _composite(surfaceRaised(mode), _color(mode, _TC.BasicText))


def textMuted(mode) -> QColor:
    """次要 / 说明文字。``BasicTextNoFocus`` 叠在卡片表面上。"""
    return _composite(surfaceRaised(mode), _color(mode, _TC.BasicTextNoFocus))


def textDisabled(mode) -> QColor:
    """禁用文字。``BasicTextDisable`` 叠在卡片表面上。"""
    return _composite(surfaceRaised(mode), _color(mode, _TC.BasicTextDisable))


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


def statusColor(mode, role: ElaStatusRoleType) -> QColor:
    """校验 / 提示状态的文字与图标色。

    ``Error`` / ``Warning`` / ``Success`` 分别取上游 ``StatusDanger`` /
    ``StatusWarning`` / ``StatusSuccess``；``Neutral`` 回落次要文字色。

    :param mode: ``None`` = 当前模式。
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
    if role == ElaStatusRoleType.Warning:
        return _color(mode, _TC.StatusWarning)
    return _color(mode, _TC.StatusSuccess)


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


#: 上游出厂强调色三元组（normal / hover / press），导入时快照。
#: 宿主应在 import 之后再换色；reload 不重新快照，否则会把自定义色当成工厂色。
if "_FACTORY_ACCENT" not in globals():
    _FACTORY_ACCENT = {
        mode: (
            _color(mode, _TC.PrimaryNormal),
            _color(mode, _TC.PrimaryHover),
            _color(mode, _TC.PrimaryPress),
        )
        for mode in (_TM.Light, _TM.Dark)
    }


def setAccentColor(color, modes=None) -> None:
    """换强调色（hover / press 由上游 ``setThemeColor`` 自动派生）。

    ``color`` 收 ``QColor`` / hex / ``rgb()`` / ``rgba()``；非法值忽略。
    """
    value = parse_color(color)
    if not value.isValid():
        return
    targets = list(modes) if modes else [_TM.Light, _TM.Dark]
    for mode in targets:
        eTheme.setThemeColor(mode, _TC.PrimaryNormal, QColor(value))


def resetAccentColor(modes=None) -> None:
    """还原成导入时快照的上游出厂强调色（normal / hover / press 逐值写回）。"""
    targets = list(modes) if modes else [_TM.Light, _TM.Dark]
    for mode in targets:
        factory = _FACTORY_ACCENT.get(mode)
        if factory is None:
            continue
        normal, hover, press = factory
        eTheme.setThemeColor(mode, _TC.PrimaryNormal, QColor(normal))
        eTheme.setThemeColor(mode, _TC.PrimaryHover, QColor(hover))
        eTheme.setThemeColor(mode, _TC.PrimaryPress, QColor(press))


def textOnAccent(color: Optional[QColor] = None) -> QColor:
    """强调色上的前景色（按亮度自动黑 / 白，分界取 0.6，与上游按钮一致）。
    ``color=None`` 取**当前模式**的强调色 —— 用 Light 档算会在暗色下给出反的
    答案（暗色强调色是亮青，该给黑字却给了白字）。
    """
    base = accent(currentMode()) if color is None else color
    if base.lightnessF() > 0.6:
        return QColor(0, 0, 0)
    return QColor(255, 255, 255)
