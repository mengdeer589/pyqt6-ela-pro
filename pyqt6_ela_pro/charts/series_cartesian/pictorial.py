"""象形柱系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPainter,
    QPainterPath,
)

from .._utils import to_float as _to_float
from ..axes import GridCoord
from .bar import BarSeriesRenderer


class PictorialBarSeriesRenderer(BarSeriesRenderer):
    """象形柱图：以小图形（symbol）填充柱体。

    option 键：
    - ``symbol``: "rect" | "circle" | "pin"（默认 "rect"）；
    - ``symbolRepeat``: True 时按 symbolSize 沿柱方向重复堆叠小图形直至
      柱顶；整数时为固定重复次数（在柱长内均布）；
    - ``symbolSize``: 数值（边长）或 [宽, 高]。
    不支持 stack（同名槽位逻辑退化为各占一槽）。
    """

    def _stack_bases(self):  # 象形柱不堆叠
        return {}, {}

    def _symbol_size(self):
        ss = self.opt.get("symbolSize", 10)
        if isinstance(ss, (list, tuple)) and ss:
            w = _to_float(ss[0], 10.0)
            h = _to_float(ss[1], w) if len(ss) > 1 else w
            return max(2.0, w), max(2.0, h)
        v = _to_float(ss, 10.0)
        return max(2.0, v), max(2.0, v)

    def _draw_symbol(self, p, cx, cy, w, h):
        """以 (cx, cy) 为中心绘制一个小图形（w×h 外接框）。"""
        kind = str(self.opt.get("symbol") or "rect")
        r = min(w, h) / 2
        if kind == "circle":
            p.drawEllipse(QPointF(cx, cy), w / 2, h / 2)
        elif kind == "pin":
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy - h * 0.12), r, r)
            path.moveTo(cx - r * 0.55, cy + h * 0.12)
            path.lineTo(cx, cy + h * 0.52)
            path.lineTo(cx + r * 0.55, cy + h * 0.12)
            path.closeSubpath()
            p.drawPath(path)
        else:  # rect
            p.drawRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), 2, 2)

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._bars:
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        val_axis = coord.x_axis if self._horizontal else coord.y_axis
        sw, sh = self._symbol_size()
        repeat = self.opt.get("symbolRepeat", False)
        p.save()
        p.setClipRect(coord.plot)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color())
        for bar in self._bars:
            y_t = self._animated_value(bar, anim_t)
            v1 = bar["v0"] + y_t
            if self._horizontal:
                pa = val_axis.map(bar["v0"], coord.plot.left(), coord.plot.right())
                pb = val_axis.map(v1, coord.plot.left(), coord.plot.right())
                along, cross = sw, sh
            else:
                pa = val_axis.map(bar["v0"], coord.plot.bottom(), coord.plot.top())
                pb = val_axis.map(v1, coord.plot.bottom(), coord.plot.top())
                along, cross = sh, sw
            direction = 1.0 if pb >= pa else -1.0
            total = abs(pb - pa)
            if total <= 0:
                continue
            if repeat is True:
                n = max(1, int(total // max(1.0, along)))
                offsets = [(k + 0.5) * along for k in range(n)]
                offsets = [o for o in offsets if o <= total] or [total / 2]
            elif repeat:
                n = max(1, int(_to_float(repeat, 1)))
                offsets = [(k + 0.5) * total / n for k in range(n)]
            else:
                offsets = [max(along / 2, total - along / 2)]
            for off in offsets:
                d = pa + direction * off
                if self._horizontal:
                    self._draw_symbol(p, d, bar["center"], along, cross)
                else:
                    self._draw_symbol(p, bar["center"], d, cross, along)
        p.restore()
