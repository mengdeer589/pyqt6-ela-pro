"""饼图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)

from .._tokens import T
from .._utils import ON_FILL_WHITE, clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import parse_color
from ..axes import chartFont, formatValue
from ..core import SeriesRenderer, formatLabelTemplate
from ._shared import (
    _label_font,
    _parse_named_values,
    _parse_pct,
    _series_palette_color,
    _text_color,
)


class PieSeriesRenderer(SeriesRenderer):
    """饼 / 环形 / 南丁格尔玫瑰图。

    option 键（系列级）：
    - ``data``: [{"name","value"}, ...] 或数值列表；
    - ``radius``: "75%" / px / ["40%","70%"]（内外半径，环形）；
    - ``center``: ["50%","50%"]（相对内容区）；
    - ``startAngle``: 起始角（ECharts 角度约定：0 = 3 点方向、逆时针；
      默认 90 = 12 点方向）；
    - ``roseType``: "radius"（半径映射值）/ "area"（面积映射值）；
    - ``label``: {"show": True, "position": "outside|inside|center",
      "fontSize": px}；outside 为外部引线 + 名称，inside 为内部百分比，
      center 于环形中心孔显示总计；
    - ``totalLabel``: {"show": False, "text": "总计"}：环形中心孔总计。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._sectors = []  # [dict(name,value,color,a0,a1,r0,r1)]
        self._center = QPointF()
        self._total = 0.0
        self._r_in = 0.0
        self._r_out = 1.0

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._sectors = []
        entries = _parse_named_values(self.data())
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        label_pos = str(label_opt.get("position") or "outside")
        center_opt = self.opt.get("center") or ["50%", "50%"]
        if not isinstance(center_opt, (list, tuple)):
            # **别让标量按字符下标取值**：``"50%"[0] == "5"`` → 圆心跑到左上角
            # 5px 处（用户看到的是「饼心不见了」）；而裸数字连 ``len()`` 都
            # 没有，直接抛 ``TypeError`` 把整张图打没（异常被 ``warn_once``
            # 吞掉，只剩「饼不见了 + 控制台一行告警」）。
            # ECharts 规定 ``center`` 是二元组，但单个值按「两轴同值」处理
            # 比悄悄画错好得多。
            center_opt = [center_opt, center_opt]
        cx = rect.left() + _parse_pct(
            center_opt[0] if len(center_opt) > 0 else "50%",
            rect.width(),
            rect.width() / 2,
        )
        cy = rect.top() + _parse_pct(
            center_opt[1] if len(center_opt) > 1 else "50%",
            rect.height(),
            rect.height() / 2,
        )
        self._center = QPointF(cx, cy)
        half = min(rect.width(), rect.height()) / 2
        margin = 56.0 if (label_show and label_pos == "outside") else 14.0
        base = max(10.0, half - margin)
        radius_opt = self.opt.get("radius", "75%")
        if isinstance(radius_opt, (list, tuple)):
            r_in = _parse_pct(radius_opt[0] if radius_opt else 0, base, 0.0)
            r_out = _parse_pct(
                radius_opt[1] if len(radius_opt) > 1 else "75%", base, base
            )
        else:
            r_in = 0.0
            r_out = _parse_pct(radius_opt, base, base)
        r_in = _clamp(r_in, 0.0, r_out)
        self._r_in, self._r_out = r_in, r_out
        self._total = sum(v for _, v in entries)
        if not entries or self._total <= 0:
            return
        vmax = max(v for _, v in entries) or 1.0
        rose = str(self.opt.get("roseType") or "")
        scale = 1.0
        spans = self._sector_spans([v for _, v in entries])
        for i, (name, v) in enumerate(entries):
            a0, span_eff = spans[i]
            if rose == "radius":
                scale = _clamp(v / vmax, 0.05, 1.0)
            elif rose == "area":
                scale = _clamp(math.sqrt(_clamp(v / vmax, 0.0, 1.0)), 0.05, 1.0)
            self._sectors.append(
                {
                    "index": i,
                    "name": name,
                    "value": v,
                    "color": self.itemColor(
                        i, default=_series_palette_color(self.chart, i)
                    ),
                    "a0": a0,
                    "a1": a0 + span_eff,
                    "r0": r_in,
                    "r1": r_in + (r_out - r_in) * scale,
                }
            )

    def _sector_spans(self, values):
        """给定一组数值算出每个扇区的 ``(a0, span_eff)``（含 min/pad 角）。

        ``_animated_sectors``（过渡动画）与 ``layout``（终态）**必须走同一份
        公式**：原先过渡路径自己重算 ``v / total * 360``，把 ``minAngle``
        与 ``padAngle`` 整个丢了 —— 于是「动画播完的那一帧」扇区突然贴到
        一起、小值扇区缩回 0 角，视觉上是「饼图在动画结束时跳了一下」。
        """
        min_angle = max(0.0, _to_float(self.opt.get("minAngle"), 0.0))
        pad_angle = max(0.0, _to_float(self.opt.get("padAngle"), 0.0))
        total = sum(values) or 1.0
        spans = [max(v / total * 360.0, min_angle) for v in values]
        span_total = sum(spans)
        if span_total > 360.0:
            spans = [s * 360.0 / span_total for s in spans]
        out = []
        acc = self._start_angle()
        for span in spans:
            if pad_angle > 0 and span > pad_angle:
                out.append((acc + pad_angle / 2.0, span - pad_angle))
            else:
                out.append((acc, span))
            acc += span
        return out

    # -- 角度换算：a 为自 12 点方向顺时针度数 -------------------------------
    def _start_angle(self) -> float:
        """ECharts ``startAngle``（0 = 3 点、逆时针）→ 内部角度（12 点起顺时针）。"""
        return 90.0 - _to_float(self.opt.get("startAngle"), 90.0)

    def _pt(self, a_deg, r):
        rad = math.radians(a_deg)
        return QPointF(
            self._center.x() + r * math.sin(rad), self._center.y() - r * math.cos(rad)
        )

    def _sector_path(self, sec, anim_t):
        """扇区 QPainterPath（anim_t 控制扫掠展开）。"""
        a0, a1 = sec["a0"], sec["a1"]
        span = (a1 - a0) * anim_t
        r1 = sec["r1"]
        r0 = min(sec["r0"], r1)
        path = QPainterPath()
        if span <= 0:
            return path
        rect_out = QRectF(self._center.x() - r1, self._center.y() - r1, 2 * r1, 2 * r1)
        # Qt 角度：0° 于 3 点方向，逆时针为正（1/16 度单位）
        qt_start = 90.0 - a0
        qt_span = -span
        if r0 > 0.5:
            rect_in = QRectF(
                self._center.x() - r0, self._center.y() - r0, 2 * r0, 2 * r0
            )
            path.arcMoveTo(rect_out, qt_start)
            path.arcTo(rect_out, qt_start, qt_span)
            path.arcTo(rect_in, qt_start + qt_span, -qt_span)
            path.closeSubpath()
        else:
            path.moveTo(self._center)
            path.arcTo(rect_out, qt_start, qt_span)
            path.closeSubpath()
        return path

    def _animated_sectors(self, anim_t):
        """过渡动画：旧→新数值插值（等长时重建角度），否则返回原扇区。"""
        prev = _parse_named_values(self.prev_data)
        if (
            self.prev_data is None
            or len(prev) != len(self._sectors)
            or not self._sectors
        ):
            return self._sectors
        values = [
            p[1] + (s["value"] - p[1]) * anim_t for p, s in zip(prev, self._sectors)
        ]
        vmax = max(values) or 1.0
        rose = str(self.opt.get("roseType") or "")
        # 角度走 ``_sector_spans``：minAngle / padAngle 在过渡动画里同样生效，
        # 否则动画结束那一帧扇区会突然贴合（见该方法 docstring）。
        spans = self._sector_spans(values)
        rebuilt = []
        for sec, v, (a0, span_eff) in zip(self._sectors, values, spans):
            scale = 1.0
            if rose == "radius":
                scale = _clamp(v / vmax, 0.05, 1.0)
            elif rose == "area":
                scale = _clamp(math.sqrt(_clamp(v / vmax, 0.0, 1.0)), 0.05, 1.0)
            s = dict(sec)
            s["a0"], s["a1"] = a0, a0 + span_eff
            s["r1"] = self._r_in + (self._r_out - self._r_in) * scale
            rebuilt.append(s)
        return rebuilt

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._sectors:
            return
        p.save()
        sectors = self._animated_sectors(anim_t)
        border = QColor(T("color.bg.base"))
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for sec in sectors:
            path = self._sector_path(sec, anim_t)
            if path.isEmpty():
                continue
            color = parse_color(sec["color"])
            alpha = self.itemOpacity(sec["index"])
            border_color, border_w = self.itemBorder(sec["index"])
            if hovered is not None:
                if sec["index"] == hovered:
                    emphasis = self.emphasisColor(sec["index"])
                    color = emphasis if emphasis is not None else color.lighter(112)
                elif self.blursOtherItems():
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.35
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            if border_color is not None and border_w > 0:
                p.setPen(QPen(border_color, border_w))
            else:
                p.setPen(QPen(border, 1.2))
            p.setBrush(color)
            p.drawPath(path)
        self._paint_labels(p, sectors, anim_t)
        p.restore()

    def _label_text(self, sec, pct: str, default_text: str) -> str:
        """饼图标签文本：``label.formatter``（callable / ``{b} {c} {d}`` 模板）优先。"""
        formatter = self.labelOption().get("formatter")
        params = {
            "a": self.name,
            "b": sec["name"],
            "c": sec["value"],
            "d": pct,
            "value": sec["value"],
            "name": sec["name"],
            "percent": pct,
            "series": self.name,
            "dataIndex": sec["index"],
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
        return default_text

    def _paint_labels(self, p, sectors, anim_t):
        label_opt = dict(self.opt.get("label") or {})
        if not bool(label_opt.get("show", True)):
            return
        pos = str(label_opt.get("position") or "outside")
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        total = sum(s["value"] for s in self._sectors) or 1.0
        c_text = self.labelColor()
        c_line = _text_color("color.border.strong")
        if pos == "center":
            self._paint_center_total(p, font)
            return
        for sec in sectors:
            span = (sec["a1"] - sec["a0"]) * anim_t
            if span < 4.0:
                continue  # 扇区过小省略标签
            mid = sec["a0"] + span / 2
            name = sec["name"] or formatValue(sec["value"])
            pct = formatValue(round(sec["value"] / total * 100, 1)) + "%"
            if pos == "inside":
                r = (sec["r0"] + sec["r1"]) / 2
                pt = self._pt(mid, r)
                text = self._label_text(sec, pct, pct)
                p.setPen(QColor(ON_FILL_WHITE))
                p.drawText(
                    QRectF(pt.x() - 40, pt.y() - fm.height() / 2, 80, fm.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )
            else:  # outside：引线 + 名称（含百分比）
                pt1 = self._pt(mid, sec["r1"] + 2)
                pt2 = self._pt(mid, sec["r1"] + 14)
                right_side = math.sin(math.radians(mid)) >= 0
                pt3 = QPointF(pt2.x() + (14 if right_side else -14), pt2.y())
                p.setPen(QPen(c_line, 1))
                p.drawLine(pt1, pt2)
                p.drawLine(pt2, pt3)
                p.setPen(c_text)
                text = self._label_text(
                    sec, pct, f"{name} {pct}" if sec["name"] else pct
                )
                tw = fm.horizontalAdvance(text)
                if right_side:
                    tr = QRectF(
                        pt3.x() + 3, pt3.y() - fm.height() / 2, tw + 4, fm.height()
                    )
                    p.drawText(
                        tr,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        text,
                    )
                else:
                    tr = QRectF(
                        pt3.x() - tw - 3, pt3.y() - fm.height() / 2, tw + 4, fm.height()
                    )
                    p.drawText(
                        tr,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        text,
                    )
        # 环形中心孔总计
        if self._r_in > 4 and bool(
            dict(self.opt.get("totalLabel") or {}).get("show", False)
        ):
            self._paint_center_total(p, font)

    def _paint_center_total(self, p, font):
        """环形中心孔显示总计数值。"""
        total_opt = dict(self.opt.get("totalLabel") or {})
        title = str(total_opt.get("text") or "")
        p.setFont(
            chartFont(
                T("font.title.md"),
                T("font.weight.semibold"),
                self.chart.fontFamily(),
            )
        )
        fm = QFontMetricsF(p.font())
        value_text = formatValue(self._total)
        cy = self._center.y()
        if title:
            cy -= fm.height() / 2
        p.setPen(_text_color("color.text.primary"))
        p.drawText(
            QRectF(
                self._center.x() - self._r_in,
                cy - fm.height() / 2,
                self._r_in * 2,
                fm.height(),
            ),
            Qt.AlignmentFlag.AlignCenter,
            value_text,
        )
        if title:
            p.setFont(font)
            fm2 = QFontMetricsF(font)
            p.setPen(_text_color("color.text.secondary"))
            p.drawText(
                QRectF(
                    self._center.x() - self._r_in,
                    cy + fm.height() / 2,
                    self._r_in * 2,
                    fm2.height(),
                ),
                Qt.AlignmentFlag.AlignCenter,
                title,
            )

    # -- 命中 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        if not self._sectors:
            return None
        dx = pos.x() - self._center.x()
        dy = pos.y() - self._center.y()
        r = math.hypot(dx, dy)
        a = math.degrees(math.atan2(dx, -dy)) % 360.0
        # 与 ``paint`` 逐项对齐：先按进度插值出当前角度（更新动画），
        # 再按进度缩放扫掠角宽（入场动画），见 ``_sector_path``。
        anim_t = self._anim_t
        sectors = self._animated_sectors(anim_t)
        for i, sec in enumerate(sectors):
            a0 = float(sec["a0"]) % 360.0
            a1 = (
                float(sec["a0"]) + (float(sec["a1"]) - float(sec["a0"])) * anim_t
            ) % 360.0
            # **整圆必须特判**。``a1`` 原先也取 ``% 360``，于是占满 360° 的
            # 扇区（单个数据点、单扇区饼图）拿到 ``a0 == a1 == 0``，角度判据
            # 变成 ``0 <= a < 0`` —— **恒不命中**。后果是这类扇区既没有
            # tooltip 也没有 click / emphasis，用户看到的是「点不动的饼」。
            span = (float(sec["a1"]) - float(sec["a0"])) * anim_t
            if span >= 360.0:
                in_angle = True
            elif a0 <= a1:
                in_angle = a0 <= a < a1
            else:
                # 跨 0° 边界（如 350° → 10°）
                in_angle = a >= a0 or a < a1
            if in_angle and sec["r0"] - 1 <= r <= sec["r1"] + 1:
                pct = sec["value"] / (self._total or 1.0) * 100
                return {
                    "name": sec["name"],
                    "value": sec["value"],
                    "series": self.name,
                    "dataIndex": i,
                    "percent": round(pct, 2),
                    # 数据项颜色：tooltip 圆点要跟扇区颜色一致，不能拿系列色
                    "color": sec["color"],
                }
        return None
