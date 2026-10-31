"""仪表盘系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPen,
    QPolygonF,
)

from .._tokens import T
from .._utils import clamp as _clamp
from .._utils import merged_text_style, text_italic, text_weight
from .._utils import to_float as _to_float
from .._utils import parse_color
from ..axes import chartFont, formatValue
from ..core import SeriesRenderer
from ._shared import _dist, _label_font, _parse_named_values, _parse_pct, _text_color


class GaugeSeriesRenderer(SeriesRenderer):
    """仪表盘。

    支持 ``data`` / ``min`` / ``max`` / ``startAngle`` / ``endAngle`` /
    ``radius`` / ``progress`` / ``axisLine`` / ``pointer`` / ``anchor`` /
    ``detail`` / ``title``。ECharts 角度约定：0° 在 3 点方向、逆时针为正，
    默认 225 / -45（开口在底部）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._center = QPointF()
        self._radius = 1.0
        self._value = 0.0
        self._entries = []

    def _vmin(self):
        return _to_float(self.opt.get("min"), 0.0)

    def _vmax(self):
        v0, v1 = self._vmin(), _to_float(self.opt.get("max"), 100.0)
        return v1 if v1 > v0 else v0 + 1.0

    @staticmethod
    def _to_internal_angle(a):
        """ECharts 角度（0=3 点、逆时针为正）→ 内部角度（0=3 点、顺时针为正）。"""
        return -_to_float(a, 0.0)

    def _start_angle(self):
        """内部起始角（默认 ECharts 225° → 内部 -225° = 左下）。"""
        return self._to_internal_angle(self.opt.get("startAngle", 225.0))

    def _end_angle(self):
        """内部终止角（默认 ECharts -45° → 内部 45° 右下，归一化 > start）。"""
        e = self._to_internal_angle(self.opt.get("endAngle", -45.0))
        s = self._start_angle()
        while e <= s:
            e += 360.0
        return e

    def layout(self, rect: QRectF) -> None:
        self._center = rect.center()
        half = min(rect.width(), rect.height()) / 2
        self._radius = max(
            12.0, _parse_pct(self.opt.get("radius", "75%"), half, half) - 8.0
        )
        self._entries = _parse_named_values(self.data())
        self._value = self._entries[0][2] if self._entries else self._vmin()

    # 屏幕坐标：a 为自 3 点方向顺时针度数
    def _pt(self, a_deg, r):
        rad = math.radians(a_deg)
        return QPointF(
            self._center.x() + r * math.cos(rad), self._center.y() + r * math.sin(rad)
        )

    def _value_angle(self, v):
        f = _clamp((v - self._vmin()) / (self._vmax() - self._vmin()), 0.0, 1.0)
        return self._start_angle() + (self._end_angle() - self._start_angle()) * f

    def _arc(self, p, a_hi, a_lo, r, width, color):
        """绘制内部角度下自 a_lo 顺时针扫到 a_hi 的圆弧（pen 宽度 width）。"""
        a_lo, a_hi = min(a_lo, a_hi), max(a_lo, a_hi)
        if a_hi <= a_lo or r <= 0:
            return
        rect = QRectF(self._center.x() - r, self._center.y() - r, 2 * r, 2 * r)
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, int(-a_lo * 16), int((a_lo - a_hi) * 16))

    def paint(self, p: QPainter, anim_t: float) -> None:
        p.save()
        start, end = self._start_angle(), self._end_angle()
        # 动画：旧值 → 新值（过渡）；首帧从 min 摆起
        prev_v = self._vmin()
        prev_entries = _parse_named_values(self.prev_data)
        if prev_entries:
            prev_v = prev_entries[0][2]
        cur_v = prev_v + (self._value - prev_v) * anim_t
        cur_a = self._value_angle(cur_v)
        r = self._radius
        # 背景分段色弧
        axis_opt = dict(self.opt.get("axisLine") or {})
        line_style = dict(axis_opt.get("lineStyle") or {})
        width = _to_float(line_style.get("width"), 12.0)
        segments = line_style.get("color")
        r_arc = r - width / 2
        if isinstance(segments, list) and segments:
            segs = []
            for item in segments:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    segs.append(
                        (
                            _clamp(_to_float(item[0], 0.0), 0.0, 1.0),
                            parse_color(str(item[1])),
                        )
                    )
            segs.sort(key=lambda s: s[0])
            prev_frac = 0.0
            last_color = segs[-1][1]
            for frac, color in segs:
                a1 = start + (end - start) * prev_frac
                a2 = start + (end - start) * frac
                self._arc(p, a1, a2, r_arc, width, color)
                prev_frac = frac
            if prev_frac < 1.0:
                a1 = start + (end - start) * prev_frac
                self._arc(p, a1, end, r_arc, width, last_color)
        else:
            self._arc(p, start, end, r_arc, width, _text_color("color.border"))
        # 进度弧
        prog_opt = dict(self.opt.get("progress") or {})
        if bool(prog_opt.get("show", False)):
            pw = _to_float(prog_opt.get("width"), width)
            self._arc(
                p, max(start, cur_a), min(start, cur_a), r - pw / 2, pw, self.color()
            )
        # 指针
        ptr_opt = dict(self.opt.get("pointer") or {})
        if bool(ptr_opt.get("show", True)):
            plen = _parse_pct(ptr_opt.get("length", "60%"), r, r * 0.6)
            pwid = _to_float(ptr_opt.get("width"), 4.0)
            tip = self._pt(cur_a, plen)
            back = self._pt(cur_a + 180, 14.0)
            perp = math.radians(cur_a + 90)
            px, py = math.cos(perp) * pwid / 2, math.sin(perp) * pwid / 2
            poly = QPolygonF(
                [
                    tip,
                    QPointF(self._center.x() + px, self._center.y() + py),
                    back,
                    QPointF(self._center.x() - px, self._center.y() - py),
                ]
            )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.color())
            p.drawPolygon(poly)
        # 中心小圆
        anchor_opt = dict(self.opt.get("anchor") or {})
        if bool(anchor_opt.get("show", True)):
            size = _to_float(anchor_opt.get("size"), 10.0)
            p.setPen(QPen(QColor(T("color.bg.elevated")), 2))
            p.setBrush(self.color())
            p.drawEllipse(self._center, size / 2, size / 2)
        # 中央数值 + 名称
        detail_opt = dict(self.opt.get("detail") or {})
        fm_h = 0.0
        if bool(detail_opt.get("show", True)):
            detail_style = self.detailStyle()
            font = chartFont(
                detail_style.get("fontSize") or T("font.title.md"),
                text_weight(detail_style.get("fontWeight"), T("font.weight.semibold")),
                detail_style.get("fontFamily"),
                text_italic(detail_style.get("fontStyle")),
            )
            p.setFont(font)
            fm = QFontMetricsF(font)
            fm_h = fm.height()
            p.setPen(
                parse_color(detail_style.get("color"))
                if isinstance(detail_style.get("color"), str)
                and detail_style.get("color")
                else _text_color("color.text.primary")
            )
            p.drawText(
                QRectF(
                    self._center.x() - r,
                    self._center.y() + r * 0.22,
                    2 * r,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._detail_text(cur_v),
            )
        title_opt = dict(self.opt.get("title") or {})
        name = self._entries[0][0] if self._entries else self.name
        if bool(title_opt.get("show", True)) and name:
            font = _label_font(self, title_opt)
            p.setFont(font)
            fm2 = QFontMetricsF(font)
            title_style = self.titleStyle()
            p.setPen(
                parse_color(title_style.get("color"))
                if isinstance(title_style.get("color"), str)
                and title_style.get("color")
                else _text_color("color.text.secondary")
            )
            p.drawText(
                QRectF(
                    self._center.x() - r,
                    self._center.y() + r * 0.22 + fm_h + 4,
                    2 * r,
                    fm2.height(),
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                name,
            )
        p.restore()

    def detailStyle(self) -> dict:
        """中央数值样式（``detail`` 的 fontSize / fontWeight / color）。"""
        return merged_text_style(self.chart, self.opt.get("detail"))

    def titleStyle(self) -> dict:
        """名称样式（``title`` 的 fontSize / fontWeight / color）。"""
        return merged_text_style(self.chart, self.opt.get("title"))

    def _detail_text(self, value) -> str:
        """中央数值文案（``detail.formatter``：callable 或含 ``{value}`` 的模板）。"""
        detail = self.opt.get("detail")
        formatter = detail.get("formatter") if isinstance(detail, dict) else None
        if callable(formatter):
            try:
                out = formatter(value)
            except Exception:
                out = None
            if out is not None:
                return str(out)
        elif isinstance(formatter, str):
            return formatter.replace("{value}", formatValue(value))
        return formatValue(value)

    def hitTest(self, pos: QPointF):
        d = _dist(pos, self._center)
        if d > self._radius + 6:
            return None
        if d > 12:
            a = math.degrees(
                math.atan2(pos.y() - self._center.y(), pos.x() - self._center.x())
            )
            start, end = self._start_angle(), self._end_angle()
            rel = (a - start) % 360.0
            if rel > (end - start) + 1e-6:
                return None
        name = self._entries[0][0] if self._entries else self.name
        return {"name": name, "value": self._value, "series": self.name}
