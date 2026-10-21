"""ECharts symbol 形状子集（纯 QPainterPath，供 scatter/line/graph/tree 等共用）。

支持：``circle`` / ``rect`` / ``roundRect`` / ``triangle`` / ``diamond`` /
``pin`` / ``arrow``；未知形状回退 ``circle``（不抛异常）。
"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

__all__ = ["symbolPath", "drawSymbol", "symbolPixmap", "KNOWN_SYMBOLS"]

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


#: 符号位图缓存：``(kind, 直径 0.5px 量化, 填充色, 描边色, 描边宽, dpr)`` → QPixmap
_SPRITE_CACHE: dict = {}
_SPRITE_CACHE_MAX = 512


def symbolPixmap(
    kind: str,
    size: float,
    color,
    border_color=None,
    border_width: float = 0.0,
    dpr: float = 1.0,
) -> QPixmap:
    """符号的**预渲染位图**（点量大时批量贴图用）。

    实测 5556 个点（r=2，AA 开）：逐点 ``drawEllipse`` 14.7ms、合并成一条
    ``QPainterPath`` **204ms**（AA 椭圆路径光栅化极贵）、**QPixmap + 贴图 3.5ms**
    —— 所以「量大 + 同尺寸同色」的符号一律走位图贴图。

    位图按 ``dpr`` 以物理像素渲染并 ``setDevicePixelRatio``，高 DPI 下不发虚。

    **返回副本**（对齐 ``svg_icon`` 的教训：缓存里存的活动对象一旦被调用方
    就地改写 —— 例如 ``fill(red)`` —— 之后所有调用方都会拿到被改过的图）。
    """
    fill = QColor(color)
    stroke = QColor(border_color) if border_color is not None else None
    width = float(border_width or 0.0)
    dpr = max(0.5, float(dpr or 1.0))
    size = max(1.0, float(size))
    key = (
        str(kind or "circle"),
        round(size * 2.0) / 2.0,
        fill.rgba(),
        stroke.rgba() if stroke is not None else -1,
        round(width, 2),
        round(dpr, 2),
    )
    cached = _SPRITE_CACHE.get(key)
    if cached is not None:
        return QPixmap(cached)
    pad = 2
    physical = max(2, int(round(size * dpr)) + pad)
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(fill)
        painter.setPen(QPen(stroke, width) if stroke is not None else QPen(Qt.PenStyle.NoPen))
        center = QPointF(physical / 2.0, physical / 2.0)
        painter.drawPath(symbolPath(key[0], center, size * dpr))
    finally:
        painter.end()
    pixmap.setDevicePixelRatio(dpr)
    if len(_SPRITE_CACHE) >= _SPRITE_CACHE_MAX:
        _SPRITE_CACHE.clear()
    _SPRITE_CACHE[key] = pixmap
    return QPixmap(pixmap)
