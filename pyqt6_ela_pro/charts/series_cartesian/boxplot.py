"""箱线图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QPainter,
    QPen,
)

from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_color
from ..axes import GridCoord, formatValue
from ..core import SeriesRenderer
from ._shared import _axis_label, _datum_list, _fix_value_axis, _lerp


class BoxplotSeriesRenderer(SeriesRenderer):
    """箱线图。数据项：[min, Q1, 中位, Q3, max]（或 {"value": [...]}）。

    ``barWidth``：箱体宽 px（缺省 band 的 50%，上限 28）；``itemStyle`` 的
    ``color`` / ``borderColor`` / ``borderWidth`` 控制箱体填充与描边。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._items = []  # [dict(cx, w, vals=[5], x, index)]

    def layout(self, rect: QRectF) -> None:
        self._items = []
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        _fix_value_axis(coord.y_axis, self.chart, self.opt, "y")
        band = coord.x_axis.bandWidth(coord.plot.left(), coord.plot.right())
        if band <= 0:
            band = coord.plot.width() / max(1, len(self.data()))
        w = _to_float(self.opt.get("barWidth"), None)
        w = max(4.0, min(w, band * 0.9)) if w else min(band * 0.5, 28.0)
        for i, item in enumerate(self.data()):
            nums = _datum_list(item)
            if not nums or len(nums) < 5:
                continue
            x = i  # 五元数组不含类别，按下标对位 xAxis 类别
            cx = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
            self._items.append({"cx": cx, "w": w, "vals": nums[:5], "x": x, "index": i})

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._items:
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        ax = coord.y_axis
        color = self.color()
        style = self.itemStyle()
        fill_raw = style.get("color")
        stroke_raw = style.get("borderColor")
        stroke = (
            parse_color(stroke_raw)
            if isinstance(stroke_raw, str) and stroke_raw
            else color
        )
        try:
            stroke_w = max(0.5, float(style.get("borderWidth", 1.4)))
        except (TypeError, ValueError, OverflowError):
            stroke_w = 1.4
        fill = parse_color(fill_raw) if isinstance(fill_raw, str) and fill_raw else None
        if fill is not None:
            fill.setAlphaF(fill.alphaF() * 0.35)
        else:
            fill = with_alpha(color, 60)
        p.save()
        p.setClipRect(coord.plot)
        for it in self._items:
            vmin, q1, med, q3, vmax = it["vals"]
            mid = (q1 + q3) / 2
            if anim_t < 1.0:  # 入场：自箱体中线向两端展开
                vmin = _lerp(mid, vmin, anim_t)
                vmax = _lerp(mid, vmax, anim_t)
                q1 = _lerp(mid, q1, anim_t)
                q3 = _lerp(mid, q3, anim_t)
                med = _lerp(mid, med, anim_t)
            y_min = ax.map(vmin, coord.plot.bottom(), coord.plot.top())
            y_q1 = ax.map(q1, coord.plot.bottom(), coord.plot.top())
            y_med = ax.map(med, coord.plot.bottom(), coord.plot.top())
            y_q3 = ax.map(q3, coord.plot.bottom(), coord.plot.top())
            y_max = ax.map(vmax, coord.plot.bottom(), coord.plot.top())
            cx, w = it["cx"], it["w"]
            # 须线 + 端帽
            p.setPen(QPen(stroke, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(cx, y_max), QPointF(cx, y_min))
            p.drawLine(QPointF(cx - w / 4, y_min), QPointF(cx + w / 4, y_min))
            p.drawLine(QPointF(cx - w / 4, y_max), QPointF(cx + w / 4, y_max))
            # 箱体
            box = QRectF(cx - w / 2, min(y_q1, y_q3), w, max(1.0, abs(y_q3 - y_q1)))
            p.setPen(QPen(stroke, stroke_w))
            p.setBrush(fill)
            p.drawRect(box)
            # 中位线
            p.setPen(QPen(stroke, 2))
            p.drawLine(QPointF(cx - w / 2, y_med), QPointF(cx + w / 2, y_med))
        p.restore()

    def hitTest(self, pos: QPointF):
        if self._anim_t < 1.0:
            # 箱体从 mid 向两端生长：终态 high/low 位置此刻还是空白。
            return None
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        ax = coord.y_axis
        for it in self._items:
            y_min = ax.map(it["vals"][0], coord.plot.bottom(), coord.plot.top())
            y_max = ax.map(it["vals"][4], coord.plot.bottom(), coord.plot.top())
            if (
                abs(pos.x() - it["cx"]) <= it["w"] / 2 + 3
                and y_max - 3 <= pos.y() <= y_min + 3
            ):
                return {
                    "name": formatValue(it["x"]),
                    "value": it["vals"],
                    "series": self.name,
                    "dataIndex": it["index"],
                }
        return None

    def valueAtIndex(self, index: int):
        coord = self.chart.coordFor(self.opt)
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        for it in self._items:
            if it["index"] == idx:
                pos = None
                if isinstance(coord, GridCoord):
                    y_med = coord.y_axis.map(
                        it["vals"][2], coord.plot.bottom(), coord.plot.top()
                    )
                    pos = QPointF(it["cx"], y_med)
                return {
                    "name": _axis_label(coord.x_axis, it["x"]),
                    "value": it["vals"][2],
                    "series": self.name,
                    "pos": pos,
                }
        return None
