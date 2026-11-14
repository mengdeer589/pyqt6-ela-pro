"""通知组件共享的等级映射、卡片绘制与堆叠计算。"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6ElaWidgetTools import ElaIconType, ElaThemeType, eTheme

from ._internal import is_deleted
from ._styles import SHADOW_MARGIN, paintRoundedCard
from ._theme import ElaSeverity, blend, border, severityColor, surfacePopup

__all__ = [
    "BADGE_SIZE",
    "GAP",
    "PROGRESS_HEIGHT",
    "RADIUS",
    "SEVERITY_ALIASES",
    "SEVERITY_ICONS",
    "STACK_GAP",
    "coerceSeverity",
    "liveItems",
    "paintNotificationCard",
    "severityIcon",
    "stackOffset",
    "stackStep",
]

RADIUS = 8
BADGE_SIZE = 20
GAP = 10
PROGRESS_HEIGHT = 2.0
STACK_GAP = 10

SEVERITY_ALIASES = {
    "info": ElaSeverity.Info,
    "success": ElaSeverity.Success,
    "warning": ElaSeverity.Warning,
    "error": ElaSeverity.Error,
}

#: 实心圆内的字形用「非圆形」图标，避免与圆底重复。
SEVERITY_ICONS = {
    ElaSeverity.Info: ElaIconType.IconName.Info,
    ElaSeverity.Success: ElaIconType.IconName.Check,
    ElaSeverity.Warning: ElaIconType.IconName.Exclamation,
    ElaSeverity.Error: ElaIconType.IconName.Xmark,
}


def coerceSeverity(value) -> ElaSeverity:  # noqa: N802 (Qt 命名)
    """把 ``ElaSeverity`` / 字符串 / 整数归一成枚举；非法值抛 ``ValueError``。"""
    if isinstance(value, ElaSeverity):
        return value
    if isinstance(value, str):
        try:
            return SEVERITY_ALIASES[value.strip().lower()]
        except KeyError:
            raise ValueError(
                f"未知的通知等级 {value!r}；可用：info / success / warning / error"
            ) from None
    try:
        return ElaSeverity(int(value))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(
            f"未知的通知等级 {value!r}；可用：info / success / warning / error"
        ) from None


def severityIcon(severity: ElaSeverity) -> ElaIconType.IconName:  # noqa: N802
    """等级对应的实心圆内图标。"""
    return SEVERITY_ICONS[severity]


def liveItems(  # noqa: N802 (Qt 命名)
    items: Iterable,
    predicate: Optional[Callable] = None,
) -> list:
    """过滤已销毁条目；``predicate`` 可再叠加可见 / 关闭态条件。"""
    result = []
    for item in items:
        if is_deleted(item):
            continue
        if predicate is not None and not predicate(item):
            continue
        result.append(item)
    return result


def stackStep(  # noqa: N802 (Qt 命名)
    item,
    *,
    gap: int = STACK_GAP,
    margin: int = SHADOW_MARGIN,
) -> int:
    """单条目在堆叠中占用的纵向步长（扣掉两侧阴影边距，再加视觉间距）。"""
    return item.height() - 2 * margin + gap


def stackOffset(  # noqa: N802 (Qt 命名)
    items: Iterable,
    *,
    gap: int = STACK_GAP,
    margin: int = SHADOW_MARGIN,
    predicate: Optional[Callable] = None,
) -> int:
    """计算新条目在堆叠中的纵向偏移（已含阴影边距与条目间距）。"""
    return sum(
        stackStep(item, gap=gap, margin=margin) for item in liveItems(items, predicate)
    )


def paintNotificationCard(
    painter: QPainter,
    rect: QRectF,
    severity: ElaSeverity,
    *,
    progress: float = -1.0,
    radius: float = RADIUS,
) -> QColor:
    """画通知卡片（等级色浅底 + 描边 + 可选底部时间条），返回等级色。

    ``rect`` 是**卡片**区域，调用方需先平移到阴影边距之后。
    """
    mode = eTheme.getThemeMode()
    color = severityColor(mode, severity)
    tint = 0.08 if mode == ElaThemeType.ThemeMode.Light else 0.12
    paintRoundedCard(
        painter,
        rect,
        background=blend(surfacePopup(mode), color, tint),
        border=border(mode),
        radius=radius,
    )
    if progress >= 0.0:
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(clip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(
            QRectF(
                rect.left(),
                rect.top() + rect.height() - PROGRESS_HEIGHT,
                rect.width() * progress,
                PROGRESS_HEIGHT,
            )
        )
        painter.restore()
    return color
