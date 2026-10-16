"""
图表标注组件与 map 系列。

本模块提供：

- ``MarkPointComponent``（optionKey="markPoint"，系列级）：
  最大 / 最小值或指定坐标的圆点 + 值文本标注。
- ``MarkLineComponent``（optionKey="markLine"，系列级）：
  平均值 / 最大 / 最小或指定 yAxis / xAxis 的虚线标线 + 端部标签。
- ``MarkAreaComponent``（optionKey="markArea"，系列级）：
  xAxis / yAxis 区间对的半透明标域（主题主色低透明度填充）。
- ``GraphicComponent``（optionKey="graphic"，顶层）：
  绝对定位图形元素（circle / rect / text / line）。
- ``MapSeriesRenderer``（经 ``registerSeries("map", ...)`` 注册）：
  简化地图系列，区域多边形着色 + 名称标签 + 命中检测。

内置演示地图 ``DEMO_MAP`` 为 7 个大区块的**示意轮廓**（自定义平面示意
坐标，非真实地理数据，不表示任何真实行政区划边界），仅用于功能演示；
真实使用请经 ``option["geo"]["regions"]`` 传入自定义多边形。

移植自 InstructionX_UIKit.charts.components（原库为 PyQt6；主题令牌
经 charts._tokens 适配到 eTheme / ElaThemeType，原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen, QPolygonF

from ._tokens import T
from ._utils import ON_FILL_WHITE, parse_roam as _parse_roam
from ._utils import to_float as _to_float, warn_once, with_alpha
from .axes import GridCoord, chartFont, formatValue
from .core import (
    SeriesRenderer,
    parseDataPoint,
    registerComponent,
    registerSeries,
)

__all__ = [
    "MarkPointComponent",
    "MarkLineComponent",
    "MarkAreaComponent",
    "GraphicComponent",
    "MapSeriesRenderer",
    "DEMO_MAP",
    "lerp_color",
]


def lerp_color(c1, c2, t: float) -> QColor:
    """两种颜色按 t ∈ [0,1] 线性插值（RGB 空间）。"""
    t = min(max(float(t), 0.0), 1.0)
    a, b = QColor(c1), QColor(c2)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


# ---------------------------------------------------------------------------
# 系列级标注组件基类
# ---------------------------------------------------------------------------


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

    def _points(self):
        """系列数据解析为 ``[(x, y)]``（跳过 None 值）。"""
        r = self._renderer()
        if r is None:
            return []
        out = []
        for i, item in enumerate(r.data()):
            x, y = parseDataPoint(item, i)
            if y is not None:
                out.append((x, y))
        return out

    def _color(self) -> QColor:
        """标注主色：跟随系列色（无系列时取主题主色）。"""
        r = self._renderer()
        if r is not None:
            return r.color()
        return QColor(T("color.primary"))

    def _visible(self) -> bool:
        r = self._renderer()
        return r is not None and r.visible


# ---------------------------------------------------------------------------
# markPoint
# ---------------------------------------------------------------------------


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
        pts = self._points()
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict):
                continue
            x = y = None
            typ = item.get("type")
            if typ in ("max", "min") and pts:
                x, y = (max if typ == "max" else min)(pts, key=lambda p: p[1])
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
            self._marks.append({"pos": pos, "text": str(label), "x": x, "y": y})

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._marks or not self._visible():
            return
        p.save()
        color = self._color()
        font = chartFont(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        for m in self._marks:
            pos = m["pos"]
            # 圆点（小旗式：实心圆 + 向上引线 + 值文本）
            p.setPen(QPen(QColor(T("color.bg.elevated")), 1.4))
            p.setBrush(color)
            p.drawEllipse(pos, 4.2, 4.2)
            top = QPointF(pos.x(), pos.y() - 14)
            p.setPen(QPen(color, 1.4))
            p.drawLine(QPointF(pos.x(), pos.y() - 4.5), top)
            p.setPen(QColor(T("color.text.primary")))
            tw = fm.horizontalAdvance(m["text"])
            p.drawText(
                QRectF(
                    pos.x() - tw / 2 - 2, top.y() - fm.height() - 2, tw + 4, fm.height()
                ),
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


# ---------------------------------------------------------------------------
# markLine
# ---------------------------------------------------------------------------

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
        pts = self._points()
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict):
                continue
            orient = value = None
            default_label = ""
            typ = item.get("type")
            if typ in _TYPE_LABELS and pts:
                vals = [y for _, y in pts]
                if typ == "average":
                    value = sum(vals) / len(vals)
                elif typ == "max":
                    value = max(vals)
                else:
                    value = min(vals)
                orient = "h"
                default_label = _TYPE_LABELS[typ]
            elif "yAxis" in item:
                value = _to_float(item.get("yAxis"), None)
                orient = "h"
            elif "xAxis" in item:
                value = item.get("xAxis")
                orient = "v"
            if orient is None or value is None:
                continue
            name = str(item.get("name") or default_label)
            vtxt = formatValue(value) if isinstance(value, (int, float)) else str(value)
            text = f"{name} {vtxt}" if name else vtxt
            self._lines.append({"orient": orient, "value": value, "text": text})

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._lines or not self._visible():
            return
        coord = self._coord()
        if not isinstance(coord, GridCoord):
            return
        plot = coord.plot
        p.save()
        color = self._color()
        pen = QPen(color, 1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        font = chartFont(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        for ln in self._lines:
            if ln["orient"] == "h":
                py = coord.y_axis.map(
                    _to_float(ln["value"], 0.0), plot.bottom(), plot.top()
                )
                p.setPen(pen)
                p.drawLine(QPointF(plot.left(), py), QPointF(plot.right(), py))
                p.setPen(color)
                p.drawText(
                    QRectF(plot.right() - 120, py - fm.height() - 3, 118, fm.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    ln["text"],
                )
            else:
                px = coord.x_axis.map(ln["value"], plot.left(), plot.right())
                p.setPen(pen)
                p.drawLine(QPointF(px, plot.top()), QPointF(px, plot.bottom()))
                p.setPen(color)
                p.drawText(
                    QRectF(px + 4, plot.top() + 3, 120, fm.height()),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    ln["text"],
                )
        p.restore()

    def hitTest(self, pos: QPointF):
        coord = self._coord()
        if not isinstance(coord, GridCoord):
            return None
        plot = coord.plot
        for ln in self._lines:
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


# ---------------------------------------------------------------------------
# markArea
# ---------------------------------------------------------------------------


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
            if "xAxis" in a and "xAxis" in b:
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


# ---------------------------------------------------------------------------
# graphic（绝对定位图形元素）
# ---------------------------------------------------------------------------


class GraphicComponent:
    """绝对定位图形元素：circle / rect / text / line。

    option（顶层）::

        "graphic": [
            {"type": "circle", "left": 40, "top": 40,
             "shape": {"cx": 0, "cy": 0, "r": 20},
             "style": {"fill": "#3F5E8C", "stroke": "#..."}},
            {"type": "rect", "left": "center", "top": 20,
             "shape": {"x": -40, "y": 0, "width": 80, "height": 24, "r": 4},
             "style": {"fill": "#..."}},
            {"type": "text", "left": 12, "top": 12,
             "style": {"text": "水印", "fill": "#98A0AC", "fontSize": 14}},
            {"type": "line", "left": 0, "top": 0,
             "shape": {"x1": 0, "y1": 0, "x2": 100, "y2": 40},
             "style": {"stroke": "#...", "lineWidth": 2}},
        ]

    ``left`` / ``top`` 为相对图表内容区的像素偏移，或 ``"center"``
    （水平 / 垂直居中锚点）；shape 内坐标相对该锚点。未知类型静默跳过。
    """

    optionKey = "graphic"

    def __init__(self, chart, opt):
        self.chart = chart
        if isinstance(opt, dict):
            opt = [opt]
        self.elements = [e for e in (opt or []) if isinstance(e, dict)]
        self.rect = QRectF()

    def layout(self, rect: QRectF) -> None:
        self.rect = QRectF(rect)

    def _anchor(self, el: dict) -> QPointF:
        """元素锚点：``left`` / ``top`` 解析成内容区内的绝对坐标。

        支持三类写法（ECharts 语义）：

        * 数值 —— 相对内容区左上角的**像素**偏移；
        * ``"center"`` —— 该轴居中；
        * ``"middle"`` —— 垂直居中（ECharts 官方拼写；``top: "middle"`` 是
          最常见的一处，原先只认 ``"center"`` 而静默按 0 处理 → 水印类
          纵向居中的文字全贴到顶边）；
        * ``"30%"`` —— 相对内容区宽 / 高的百分比。

        百分比与 ``"middle"`` 原先都落进 ``_to_float`` 的兜底分支（0），
        **不报错也不告警**，只是元素悄悄跑到左上角。
        """
        return QPointF(
            self._anchor_axis(el.get("left", 0), self.rect.left(), self.rect.width()),
            self._anchor_axis(el.get("top", 0), self.rect.top(), self.rect.height()),
        )

    def _anchor_axis(self, value, origin: float, extent: float) -> float:
        text = str(value).strip().lower()
        if text in ("center", "middle"):
            return origin + extent / 2.0
        if text.endswith("%"):
            try:
                return origin + extent * float(text[:-1]) / 100.0
            except ValueError:
                return origin
        if text in ("left", "top"):
            return origin
        if text in ("right", "bottom"):
            return origin + extent
        return origin + _to_float(value, 0.0)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self.elements:
            return
        p.save()
        for el in self.elements:
            typ = str(el.get("type") or "")
            shape = el.get("shape") or {}
            style = el.get("style") or {}
            base = self._anchor(el)
            try:
                self._paint_element(p, typ, shape, style, base)
            except Exception:
                continue  # 单元素异常不影响其他元素
        p.restore()

    def _paint_element(
        self, p: QPainter, typ: str, shape: dict, style: dict, base: QPointF
    ) -> None:
        if typ == "circle":
            cx = base.x() + _to_float(shape.get("cx"), 0.0)
            cy = base.y() + _to_float(shape.get("cy"), 0.0)
            r = _to_float(shape.get("r"), 20.0)
            self._apply_brush(p, style, default_fill=T("color.primary"))
            p.drawEllipse(QPointF(cx, cy), r, r)
        elif typ == "rect":
            x = base.x() + _to_float(shape.get("x"), 0.0)
            y = base.y() + _to_float(shape.get("y"), 0.0)
            w = _to_float(shape.get("width"), 40.0)
            h = _to_float(shape.get("height"), 24.0)
            radius = _to_float(shape.get("r"), 0.0)
            self._apply_brush(p, style, default_fill=T("color.primary.subtle"))
            if radius > 0:
                p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
            else:
                p.drawRect(QRectF(x, y, w, h))
        elif typ == "text":
            text = str(style.get("text") or "")
            if not text:
                return
            size = int(_to_float(style.get("fontSize"), T("font.xs")))
            p.setFont(chartFont(size))
            # ``fill: "none"`` 要跟 circle / rect 一样被认出来：直接喂给
            # ``QColor`` 会得到**无效颜色**，而无效 pen 的文字**根本不画**
            # —— 用户写「不要文字」结果得到空白，且没有任何报错。
            fill = style.get("fill")
            if fill == "none" or fill is False:
                return
            color = QColor(fill) if isinstance(fill, str) and fill else QColor()
            if not color.isValid():
                warn_once(
                    "graphic-text-fill", f"graphic text 的 fill 非法，已跳过: {fill!r}"
                )
                return
            p.setPen(color or QColor(T("color.text.primary")))
            p.setBrush(Qt.BrushStyle.NoBrush)
            fm = QFontMetricsF(p.font())
            x = base.x() + _to_float(shape.get("x"), 0.0)
            y = base.y() + _to_float(shape.get("y"), 0.0)
            p.drawText(
                QRectF(x, y, fm.horizontalAdvance(text) + 4, fm.height() + 2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                text,
            )
        elif typ == "line":
            x1 = base.x() + _to_float(shape.get("x1"), 0.0)
            y1 = base.y() + _to_float(shape.get("y1"), 0.0)
            x2 = base.x() + _to_float(shape.get("x2"), 40.0)
            y2 = base.y() + _to_float(shape.get("y2"), 0.0)
            stroke = QColor(style.get("stroke") or T("color.border.strong"))
            width = _to_float(style.get("lineWidth"), 2.0)
            p.setPen(QPen(stroke, width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    @staticmethod
    def _apply_brush(p: QPainter, style: dict, default_fill) -> None:
        fill = style.get("fill")
        stroke = style.get("stroke")
        if fill == "none" or fill is False:
            p.setBrush(Qt.BrushStyle.NoBrush)
        else:
            p.setBrush(QColor(fill or default_fill))
        if stroke:
            p.setPen(QPen(QColor(stroke), _to_float(style.get("lineWidth"), 1.0)))
        else:
            p.setPen(Qt.PenStyle.NoPen)

    def hitTest(self, pos: QPointF):
        """恒返回 None —— graphic 是**装饰元素**，不参与命中。

        ECharts 的 graphic 同为纯覆盖层（要交互得自己接 ``chart.on("click")``
        自己做坐标判定）。保留本方法只为把这个决定写成代码而不是留白：
        ``core`` 的命中分发只问 ``_HOVERABLE_COMPONENTS``，graphic 不在其中。
        """
        return None


# ---------------------------------------------------------------------------
# map 系列（geo 简化）
# ---------------------------------------------------------------------------

#: 内置演示地图：7 个大区块的示意多边形（自定义平面示意坐标系，
#: 非真实地理数据，不表示任何真实行政区划），仅供功能演示。
DEMO_MAP = {
    "华北": [(30, 18), (48, 14), (55, 24), (50, 34), (36, 32)],
    "东北": [(56, 4), (74, 6), (78, 20), (62, 26), (55, 18)],
    "华东": [(52, 36), (66, 34), (70, 48), (56, 52), (50, 44)],
    "华南": [(46, 56), (62, 54), (66, 68), (50, 72), (42, 64)],
    "华中": [(36, 36), (50, 36), (48, 52), (34, 50)],
    "西南": [(16, 40), (34, 38), (32, 58), (14, 60), (10, 48)],
    "西北": [(4, 10), (28, 12), (34, 34), (16, 38), (6, 28)],
}


class MapSeriesRenderer(SeriesRenderer):
    """简化地图系列（type="map"）。

    option::

        {"type": "map", "map": "demo"|自定义名, "nameProperty": "name",
         "data": [{"name": "华北", "value": 120, "itemStyle": {...}}, ...]}

    - ``map`` 为 ``"demo"``（或缺省）时使用内置示意地图 ``DEMO_MAP``；
    - 自定义地图经 ``option["geo"]["regions"] = {"名称": [[x, y], ...]}``
      传入多边形顶点列表（任意平面坐标，自动等比缩放到绘图区）；
    - 区域着色：优先经 ``chart.components`` 中 visualMap 组件的
      ``mapColor(v)``，其次 ``itemStyle.color``，否则按 primary.subtle →
      primary 色带插值；
    - ``nameProperty``：区域标签取自 data 项的该键（缺省 "name"）；
    - ``roam``：True / ``1`` / ``"true"`` / ``"scale"`` / ``"move"`` 控制滚轮
      缩放 + 拖拽平移（ECharts 语义；默认 False）；``zoom`` 初始缩放；
      ``resetRoam()`` 复位。**数字与布尔字符串都按 true 认** —— 从 JSON 读进
      来的 option 里 ``roam`` 常是数字，原先落进「方向名」分支被静默关掉。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._polys = []  # [(region_name, QPolygonF, data_index)]
        self._rect = QRectF()
        self._roam = _parse_roam(self.opt.get("roam", False))
        try:
            self._zoom = max(0.2, min(6.0, float(self.opt.get("zoom") or 1.0)))
        except (TypeError, ValueError, OverflowError):
            self._zoom = 1.0
        self._pan = QPointF()
        self._pan_start = None
        self._pan_origin = QPointF()
        self._panning = False

    def _index_map(self) -> dict:
        """区域名 → data 下标（itemStyle / 命中回传用）。"""
        out = {}
        for i, item in enumerate(self.data()):
            if isinstance(item, dict):
                name = str(item.get(self.opt.get("nameProperty") or "name") or "")
            else:
                name = str(item)
            out.setdefault(name, i)
        return out

    # -- 数据 ------------------------------------------------------------
    def _regions(self) -> dict:
        """当前生效的 {名称: [[x, y], ...]} 多边形字典。"""
        name = str(self.opt.get("map") or "demo")
        geo = (getattr(self.chart, "_option", {}) or {}).get("geo") or {}
        custom = geo.get("regions") if isinstance(geo, dict) else None
        if name not in ("demo", "china-simple") and isinstance(custom, dict) and custom:
            out = {}
            for k, poly in custom.items():
                pts = []
                for pt in poly or []:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        px = _to_float(pt[0], None)
                        py = _to_float(pt[1], None)
                        if px is not None and py is not None:
                            pts.append((px, py))
                if len(pts) >= 3:
                    out[str(k)] = pts
            if out:
                return out
        if name not in ("demo", "china-simple"):
            # **不要静默回落演示地图**。用户写了 ``map: "my-map"`` 却没给
            # ``geo.regions``，拿到的是内置的「华北 / 东北 / …」，而他的数据
            # 用的是真实地图的省名 —— 一个都匹配不上，整张图全是底色，且
            # 没有任何报错。回落保留（空图更难排查），但必须喊一声。
            warn_once(
                "map-regions-missing",
                f"map={name!r} 需要 option['geo']['regions'] 提供多边形顶点，"
                f"缺省已回落到内置演示地图（{len(DEMO_MAP)} 个区块）；"
                f"数据里的区域名多半匹配不上",
            )
        return {k: [tuple(pt) for pt in v] for k, v in DEMO_MAP.items()}

    def _value_map(self) -> dict:
        """data [{name, value}] → {区域名: 数值}（nameProperty 可改键）。"""
        key = str(self.opt.get("nameProperty") or "name")
        out = {}
        for item in self.data():
            if not isinstance(item, dict):
                continue
            nm = item.get(key, item.get("name"))
            v = _to_float(item.get("value"), None)
            if nm is not None:
                out[str(nm)] = v
        return out

    # -- 协议 ------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)
        self._polys = []
        regions = self._regions()
        if not regions:
            return
        xs = [pt[0] for pts in regions.values() for pt in pts]
        ys = [pt[1] for pts in regions.values() for pt in pts]
        if not xs or not ys:
            return
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        span_x = max(1e-6, x1 - x0)
        span_y = max(1e-6, y1 - y0)
        margin = 18.0
        avail_w = max(10.0, rect.width() - margin * 2)
        avail_h = max(10.0, rect.height() - margin * 2)
        scale = min(avail_w / span_x, avail_h / span_y) * self._zoom
        ox = rect.left() + (rect.width() - span_x * scale) / 2 + self._pan.x()
        oy = rect.top() + (rect.height() - span_y * scale) / 2 + self._pan.y()
        index_map = self._index_map()
        for name, pts in regions.items():
            poly = QPolygonF(
                [
                    QPointF(ox + (px - x0) * scale, oy + (py - y0) * scale)
                    for px, py in pts
                ]
            )
            self._polys.append((name, poly, index_map.get(name)))

    # -- 交互：缩放 / 平移（roam） ----------------------------------------
    def onWheel(self, event) -> bool:
        if not self._roam[0]:
            return False
        try:
            pos = (
                event.position() if hasattr(event, "position") else QPointF(event.position().toPoint())
            )
            delta = event.angleDelta().y()
        except Exception:
            return False
        if self._rect.isNull() or not self._rect.contains(pos):
            return False
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.2, min(6.0, self._zoom * factor))
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def onMousePress(self, pos: QPointF) -> bool:
        if not self._roam[1] or not self._rect.contains(pos):
            return False
        self._pan_start = QPointF(pos)
        self._pan_origin = QPointF(self._pan)
        self._panning = False
        return False  # 不消费点击：区域点击仍可触发 itemClicked

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._pan_start is None:
            return False
        dx = pos.x() - self._pan_start.x()
        dy = pos.y() - self._pan_start.y()
        if not self._panning and abs(dx) + abs(dy) < 3.0:
            return False
        self._panning = True
        self._pan = self._pan_origin + QPointF(dx, dy)
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def onMouseRelease(self, pos: QPointF) -> bool:
        was_panning = self._panning
        self._pan_start = None
        self._panning = False
        return was_panning

    def resetRoam(self) -> None:
        """复位缩放与平移。"""
        self._zoom = 1.0
        self._pan = QPointF()
        self.chart.invalidateLayout()
        self.chart.update()

    def _visual_map(self):
        """本系列该用哪个 visualMap 组件（``None`` = 用内置色带）。

        **必须按绑定挑，不能取「第一个带 mapColor 的」**：原先那条规则让多个
        map / heatmap 系列**共用同一个** visualMap —— 给第二个系列配的独立
        色带（``inRange.colors``）永远不生效，表现为「明明配了两套配色，
        两张图却是同一个颜色」。
        优先级：显式绑定本系列的 → 未绑定的通用件 → 没有。
        """
        idx = getattr(self, "_series_index", 0)
        sid = str(self.opt.get("id") or "")
        generic = None
        for c in self.chart.components:
            mapper = getattr(c, "mapColor", None)
            if not callable(mapper):
                continue
            binds = getattr(c, "bindsTo", None)
            if not callable(binds):
                # 自定义组件没有绑定语义：按「第一个」处理（保持旧行为）
                return c
            if not binds(idx, sid):
                continue
            if getattr(c, "isGeneric", False):
                if generic is None:
                    generic = c
                continue
            return c
        return generic

    def _fill_color(
        self, name: str, values: dict, vmin: float, vmax: float, vm
    ) -> QColor:
        v = values.get(name)
        if v is None:
            return QColor(T("color.bg.muted"))
        if vm is not None:
            try:
                return QColor(vm.mapColor(v))
            except Exception:
                pass
        span = vmax - vmin
        frac = 0.5 if span == 0 else (v - vmin) / span
        return lerp_color(T("color.primary.subtle"), T("color.primary"), frac)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._polys:
            return
        values = self._value_map()
        vals = [v for v in values.values() if v is not None]
        vmin = min(vals) if vals else 0.0
        vmax = max(vals) if vals else 1.0
        vm = self._visual_map()
        p.save()
        font = chartFont(T("font.xs"))
        p.setFont(font)
        border = QPen(QColor(T("color.border.strong")), 1)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for name, poly, data_index in self._polys:
            fill = self._fill_color(name, values, vmin, vmax, vm)
            if data_index is not None:
                override = self.itemColor(data_index, default=fill)
                if override != fill:
                    fill = override
            if hovered is not None and data_index is not None:
                if data_index == hovered:
                    fill = QColor(fill).lighter(112)
                else:
                    fill = with_alpha(QColor(fill), 150)
            p.setPen(border)
            p.setBrush(fill)
            p.drawPolygon(poly)
            # 区域名称标签（多边形包围盒中心，按底色亮度选文字色）
            c = poly.boundingRect().center()
            if fill.lightness() < 130:
                p.setPen(QColor(ON_FILL_WHITE))
            else:
                p.setPen(QColor(T("color.text.primary")))
            label = name
            p.drawText(
                QRectF(c.x() - 40, c.y() - 8, 80, 16),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        p.restore()

    def hitTest(self, pos: QPointF):
        values = self._value_map()
        for name, poly, data_index in reversed(self._polys):
            if poly.containsPoint(pos, Qt.FillRule.OddEvenFill):
                return {
                    "name": name,
                    "value": values.get(name),
                    "series": self.name,
                    "dataIndex": data_index,
                }
        return None

    def valueAtIndex(self, index: int):
        return None


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registerComponent("markPoint", MarkPointComponent)
registerComponent("markLine", MarkLineComponent)
registerComponent("markArea", MarkAreaComponent)
registerComponent("graphic", GraphicComponent)
registerSeries("map", MapSeriesRenderer)
