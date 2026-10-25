"""K 线系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPen,
)

from .._tokens import T
from .._utils import to_float as _to_float
from .._utils import parse_color
from ..axes import GridCoord
from ..core import SeriesRenderer
from ._shared import _axis_label, _datum_list, _fix_value_axis, _lerp


class CandlestickSeriesRenderer(SeriesRenderer):
    """K线（OHLC）。数据项：[开, 收, 最低, 最高]（或 {"value": [...]}）。

    配色遵循 ECharts 默认（红涨绿跌）：``itemStyle.color``（涨）/ ``color0``（跌）、
    ``itemStyle.borderColor`` / ``borderColor0``；缺省涨用 ``color.danger``、
    跌用 ``color.success``（与库主题语义一致）。

    option 键：``barWidth``（实体宽 px，缺省为 band 的 60%，上限 24）；
    setOption 同长度数据逐值插值。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._items = []  # [dict(cx, open, close, low, high, w, x, index, prev)]

    # -- 布局 -------------------------------------------------------------
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
        w = max(3.0, min(w, band * 0.9)) if w else min(band * 0.6, 24.0)
        prev = self.prev_data if isinstance(self.prev_data, list) else None
        for i, item in enumerate(self.data()):
            nums = _datum_list(item)
            if not nums or len(nums) < 4:
                continue
            o, c, lo, hi = nums[0], nums[1], nums[2], nums[3]
            x = i  # OHLC 数组不含类别，按下标对位 xAxis 类别
            cx = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
            prev_nums = None
            if prev is not None and i < len(prev):
                prev_nums = _datum_list(prev[i])
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

    # -- 配色（ECharts itemStyle 语义：color=涨 / color0=跌） ---------------
    def _up_color(self):
        style = self.itemStyle()
        c = style.get("color") or style.get("borderColor")
        return parse_color(c) if isinstance(c, str) and c else QColor(T("color.danger"))

    def _down_color(self):
        style = self.itemStyle()
        c = style.get("color0") or style.get("borderColor0")
        return (
            parse_color(c) if isinstance(c, str) and c else QColor(T("color.success"))
        )

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._items:
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        ax = coord.y_axis
        up, down = self._up_color(), self._down_color()
        p.save()
        p.setClipRect(coord.plot)
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
            color = up if rising else down
            cx, w = it["cx"], it["w"]
            # 影线
            p.setPen(QPen(color, 1.2))
            p.drawLine(QPointF(cx, yh), QPointF(cx, yl))
            # 实体
            body = QRectF(cx - w / 2, min(yo, yc), w, max(1.0, abs(yc - yo)))
            p.setPen(QPen(color, 1))
            p.setBrush(color)
            p.drawRect(body)
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        ax = coord.y_axis
        for it in self._items:
            yl = ax.map(it["low"], coord.plot.bottom(), coord.plot.top())
            yh = ax.map(it["high"], coord.plot.bottom(), coord.plot.top())
            if (
                abs(pos.x() - it["cx"]) <= max(it["w"] / 2, 4.0) + 2
                and yh - 3 <= pos.y() <= yl + 3
            ):
                return {
                    "name": _axis_label(coord.x_axis, it["x"]),
                    "value": [it["open"], it["close"], it["low"], it["high"]],
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
                    yc = coord.y_axis.map(
                        it["close"], coord.plot.bottom(), coord.plot.top()
                    )
                    pos = QPointF(it["cx"], yc)
                return {
                    "name": _axis_label(coord.x_axis, it["x"]),
                    "value": it["close"],
                    "series": self.name,
                    "pos": pos,
                }
        return None
