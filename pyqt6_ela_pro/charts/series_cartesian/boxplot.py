"""箱线图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._utils import to_float as _to_float
from .._utils import with_alpha, warn_once
from ..axes import GridCoord, formatValue
from ..core import SeriesRenderer
from ._shared import (
    _axis_label,
    _datum_list,
    _fix_value_axis,
    _label_placement,
    _lerp,
    label_align,
    label_anchor_offset,
    label_rotate,
    paint_label_at,
)


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
            warn_once(
                "boxplot-coord",
                f"boxplot 只支持 grid 坐标系（当前 {getattr(coord, 'kind', '?')}），已跳过",
            )
            return
        _fix_value_axis(coord.y_axis, self.chart, self.opt, "y")
        band = coord.x_axis.bandWidth(coord.plot.left(), coord.plot.right())
        if band <= 0:
            band = coord.plot.width() / max(1, len(self.data()))
        w = _to_float(self.opt.get("barWidth"), None)
        w = max(4.0, min(w, band * 0.9)) if w else min(band * 0.5, 28.0)
        for i, item in enumerate(self.data()):
            nums = _datum_list(item, 5)
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
        p.save()
        self._label_rects = []
        p.setClipRect(coord.plot)
        show_label = self.labelShown()
        label_opt = self.labelOption()
        label_font = self.labelFont() if show_label else None
        label_fm = QFontMetricsF(label_font) if label_font is not None else None
        label_position = str(label_opt.get("position") or "top")
        label_distance = _to_float(label_opt.get("distance"), 4.0)
        label_rotate_angle = label_rotate(label_opt)
        label_align_flag = label_align(label_opt)
        if show_label:
            p.setFont(label_font)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for it in self._items:
            # 逐项 itemStyle：命中色 / tooltip 与绘制同一个真源
            box_color = self.dataColor(it["index"], default=self.color())
            border_color, border_w = self.itemBorder(it["index"])
            alpha = self.itemOpacity(it["index"])
            box_color, alpha, border_color, border_w = self.stateStyle(
                it["index"], hovered, box_color, alpha, border_color, border_w
            )
            stroke = border_color or box_color
            stroke_w = max(0.5, border_w or 1.4)
            explicit = self.itemStyle().get("color") or self._itemStyleFor(
                it["index"]
            ).get("color")
            fill = with_alpha(box_color, (255 * 0.35 if explicit else 60) * alpha)
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
            if show_label and label_fm is not None:
                text = self.labelText(
                    it["index"], it["vals"], self.nameAtIndex(it["index"])
                )
                if text:
                    top_y = (
                        max(y_max, y_min)
                        if label_position == "bottom"
                        else min(y_max, y_min)
                    )
                    anchor, rect = _label_placement(
                        QPointF(cx, top_y),
                        text,
                        label_fm,
                        label_position,
                        label_distance,
                    )
                    if label_position in ("top", "bottom", "inside"):
                        offset = label_anchor_offset(label_align_flag, rect.width())
                        if offset:
                            anchor = QPointF(anchor.x() + offset, anchor.y())
                    p.setPen(self.labelColorFor(it["index"]))
                    hit = paint_label_at(
                        p,
                        anchor,
                        text,
                        label_fm,
                        label_rotate_angle,
                        series=self,
                        index=it["index"],
                        color=self.labelColorFor(it["index"]),
                    )
                    if hit.isNull():
                        continue
                    self._label_rects.append(
                        (it["index"], hit.adjusted(-2, -2, 2, 2), text)
                    )
        p.restore()

    def hitTest(self, pos: QPointF):
        if self._anim_t < 1.0:
            # 箱体从 mid 向两端生长：终态 high/low 位置此刻还是空白。
            return None
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        ax = coord.y_axis
        if not coord.plot.adjusted(-2, -2, 2, 2).contains(pos):
            return None
        best = None
        best_d = None
        for it in self._items:
            y_min = ax.map(it["vals"][0], coord.plot.bottom(), coord.plot.top())
            y_max = ax.map(it["vals"][4], coord.plot.bottom(), coord.plot.top())
            distance = abs(pos.x() - it["cx"])
            if (
                distance <= it["w"] / 2 + 3
                and min(y_min, y_max) - 3 <= pos.y() <= max(y_min, y_max) + 3
                and (best_d is None or distance < best_d)
            ):
                best_d = distance
                best = it
        if best is None:
            return None
        return {
            "name": _axis_label(coord.x_axis, best["x"]),
            "value": best["vals"],
            "color": self.dataColor(best["index"]),
            "series": self.name,
            "dataIndex": best["index"],
        }

    def valueAtIndex(self, index: int):
        coord = self.chart.coordFor(self.opt)
        idx = index
        for it in self._items:
            if it["index"] == idx:
                pos = None
                if isinstance(coord, GridCoord):
                    y_med = coord.y_axis.map(
                        it["vals"][2], coord.plot.bottom(), coord.plot.top()
                    )
                    pos = QPointF(it["cx"], y_med)
                name = (
                    _axis_label(coord.x_axis, it["x"])
                    if isinstance(coord, GridCoord)
                    else formatValue(it["x"])
                )
                return {
                    "name": name,
                    "value": it["vals"][2],
                    "color": self.dataColor(it["index"]),
                    "series": self.name,
                    "dataIndex": it["index"],
                    "pos": pos,
                }
        return None
