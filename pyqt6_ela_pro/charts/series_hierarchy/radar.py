"""雷达图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from .._utils import clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import single_option, with_alpha
from .._utils import parse_color
from ..core import SeriesRenderer
from ._shared import (
    _dist_to_polygon_edge,
    _label_font,
    _parse_pct,
    _series_palette_color,
    _text_color,
)


class RadarSeriesRenderer(SeriesRenderer):
    """雷达图（自绘蛛网坐标：圈环 + 轴线 + 维度标签）。

    支持 ``indicator`` / ``data`` / ``shape`` / ``areaStyle`` / ``splitNumber`` /
    ``axisName`` / ``splitLine`` / ``axisLine``，以及顶层 ``radar`` 组件。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._center = QPointF()
        self._radius = 1.0
        self._indicators = []  # [{"name","max"}]
        self._polys = []  # [{"name","values","color","points":[QPointF]}]
        self._radar_opt = {}

    def layout(self, rect: QRectF) -> None:
        self._polys = []
        # 顶层 ``radar`` 组件提供 indicator / center / radius，系列同名键优先。
        radar_opt = single_option(self.chart._option.get("radar"), "radar") or {}
        self._radar_opt = radar_opt
        indicators = self.opt.get("indicator")
        if not isinstance(indicators, (list, tuple)) or not indicators:
            indicators = radar_opt.get("indicator")
        inds = []
        for item in indicators or []:
            if isinstance(item, dict):
                inds.append(
                    {
                        "name": str(item.get("name") or ""),
                        "min": item.get("min"),
                        "max": item.get("max"),
                    }
                )
        entries = []
        for item in self.data():
            if isinstance(item, dict):
                name = str(item.get("name") or "")
                values = item.get("value")
            else:
                name, values = "", item
            if isinstance(values, (list, tuple)):
                vals = [_to_float(v, 0.0) for v in values]
            else:
                vals = [_to_float(values, 0.0)]
            entries.append((name, vals))
        if not inds and entries:
            n = max(len(v) for _, v in entries)
            inds = [{"name": f"dim{i + 1}", "max": None} for i in range(n)]
        if not inds:
            self._indicators = []
            return
        # 每维 min/max：min 缺省 0，max 缺省取全数据该维最大 * 1.1
        n = len(inds)
        for j in range(n):
            lo = _to_float(inds[j].get("min"), 0.0)
            if not math.isfinite(lo):
                lo = 0.0
            if inds[j]["max"] is None:
                col = [vals[j] for _, vals in entries if j < len(vals)]
                hi = (max(col) * 1.1) if col else 1.0
            else:
                hi = _to_float(inds[j]["max"], 1.0)
            if not math.isfinite(hi):
                hi = 1.0
            if hi <= lo:
                hi = lo + 1e-6
            inds[j]["min"], inds[j]["max"] = lo, hi
        self._indicators = inds
        center_opt = self.opt.get("center") or radar_opt.get("center") or ["50%", "50%"]
        if not isinstance(center_opt, (list, tuple)):
            center_opt = [center_opt, center_opt]
        self._center = QPointF(
            rect.left()
            + _parse_pct(
                center_opt[0] if center_opt else "50%",
                rect.width(),
                rect.width() / 2,
            ),
            rect.top()
            + _parse_pct(
                center_opt[1] if len(center_opt) > 1 else "50%",
                rect.height(),
                rect.height() / 2,
            ),
        )
        half = min(rect.width(), rect.height()) / 2
        radius_opt = self.opt.get("radius")
        if radius_opt is None:
            radius_opt = radar_opt.get("radius")
        if isinstance(radius_opt, (list, tuple)):
            radius_opt = radius_opt[1] if len(radius_opt) > 1 else radius_opt[0]
        base = max(12.0, half - 34.0)
        self._radius = max(12.0, _parse_pct(radius_opt, base, base))
        base_idx = (
            self.chart.seriesRenderers.index(self)
            if self in self.chart.seriesRenderers
            else 0
        )
        for k, (name, vals) in enumerate(entries):
            pts = []
            for j in range(n):
                v = vals[j] if j < len(vals) else 0.0
                lo, hi = inds[j]["min"], inds[j]["max"]
                frac = _clamp((v - lo) / (hi - lo), 0.0, 1.0)
                theta = -math.pi / 2 + j / n * 2 * math.pi
                r = self._radius * frac
                pts.append(
                    QPointF(
                        self._center.x() + r * math.cos(theta),
                        self._center.y() + r * math.sin(theta),
                    )
                )
            self._polys.append(
                {
                    "name": name,
                    "values": vals,
                    "color": _series_palette_color(self.chart, base_idx + k),
                    "points": pts,
                }
            )

    def _ring_path(self, frac):
        n = len(self._indicators)
        path = QPainterPath()
        if str(self.opt.get("shape") or "polygon") == "circle":
            path.addEllipse(self._center, self._radius * frac, self._radius * frac)
            return path
        for j in range(n):
            theta = -math.pi / 2 + j / n * 2 * math.pi
            pt = QPointF(
                self._center.x() + self._radius * frac * math.cos(theta),
                self._center.y() + self._radius * frac * math.sin(theta),
            )
            if j == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        return path

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._indicators:
            return
        p.save()
        n = len(self._indicators)
        split = max(1, int(_to_float(self.opt.get("splitNumber"), 5)))
        c_grid = _text_color("color.border")
        c_axis = _text_color("color.border.strong")
        c_text = _text_color("color.text.secondary")
        # axisName / splitLine / axisLine（ECharts 键）
        radar_opt = getattr(self, "_radar_opt", None) or {}
        axis_name_opt = dict(
            self.opt.get("axisName") or radar_opt.get("axisName") or {}
        )
        split_line_opt = dict(self.opt.get("splitLine") or {})
        axis_line_opt = dict(self.opt.get("axisLine") or {})
        if not bool(axis_name_opt.get("show", True)):
            axis_name_opt["_hide"] = True
        if isinstance(axis_name_opt.get("color"), str) and axis_name_opt["color"]:
            c_text = parse_color(axis_name_opt["color"])
        if isinstance(split_line_opt.get("lineStyle"), dict):
            raw = split_line_opt["lineStyle"].get("color")
            if isinstance(raw, str) and raw:
                c_grid = parse_color(raw)
        if isinstance(axis_line_opt.get("lineStyle"), dict):
            raw = axis_line_opt["lineStyle"].get("color")
            if isinstance(raw, str) and raw:
                c_axis = parse_color(raw)
        font = _label_font(self, axis_name_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        # 圈环
        if bool(split_line_opt.get("show", True)):
            for k in range(1, split + 1):
                p.setPen(QPen(c_grid, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(self._ring_path(k / split))
        # 轴线 + 维度标签
        if bool(axis_line_opt.get("show", True)):
            for j in range(n):
                theta = -math.pi / 2 + j / n * 2 * math.pi
                outer = QPointF(
                    self._center.x() + self._radius * math.cos(theta),
                    self._center.y() + self._radius * math.sin(theta),
                )
                p.setPen(QPen(c_axis, 1))
                p.drawLine(self._center, outer)
        if not axis_name_opt.get("_hide"):
            for j, ind in enumerate(self._indicators):
                theta = -math.pi / 2 + j / n * 2 * math.pi
                lx = self._center.x() + (self._radius + 16) * math.cos(theta)
                ly = self._center.y() + (self._radius + 16) * math.sin(theta)
                p.setPen(c_text)
                p.drawText(
                    QRectF(lx - 48, ly - fm.height() / 2, 96, fm.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    ind["name"],
                )
        # 多边形系列（anim_t 由中心向外展开）
        area_opt = self.opt.get("areaStyle")
        opacity = 0.25
        if isinstance(area_opt, dict):
            opacity = _clamp(_to_float(area_opt.get("opacity"), 0.25), 0.0, 1.0)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        show_label = self.labelShown()
        for k, poly in enumerate(self._polys):
            pts = self._animated_polygon(poly, anim_t)
            qpoly = QPolygonF(pts)
            color = parse_color(self.itemColor(k, default=poly["color"]))
            alpha = self.itemOpacity(k)
            if hovered is not None:
                if k == hovered:
                    emphasis = self.emphasisColor(k)
                    color = emphasis if emphasis is not None else color.lighter(112)
                elif self.blursOtherItems():
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.35
            if area_opt is not None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(with_alpha(color, opacity * 255 * alpha))
                p.drawPolygon(qpoly)
            pen = QPen(color, 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(qpoly)
            if pts:
                p.drawLine(pts[-1], pts[0])
            p.setBrush(color)
            for pt in pts:
                p.drawEllipse(pt, 2.5, 2.5)
            if show_label:
                p.setPen(self.labelColor())
                for j, pt in enumerate(pts):
                    value = poly["values"][j] if j < len(poly["values"]) else 0.0
                    text = self.labelText(j, value)
                    p.drawText(
                        QRectF(pt.x() - 30, pt.y() - fm.height() - 2, 60, fm.height()),
                        Qt.AlignmentFlag.AlignCenter,
                        text,
                    )
        p.restore()

    def _animated_polygon(self, poly, anim_t):
        """多边形在给定动画进度下的顶点（``paint`` 与 ``hitTest`` 共用）。"""
        return [
            QPointF(
                self._center.x() + (pt.x() - self._center.x()) * anim_t,
                self._center.y() + (pt.y() - self._center.y()) * anim_t,
            )
            for pt in poly["points"]
        ]

    def _hit_info(self, index: int, poly: dict) -> dict:
        """命中信息：带逐维度行与数据项颜色（tooltip 靠它们区分数据源）。"""
        inds = self._indicators
        vals = poly["values"]
        rows = [
            (
                inds[j]["name"] if j < len(inds) else f"dim{j + 1}",
                vals[j] if j < len(vals) else 0.0,
            )
            for j in range(len(inds))
        ]
        name = poly["name"] or self.name
        return {
            "name": name,
            "value": list(vals),
            "series": self.name,
            "dataIndex": index,
            # 数据项颜色：tooltip 圆点与事件 params 都用它，拿系列色两条多边形会同色。
            "color": self.itemColor(index, default=poly["color"]),
            # 标题 = 数据项名（ECharts radar formatTooltip 的 header）
            "title": name,
            # 逐维度 (指标名, 值)：Tooltip 渲染成多行
            "rows": rows,
        }

    def hitTest(self, pos: QPointF):
        anim_t = self._anim_t
        # 重叠时取边界离光标最近的那个：z 序会让后画的多边形永远抢走命中。
        best = None
        best_dist = float("inf")
        for k in range(len(self._polys) - 1, -1, -1):
            poly = self._polys[k]
            if len(poly["points"]) < 3:
                continue
            pts = self._animated_polygon(poly, anim_t)
            if not QPolygonF(pts).containsPoint(pos, Qt.FillRule.OddEvenFill):
                continue
            d = _dist_to_polygon_edge(pos, pts)
            if d < best_dist:
                best_dist = d
                best = (k, poly)
        if best is None:
            return None
        return self._hit_info(best[0], best[1])
