"""热力图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._tokens import T
from .._utils import parse_color, to_float as _to_float
from ..axes import CalendarCoord, GridCoord, formatValue
from ..core import SeriesRenderer
from ._shared import (
    _axis_label,
    _ramp_color,
    label_rotate,
    paint_label_in,
)


class HeatmapSeriesRenderer(SeriesRenderer):
    """热力图。

    Grid 直角：x/y 轴均为 category，数据项 [x, y, value]，按 band 填格。日历：
    ``coordinateSystem: "calendar"``，数据项 [日期, value]，无数据日铺浅色底格。
    色带默认 ``color.primary.subtle`` → ``color.primary``，有 ``visualMap`` 时按其
    min/max 与 ``inRange.colors`` 映射。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._cells = []  # [dict(rect, value, label, color[, text, title])]
        self._calendar = False
        self._empty_color = None
        self._cell_gap = 1.0
        self._cell_radius = 2.0

    # -- 数据 -------------------------------------------------------------
    def _parse_items(self):
        """→ [(x, y, value, text, style)]（日历模式 y 为 None，x 为日期）。"""
        out = []
        for item in self.data():
            text = None
            if isinstance(item, dict):
                v = item.get("value")
                tooltip = item.get("tooltip")
                if isinstance(tooltip, dict):
                    fmt = tooltip.get("formatter")
                    if isinstance(fmt, str):
                        text = fmt
            else:
                v = item
            if not isinstance(v, (list, tuple)) or len(v) < 2:
                continue
            style = self.itemStyleOf(item)
            if self._calendar:
                val = _to_float(v[1], None)
                if val is not None:
                    out.append((v[0], None, val, text, style))
            else:
                if len(v) < 3:
                    continue
                val = _to_float(v[2], None)
                if val is not None:
                    out.append((v[0], v[1], val, text, style))
        return out

    def _colors_and_range(self, items):
        """→ (colors, vmin, vmax)：visualMap 优先，否则默认色带 + 数据范围。

        必须读组件实例的活值：``calculable`` 拖动改的是实例 min/max，读 option
        静态值会让拖动完全不改配色。
        """
        vm = self.visualMapComponent()
        colors = None
        vmin = vmax = None
        if vm is not None:
            try:
                colors = vm.colors()
            except Exception:
                colors = None
            vmin = _to_float(getattr(vm, "min", None), None)
            vmax = _to_float(getattr(vm, "max", None), None)
        if colors is None:
            raw = self.chart._option_ref().get("visualMap")
            if isinstance(raw, dict):
                in_range = raw.get("inRange") or {}
                if isinstance(in_range.get("colors"), list) and in_range["colors"]:
                    colors = in_range["colors"]
        if colors is None:
            colors = [T("color.primary.subtle"), T("color.primary")]
        vals = [v for _, _, v, _, _ in items]
        if vmin is None:
            vmin = min(vals) if vals else 0.0
        if vmax is None:
            vmax = max(vals) if vals else 1.0
        return colors, vmin, vmax

    def _load_calendar_style(self, coord) -> None:
        """读取日历外观：``calendar.itemStyle`` 控制空日底色与格子间距 / 圆角。"""
        style = coord.itemStyle() if hasattr(coord, "itemStyle") else {}
        raw_empty = style.get("color")
        if isinstance(raw_empty, str) and raw_empty.lower() in ("none", "transparent"):
            self._empty_color = None
        elif raw_empty:
            color = parse_color(raw_empty)
            self._empty_color = (
                color if color.isValid() else QColor(T("color.bg.muted"))
            )
        else:
            self._empty_color = QColor(T("color.bg.muted"))
        series_style = self.itemStyle()
        try:
            self._cell_gap = max(0.0, float(series_style.get("borderWidth", 1.0)))
        except (TypeError, ValueError, OverflowError):
            self._cell_gap = 1.0
        try:
            self._cell_radius = max(0.0, float(series_style.get("borderRadius", 2.0)))
        except (TypeError, ValueError, OverflowError):
            self._cell_radius = 2.0

    def _calendar_cells(self, coord, data_map, colors, vmin, vmax) -> list:
        """范围内全部日期 → 单元格（无数据日为底色格，可命中）。"""
        gap = self._cell_gap
        span = vmax - vmin
        cells = []
        for day in coord.iterDates():
            rect = coord.cellRect(day)
            if rect.isNull():
                continue
            cell = rect.adjusted(gap, gap, -gap, -gap)
            entry = data_map.get(day)
            if entry is None:
                cells.append(
                    {
                        # 空日不是数据项：dataIndex 必须为 None（拿「日序号」冒充
                        # 会让事件的 dataIndex 与 series.data 完全对不上）。
                        "index": None,
                        "rect": cell,
                        "value": None,
                        "label": day.isoformat(),
                        "color": self._empty_color,
                        "title": day.isoformat(),
                        "tooltipFormatter": None,
                        "empty": True,
                    }
                )
                continue
            value, text, item_style, data_index = entry
            t = 0.5 if span == 0 else (value - vmin) / span
            raw = item_style.get("color")
            color = (
                parse_color(raw)
                if isinstance(raw, str) and raw
                else _ramp_color(colors, t)
            )
            border_color, border_w = self.itemBorder(data_index)
            if border_color is None and border_w <= 0:
                raw_border = item_style.get("borderColor")
                try:
                    raw_width = float(item_style.get("borderWidth", 0))
                except (TypeError, ValueError, OverflowError):
                    raw_width = 0.0
                if isinstance(raw_border, str) and raw_border:
                    border_color = parse_color(raw_border)
                    border_w = max(0.0, raw_width)
            cells.append(
                {
                    "index": data_index,
                    "rect": cell,
                    "value": value,
                    "label": day.isoformat(),
                    "color": color,
                    "border": (border_color, border_w),
                    "title": day.isoformat(),
                    "tooltipFormatter": text,
                    "empty": False,
                }
            )
            data_index += 1
        return cells

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._cells = []
        coord = self.chart.coordFor(self.opt)
        self._calendar = isinstance(coord, CalendarCoord)
        items = self._parse_items()
        if not items or coord is None:
            return
        colors, vmin, vmax = self._colors_and_range(items)
        span = vmax - vmin
        if self._calendar:
            self._load_calendar_style(coord)
            data_map = {}
            for data_index, (x, _y, val, text, style) in enumerate(items):
                day = coord._parse_date(x)
                if day is not None:
                    data_map[day] = (val, text, style, data_index)
            self._cells = self._calendar_cells(coord, data_map, colors, vmin, vmax)
            return
        for data_index, (x, y, val, text, _style) in enumerate(items):
            if not isinstance(coord, GridCoord):
                continue
            t = 0.5 if span == 0 else (val - vmin) / span
            color = _ramp_color(colors, t)
            px = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
            py = coord.y_axis.map(y, coord.plot.bottom(), coord.plot.top())
            bw = coord.x_axis.bandWidth(coord.plot.left(), coord.plot.right()) or 10.0
            bh = coord.y_axis.bandWidth(coord.plot.bottom(), coord.plot.top()) or 10.0
            label = f"{_axis_label(coord.x_axis, x)}, {_axis_label(coord.y_axis, y)}"
            cell = QRectF(px - bw / 2 + 1, py - bh / 2 + 1, bw - 2, bh - 2)
            border_color, border_w = self.itemBorder(data_index)
            self._cells.append(
                {
                    "index": data_index,
                    "rect": cell,
                    "value": val,
                    "label": label,
                    "color": self.itemColor(data_index, default=color),
                    "border": (border_color, border_w),
                    "tooltipFormatter": text,
                    "empty": False,
                }
            )

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._cells:
            return
        p.save()
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        show_label = self.labelShown()
        if show_label:
            font = self.labelFont()
            p.setFont(font)
            fm = QFontMetricsF(font)
            label_color = self.labelColor()
            label_rotate_angle = label_rotate(self.labelOption())
        radius = self._cell_radius if self._calendar else 0.0
        for cell in self._cells:
            color = cell["color"]
            if color is None:
                continue
            c = self._cell_fill_color(cell, hovered, anim_t)
            border_color, border_w = cell.get("border", (None, 0))
            if hovered is not None and cell.get("index") == hovered:
                # 仅高亮悬浮格：不加粗描边、不淡化其余格（避免快速移动整图闪烁）
                if border_color is None or border_w <= 0:
                    border_color = c.darker(130)
                    border_w = 1.0
            if border_color is not None and border_w > 0:
                p.setPen(QPen(border_color, border_w))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            if radius:
                p.drawRoundedRect(cell["rect"], radius, radius)
            else:
                p.drawRect(cell["rect"])
            if show_label and cell["value"] is not None:
                text = formatValue(cell["value"])
                rect = cell["rect"]
                if (
                    rect.width() >= fm.horizontalAdvance(text) + 4
                    and rect.height() >= fm.height()
                ):
                    p.setPen(label_color)
                    paint_label_in(
                        p,
                        rect,
                        text,
                        label_rotate_angle,
                        Qt.AlignmentFlag.AlignCenter,
                    )
        p.restore()

    def _cell_fill_color(self, cell: dict, hovered, anim_t: float) -> QColor:
        """单元格填充色：仅命中格加亮（``emphasis.itemStyle.color`` 可覆盖），其余保持原样。"""
        index = cell.get("index")
        if hovered is not None and index == hovered:
            emphasis = self.emphasisColor(index)
            color = (
                parse_color(emphasis)
                if emphasis is not None
                else parse_color(cell["color"]).lighter(112)
            )
        else:
            color = parse_color(cell["color"])
            blur = self.blurOpacity()
            if hovered is not None and blur is not None and self.blursOtherItems():
                color.setAlphaF(color.alphaF() * blur)
        alpha = self.itemOpacity(index)
        color.setAlpha(int(255 * max(0.15, anim_t) * alpha))
        return color

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        for cell in self._cells:
            if cell["rect"].adjusted(-1, -1, 1, 1).contains(pos):
                return {
                    "name": cell["label"],
                    "value": cell["value"],
                    "series": self.name,
                    "dataIndex": cell.get("index"),
                    "title": cell.get("title"),
                    "tooltipFormatter": cell.get("tooltipFormatter"),
                }
        return None
