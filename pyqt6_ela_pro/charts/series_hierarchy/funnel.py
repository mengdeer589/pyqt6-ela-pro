"""漏斗图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPen,
    QPolygonF,
)

from .._tokens import T
from .._utils import ON_FILL_WHITE, clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import parse_color
from ..axes import formatValue
from ..core import SeriesRenderer, formatLabelTemplate
from ._shared import _label_font, _parse_named_values, _series_palette_color


class FunnelSeriesRenderer(SeriesRenderer):
    """漏斗图（梯形层叠）。

    option 键：
    - ``data``: [{"name","value"}, ...]；
    - ``sort``: "descending"（默认）/ "ascending" / "none"；
    - ``gap``: 层间距 px（默认 2）；
    - ``minSize``: 最小宽度占比（默认 0.12，相对最大宽度）；
    - ``label``: {"show": True, "position": "outer|inside", "fontSize": px}；
    - ``orient``: "vertical"（当前仅支持纵向，自上而下）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._layers = []  # [dict(name,value,color,poly=QPolygonF)]
        #: 图例隐藏的数据项名（漏斗图例按数据项开关）
        self._hidden_items = set()

    def setHiddenItems(self, names) -> None:
        """设置被图例隐藏的数据项（按名称）。"""
        self._hidden_items = {str(n) for n in (names or [])}

    def legendItems(self) -> list:
        """漏斗图例条目 = 数据项名（不是系列名）。"""
        out = []
        for index, item in enumerate(self.data()):
            if isinstance(item, dict):
                name = str(item.get("name") or "")
            else:
                name = str(item or "")
            if not name:
                continue
            out.append(
                (
                    name,
                    self.itemColor(
                        index, default=_series_palette_color(self.chart, index)
                    ),
                )
            )
        return out

    def layout(self, rect: QRectF) -> None:
        self._layers = []
        raw_entries = [
            entry
            for entry in _parse_named_values(self.data())
            if entry[1] not in self._hidden_items
        ]
        if not raw_entries:
            return
        # 保留原始 data 下标（负值不再被删，否则后续项的 itemStyle 整体前移）
        entries = list(raw_entries)
        sort = str(self.opt.get("sort") or "descending")
        if sort == "descending":
            entries.sort(key=lambda e: e[2], reverse=True)
        elif sort == "ascending":
            entries.sort(key=lambda e: e[2])
        # "none" 保持原顺序
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        self._label_pos = str(label_opt.get("position") or "outer")
        outside = self._label_pos in ("outer", "left", "right")
        margin_l = 96.0 if (label_show and outside) else 12.0
        margin_r = 84.0 if (label_show and outside) else 12.0
        n = len(entries)
        gap = _clamp(_to_float(self.opt.get("gap"), 2.0), 0.0, 24.0)
        h = (rect.height() - gap * (n - 1)) / n
        if h <= 1:
            return
        vmax = max((max(value, 0.0) for _, _, value in entries), default=0.0) or 1.0
        min_frac = _clamp(_to_float(self.opt.get("minSize"), 0.12), 0.0, 1.0)
        max_w = max(20.0, rect.width() - margin_l - margin_r)
        cx = rect.left() + margin_l + max_w / 2
        # ECharts funnelAlign：left / center（默认）/ right
        align = str(self.opt.get("funnelAlign") or "center")

        def width_of(v):
            return max_w * (min_frac + (1 - min_frac) * max(v, 0.0) / vmax)

        for slot, (data_index, name, v) in enumerate(entries):
            top_w = width_of(v)
            # 最后一层收到 ``minSize``（默认 12% 宽），不是「与上一层同宽」——
            # 原式 ``width_of(v) * min_frac / max(min_frac, 1e-6)`` 在
            # min_frac>0 时恒等于 width_of(v)，退化成矩形。
            bot_w = (
                width_of(entries[slot + 1][2])
                if slot + 1 < n
                else max_w * min_frac
            )
            y0 = rect.top() + slot * (h + gap)
            y1 = y0 + h
            if align == "left":
                left_edge = rect.left() + margin_l
                x0l, x0r = left_edge, left_edge + top_w
                x1l, x1r = left_edge, left_edge + bot_w
                layer_cx = left_edge + top_w / 2
            elif align == "right":
                right_edge = rect.right() - margin_r
                x0l, x0r = right_edge - top_w, right_edge
                x1l, x1r = right_edge - bot_w, right_edge
                layer_cx = right_edge - top_w / 2
            else:
                x0l, x0r = cx - top_w / 2, cx + top_w / 2
                x1l, x1r = cx - bot_w / 2, cx + bot_w / 2
                layer_cx = cx
            poly = QPolygonF(
                [
                    QPointF(x0l, y0),
                    QPointF(x0r, y0),
                    QPointF(x1r, y1),
                    QPointF(x1l, y1),
                ]
            )
            border_color, border_w = self.itemBorder(data_index)
            self._layers.append(
                {
                    "index": data_index,
                    "name": name,
                    "value": v,
                    "poly": poly,
                    "color": self.itemColor(
                        data_index, default=_series_palette_color(self.chart, slot)
                    ),
                    "border": (border_color, border_w),
                    "cy": (y0 + y1) / 2,
                    "left": min(x0l, x1l),
                    "right": max(x0r, x1r),
                    "layer_cx": layer_cx,
                }
            )

    def _funnel_label(self, layer, pct: str) -> str:
        """funnel 标签文本：``label.formatter`` 优先，缺省「名称 值 (百分比)」。"""
        formatter = self.labelOption().get("formatter")
        params = {
            "a": self.name,
            "b": layer["name"],
            "c": layer["value"],
            "d": pct,
            "name": layer["name"],
            "value": layer["value"],
            "percent": pct,
            "series": self.name,
            "dataIndex": layer["index"],
        }
        if callable(formatter):
            try:
                text = formatter(params)
                if text is not None:
                    return str(text)
            except Exception:
                pass
        elif isinstance(formatter, str):
            text = formatLabelTemplate(formatter, params)
            if text is not None:
                return text
        name = layer["name"] or formatValue(layer["value"])
        return f"{name} {formatValue(layer['value'])} ({pct})"

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._layers:
            return
        p.save()
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        pos = str(label_opt.get("position") or "outer")
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        total = sum(layer["value"] for layer in self._layers) or 1.0
        border = QColor(T("color.bg.base"))
        c_text = self.labelColor()
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        # 入场动画：自上而下逐层显现 + 宽度展开
        n = len(self._layers)
        for i, layer in enumerate(self._layers):
            local_t = _clamp(anim_t * n - i, 0.0, 1.0)
            if local_t <= 0:
                continue
            poly = layer["poly"]
            if local_t < 1.0:
                scaled = QPolygonF(
                    [
                        QPointF(
                            layer["poly"][k].x() * local_t
                            + (layer["left"] + layer["right"]) / 2 * (1 - local_t),
                            layer["poly"][k].y(),
                        )
                        for k in range(4)
                    ]
                )
                poly = scaled
            color = parse_color(layer["color"])
            alpha = self.itemOpacity(layer["index"])
            if hovered is not None:
                if layer["index"] == hovered:
                    emphasis = self.emphasisColor(layer["index"])
                    color = emphasis if emphasis is not None else color.lighter(112)
                elif self.blursOtherItems():
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.35
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            border_color, border_w = layer.get("border", (None, 0))
            if border_color is not None and border_w > 0:
                p.setPen(QPen(border_color, border_w))
            else:
                p.setPen(QPen(border, 1.2))
            p.setBrush(color)
            p.drawPolygon(poly)
            if not label_show or local_t < 0.6:
                continue
            name = layer["name"] or formatValue(layer["value"])
            value_text = formatValue(layer["value"])
            pct = formatValue(round(layer["value"] / total * 100, 1)) + "%"
            full = self._funnel_label(layer, pct)
            cy = layer["cy"]
            left, right = layer["left"], layer["right"]
            if pos in ("inside", "insideLeft", "insideRight"):
                p.setPen(QColor(ON_FILL_WHITE))
                if pos == "inside":
                    align = Qt.AlignmentFlag.AlignCenter
                    rect = QRectF(left, cy - fm.height() / 2, right - left, fm.height())
                elif pos == "insideLeft":
                    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    rect = QRectF(
                        left + 8,
                        cy - fm.height() / 2,
                        max(8.0, right - left - 16),
                        fm.height(),
                    )
                else:  # insideRight
                    align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    rect = QRectF(
                        left + 8,
                        cy - fm.height() / 2,
                        max(8.0, right - left - 16),
                        fm.height(),
                    )
                p.drawText(rect, align, full)
            elif pos == "left":
                p.setPen(c_text)
                p.drawText(
                    QRectF(0, cy - fm.height() / 2, max(0.0, left - 8), fm.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    full,
                )
            elif pos == "right":
                p.setPen(c_text)
                p.drawText(
                    QRectF(right + 8, cy - fm.height() / 2, 140, fm.height()),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    full,
                )
            elif pos == "top":
                p.setPen(c_text)
                p.drawText(
                    QRectF(
                        left,
                        cy - fm.height() / 2 - fm.height() - 2,
                        max(8.0, right - left),
                        fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                    full,
                )
            elif pos == "bottom":
                p.setPen(c_text)
                p.drawText(
                    QRectF(
                        left,
                        cy + fm.height() / 2 + 2,
                        max(8.0, right - left),
                        fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    full,
                )
            else:  # outer（默认，引擎扩展）：名称居左、数值居右
                p.setPen(c_text)
                p.drawText(
                    QRectF(0, cy - fm.height() / 2, left - 8, fm.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    name,
                )
                p.drawText(
                    QRectF(right + 8, cy - fm.height() / 2, 110, fm.height()),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"{value_text} ({pct})",
                )
        p.restore()

    def hitTest(self, pos: QPointF):
        if self._anim_t < 1.0:
            # 入场动画按层展开，终态几何尚未画出：命中会指到空白处。
            return None
        for layer in self._layers:
            if layer["poly"].containsPoint(pos, Qt.FillRule.OddEvenFill):
                return {
                    "name": layer["name"],
                    "value": layer["value"],
                    "series": self.name,
                    "dataIndex": layer["index"],
                }
        return None
