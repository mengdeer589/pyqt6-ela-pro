"""内容语义色：diff 增删 / hunk 与 Callout 警告 / 注意。"""

from __future__ import annotations

from PyQt6.QtGui import QColor

from ._colors import _contrast_ratio
from ._theme import ElaStatusRoleType, statusColor, surfaceRaised, textMuted

__all__ = ["calloutColors", "diffColors"]


def _readable(color: QColor, background: QColor, minimum: float = 4.5) -> QColor:
    """把内容前景色沿 HSL 亮度推到与背景 ≥ ``minimum`` 对比度。"""
    out = QColor(color)
    if _contrast_ratio(out, background) >= minimum:
        return out
    hue, sat, light, alpha = out.getHslF()
    step = 0.04 if background.lightness() < 128 else -0.04
    for _ in range(24):
        light = min(1.0, max(0.0, light + step))
        out.setHslF(hue, sat, light, alpha)
        if _contrast_ratio(out, background) >= minimum:
            break
    return out


def diffColors(mode=None, background=None) -> dict:  # noqa: N802 (与 Qt 命名一致)
    """diff 视图的语义前景色（add / delete / hunk）。

    hunk 用中性弱文本色而不是 accent：强调色可被宿主改成红色，会和删除色撞车。
    ``background`` 缺省为 ``surfaceRaised``；前景会在必要时调整亮度保证 4.5:1。
    """
    bg = surfaceRaised(mode) if background is None else QColor(background)
    return {
        "add": _readable(statusColor(mode, ElaStatusRoleType.Success), bg),
        "delete": _readable(statusColor(mode, ElaStatusRoleType.Error), bg),
        "hunk": QColor(textMuted(mode)),
    }


def calloutColors(mode=None, background=None) -> dict:  # noqa: N802 (与 Qt 命名一致)
    """Markdown Callout 的警告 / 注意前景色（保证与背景 4.5:1）。"""
    bg = surfaceRaised(mode) if background is None else QColor(background)
    return {
        "warning": _readable(statusColor(mode, ElaStatusRoleType.Warning), bg),
        "caution": _readable(statusColor(mode, ElaStatusRoleType.Error), bg),
    }
