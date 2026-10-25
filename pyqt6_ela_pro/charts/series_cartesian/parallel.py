"""平行坐标系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

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
from .._utils import dist_point_segment
from .._utils import merged_text_style, text_italic, text_weight
from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_color
from ..axes import chartFont, formatValue
from ..core import SeriesRenderer
from ._shared import _datum_list, _lerp


class ParallelSeriesRenderer(SeriesRenderer):
    """平行坐标：自带多条垂直轴，每行数据一条折线穿轴，半透明多系列。

    维度名来源：顶层 option ``parallelAxis``（[{"name":..,"min":..,"max":..}
    或字符串列表]）；缺省时若本系列 data 第一行全为字符串则取其为维度名
    （该行不参与绘制），否则自动生成 dim0..dimN。
    数据：每行一个等长数值列表。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._axes = []  # [dict(name, x, vmin, vmax)]（vmin/vmax 数据范围）
        self._rows = []  # [dict(pts=[QPointF], values=[float], index)]
        self._area = QRectF()

    # -- 维度 -------------------------------------------------------------
    def _raw_rows(self):
        rows = []
        for item in self.data():
            nums = _datum_list(item)
            if nums is not None:
                rows.append(nums)
                continue
            v = item.get("value") if isinstance(item, dict) else item
            if (
                isinstance(v, (list, tuple))
                and v
                and all(isinstance(x, str) for x in v)
            ):
                rows.append(list(v))  # 字符串行：候选维度名
        return rows

    def _dims(self, rows):
        pa = self.chart._option_ref().get("parallelAxis")
        dims = []
        if isinstance(pa, list) and pa:
            for d in pa:
                if isinstance(d, dict):
                    dims.append(
                        {
                            "name": str(d.get("name") or f"dim{len(dims)}"),
                            "min": _to_float(d.get("min"), None),
                            "max": _to_float(d.get("max"), None),
                            "nameStyle": d.get("nameTextStyle"),
                            "labelStyle": d.get("axisLabel"),
                        }
                    )
                else:
                    dims.append(
                        {
                            "name": str(d),
                            "min": None,
                            "max": None,
                            "nameStyle": None,
                            "labelStyle": None,
                        }
                    )
            return dims, rows
        if rows and all(isinstance(x, str) for x in rows[0]):
            names = rows[0]
            return [
                {"name": n, "min": None, "max": None, "nameStyle": None, "labelStyle": None}
                for n in names
            ], rows[1:]
        n = max((len(r) for r in rows), default=0)
        return [
            {
                "name": f"dim{i}",
                "min": None,
                "max": None,
                "nameStyle": None,
                "labelStyle": None,
            }
            for i in range(n)
        ], rows

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._axes = []
        self._rows = []
        rows = self._raw_rows()
        dims, rows = self._dims(rows)
        rows = [r for r in rows if all(_to_float(x, None) is not None for x in r)]
        if not dims or not rows:
            return
        n = len(dims)
        self._area = QRectF(
            rect.left() + 40,
            rect.top() + 34,
            max(40.0, rect.width() - 80),
            max(30.0, rect.height() - 34 - 26),
        )
        for j, dim in enumerate(dims):
            x = self._area.left() + (
                self._area.width() * j / (n - 1) if n > 1 else self._area.width() / 2
            )
            col = [r[j] for r in rows if j < len(r)]
            lo = dim["min"] if dim["min"] is not None else (min(col) if col else 0.0)
            hi = dim["max"] if dim["max"] is not None else (max(col) if col else 1.0)
            if lo == hi:
                hi = lo + 1.0
            self._axes.append(
                {
                    "name": dim["name"],
                    "x": x,
                    "vmin": lo,
                    "vmax": hi,
                    "nameStyle": dim.get("nameStyle"),
                    "labelStyle": dim.get("labelStyle"),
                }
            )
        for i, r in enumerate(rows):
            pts = []
            for j, ax in enumerate(self._axes):
                v = r[j] if j < len(r) else ax["vmin"]
                f = (v - ax["vmin"]) / (ax["vmax"] - ax["vmin"])
                f = max(0.0, min(1.0, f))
                pts.append(
                    QPointF(ax["x"], self._area.bottom() - f * self._area.height())
                )
            self._rows.append({"pts": pts, "values": list(r), "index": i})

    @staticmethod
    def _axis_label_shown(ax: dict) -> bool:
        """该维度的 ``axisLabel.show``（默认 True）。"""
        label = ax.get("labelStyle")
        return not (isinstance(label, dict) and label.get("show", True) is False)

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._axes:
            return
        p.save()
        # 兜底 grid 坐标系对平行坐标无意义，覆盖其轴线背景
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T("color.bg.base")))
        p.drawRect(
            QRectF(
                self._area.left() - 40,
                self._area.top() - 34,
                self._area.width() + 80,
                self._area.height() + 60,
            )
        )
        color = self.color()
        # lineStyle：{"color", "width", "opacity"}（ECharts parallel 语义）
        line_style = self.opt.get("lineStyle") or {}
        if isinstance(line_style.get("color"), str) and line_style["color"]:
            color = parse_color(line_style["color"])
        try:
            width = max(0.5, float(line_style.get("width", 1.6)))
        except (TypeError, ValueError, OverflowError):
            width = 1.6
        try:
            opacity = max(0.0, min(1.0, float(line_style.get("opacity", 110 / 255.0))))
        except (TypeError, ValueError, OverflowError):
            opacity = 110 / 255.0
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        # 数据线（半透明，多条重叠可见；hover 高亮当前行、淡化其他）
        pen = QPen(with_alpha(color, int(255 * opacity)), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        reveal = max(0.0, min(1.0, anim_t))
        for row in self._rows:
            pts = row["pts"]
            if len(pts) < 2:
                continue
            if hovered is not None:
                if row["index"] == hovered:
                    p.setPen(QPen(color.lighter(112), width + 0.6))
                elif row["index"] != hovered:
                    p.setPen(QPen(with_alpha(color, int(255 * opacity * 0.25)), width))
            if reveal < 1.0:
                # 入场：按进度自左向右揭示
                total = len(pts) - 1
                upto = reveal * total
                seg = []
                for k, pt in enumerate(pts):
                    if k <= int(upto):
                        seg.append(pt)
                    elif k == int(upto) + 1:
                        f = upto - int(upto)
                        seg.append(
                            QPointF(
                                _lerp(pts[k - 1].x(), pt.x(), f),
                                _lerp(pts[k - 1].y(), pt.y(), f),
                            )
                        )
                if len(seg) >= 2:
                    p.drawPolyline(QPolygonF(seg))
            else:
                p.drawPolyline(QPolygonF(pts))
        # 轴 + 标签（``parallelAxis[].nameTextStyle`` / ``axisLabel``）
        c_axis = QColor(T("color.border.strong"))
        for ax in self._axes:
            raw_label = ax.get("labelStyle")
            raw_label = raw_label if isinstance(raw_label, dict) else {}
            name_style = merged_text_style(self.chart, ax.get("nameStyle"))
            label_style = merged_text_style(self.chart, raw_label)
            name_font = chartFont(
                name_style.get("fontSize", T("font.xs")),
                text_weight(name_style.get("fontWeight")),
                name_style.get("fontFamily"),
                text_italic(name_style.get("fontStyle")),
            )
            label_font = chartFont(
                label_style.get("fontSize", T("font.xs")),
                text_weight(label_style.get("fontWeight")),
                label_style.get("fontFamily"),
                text_italic(label_style.get("fontStyle")),
            )
            name_fm = QFontMetricsF(name_font)
            label_fm = QFontMetricsF(label_font)
            p.setPen(QPen(c_axis, 1))
            p.drawLine(
                QPointF(ax["x"], self._area.top()),
                QPointF(ax["x"], self._area.bottom()),
            )
            p.setFont(name_font)
            p.setPen(parse_color(name_style.get("color") or T("color.text.secondary")))
            p.drawText(
                QRectF(
                    ax["x"] - 50,
                    self._area.top() - name_fm.height() - 6,
                    100,
                    name_fm.height(),
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                ax["name"],
            )
            if not self._axis_label_shown(ax):
                continue
            p.setFont(label_font)
            p.setPen(parse_color(label_style.get("color") or T("color.text.secondary")))
            p.drawText(
                QRectF(ax["x"] - 50, self._area.top() + 2, 100, label_fm.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                formatValue(ax["vmax"]),
            )
            p.drawText(
                QRectF(
                    ax["x"] - 50,
                    self._area.bottom() - label_fm.height() - 2,
                    100,
                    label_fm.height(),
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                formatValue(ax["vmin"]),
            )
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        best = None
        best_d = 6.0
        for row in self._rows:
            pts = row["pts"]
            for a, b in zip(pts, pts[1:]):
                d = dist_point_segment(pos, a, b)
                if d <= best_d:
                    best_d = d
                    best = row
        if best is None:
            return None
        return {
            "name": f"{self.name} #{best['index']}",
            "value": best["values"],
            "series": self.name,
            "dataIndex": best["index"],
        }
