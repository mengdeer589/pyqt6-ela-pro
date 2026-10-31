"""极坐标系。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen

from .._tokens import T
from .._utils import single_option
from ._shared import _datum_y, _line_pen, _to_float, formatValue
from .base import AxisModel, Coord


class PolarCoord(Coord):
    """极坐标系：radiusAxis（value）+ angleAxis（category/value）。

    ``polar`` 收 ``radius``（数值 / ``"N%"`` / ``[inner, outer]``，默认 ``"80%"``）
    与 ``center``。``mapPoint(angle, radius)``：角度自正上方起顺时针。
    """

    kind = "polar"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        polar = dict(single_option(self.option.get("polar"), "polar") or {})
        aopt = dict(single_option(self.option.get("angleAxis"), "angleAxis") or {})
        a_default = "category" if aopt.get("data") else "value"
        self.angle_axis = AxisModel(aopt, a_default, self.chart)
        self.radius_axis = AxisModel(
            dict(single_option(self.option.get("radiusAxis"), "radiusAxis") or {}),
            "value",
            self.chart,
        )
        self._radius_opt = polar.get("radius", "80%")
        center = polar.get("center")
        self._center_opt = (
            list(center)
            if isinstance(center, (list, tuple)) and len(center) >= 2
            else ["50%", "50%"]
        )
        self.center = QPointF()
        self.radius = 1.0

    def setSeries(self, series_opts: list) -> None:
        rs = []
        for s in series_opts or []:
            if not isinstance(s, dict) or s.get("coordinateSystem") != "polar":
                continue
            for item in s.get("data") or []:
                r = _datum_y(item)
                if r is not None:
                    rs.append(r)
        if rs:
            self.radius_axis.setExtent(0.0, max(rs))
        else:
            self.radius_axis.setExtent(0.0, 1.0)
        if self.angle_axis.type == "value":
            self.angle_axis.setExtent(0.0, 360.0, segments=4)

    @staticmethod
    def _extent_px(value, avail: float, default_frac: float) -> float:
        """极坐标 radius / center 分量：数值 px、``"N%"`` 或非法 → 默认比例。"""
        if value is None:
            return avail * default_frac
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        text = str(value).strip()
        if text.endswith("%"):
            try:
                return avail * float(text[:-1]) / 100.0
            except ValueError:
                return avail * default_frac
        try:
            return float(text)
        except ValueError:
            return avail * default_frac

    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        cx = self._extent_px(self._center_opt[0], rect.width(), 0.5)
        cy = self._extent_px(self._center_opt[1], rect.height(), 0.5)
        self.center = QPointF(rect.left() + cx, rect.top() + cy)
        radius_opt = self._radius_opt
        if isinstance(radius_opt, (list, tuple)):
            radius_opt = radius_opt[-1] if radius_opt else "80%"
        self.radius = max(
            10.0,
            self._extent_px(radius_opt, min(rect.width(), rect.height()) / 2, 0.8),
        )

    def _angle_frac(self, angle) -> float:
        ax = self.angle_axis
        if ax.type == "category":
            n = max(1, len(ax.categories))
            return (ax.categoryIndex(angle) % n) / n
        span = ax.vmax - ax.vmin
        return 0.0 if span == 0 else (_to_float(angle) - ax.vmin) / span

    def mapPoint(self, x, y=None) -> QPointF:
        """(angle, radius) → 像素。angle 类别/数值；radius 数值。"""
        frac = self._angle_frac(x)
        theta = -math.pi / 2 + frac * 2 * math.pi  # 正上方起顺时针
        r_span = self.radius_axis.vmax - self.radius_axis.vmin
        r_frac = 0.0 if r_span == 0 else (_to_float(y) - self.radius_axis.vmin) / r_span
        r_frac = min(max(r_frac, 0.0), 1.0)
        r = self.radius * r_frac
        return QPointF(
            self.center.x() + r * math.cos(theta), self.center.y() + r * math.sin(theta)
        )

    def invertPoint(self, pos: QPointF):
        """像素 → ``[angle, radius]``（category 角轴返回下标）。"""
        dx = pos.x() - self.center.x()
        dy = pos.y() - self.center.y()
        r = math.hypot(dx, dy)
        r_span = self.radius_axis.vmax - self.radius_axis.vmin
        r_frac = (r / self.radius) if self.radius else 0.0
        radius_val = self.radius_axis.vmin + min(max(r_frac, 0.0), 1.0) * r_span
        frac = ((math.atan2(dy, dx) + math.pi / 2) % (2 * math.pi)) / (2 * math.pi)
        if self.angle_axis.type == "category":
            n = max(1, len(self.angle_axis.categories))
            angle = min(int(frac * n), n - 1)
        else:
            span = self.angle_axis.vmax - self.angle_axis.vmin
            angle = self.angle_axis.vmin + frac * span
        return [angle, radius_val]

    def containPoint(self, pos: QPointF) -> bool:
        return (
            math.hypot(pos.x() - self.center.x(), pos.y() - self.center.y())
            <= self.radius + 1e-6
        )

    def _ring_path(self, frac: float) -> QPainterPath:
        r = self.radius * frac
        path = QPainterPath()
        path.addEllipse(self.center, r, r)
        return path

    def paintAxes(self, p: QPainter) -> None:
        p.save()
        c_grid = QColor(T("color.border"))
        c_text = QColor(T("color.text.secondary"))
        font = self.radius_axis.labelFont()
        p.setFont(font)
        fm = QFontMetricsF(font)
        ticks = self.radius_axis.ticks()
        span = self.radius_axis.vmax - self.radius_axis.vmin
        # 环形网格
        for tv in ticks[1:]:
            frac = 1.0 if span == 0 else (tv - self.radius_axis.vmin) / span
            p.setPen(QPen(c_grid, 1))
            p.drawPath(self._ring_path(frac))
        # 角轴辐条 + 外圈类别标签
        if self.angle_axis.type == "category" and self.angle_axis.categories:
            n = len(self.angle_axis.categories)
            for i, cat in enumerate(self.angle_axis.categories):
                theta = -math.pi / 2 + i / n * 2 * math.pi
                outer = QPointF(
                    self.center.x() + self.radius * math.cos(theta),
                    self.center.y() + self.radius * math.sin(theta),
                )
                p.setPen(QPen(c_grid, 1))
                p.drawLine(self.center, outer)
                lx = self.center.x() + (self.radius + 14) * math.cos(theta)
                ly = self.center.y() + (self.radius + 14) * math.sin(theta)
                p.setPen(c_text)
                p.drawText(
                    QRectF(lx - 40, ly - fm.height() / 2, 80, fm.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    str(cat),
                )
        # 半径刻度标签（沿正上方辐条）
        for tv in ticks[1:]:
            frac = 1.0 if span == 0 else (tv - self.radius_axis.vmin) / span
            p.setPen(c_text)
            p.drawText(
                QRectF(
                    self.center.x() + 2,
                    self.center.y() - self.radius * frac - fm.height() / 2,
                    48,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                formatValue(tv),
            )
        p.restore()

    def paintTooltipMarker(
        self, p: QPainter, pos: QPointF, kind: str = "cross", line_style: dict = None
    ) -> None:
        if kind == "none":
            return
        p.save()
        style = line_style if isinstance(line_style, dict) else {}
        pen = _line_pen({"lineStyle": style}, T("color.border.strong"))
        if not isinstance(style.get("type"), str):
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(self.center, pos)
        if kind == "cross":
            r = math.hypot(pos.x() - self.center.x(), pos.y() - self.center.y())
            if r > 1:
                p.drawEllipse(self.center, r, r)
        p.restore()
