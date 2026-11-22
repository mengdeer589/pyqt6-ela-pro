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
from .._utils import clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import parse_color, resolve_color_option, text_italic, text_weight
from ..axes import chartFont, formatValue
from ..core import SeriesRenderer, formatLabelTemplate
from ..labels import label_text_size
from ._shared import (
    _label_font,
    _parse_named_values,
    _parse_pct,
    _series_palette_color,
    _text_color,
)


class PieSeriesRenderer(SeriesRenderer):
    """饼 / 环形 / 南丁格尔玫瑰图。
    支持 ``data`` / ``radius`` / ``center`` / ``startAngle`` / ``roseType`` /
    ``minAngle`` / ``padAngle`` / ``label`` / ``totalLabel``。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._sectors = []  # [dict(name,value,color,a0,a1,r0,r1)]
        self._center = QPointF()
        self._layout_rect = QRectF()
        self._total = 0.0
        self._r_in = 0.0
        self._r_out = 1.0
        #: 图例隐藏的数据项名（饼图图例按数据项开关）
        self._hidden_items = set()

    def setHiddenItems(self, names) -> None:
        """设置被图例隐藏的数据项（按名称）。"""
        self._hidden_items = {str(n) for n in (names or [])}

    def legendItems(self) -> list:
        """饼图图例条目 = 数据项名（不是系列名）。"""
        out = []
        for index, item in enumerate(self.data()):
            if isinstance(item, dict):
                name = str(item.get("name") or formatValue(item.get("value")))
            elif isinstance(item, (int, float)) and not isinstance(item, bool):
                name = formatValue(item)
            else:
                name = str(item or "")
            if not name:
                continue
            out.append(
                (
                    name,
                    self.dataColor(
                        index, default=_series_palette_color(self.chart, index)
                    ),
                )
            )
        return out

    def layout(self, rect: QRectF) -> None:
        self._sectors = []
        self._layout_rect = QRectF(rect)
        entries = [
            entry
            for entry in _parse_named_values(self.data())
            if entry[1] not in self._hidden_items
            and formatValue(entry[2]) not in self._hidden_items
        ]
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        label_pos = str(label_opt.get("position") or "outside")
        center_opt = self.opt.get("center") or ["50%", "50%"]
        if not isinstance(center_opt, (list, tuple)):
            # 标量按两轴同值处理：按字符下标取值会把圆心算到左上角。
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
        # 半径百分比按 ECharts 语义相对「短边的一半」；再扣固定边距会把小图吃掉一半。
        base = max(10.0, half)
        radius_opt = self.opt.get("radius", "75%")
        if isinstance(radius_opt, (list, tuple)):
            r_in = _parse_pct(radius_opt[0] if radius_opt else 0, base, 0.0)
            r_out = _parse_pct(
                radius_opt[1] if len(radius_opt) > 1 else "75%", base, base
            )
        else:
            r_in = 0.0
            r_out = _parse_pct(radius_opt, base, base)
        if label_show and label_pos == "outside":
            # 外侧标签的引线 + 半行文字不能顶出内容区上下边；最多压缩一半半径，
            # 再小就让标签溢出（横向本来由画布裁切兜底），不能把饼压成一个点。
            lead = 16.0 + QFontMetricsF(_label_font(self, label_opt)).height() / 2.0
            limit = max(10.0, half * 0.5, half - lead)
            if r_out > limit > 0:
                ratio = limit / r_out
                r_in *= ratio
                r_out = limit
        r_in = _clamp(r_in, 0.0, r_out)
        self._r_in, self._r_out = r_in, r_out
        self._total = sum(max(v, 0.0) for _, _, v in entries)
        if not entries or self._total <= 0:
            return
        vmax = max((max(v, 0.0) for _, _, v in entries), default=0.0) or 1.0
        rose = str(self.opt.get("roseType") or "")
        scale = 1.0
        spans = self._sector_spans([max(v, 0.0) for _, _, v in entries])
        for i, (data_index, name, v) in enumerate(entries):
            a0, span_eff = spans[i]
            v_pos = max(v, 0.0)
            if rose == "radius":
                scale = _clamp(v_pos / vmax, 0.05, 1.0)
            elif rose == "area":
                scale = _clamp(math.sqrt(_clamp(v_pos / vmax, 0.0, 1.0)), 0.05, 1.0)
            self._sectors.append(
                {
                    "index": data_index,
                    "name": name or formatValue(v),
                    "value": v,
                    "color": self.dataColor(
                        data_index,
                        default=_series_palette_color(self.chart, data_index),
                    ),
                    "a0": a0,
                    "a1": a0 + span_eff,
                    "r0": r_in,
                    "r1": r_in + (r_out - r_in) * scale,
                }
            )

    def _sector_spans(self, values):
        """每个扇区的 ``(a0, span_eff)``（含 minAngle / padAngle）；动画与终态共用。"""
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
        if not self.clockwise():
            start = self._start_angle()
            out = [((2.0 * start - (a0 + span)) % 360.0, span) for a0, span in out]
        return out

    def clockwise(self) -> bool:
        """ECharts ``clockwise``（默认 True）。"""
        return self.opt.get("clockwise", True) is not False

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
            p[2] + (s["value"] - p[2]) * anim_t for p, s in zip(prev, self._sectors)
        ]
        vmax = max(values) or 1.0
        rose = str(self.opt.get("roseType") or "")
        # 角度走 ``_sector_spans``，否则动画结束那一帧扇区会突然贴合。
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
        self._label_rects = []
        if not self._sectors:
            return
        p.save()
        sectors = self._animated_sectors(anim_t)
        border = QColor(T("color.bg.base", self.chart))
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        legend_hover = self.chart._legend_hover
        for sec in sectors:
            path = self._sector_path(sec, anim_t)
            if path.isEmpty():
                continue
            color = parse_color(sec["color"])
            alpha = self.itemOpacity(sec["index"])
            border_color, border_w = self.itemBorder(sec["index"])
            if (
                hovered is None
                and legend_hover is not None
                and sec["name"] == legend_hover
            ):
                emphasis = self.emphasisColor(sec["index"])
                color = emphasis if emphasis is not None else color.lighter(112)
            color, alpha, border_color, border_w = self.stateStyle(
                sec["index"], hovered, color, alpha, border_color, border_w
            )
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

    def labelShown(self) -> bool:
        """饼图 ``label.show`` 默认开（ECharts 语义）。"""
        return bool(self.labelOption().get("show", True))

    def _label_text(self, sec, pct: float, default_text: str) -> str:
        """饼图标签文本：双击编辑覆盖 → ``label.formatter`` → 默认文本。

        ``d`` / ``percent`` 按 ECharts 语义给**百分数本身**（不带 ``%``），
        默认文本才带百分号；否则 ``{b} {d}%`` 会渲染成 ``42%%``。
        """
        overrides = self._source_opt.get("labelTexts")
        if isinstance(overrides, dict):
            key = str(sec["index"])
            if key in overrides:
                return str(overrides[key])
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
            # totalLabel 是独立开关：关数据标签不能连中心总计一起吞掉。
            if self._r_in > 4 and bool(
                dict(self.opt.get("totalLabel") or {}).get("show", False)
            ):
                font = _label_font(self, label_opt)
                p.setFont(font)
                self._paint_center_total(p, font)
            return
        pos = str(label_opt.get("position") or "outside")
        line_opt = self.opt.get("labelLine")
        line_opt = dict(line_opt) if isinstance(line_opt, dict) else {}
        line_show = bool(line_opt.get("show", True))
        line_length = _to_float(line_opt.get("length"), 12.0)
        line_length2 = _to_float(line_opt.get("length2"), 14.0)
        line_style = line_opt.get("lineStyle")
        line_style = dict(line_style) if isinstance(line_style, dict) else {}
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        total = self._total or 1.0
        c_text = self.labelColor()
        explicit_label = self.labelTextStyle().get("color")
        explicit_label = (
            self.resolveColor(explicit_label)
            if isinstance(explicit_label, str) and explicit_label
            else None
        )
        c_line = _text_color("color.border.strong", self.chart)
        if pos == "center":
            self._paint_center_total(p, font)
            return
        outside = []
        for sec in sectors:
            span = (sec["a1"] - sec["a0"]) * anim_t
            if span < 4.0:
                continue  # 扇区过小省略标签
            mid = sec["a0"] + span / 2
            name = sec["name"] or formatValue(sec["value"])
            pct_value = round(sec["value"] / total * 100, 1)
            if isinstance(pct_value, float) and pct_value.is_integer():
                pct_value = int(pct_value)
            pct_text = formatValue(pct_value) + "%"
            if pos == "inside":
                r = (sec["r0"] + sec["r1"]) / 2
                pt = self._pt(mid, r)
                text = self._label_text(sec, pct_value, pct_text)
                rect = QRectF(pt.x() - 40, pt.y() - fm.height() / 2, 80, fm.height())
                hit = self.paintLabelIn(
                    p,
                    rect,
                    text,
                    index=sec["index"],
                    align=Qt.AlignmentFlag.AlignCenter,
                    color=self.contrastLabelColor(sec["color"], sec["index"]),
                )
                if hit.isNull():
                    continue
                tw = fm.horizontalAdvance(text)
                self._label_rects.append(
                    (
                        sec["index"],
                        QRectF(
                            pt.x() - tw / 2.0 - 2,
                            pt.y() - fm.height() / 2,
                            tw + 4,
                            fm.height(),
                        ),
                        text,
                    )
                )
            else:  # outside：先收集，排开 y 后再画引线 + 名称（含百分比）
                text = self._label_text(
                    sec,
                    pct_value,
                    f"{name} {pct_text}" if sec["name"] else pct_text,
                )
                outside.append(
                    (
                        sec,
                        self._pt(mid, sec["r1"] + 2),
                        self._pt(mid, sec["r1"] + 2 + line_length),
                        text,
                    )
                )
        if outside:
            self._paint_outside_labels(
                p,
                outside,
                fm,
                c_line,
                c_text,
                line_show,
                line_length2,
                line_style,
            )
        # 环形中心孔总计
        if self._r_in > 4 and bool(
            dict(self.opt.get("totalLabel") or {}).get("show", False)
        ):
            self._paint_center_total(p, font)

    def _paint_outside_labels(
        self,
        p,
        items,
        fm,
        c_line,
        c_text,
        line_show=True,
        length2=14.0,
        line_style=None,
    ):
        """外侧标签：同侧按 y 排开，小扇区的标签 / 引线不会叠在一起。"""
        gap = fm.height() + 2.0
        top = self._layout_rect.top() + fm.height() / 2.0
        bottom = max(top, self._layout_rect.bottom() - fm.height() / 2.0)
        groups = {True: [], False: []}
        for item in items:
            groups[item[2].x() >= self._center.x()].append(item)
        line_style = line_style if isinstance(line_style, dict) else {}
        line_color = resolve_color_option(line_style.get("color"), self.chart, c_line)
        try:
            line_width = max(0.0, float(line_style.get("width", 1.0)))
        except (TypeError, ValueError, OverflowError):
            line_width = 1.0
        p.setPen(QPen(line_color, line_width))
        for right_side, group in groups.items():
            if not group:
                continue
            group.sort(key=lambda item: item[2].y())
            ys = self._spread_labels([item[2].y() for item in group], gap, top, bottom)
            for (sec, pt1, pt2, text), y in zip(group, ys):
                pt3 = QPointF(pt2.x() + (length2 if right_side else -length2), y)
                if line_show and line_width > 0:
                    p.drawLine(pt1, pt2)
                    p.drawLine(pt2, pt3)
                option = self.labelVisualOption(sec["index"])
                font = self._label_font_for(option)
                size = label_text_size(text, font, option)
                tw = size.width()
                th = max(fm.height(), size.height())
                if right_side:
                    tr = QRectF(pt3.x() + 3, pt3.y() - th / 2, tw + 4, th)
                    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                else:
                    tr = QRectF(pt3.x() - tw - 3, pt3.y() - th / 2, tw + 4, th)
                    align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                p.setPen(c_text)
                hit = self.paintLabelIn(
                    p,
                    tr,
                    text,
                    index=sec["index"],
                    align=align,
                    color=c_text,
                )
                p.setPen(QPen(c_line, 1))
                if not hit.isNull():
                    self._label_rects.append((sec["index"], hit, text))

    @staticmethod
    def _spread_labels(values, gap, top, bottom):
        """单调下推 + 整体回收：同侧标签互不重叠，也不越出内容区上下边。"""
        out = list(values)
        for i in range(1, len(out)):
            out[i] = max(out[i], out[i - 1] + gap)
        if out and out[-1] > bottom:
            shift = out[-1] - bottom
            out = [v - shift for v in out]
        if out and out[0] < top:
            shift = top - out[0]
            out = [v + shift for v in out]
        # 标签数超过可用高度时无法完全不重叠，但绝不能画出内容区。
        return [min(max(v, top), bottom) for v in out]

    def _paint_center_total(self, p, font):
        """环形中心孔显示总计数值（字号随内半径自适应，可被 totalLabel 覆盖）。"""
        total_opt = dict(self.opt.get("totalLabel") or {})
        if total_opt.get("show", False) is False:
            return
        title = str(total_opt.get("text") or "")
        label_style = self.labelTextStyle()
        label_px = _to_float(label_style.get("fontSize"), T("font.xs"))
        value_px = _to_float(total_opt.get("fontSize"), None)
        if value_px is None:
            # 中心孔越大字号越大；上下限避免小图挤爆 / 大图过小。
            value_px = _clamp(max(label_px + 2.0, self._r_in * 0.32), 12.0, 22.0)
        value_font = chartFont(
            value_px,
            text_weight(total_opt.get("fontWeight") or T("font.weight.semibold")),
            total_opt.get("fontFamily") or self.chart.fontFamily(),
            text_italic(total_opt.get("fontStyle")),
        )
        p.setFont(value_font)
        fm = QFontMetricsF(value_font)
        value_text = formatValue(self._total)
        cy = self._center.y()
        if title:
            cy -= fm.height() / 2
        raw_color = total_opt.get("color")
        value_color = self.resolveColor(raw_color) if raw_color is not None else None
        p.setPen(
            value_color
            if value_color is not None and value_color.isValid()
            else _text_color("color.text.primary", self.chart)
        )
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
            sub_px = _to_float(total_opt.get("subtextFontSize"), None)
            if sub_px is not None:
                font = chartFont(
                    sub_px,
                    text_weight(
                        total_opt.get("subtextFontWeight")
                        or label_style.get("fontWeight")
                    ),
                    total_opt.get("subtextFontFamily") or self.chart.fontFamily(),
                    text_italic(
                        total_opt.get("subtextFontStyle")
                        or label_style.get("fontStyle")
                    ),
                )
            p.setFont(font)
            fm2 = QFontMetricsF(font)
            raw_sub = total_opt.get("subtextColor")
            sub_color = self.resolveColor(raw_sub) if raw_sub is not None else None
            p.setPen(
                sub_color
                if sub_color is not None and sub_color.isValid()
                else _text_color("color.text.secondary", self.chart)
            )
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

    def hitTest(self, pos: QPointF):
        if not self._sectors:
            return None
        dx = pos.x() - self._center.x()
        dy = pos.y() - self._center.y()
        r = math.hypot(dx, dy)
        a = math.degrees(math.atan2(dx, -dy)) % 360.0
        # 与 ``paint`` 对齐：先按进度插值角度，再按进度缩放扫掠角宽。
        anim_t = self._anim_t
        sectors = self._animated_sectors(anim_t)
        for i, sec in enumerate(sectors):
            a0 = float(sec["a0"]) % 360.0
            a1 = (
                float(sec["a0"]) + (float(sec["a1"]) - float(sec["a0"])) * anim_t
            ) % 360.0
            # 整圆必须特判：占满 360° 的扇区取模后 ``a0 == a1``，角度判据恒不命中。
            span = (float(sec["a1"]) - float(sec["a0"])) * anim_t
            if span >= 360.0:
                in_angle = True
            elif a0 <= a1:
                in_angle = a0 <= a < a1
            else:
                # 跨 0° 边界（如 350° → 10°）
                in_angle = a >= a0 or a < a1
            if in_angle and sec["r0"] - 1 <= r <= sec["r1"] + 1:
                pct = round(sec["value"] / (self._total or 1.0) * 100, 2)
                if isinstance(pct, float) and pct.is_integer():
                    pct = int(pct)
                return {
                    "name": sec["name"],
                    "value": sec["value"],
                    "series": self.name,
                    "dataIndex": sec["index"],
                    "percent": pct,
                    # 数据项颜色：tooltip 圆点要跟扇区颜色一致，不能拿系列色
                    "color": sec["color"],
                }
        return None
