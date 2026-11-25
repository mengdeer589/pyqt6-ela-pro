"""通知组件共享的等级映射、卡片 / 标识绘制与堆叠计算。"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6ElaWidgetTools import ElaIconType, ElaThemeType, eTheme

from ._colors import soft_surface
from ._internal import is_deleted
from ._styles import SHADOW_MARGIN, iconGlyph, paintRoundedCard
from ._theme import (
    ElaSeverity,
    blend,
    border,
    borderStrong,
    severityColor,
    surfacePopup,
)

__all__ = [
    "CHIP_GLYPH_SIZE",
    "CHIP_RADIUS",
    "CHIP_SIZE",
    "GAP",
    "PROGRESS_BOTTOM",
    "PROGRESS_HEIGHT",
    "PROGRESS_INSET",
    "RADIUS",
    "SEVERITY_ALIASES",
    "SEVERITY_ICONS",
    "STACK_GAP",
    "coerceSeverity",
    "liveItems",
    "notificationCardBackground",
    "paintNotificationCard",
    "paintNotificationChip",
    "severityIcon",
    "stackOffset",
    "stackStep",
]

RADIUS = 10
CHIP_SIZE = 24
CHIP_RADIUS = 8
CHIP_GLYPH_SIZE = 13
GAP = 10
PROGRESS_HEIGHT = 2.0
#: 时间条左右内缩 / 距卡片底边，避免贴边通栏像加载条
PROGRESS_INSET = 12.0
PROGRESS_BOTTOM = 6.0
STACK_GAP = 10

#: 整卡等级色叠加强度：只留一点温度，层次交给 chip / 时间条
_TINT_LIGHT = 0.04
_TINT_DARK = 0.04
_TINT_HOVER_BOOST = 0.02

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
    """等级对应的 chip 图标。"""
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


def paintNotificationChip(
    painter: QPainter,
    rect,
    severity: ElaSeverity,
    icon,
    *,
    mode,
    surface,
    hovered: bool = False,
) -> None:
    """等级 chip：全库统一的软彩色表面（底 + 描边 + 可读彩字）。

    :param surface: chip 实际所在的底色（通知卡片底，不是窗口底）。
    """
    box = QRectF(rect)
    if box.isEmpty():
        return
    bg, border, glyph = soft_surface(
        severityColor(mode, severity), mode, surface, hovered=hovered
    )
    paintRoundedCard(painter, box, background=bg, border=border, radius=CHIP_RADIUS)
    font = QFont("ElaAwesome")
    font.setPixelSize(CHIP_GLYPH_SIZE)
    painter.save()
    painter.setFont(font)
    painter.setPen(glyph)
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, iconGlyph(icon))
    painter.restore()


def _paintProgress(
    painter: QPainter,
    rect: QRectF,
    color: QColor,
    mode,
    progress: float,
) -> None:
    """卡片底部内缩的时间条：淡轨道 + 等级色进度。"""
    left = rect.left() + PROGRESS_INSET
    width = rect.width() - 2 * PROGRESS_INSET
    if width <= 0:
        return
    top = rect.bottom() - PROGRESS_BOTTOM - PROGRESS_HEIGHT
    radius = PROGRESS_HEIGHT / 2.0
    track = QColor(border(mode))
    track.setAlphaF(0.3)
    bar = QColor(color)
    bar.setAlphaF(0.65)
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track)
    painter.drawRoundedRect(QRectF(left, top, width, PROGRESS_HEIGHT), radius, radius)
    if progress > 0.0:
        painter.setBrush(bar)
        painter.drawRoundedRect(
            QRectF(left, top, max(PROGRESS_HEIGHT, width * progress), PROGRESS_HEIGHT),
            radius,
            radius,
        )
    painter.restore()


def notificationCardBackground(
    mode,
    severity: ElaSeverity,
    *,
    hovered: bool = False,
    tint: Optional[float] = None,
) -> QColor:
    """通知卡片底：弹层表面混入 4% 等级色。

    chip 的可读文字按这个底计算，因此它必须与实际绘制出的卡片底色一致。
    """
    accent = severityColor(mode, severity)
    if tint is None:
        tint = _TINT_LIGHT if mode == ElaThemeType.ThemeMode.Light else _TINT_DARK
    if hovered:
        tint += _TINT_HOVER_BOOST
    return blend(surfacePopup(mode), accent, tint)


def paintNotificationCard(
    painter: QPainter,
    rect: QRectF,
    severity: ElaSeverity,
    *,
    progress: float = -1.0,
    radius: float = RADIUS,
    tint: Optional[float] = None,
    hovered: bool = False,
) -> QColor:
    """画通知卡片（近乎中性的底 + 描边 + 可选底部时间条），返回卡底。

    ``rect`` 是**卡片**区域，调用方需先平移到阴影边距之后。

    :param tint: 等级色叠加强度；``None`` = 按主题取默认值。
    :param hovered: 悬停态提亮描边与底色。
    """
    mode = eTheme.getThemeMode()
    accent = severityColor(mode, severity)
    card_bg = notificationCardBackground(mode, severity, hovered=hovered, tint=tint)
    paintRoundedCard(
        painter,
        rect,
        background=card_bg,
        border=borderStrong(mode) if hovered else border(mode),
        radius=radius,
    )
    if progress >= 0.0:
        _paintProgress(painter, QRectF(rect), accent, mode, progress)
    return card_bg
