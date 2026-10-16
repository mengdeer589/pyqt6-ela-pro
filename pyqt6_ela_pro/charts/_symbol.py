"""ECharts symbol 形状子集（纯 QPainterPath，供 scatter/line/graph/tree 等共用）。

支持：``circle`` / ``rect`` / ``roundRect`` / ``triangle`` / ``diamond`` /
``pin`` / ``arrow``；未知形状回退 ``circle``（不抛异常）。
"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainter, QPainterPath

__all__ = ["symbolPath", "drawSymbol", "KNOWN_SYMBOLS"]

#: 支持的形状名（ECharts symbol 子集）
KNOWN_SYMBOLS = (
    "circle",
    "rect",
    "roundRect",
    "triangle",
    "diamond",
    "pin",
    "arrow",
)


def symbolPath(kind: str, center: QPointF, size: float) -> QPainterPath:
    """形状 → 路径（以 center 为中心，外接尺寸 ``size``）。"""
    name = str(kind or "circle")
    half = max(0.5, float(size) / 2.0)
    cx, cy = center.x(), center.y()
    path = QPainterPath()
    if name == "rect":
        path.addRect(QRectF(cx - half, cy - half, half * 2, half * 2))
        return path
    if name == "roundRect":
        radius = half * 0.25
        path.addRoundedRect(
            QRectF(cx - half, cy - half, half * 2, half * 2), radius, radius
        )
        return path
    if name == "triangle":
        path.moveTo(cx, cy - half)
        path.lineTo(cx + half, cy + half)
        path.lineTo(cx - half, cy + half)
        path.closeSubpath()
        return path
    if name == "diamond":
        path.moveTo(cx, cy - half)
        path.lineTo(cx + half, cy)
        path.lineTo(cx, cy + half)
        path.lineTo(cx - half, cy)
        path.closeSubpath()
        return path
    if name == "arrow":
        path.moveTo(cx, cy - half)
        path.lineTo(cx + half, cy - half * 0.2)
        path.lineTo(cx + half * 0.35, cy - half * 0.2)
        path.lineTo(cx + half * 0.35, cy + half)
        path.lineTo(cx - half * 0.35, cy + half)
        path.lineTo(cx - half * 0.35, cy - half * 0.2)
        path.lineTo(cx - half, cy - half * 0.2)
        path.closeSubpath()
        return path
    if name == "pin":
        # 地图钉：上圆下尖
        radius = half * 0.72
        path.addEllipse(QPointF(cx, cy - half + radius), radius, radius)
        tip = QPainterPath()
        tip.moveTo(cx - radius * 0.72, cy - half + radius * 1.6)
        tip.lineTo(cx, cy + half)
        tip.lineTo(cx + radius * 0.72, cy - half + radius * 1.6)
        tip.closeSubpath()
        path = path.united(tip)
        return path
    path.addEllipse(center, half, half)
    return path


def drawSymbol(painter: QPainter, kind: str, center: QPointF, size: float) -> None:
    """按当前画笔/画刷绘制符号（``size`` 为外接尺寸）。"""
    painter.drawPath(symbolPath(kind, center, size))
