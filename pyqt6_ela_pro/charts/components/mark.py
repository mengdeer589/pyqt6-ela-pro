"""markPoint / markLine / markArea 组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen

from .._tokens import T
from .._symbol import drawSymbol
from .._utils import (
    dist_point_segment,
    merged_text_style,
    parse_color,
    resolve_color_option,
    text_italic,
    text_on_fill,
    text_weight,
    warn_once,
)
from .._utils import to_float as _to_float
from ..axes import (
    CalendarCoord,
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
    chartFont,
    formatValue,
)
from ..core._shared import parseDataPoint
from ..models import OptionModel


class _SeriesMarkBase:
    """markPoint / markLine / markArea 的公共基类。
    core 重建时对每个含同名键的 series 注入 ``comp.series_opt``；构造期它尚未
    注入，所以系列 / 坐标解析一律推迟到 layout / paint。
    """

    optionKey = ""

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = opt if isinstance(opt, OptionModel) else dict(opt or {})
        #: 所属系列 option（core 注入；顶层实例化为 None）
        self.series_opt = None

    def _renderer(self):
        """所属系列的渲染器（找不到返回 None）。"""
        chart = self.chart
        s = getattr(self, "series_opt", None)
        if s is None:
            return None
        series_opts = getattr(chart, "_option", {}).get("series") or []
        idx = None
        for i, d in enumerate(series_opts):
            if d is s:
                idx = i
                break
        if idx is not None:
            for r in chart.seriesRenderers:
                if getattr(r, "_series_index", None) == idx:
                    return r
        name = str(s.get("name") or (f"series{idx}" if idx is not None else ""))
        matches = [r for r in chart.seriesRenderers if r.name == name]
        if len(matches) == 1:
            return matches[0]
        for r in chart.seriesRenderers:  # 兜底：字典相等匹配
            if r.opt == s:
                return r
        return None

    def _coord(self):
        """所属系列的坐标系（默认主坐标系）。"""
        s = getattr(self, "series_opt", None) or {}
        return self.chart.coordFor(s)

    def _datum_at(self, index):
        """取系列第 ``index`` 个数据项的 ``(x, y)``（越过越界 / 空值返回 None）。"""
        r = self._renderer()
        if r is None or not isinstance(index, int):
            return None
        data = r.data()
        if not (0 <= index < len(data)):
            return None
        x, y = parseDataPoint(data[index], index)
        if y is None:
            return None
        return x, y

    def _color(self) -> QColor:
        """标注主色：跟随系列色（无系列时取主题主色）。"""
        r = self._renderer()
        if r is not None:
            return r.color()
        return QColor(T("color.primary", self.chart))

    def _visible(self) -> bool:
        r = self._renderer()
        return r is not None and r.visible

    def _label_option(self, item: dict) -> dict:
        """标注标签 option：系列级 ``label`` 叠加项级 ``label``（返回原始键）。"""
        base = self.opt.get("label")
        base = dict(base) if isinstance(base, dict) else {}
        item_label = item.get("label") if isinstance(item, dict) else None
        if isinstance(item_label, dict):
            base.update(item_label)
        return base

    def _label_style(self, item: dict) -> dict:
        """标注标签的字号 / 颜色 / 字重（含顶层 ``textStyle`` 兜底）。"""
        return merged_text_style(self.chart, self._label_option(item))

    def _label_font(self, style: dict):
        return chartFont(
            style.get("fontSize", T("font.xs")),
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )


class MarkPointComponent(_SeriesMarkBase):
    """数据点标注：最大 / 最小值或指定坐标，圆点（小旗式插针）+ 值文本。
    ``markPoint.data`` 项为 ``{"type": "max"|"min"}`` 或
    ``{"coord": [x, y], "value": v, "name": "..."}``。
    """

    optionKey = "markPoint"

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._marks = []  # [{"pos": QPointF, "text": str, "x": x, "y": y}]

    def layout(self, rect: QRectF) -> None:
        self._marks = []
        if not self._visible():
            return
        coord = self._coord()
        if coord is None:
            return
        horizontal = (
            isinstance(coord, GridCoord)
            and coord.y_axis.type == "category"
            and coord.x_axis.type != "category"
        )
        renderer = self._renderer()
        stats = renderer.valueStats() if renderer is not None else {}
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            x = y = None
            typ = item.get("type")
            if typ in ("max", "min") and stats and stats.get("count"):
                at = stats.get("maxIndex") if typ == "max" else stats.get("minIndex")
                point = self._datum_at(at)
                if point is not None:
                    x, y = point
                    if horizontal:
                        # 横向柱的数据项是 (类别下标, 数值)，坐标要反过来。
                        x, y = y, x
            elif (
                isinstance(item.get("coord"), (list, tuple)) and len(item["coord"]) >= 2
            ):
                # coord 就是 [xAxisValue, yAxisValue]：类目名必须原样交给
                # AxisModel.map，不能先 _to_float 吞成 None。
                x = item["coord"][0]
                y = item["coord"][1]
            if y is None:
                continue
            try:
                pos = coord.mapPoint(x, y)
            except Exception:
                continue
            mark_value = item.get("value")
            if mark_value is None:
                mark_value = x if horizontal else y
            label = item.get("name")
            if label is None:
                label = formatValue(mark_value)
            text = str(label)
            label_option = self._label_option(item)
            style = self._label_style(item)
            show = bool(label_option.get("show", True))
            font = self._label_font(style)
            fm = QFontMetricsF(font)
            tw = fm.horizontalAdvance(text)
            position = str(label_option.get("position") or "top").strip().lower()
            if position == "bottom":
                label_rect = QRectF(
                    pos.x() - tw / 2 - 2, pos.y() + 12, tw + 4, fm.height()
                )
            elif position == "left":
                label_rect = QRectF(
                    pos.x() - tw - 12, pos.y() - fm.height() / 2, tw + 4, fm.height()
                )
            elif position == "right":
                label_rect = QRectF(
                    pos.x() + 10, pos.y() - fm.height() / 2, tw + 4, fm.height()
                )
            else:  # top
                label_rect = QRectF(
                    pos.x() - tw / 2 - 2,
                    pos.y() - fm.height() - 16,
                    tw + 4,
                    fm.height(),
                )
            self._marks.append(
                {
                    "pos": pos,
                    "text": text if show else "",
                    "x": x,
                    "y": y,
                    "value": mark_value,
                    "index": index,
                    "rect": label_rect if show else None,
                    "font": font,
                    "labelColor": style.get("color"),
                    "symbol": item.get("symbol") or self.opt.get("symbol"),
                    "symbolSize": item.get("symbolSize") or self.opt.get("symbolSize"),
                }
            )

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._marks or not self._visible():
            return
        p.save()
        color = self._color()
        for m in self._marks:
            pos = m["pos"]
            size = max(3.0, _to_float(m.get("symbolSize"), 8.4))
            kind = str(m.get("symbol") or "circle").strip() or "circle"
            # 符号（默认实心圆；``symbol`` / ``symbolSize`` 可覆盖）
            p.setPen(QPen(QColor(T("color.bg.elevated", self.chart)), 1.4))
            p.setBrush(color)
            if kind in ("", "none"):
                kind = "circle"
            if kind == "circle":
                p.drawEllipse(pos, size / 2.0, size / 2.0)
            else:
                drawSymbol(p, kind, pos, size)
            top = QPointF(pos.x(), pos.y() - max(14.0, size))
            p.setPen(QPen(color, 1.4))
            p.drawLine(QPointF(pos.x(), pos.y() - size / 2.0 - 0.5), top)
            if not m["text"]:
                continue
            label_color = m.get("labelColor")
            p.setPen(
                resolve_color_option(
                    label_color,
                    self.chart,
                    T("color.text.primary", self.chart),
                )
            )
            p.setFont(m["font"])
            p.drawText(
                m["rect"],
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                m["text"],
            )
        p.restore()

    def hitTest(self, pos: QPointF):
        for m in self._marks:
            mp = m["pos"]
            if (mp.x() - pos.x()) ** 2 + (mp.y() - pos.y()) ** 2 <= 64:
                r = self._renderer()
                return {
                    "name": m["text"],
                    "value": m.get("value", m["y"]),
                    "color": self._color(),
                    "series": r.name if r is not None else "markPoint",
                }
        return None

    def labelEditHit(self, pos: QPointF):
        """标签命中：返回 ``(data_index, label_rect)``，未命中 None。"""
        for mark in reversed(self._marks):
            rect = mark.get("rect")
            if isinstance(rect, QRectF) and rect.adjusted(-2, -2, 2, 2).contains(pos):
                return mark.get("index"), QRectF(rect)
        return None

    def setLabelText(self, index: int, text: str) -> bool:
        """把 ``markPoint.data[index].name`` 改成 ``text``（共享 option 数据）。"""
        data = self.opt.get("data")
        if not isinstance(data, list) or not (0 <= int(index) < len(data)):
            return False
        item = data[int(index)]
        if not isinstance(item, dict):
            return False
        item["name"] = str(text)
        return True

    def labelEditText(self, index: int) -> str:
        """编辑框初始文本（当前标签文案；没有 name 时给默认值文案）。"""
        for mark in self._marks:
            if mark.get("index") == index:
                return str(mark.get("text") or "")
        return ""


_TYPE_LABELS = {"average": "平均值", "max": "最大值", "min": "最小值"}


class MarkLineComponent(_SeriesMarkBase):
    """参考标线：平均值 / 最大 / 最小或指定 yAxis / xAxis，虚线 + 端部标签。

    仅作用于 GridCoord 直角坐标（其它坐标系静默跳过）。
    """

    optionKey = "markLine"

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        # [{"orient": "h"|"v", "value": ..., "text": str}]
        self._lines = []

    def layout(self, rect: QRectF) -> None:
        self._lines = []
        if not self._visible():
            return
        coord = self._coord()
        if coord is None:
            return
        if not isinstance(coord, GridCoord):
            self._layout_non_grid(coord)
            return
        renderer = self._renderer()
        stats = renderer.valueStats() if renderer is not None else {}
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        plot = coord.plot
        horizontal = coord.y_axis.type == "category" and coord.x_axis.type != "category"
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            orient = value = None
            default_label = ""
            p1 = p2 = None
            typ = item.get("type")
            coord_pair = item.get("coord")
            if (
                isinstance(coord_pair, (list, tuple))
                and len(coord_pair) >= 2
                and isinstance(coord_pair[0], (list, tuple))
                and isinstance(coord_pair[1], (list, tuple))
                and len(coord_pair[0]) >= 2
                and len(coord_pair[1]) >= 2
            ):
                try:
                    p1 = coord.mapPoint(coord_pair[0][0], coord_pair[0][1])
                    p2 = coord.mapPoint(coord_pair[1][0], coord_pair[1][1])
                    orient = "arbitrary"
                except Exception:
                    p1 = p2 = None
            elif typ in _TYPE_LABELS and stats.get("count"):
                if typ == "average":
                    value = stats["sum"] / stats["count"]
                elif typ == "max":
                    value = stats["max"]
                else:
                    value = stats["min"]
                # 横向柱的数值在 x 轴：max/average 要画竖线。
                orient = "v" if horizontal else "h"
                default_label = _TYPE_LABELS[typ]
            elif "yAxis" in item:
                value = item.get("yAxis")
                orient = "h"
            elif "xAxis" in item:
                value = item.get("xAxis")
                orient = "v"
            if orient is None:
                continue
            label_option = self._label_option(item)
            style = self._label_style(item)
            show = bool(label_option.get("show", True))
            font = self._label_font(style)
            fm = QFontMetricsF(font)
            position = str(label_option.get("position") or "end").strip().lower()
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            if orient == "arbitrary":
                if p1 is None or p2 is None:
                    continue
                value = None
                name = str(item.get("name") or "")
                text = name
                rect = QRectF(p2.x() + 4, p2.y() - fm.height() - 3, 120, fm.height())
            else:
                if value is None:
                    continue
                name = str(item.get("name") or default_label)
                vtxt = (
                    formatValue(value)
                    if isinstance(value, (int, float))
                    else str(value)
                )
                text = f"{name} {vtxt}" if name else vtxt
                if orient == "h":
                    py = coord.y_axis.map(value, plot.bottom(), plot.top())
                    if position == "start":
                        rect = QRectF(
                            plot.left() + 2, py - fm.height() - 3, 118, fm.height()
                        )
                    elif position == "middle":
                        rect = QRectF(
                            plot.center().x() - 60,
                            py - fm.height() - 3,
                            120,
                            fm.height(),
                        )
                        align = (
                            Qt.AlignmentFlag.AlignHCenter
                            | Qt.AlignmentFlag.AlignVCenter
                        )
                    else:  # end（默认）
                        rect = QRectF(
                            plot.right() - 120, py - fm.height() - 3, 118, fm.height()
                        )
                        align = (
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                else:
                    px = coord.x_axis.map(value, plot.left(), plot.right())
                    if position == "start":
                        rect = QRectF(px + 4, plot.top() + 3, 120, fm.height())
                    elif position == "middle":
                        rect = QRectF(
                            px + 4,
                            plot.center().y() - fm.height() / 2,
                            120,
                            fm.height(),
                        )
                    else:  # end
                        rect = QRectF(
                            px + 4,
                            plot.bottom() - fm.height() - 3,
                            120,
                            fm.height(),
                        )
            self._lines.append(
                {
                    "orient": orient,
                    "value": value,
                    "text": text if show else "",
                    "name": name,
                    "index": index,
                    "rect": rect,
                    "align": align,
                    "font": font,
                    "labelColor": style.get("color"),
                    "p1": p1,
                    "p2": p2,
                    "lineStyle": item.get("lineStyle"),
                    "symbol": item.get("symbol"),
                    "symbolSize": item.get("symbolSize"),
                }
            )

    def _layout_non_grid(self, coord) -> None:
        """极坐标 / 单轴上的 markLine：任意两点、半径圆、角度射线、单轴竖线。"""
        kind = getattr(coord, "kind", "")
        renderer = self._renderer()
        stats = renderer.valueStats() if renderer is not None else {}
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            orient = "arbitrary"
            value = None
            p1 = p2 = None
            center = None
            radius_px = None
            angle_point = None
            px = None
            y0 = y1 = 0.0
            coord_pair = item.get("coord")
            if (
                isinstance(coord_pair, (list, tuple))
                and len(coord_pair) >= 2
                and isinstance(coord_pair[0], (list, tuple))
                and isinstance(coord_pair[1], (list, tuple))
                and len(coord_pair[0]) >= 2
                and len(coord_pair[1]) >= 2
            ):
                try:
                    p1 = coord.mapPoint(coord_pair[0][0], coord_pair[0][1])
                    p2 = coord.mapPoint(coord_pair[1][0], coord_pair[1][1])
                except Exception:
                    continue
            else:
                typ = item.get("type")
                if typ in _TYPE_LABELS and stats.get("count"):
                    if typ == "average":
                        value = stats["sum"] / stats["count"]
                    elif typ == "max":
                        value = stats["max"]
                    else:
                        value = stats["min"]
                elif "yAxis" in item:
                    value = item.get("yAxis")
                elif "xAxis" in item:
                    value = item.get("xAxis")
                if value is None:
                    continue
                if kind == "polar":
                    if "xAxis" in item:
                        orient = "polar-angle"
                        try:
                            angle_point = coord.mapPoint(value, coord.radius_axis.vmax)
                        except Exception:
                            continue
                    else:
                        orient = "polar-radius"
                        center = QPointF(coord.center)
                        try:
                            pt = coord.mapPoint(coord.angle_axis.vmin, value)
                            radius_px = math.hypot(
                                pt.x() - center.x(), pt.y() - center.y()
                            )
                        except Exception:
                            continue
                elif kind == "singleAxis":
                    orient = "single-v"
                    try:
                        px = coord.axis.map(
                            value, coord.plot.left(), coord.plot.right()
                        )
                    except Exception:
                        continue
                    y0 = coord.line_y - 20.0
                    y1 = coord.line_y + 20.0
                else:
                    continue
            label_option = self._label_option(item)
            style = self._label_style(item)
            show = bool(label_option.get("show", True))
            font = self._label_font(style)
            fm = QFontMetricsF(font)
            name = str(item.get("name") or _TYPE_LABELS.get(item.get("type"), ""))
            vtxt = (
                formatValue(value)
                if isinstance(value, (int, float))
                else (str(value) if value is not None else "")
            )
            text = f"{name} {vtxt}" if name and vtxt else (name or vtxt)
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            if orient == "arbitrary":
                if p2 is None:
                    continue
                rect = QRectF(p2.x() + 4, p2.y() - fm.height() - 3, 120, fm.height())
            elif orient == "polar-radius":
                if center is None or radius_px is None:
                    continue
                rect = QRectF(
                    center.x() + radius_px + 4,
                    center.y() - fm.height() / 2,
                    120,
                    fm.height(),
                )
            elif orient == "polar-angle":
                if angle_point is None:
                    continue
                rect = QRectF(
                    angle_point.x() + 4,
                    angle_point.y() - fm.height() - 3,
                    120,
                    fm.height(),
                )
            else:
                if px is None:
                    continue
                rect = QRectF(px + 4, y0 - fm.height() - 2, 120, fm.height())
            self._lines.append(
                {
                    "orient": orient,
                    "value": value,
                    "text": text if show else "",
                    "name": name,
                    "index": index,
                    "rect": rect,
                    "align": align,
                    "font": font,
                    "labelColor": style.get("color"),
                    "p1": p1,
                    "p2": p2,
                    "center": center,
                    "radius": radius_px,
                    "anglePoint": angle_point,
                    "px": px,
                    "y0": y0,
                    "y1": y1,
                    "lineStyle": item.get("lineStyle"),
                    "symbol": item.get("symbol"),
                    "symbolSize": item.get("symbolSize"),
                }
            )

    def _line_pen(self, ln: dict, base_color: QColor) -> QPen:
        style = ln.get("lineStyle")
        style = style if isinstance(style, dict) else {}
        color = resolve_color_option(style.get("color"), self.chart, base_color)
        if not color.isValid():
            color = parse_color(base_color)
        width = max(0.5, _to_float(style.get("width"), 1.4))
        pen = QPen(color, width)
        kind = str(style.get("type") or "dashed")
        if kind in ("solid",):
            pen.setStyle(Qt.PenStyle.SolidLine)
        elif kind in ("dotted", "dot"):
            pen.setStyle(Qt.PenStyle.DotLine)
        else:
            pen.setStyle(Qt.PenStyle.DashLine)
        return pen

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._lines or not self._visible():
            return
        coord = self._coord()
        if coord is None:
            return
        plot = getattr(coord, "plot", QRectF())
        p.save()
        color = self._color()
        for ln in self._lines:
            pen = self._line_pen(ln, color)
            p.setPen(pen)
            orient = ln["orient"]
            if orient == "arbitrary":
                p1, p2 = ln.get("p1"), ln.get("p2")
                if p1 is None or p2 is None:
                    continue
                p.drawLine(p1, p2)
                self._paint_mark_symbols(p, ln, pen.color(), (p1, p2))
                self._paint_mark_text(p, ln, pen.color())
            elif orient == "polar-radius":
                center, radius = ln.get("center"), ln.get("radius")
                if center is None or radius is None:
                    continue
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(center, radius, radius)
                points = (
                    QPointF(center.x() + radius, center.y()),
                    QPointF(center.x() - radius, center.y()),
                )
                self._paint_mark_symbols(p, ln, pen.color(), points)
                self._paint_mark_text(p, ln, pen.color())
            elif orient == "polar-angle":
                center, point = ln.get("center"), ln.get("anglePoint")
                if center is None or point is None:
                    continue
                p.drawLine(center, point)
                self._paint_mark_symbols(p, ln, pen.color(), (center, point))
                self._paint_mark_text(p, ln, pen.color())
            elif orient == "single-v":
                px = ln.get("px")
                if px is None:
                    continue
                p.drawLine(QPointF(px, ln["y0"]), QPointF(px, ln["y1"]))
                self._paint_mark_symbols(
                    p,
                    ln,
                    pen.color(),
                    (QPointF(px, ln["y0"]), QPointF(px, ln["y1"])),
                )
                self._paint_mark_text(p, ln, pen.color())
            elif orient == "h":
                py = coord.y_axis.map(ln["value"], plot.bottom(), plot.top())
                p.drawLine(QPointF(plot.left(), py), QPointF(plot.right(), py))
                self._paint_mark_symbols(
                    p,
                    ln,
                    pen.color(),
                    (QPointF(plot.left(), py), QPointF(plot.right(), py)),
                )
                self._paint_mark_text(p, ln, pen.color())
            else:
                px = coord.x_axis.map(ln["value"], plot.left(), plot.right())
                p.drawLine(QPointF(px, plot.top()), QPointF(px, plot.bottom()))
                self._paint_mark_symbols(
                    p,
                    ln,
                    pen.color(),
                    (QPointF(px, plot.top()), QPointF(px, plot.bottom())),
                )
                self._paint_mark_text(p, ln, pen.color())
        p.restore()

    def _paint_mark_text(self, p: QPainter, ln: dict, default_color: QColor) -> None:
        """标注标签（字体 / 位置 / 颜色在 layout 期已解析）。"""
        if not ln["text"]:
            return
        raw = ln.get("labelColor")
        p.setPen(resolve_color_option(raw, self.chart, default_color))
        p.setFont(ln["font"])
        p.drawText(ln["rect"], ln["align"], ln["text"])

    def _paint_mark_symbols(self, p: QPainter, ln: dict, color: QColor, points) -> None:
        symbol = ln.get("symbol")
        if symbol == "none":
            return
        size = max(2.0, _to_float(ln.get("symbolSize"), 6.0) / 2.0)
        p.setPen(QPen(color, 1.2))
        p.setBrush(QColor(T("color.bg.elevated", self.chart)))
        for point in points:
            p.drawEllipse(point, size, size)

    def hitTest(self, pos: QPointF):
        coord = self._coord()
        if coord is None:
            return None
        plot = getattr(coord, "plot", QRectF())

        def hit_info(ln, color):
            renderer = self._renderer()
            return {
                "name": ln["text"],
                "value": ln.get("value"),
                "color": color,
                "series": renderer.name if renderer is not None else "markLine",
            }

        for ln in self._lines:
            color = self._line_pen(ln, self._color()).color()
            orient = ln["orient"]
            if orient == "arbitrary":
                p1, p2 = ln.get("p1"), ln.get("p2")
                if p1 is not None and p2 is not None:
                    if dist_point_segment(pos, p1, p2) <= 4.0:
                        return hit_info(ln, color)
                continue
            if orient == "polar-radius":
                center, radius = ln.get("center"), ln.get("radius")
                if center is None or radius is None:
                    continue
                if (
                    abs(math.hypot(pos.x() - center.x(), pos.y() - center.y()) - radius)
                    <= 4.0
                ):
                    return hit_info(ln, color)
                continue
            if orient == "polar-angle":
                center, point = ln.get("center"), ln.get("anglePoint")
                if center is not None and point is not None:
                    if dist_point_segment(pos, center, point) <= 4.0:
                        return hit_info(ln, color)
                continue
            if orient == "single-v":
                px = ln.get("px")
                if (
                    px is not None
                    and abs(pos.x() - px) <= 4.0
                    and ln["y0"] <= pos.y() <= ln["y1"]
                ):
                    return hit_info(ln, color)
                continue
            if orient == "h":
                py = coord.y_axis.map(ln["value"], plot.bottom(), plot.top())
                if abs(pos.y() - py) <= 4 and plot.left() <= pos.x() <= plot.right():
                    return hit_info(ln, color)
            else:
                px = coord.x_axis.map(ln["value"], plot.left(), plot.right())
                if abs(pos.x() - px) <= 4 and plot.top() <= pos.y() <= plot.bottom():
                    return hit_info(ln, color)
        return None

    def labelEditHit(self, pos: QPointF):
        """标签命中：返回 ``(data_index, label_rect)``，未命中 None。"""
        for line in reversed(self._lines):
            rect = line.get("rect")
            if isinstance(rect, QRectF) and rect.adjusted(-2, -2, 2, 2).contains(pos):
                return line.get("index"), QRectF(rect)
        return None

    def setLabelText(self, index: int, text: str) -> bool:
        """把 ``markLine.data[index].name`` 改成 ``text``（共享 option 数据）。"""
        data = self.opt.get("data")
        if not isinstance(data, list) or not (0 <= int(index) < len(data)):
            return False
        item = data[int(index)]
        if not isinstance(item, dict):
            return False
        item["name"] = str(text)
        return True

    def labelEditText(self, index: int) -> str:
        """编辑框初始文本（当前 name；没有 name 时给默认类型名）。"""
        for line in self._lines:
            if line.get("index") == index:
                return str(line.get("name") or "")
        return ""


class MarkAreaComponent(_SeriesMarkBase):
    """区间标域：xAxis / yAxis 值对的填充区域 + 可选标签。

    仅在 Grid 直角坐标系下生效；``polar`` / ``calendar`` / ``singleAxis``
    的区间语义与矩形不等价，调用一次告警后跳过。
    """

    optionKey = "markArea"

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._areas = []  # [QRectF]（保留给查询 / 测试）
        self._area_meta = []  # [{"rect","text","font","color","fill","pen"}]
        self._label_rects = []  # [(area_index, QRectF, text)]

    def _warn_coord(self) -> None:
        warn_once(
            "mark-area-coord",
            "markArea 只支持 grid / singleAxis / polar / calendar 坐标系",
        )

    def _style_for(self, item: dict) -> dict:
        style = self.opt.get("itemStyle")
        style = dict(style) if isinstance(style, dict) else {}
        local = item.get("itemStyle") if isinstance(item, dict) else None
        if isinstance(local, dict):
            style.update(local)
        return style

    def layout(self, rect: QRectF) -> None:
        self._areas = []
        self._area_meta = []
        if not self._visible():
            return
        coord = self._coord()
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        if not isinstance(coord, GridCoord):
            if isinstance(coord, SingleAxisCoord):
                self._layout_single(coord, data)
                return
            if isinstance(coord, PolarCoord):
                self._layout_polar(coord, data)
                return
            if isinstance(coord, CalendarCoord):
                self._layout_calendar(coord, data)
                return
            self._warn_coord()
            return
        plot = coord.plot
        for pair in data:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            a, b = pair[0], pair[1]
            if not isinstance(a, dict) or not isinstance(b, dict):
                continue
            area = None
            if "coord" in a and "coord" in b:
                try:
                    xa, ya = a["coord"][0], a["coord"][1]
                    xb, yb = b["coord"][0], b["coord"][1]
                    p1 = coord.mapPoint(xa, ya)
                    p2 = coord.mapPoint(xb, yb)
                    area = QRectF(p1, p2).normalized()
                except Exception:
                    area = None
            elif "xAxis" in a and "xAxis" in b:
                x0 = coord.x_axis.map(a["xAxis"], plot.left(), plot.right())
                x1 = coord.x_axis.map(b["xAxis"], plot.left(), plot.right())
                if coord.x_axis.type == "category":
                    half = coord.x_axis.bandWidth(plot.left(), plot.right()) / 2
                    x0, x1 = x0 - half, x1 + half
                area = QRectF(min(x0, x1), plot.top(), abs(x1 - x0), plot.height())
            elif "yAxis" in a and "yAxis" in b:
                y0 = coord.y_axis.map(a["yAxis"], plot.bottom(), plot.top())
                y1 = coord.y_axis.map(b["yAxis"], plot.bottom(), plot.top())
                area = QRectF(plot.left(), min(y0, y1), plot.width(), abs(y1 - y0))
            if area is None:
                continue
            area = area.intersected(plot)
            if area.isNull() or area.width() <= 0.0 or area.height() <= 0.0:
                continue
            self._areas.append(area)
            self._area_meta.append(self._meta_for(area, a, b))

    def _layout_single(self, coord, data) -> None:
        if not isinstance(data, list):
            return
        y = float(getattr(coord, "line_y", coord.rect.center().y()))
        height = 32.0
        for pair in data:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            a, b = pair[0], pair[1]
            if not isinstance(a, dict) or not isinstance(b, dict):
                continue
            if "xAxis" not in a or "xAxis" not in b:
                continue
            try:
                x0 = coord.mapPoint(a["xAxis"]).x()
                x1 = coord.mapPoint(b["xAxis"]).x()
            except Exception:
                continue
            area = QRectF(min(x0, x1), y - height / 2, abs(x1 - x0), height)
            area = area.intersected(coord.rect)
            if area.isNull() or area.width() <= 0.0:
                continue
            self._areas.append(area)
            self._area_meta.append(self._meta_for(area, a, b))

    def _layout_polar(self, coord, data) -> None:
        if not isinstance(data, list):
            return
        vmin, vmax = float(coord.radius_axis.vmin), float(coord.radius_axis.vmax)
        span = max(1e-9, vmax - vmin)
        for pair in data:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            a, b = pair[0], pair[1]
            if not isinstance(a, dict) or not isinstance(b, dict):
                continue
            if "coord" in a and "coord" in b:
                try:
                    angle0, radius0 = a["coord"][0], a["coord"][1]
                    angle1, radius1 = b["coord"][0], b["coord"][1]
                except (TypeError, IndexError):
                    continue
            elif "xAxis" in a and "xAxis" in b and "yAxis" in a and "yAxis" in b:
                angle0, radius0 = a["xAxis"], a["yAxis"]
                angle1, radius1 = b["xAxis"], b["yAxis"]
            else:
                continue
            try:
                f0 = coord._angle_frac(angle0)
                f1 = coord._angle_frac(angle1)
                r0 = max(0.0, min(1.0, (float(radius0) - vmin) / span))
                r1 = max(0.0, min(1.0, (float(radius1) - vmin) / span))
            except (TypeError, ValueError, OverflowError):
                continue
            path = coord.sector_path(min(f0, f1), max(f0, f1), min(r0, r1), max(r0, r1))
            if path.isEmpty():
                continue
            area = path.boundingRect().intersected(coord.rect)
            if area.isNull() or area.width() <= 0.0:
                continue
            self._areas.append(area)
            self._area_meta.append(self._meta_for(area, a, b, path))

    def _layout_calendar(self, coord, data) -> None:
        if not isinstance(data, list):
            return
        for pair in data:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            a, b = pair[0], pair[1]
            if not isinstance(a, dict) or not isinstance(b, dict):
                continue
            av = a.get("coord", a.get("xAxis"))
            bv = b.get("coord", b.get("xAxis"))
            if isinstance(av, (list, tuple)) and av:
                av = av[0]
            if isinstance(bv, (list, tuple)) and bv:
                bv = bv[0]
            try:
                r0 = coord.cellRect(av)
                r1 = coord.cellRect(bv)
            except Exception:
                continue
            if r0.isNull() or r1.isNull():
                continue
            area = r0.united(r1).intersected(coord.gridRect())
            if area.isNull() or area.width() <= 0.0:
                continue
            self._areas.append(area)
            self._area_meta.append(self._meta_for(area, a, b))

    def _meta_for(self, area: QRectF, a: dict, b: dict, path=None) -> dict:
        style = self._style_for(a)
        if isinstance(b.get("itemStyle"), dict):
            style.update(b["itemStyle"])
        raw = style.get("color")
        fill = resolve_color_option(raw, self.chart, T("color.primary", self.chart))
        alpha = 28
        if isinstance(raw, QColor):
            alpha = fill.alpha()
        elif isinstance(raw, str):
            text = raw.strip().lower()
            if (text.startswith("#") and len(text) >= 9) or text.startswith("rgba("):
                alpha = fill.alpha()
        try:
            opacity = _to_float(style.get("opacity"), None)
        except Exception:
            opacity = None
        if opacity is not None:
            alpha = int(max(0.0, min(1.0, opacity)) * 255)
        fill.setAlpha(alpha)
        border = resolve_color_option(style.get("borderColor"), self.chart, fill)
        try:
            border_w = max(0.0, _to_float(style.get("borderWidth"), 0.0))
        except Exception:
            border_w = 0.0

        label_base = self.opt.get("label")
        label_base = dict(label_base) if isinstance(label_base, dict) else {}
        for item in (a, b):
            local = item.get("label") if isinstance(item, dict) else None
            if isinstance(local, dict):
                label_base.update(local)
        text = str(
            label_base.get("text")
            or label_base.get("name")
            or a.get("name")
            or b.get("name")
            or ""
        )
        show = bool(label_base.get("show", False)) and bool(text)
        if label_base.get("formatter") and text:
            formatter = label_base["formatter"]
            if callable(formatter):
                try:
                    text = str(formatter({"name": text}))
                except Exception:
                    pass
            elif isinstance(formatter, str):
                text = formatter.replace("{a}", text).replace("{b}", text)
        style_label = self._label_style(a)
        style_label.update(
            {
                key: value
                for key, value in label_base.items()
                if key
                in (
                    "color",
                    "fontSize",
                    "fontWeight",
                    "fontFamily",
                    "fontStyle",
                )
            }
        )
        font = self._label_font(style_label) if show else None
        color = resolve_color_option(
            style_label.get("color"),
            self.chart,
            text_on_fill(fill, self.chart),
        )
        return {
            "rect": area,
            "path": path,
            "text": text if show else "",
            "font": font,
            "color": color,
            "fill": fill,
            "border": border if border_w > 0 else None,
            "borderWidth": border_w,
            "position": str(label_base.get("position") or "insideTop").lower(),
        }

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._area_meta or not self._visible():
            return
        p.save()
        self._label_rects = []
        for area_index, meta in enumerate(self._area_meta):
            area = meta["rect"]
            p.setPen(
                Qt.PenStyle.NoPen
                if meta["border"] is None
                else QPen(meta["border"], meta["borderWidth"])
            )
            p.setBrush(meta["fill"])
            if meta.get("path") is not None:
                p.drawPath(meta["path"])
            else:
                p.drawRect(area)
            text = meta["text"]
            if not text or meta["font"] is None:
                continue
            font = meta["font"]
            p.setFont(font)
            p.setPen(meta["color"])
            fm = QFontMetricsF(font)
            w = min(area.width() - 8, fm.horizontalAdvance(text) + 8)
            h = fm.height() + 2
            position = meta["position"]
            if position in ("top", "outside"):
                rect = QRectF(area.center().x() - w / 2, area.top() - h - 2, w, h)
            elif position in ("bottom", "outsideBottom"):
                rect = QRectF(area.center().x() - w / 2, area.bottom() + 2, w, h)
            elif position == "left":
                rect = QRectF(area.left() + 3, area.center().y() - h / 2, w, h)
            elif position == "right":
                rect = QRectF(area.right() - w - 3, area.center().y() - h / 2, w, h)
            elif position == "insideBottom":
                rect = QRectF(area.left() + 3, area.bottom() - h - 2, w, h)
            elif position == "inside":
                rect = QRectF(
                    area.center().x() - w / 2, area.center().y() - h / 2, w, h
                )
            else:  # insideTop（默认）
                rect = QRectF(area.left() + 3, area.top() + 2, w, h)
            p.drawText(
                rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            self._label_rects.append((area_index, QRectF(rect), text))
        p.restore()

    def labelEditHit(self, pos: QPointF):
        for index, rect, text in reversed(self._label_rects):
            if rect.adjusted(-2, -2, 2, 2).contains(pos):
                return index, rect
        return None

    def labelEditText(self, index: int) -> str:
        for area_index, _rect, text in self._label_rects:
            if area_index == index:
                return text
        return ""

    def labelEditRawText(self, index: int):
        data = self.opt.get("data") or []
        if not isinstance(data, list) or not (0 <= index < len(data)):
            return None
        pair = data[index]
        if not isinstance(pair, (list, tuple)) or not pair:
            return None
        first = pair[0]
        return first.get("name") if isinstance(first, dict) else None

    def setLabelText(self, index: int, text: str) -> bool:
        data = self.opt.get("data") or []
        if not isinstance(data, list) or not (0 <= index < len(data)):
            return False
        pair = data[index]
        if not isinstance(pair, (list, tuple)) or not pair:
            return False
        first = pair[0]
        if not isinstance(first, dict):
            first = {}
            pair[0] = first
        first["name"] = str(text)
        label = first.get("label")
        if not isinstance(label, dict):
            label = {}
            first["label"] = label
        label["show"] = True
        return True

    def hitTest(self, pos: QPointF):
        """命中半透明背景区域；``silent=True`` 时不参与。"""
        if bool(self.opt.get("silent", False)):
            return None
        for meta in self._area_meta:
            area = meta.get("rect")
            path = meta.get("path")
            inside = (
                path.contains(pos)
                if path is not None
                else bool(area is not None and area.contains(pos))
            )
            if inside:
                r = self._renderer()
                return {
                    "name": "markArea",
                    "value": None,
                    "series": r.name if r is not None else "markArea",
                }
        return None
