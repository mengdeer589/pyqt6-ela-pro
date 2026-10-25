"""markPoint / markLine / markArea 组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen

from .._tokens import T
from .._symbol import drawSymbol
from .._utils import dist_point_segment
from .._utils import merged_text_style, parse_color, text_italic, text_weight
from .._utils import to_float as _to_float
from ..axes import GridCoord, chartFont, formatValue
from ..core import (
    parseDataPoint,
)


class _SeriesMarkBase:
    """markPoint / markLine / markArea 的公共基类。

    core 重建时对每个含同名键的 series 字典实例化一次，并注入
    ``comp.series_opt``（指向所属系列 option 字典）。本基类负责反查
    对应的系列渲染器与坐标系。构造时 ``series_opt`` 尚未注入，相关解析
    一律推迟到 layout / paint。
    """

    optionKey = ""

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = dict(opt or {})
        #: 所属系列 option（core 注入；顶层实例化为 None）
        self.series_opt = None

    # -- 反查 ------------------------------------------------------------
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
        name = str(s.get("name") or (f"series{idx}" if idx is not None else ""))
        for r in chart.seriesRenderers:
            if r.name == name:
                return r
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
        return QColor(T("color.primary"))

    def _visible(self) -> bool:
        r = self._renderer()
        return r is not None and r.visible

    def _label_option(self, item: dict) -> dict:
        """标注标签 option：系列级 ``label`` 叠加数据项级 ``label``（项级优先）。

        **返回原始键**（``show`` / ``position`` / ``formatter`` 也在内），
        外观键的全局兜底走 :meth:`_label_style`。
        """
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

    option（系列级）::

        "markPoint": {"data": [{"type": "max"|"min"},
                               {"coord": [x, y], "value": v, "name": "..."}]}
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
            elif (
                isinstance(item.get("coord"), (list, tuple)) and len(item["coord"]) >= 2
            ):
                x = item["coord"][0]
                y = _to_float(item["coord"][1], None)
                if y is None:
                    y = _to_float(item.get("value"), None)
            if y is None:
                continue
            try:
                pos = coord.mapPoint(x, y)
            except Exception:
                continue
            label = item.get("name")
            if label is None:
                label = formatValue(_to_float(item.get("value"), y))
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
            p.setPen(QPen(QColor(T("color.bg.elevated")), 1.4))
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
                parse_color(label_color)
                if isinstance(label_color, str) and label_color
                else QColor(T("color.text.primary"))
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
                    "value": m["y"],
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

    option（系列级）::

        "markLine": {"data": [{"type": "average"|"max"|"min", "name": "..."},
                              {"yAxis": v}, {"xAxis": v}]}

    仅作用于 GridCoord 直角坐标（其他坐标系静默跳过）。
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
        if not isinstance(coord, GridCoord):
            return
        renderer = self._renderer()
        stats = renderer.valueStats() if renderer is not None else {}
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        plot = coord.plot
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
                orient = "h"
                default_label = _TYPE_LABELS[typ]
            elif "yAxis" in item:
                value = _to_float(item.get("yAxis"), None)
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
                    py = coord.y_axis.map(
                        _to_float(value, 0.0), plot.bottom(), plot.top()
                    )
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
                        align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                    else:  # end（默认）
                        rect = QRectF(
                            plot.right() - 120, py - fm.height() - 3, 118, fm.height()
                        )
                        align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
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

    def _line_pen(self, ln: dict, base_color: QColor) -> QPen:
        style = ln.get("lineStyle")
        style = style if isinstance(style, dict) else {}
        color = parse_color(style.get("color") or base_color)
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
        if not isinstance(coord, GridCoord):
            return
        plot = coord.plot
        p.save()
        color = self._color()
        for ln in self._lines:
            pen = self._line_pen(ln, color)
            p.setPen(pen)
            if ln["orient"] == "arbitrary":
                p1, p2 = ln.get("p1"), ln.get("p2")
                if p1 is None or p2 is None:
                    continue
                p.drawLine(p1, p2)
                self._paint_mark_symbols(p, ln, pen.color(), (p1, p2))
                self._paint_mark_text(p, ln, pen.color())
            elif ln["orient"] == "h":
                py = coord.y_axis.map(
                    _to_float(ln["value"], 0.0), plot.bottom(), plot.top()
                )
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

    @staticmethod
    def _paint_mark_text(p: QPainter, ln: dict, default_color: QColor) -> None:
        """标注标签（字体 / 位置 / 颜色在 layout 期已解析）。"""
        if not ln["text"]:
            return
        raw = ln.get("labelColor")
        p.setPen(parse_color(raw) if isinstance(raw, str) and raw else default_color)
        p.setFont(ln["font"])
        p.drawText(ln["rect"], ln["align"], ln["text"])

    @staticmethod
    def _paint_mark_symbols(p: QPainter, ln: dict, color: QColor, points) -> None:
        symbol = ln.get("symbol")
        if symbol == "none":
            return
        size = max(2.0, _to_float(ln.get("symbolSize"), 6.0) / 2.0)
        p.setPen(QPen(color, 1.2))
        p.setBrush(QColor(T("color.bg.elevated")))
        for point in points:
            p.drawEllipse(point, size, size)

    def hitTest(self, pos: QPointF):
        coord = self._coord()
        if not isinstance(coord, GridCoord):
            return None
        plot = coord.plot
        for ln in self._lines:
            if ln["orient"] == "arbitrary":
                p1, p2 = ln.get("p1"), ln.get("p2")
                if p1 is not None and p2 is not None:
                    if dist_point_segment(pos, p1, p2) <= 4.0:
                        r = self._renderer()
                        return {
                            "name": ln["text"],
                            "value": ln.get("value"),
                            "series": r.name if r is not None else "markLine",
                        }
                continue
            if ln["orient"] == "h":
                py = coord.y_axis.map(
                    _to_float(ln["value"], 0.0), plot.bottom(), plot.top()
                )
                if abs(pos.y() - py) <= 4 and plot.left() <= pos.x() <= plot.right():
                    r = self._renderer()
                    return {
                        "name": ln["text"],
                        "value": ln["value"],
                        "series": r.name if r is not None else "markLine",
                    }
            else:
                px = coord.x_axis.map(ln["value"], plot.left(), plot.right())
                if abs(pos.x() - px) <= 4 and plot.top() <= pos.y() <= plot.bottom():
                    r = self._renderer()
                    return {
                        "name": ln["text"],
                        "value": ln["value"],
                        "series": r.name if r is not None else "markLine",
                    }
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
    """区间标域：xAxis / yAxis 值对的半透明填充区域。

    option（系列级）::

        "markArea": {"data": [[{"xAxis": a}, {"xAxis": b}],
                              [{"yAxis": a}, {"yAxis": b}]]}

    填充取主题主色低透明度；category 轴向两侧各扩半个 band。

    **仅在 Grid 直角坐标系下生效**（``layout`` 里 ``isinstance(coord,
    GridCoord)`` 不成立就静默返回空）。ECharts 的 markArea 依赖轴的
    ``coord`` 换算，polar / calendar / singleAxis 的区间语义与矩形不等价，
    本库不做近似 —— 所以挂在饼图 / 雷达这类系列上是不画，而不是画错。
    """

    optionKey = "markArea"

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._areas = []  # [QRectF]

    def layout(self, rect: QRectF) -> None:
        self._areas = []
        if not self._visible():
            return
        coord = self._coord()
        if not isinstance(coord, GridCoord):
            return
        plot = coord.plot
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
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
                y0 = coord.y_axis.map(
                    _to_float(a["yAxis"], 0.0), plot.bottom(), plot.top()
                )
                y1 = coord.y_axis.map(
                    _to_float(b["yAxis"], 0.0), plot.bottom(), plot.top()
                )
                area = QRectF(plot.left(), min(y0, y1), plot.width(), abs(y1 - y0))
            if area is not None:
                self._areas.append(area.intersected(plot))

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._areas or not self._visible():
            return
        p.save()
        fill = QColor(T("color.primary"))
        fill.setAlpha(28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        for area in self._areas:
            p.drawRect(area)
        p.restore()

    def hitTest(self, pos: QPointF):
        """命中半透明背景区域。

        **刻意不接进图表的命中分发**（``core._HOVERABLE_COMPONENTS`` 里没有
        ``markArea``）：markArea 是铺在数据**底下**的大块半透明区间，接进来
        之后「悬停区间内任何位置」都会抢走系列的悬停 —— 柱子 / 折线在区间内
        就再也高亮不了，是明确的退化。ECharts 侧 markArea 同样不参与命中。
        保留本方法是为了让「不参与」是**显式选择**而不是「忘了接」。
        """
        for area in self._areas:
            if area.contains(pos):
                r = self._renderer()
                return {
                    "name": "markArea",
                    "value": None,
                    "series": r.name if r is not None else "markArea",
                }
        return None
