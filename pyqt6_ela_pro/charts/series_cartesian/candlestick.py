"""K 线系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._tokens import T
from .._utils import to_float as _to_float
from .._utils import resolve_color_option, warn_once, with_alpha
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


class CandlestickSeriesRenderer(SeriesRenderer):
    """K线（OHLC）。数据项：[开, 收, 最低, 最高]（或 {"value": [...]}）。
    配色遵循 ECharts 语义：``itemStyle.color`` / ``color0`` 为涨 / 跌，
    跌用 ``color.success``。``barWidth``：实体宽 px（缺省 band 的 60%，上限 24）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._items = []  # [dict(cx, open, close, low, high, w, x, index, prev)]

    def layout(self, rect: QRectF) -> None:
        self._items = []
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            warn_once(
                "candlestick-coord",
                f"candlestick 只支持 grid 坐标系（当前 {getattr(coord, 'kind', '?')}），已跳过",
            )
            return
        _fix_value_axis(coord.y_axis, self.chart, self.opt, "y")
        band = coord.x_axis.bandWidth(coord.plot.left(), coord.plot.right())
        if band <= 0:
            band = coord.plot.width() / max(1, len(self.data()))
        w = _to_float(self.opt.get("barWidth"), None)
        w = max(3.0, min(w, band * 0.9)) if w else min(band * 0.6, 24.0)
        prev = self.prev_data if isinstance(self.prev_data, list) else None
        for i, item in enumerate(self.data()):
            nums = _datum_list(item, 4)
            if not nums or len(nums) < 4:
                continue
            o, c, lo, hi = nums[0], nums[1], nums[2], nums[3]
            x = i  # OHLC 数组不含类别，按下标对位 xAxis 类别
            cx = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
            prev_nums = None
            if prev is not None and i < len(prev):
                prev_nums = _datum_list(prev[i], 4)
            self._items.append(
                {
                    "cx": cx,
                    "open": o,
                    "close": c,
                    "low": lo,
                    "high": hi,
                    "w": w,
                    "x": x,
                    "index": i,
                    "prev": prev_nums[:4]
                    if prev_nums and len(prev_nums) >= 4
                    else None,
                }
            )

    def _up_color(self):
        style = self.itemStyle()
        c = style.get("color") or style.get("borderColor")
        color = resolve_color_option(c, self.chart) if c else QColor()
        return color if color.isValid() else QColor(T("color.danger", self.chart))

    def _down_color(self):
        style = self.itemStyle()
        c = style.get("color0") or style.get("borderColor0")
        color = resolve_color_option(c, self.chart) if c else QColor()
        return color if color.isValid() else QColor(T("color.success", self.chart))

    def _item_color(self, index, rising: bool):
        """涨跌色：数据项 ``itemStyle.color`` / ``color0`` 覆盖系列级。"""
        style = self._itemStyleFor(index)
        keys = ("color", "borderColor") if rising else ("color0", "borderColor0")
        explicit = any(
            isinstance(style.get(key), str) and style.get(key) for key in keys
        )
        if not explicit:
            visual = self.visualColor(index)
            if visual is not None:
                return visual
        for key in keys:
            raw = style.get(key)
            if isinstance(raw, str) and raw:
                color = resolve_color_option(raw, self.chart)
                if color.isValid():
                    return color
        return self._up_color() if rising else self._down_color()

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
            if it["prev"] is not None and anim_t < 1.0:
                o, c, lo, hi = (
                    _lerp(it["prev"][k], v, anim_t)
                    for k, v in enumerate(
                        (it["open"], it["close"], it["low"], it["high"])
                    )
                )
            elif anim_t < 1.0:
                # 入场：自开盘价向四周生长
                o = it["open"]
                c = _lerp(it["open"], it["close"], anim_t)
                lo = _lerp(it["open"], it["low"], anim_t)
                hi = _lerp(it["open"], it["high"], anim_t)
            else:
                o, c, lo, hi = it["open"], it["close"], it["low"], it["high"]
            yo = ax.map(o, coord.plot.bottom(), coord.plot.top())
            yc = ax.map(c, coord.plot.bottom(), coord.plot.top())
            yl = ax.map(lo, coord.plot.bottom(), coord.plot.top())
            yh = ax.map(hi, coord.plot.bottom(), coord.plot.top())
            rising = c >= o
            color = self._item_color(it["index"], rising)
            border_color, border_w = self.itemBorder(it["index"])
            if not rising:
                down_width = self._itemStyleFor(it["index"]).get(
                    "borderWidth0", self.itemStyle().get("borderWidth0")
                )
                if down_width is not None:
                    try:
                        border_w = max(0.0, float(down_width))
                    except (TypeError, ValueError, OverflowError):
                        pass
            alpha = self.itemOpacity(it["index"])
            color, alpha, border_color, border_w = self.stateStyle(
                it["index"], hovered, color, alpha, border_color, border_w
            )
            stroke = border_color or color
            cx, w = it["cx"], it["w"]
            # 影线
            p.setPen(QPen(with_alpha(color, 255 * alpha), 1.2))
            p.drawLine(QPointF(cx, yh), QPointF(cx, yl))
            # 实体
            body = QRectF(cx - w / 2, min(yo, yc), w, max(1.0, abs(yc - yo)))
            p.setPen(QPen(with_alpha(stroke, 255 * alpha), border_w or 1.0))
            p.setBrush(with_alpha(color, 255 * alpha))
            p.drawRect(body)
            if show_label and label_fm is not None:
                text = self.labelText(
                    it["index"], [o, c, lo, hi], self.nameAtIndex(it["index"])
                )
                if text:
                    top_y = max(yh, yl) if label_position == "bottom" else min(yh, yl)
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
            # 实体从 open 向 high/low 生长：终态影线位置此刻还是空白。
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
            yl = ax.map(it["low"], coord.plot.bottom(), coord.plot.top())
            yh = ax.map(it["high"], coord.plot.bottom(), coord.plot.top())
            distance = abs(pos.x() - it["cx"])
            if (
                distance <= max(it["w"] / 2, 4.0) + 2
                and min(yh, yl) - 3 <= pos.y() <= max(yh, yl) + 3
                and (best_d is None or distance < best_d)
            ):
                best_d = distance
                best = it
        if best is None:
            return None
        return {
            "name": _axis_label(coord.x_axis, best["x"]),
            "value": [best["open"], best["close"], best["low"], best["high"]],
            "color": self._item_color(best["index"], best["close"] >= best["open"]),
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
                    yc = coord.y_axis.map(
                        it["close"], coord.plot.bottom(), coord.plot.top()
                    )
                    pos = QPointF(it["cx"], yc)
                name = (
                    _axis_label(coord.x_axis, it["x"])
                    if isinstance(coord, GridCoord)
                    else formatValue(it["x"])
                )
                return {
                    "name": name,
                    "value": it["close"],
                    "color": self._item_color(it["index"], it["close"] >= it["open"]),
                    "series": self.name,
                    "dataIndex": it["index"],
                    "pos": pos,
                }
        return None
