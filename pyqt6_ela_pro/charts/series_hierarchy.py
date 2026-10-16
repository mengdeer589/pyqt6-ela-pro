"""
无坐标 / 层级 / 关系系列（完整 10 个：pie / radar / gauge / funnel /
sunburst / treemap / tree / sankey / graph / lines）。

本模块导入时经 ``registerSeries`` 注册全部系列。除 ``radar``（自绘蛛网）
与 ``lines``（Grid 直角坐标）外，全部在 rect 内自布局、不依赖坐标系；
配色经 ``T()`` 实时读取（Ela 主题令牌），主题切换后重绘即生效。

移植自 InstructionX_UIKit.charts.series_hierarchy（原库为 PyQt6；
主题令牌经 charts._tokens 适配到 eTheme / ElaThemeType，原库无 LICENSE，
保留出处）。
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QApplication

from .._motion import start_idle_loop
from ._tokens import EFFECT_TICK_MS, T
from ._utils import ON_FILL_WHITE, clamp as _clamp
from ._utils import dist_point_segment
from ._utils import parse_roam as _parse_roam
from ._utils import to_float as _to_float
from ._utils import with_alpha
from .axes import chartFont, formatValue
from .core import SeriesRenderer, formatLabelTemplate, registerSeries

__all__ = [
    "PieSeriesRenderer",
    "RadarSeriesRenderer",
    "GaugeSeriesRenderer",
    "FunnelSeriesRenderer",
    "SunburstSeriesRenderer",
    "TreemapSeriesRenderer",
    "TreeSeriesRenderer",
    "SankeySeriesRenderer",
    "GraphSeriesRenderer",
    "LinesSeriesRenderer",
]


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------


def _parse_pct(v, base, default=0.0):
    """解析像素值 / 百分比字符串（"40%" → base*0.4）。"""
    if isinstance(v, str) and v.strip().endswith("%"):
        try:
            return base * float(v.strip()[:-1]) / 100.0
        except (TypeError, ValueError, OverflowError):
            return float(default)
    if v is None:
        return float(default)
    return _to_float(v, default)


def _text_color(key="color.text.primary"):
    return QColor(T(key))


def _label_font(px=None):
    return chartFont(px if px else T("font.xs"))


def _series_palette_color(chart, index):
    """按序号取全局调色板颜色（越界循环）。"""
    pal = chart.palette()
    if not pal:
        return QColor(T("color.primary"))
    return QColor(pal[index % len(pal)])


def _parse_named_values(data):
    """解析 [{"name","value"}] / 数值 数据 → [(name, value)]（负值剔除）。"""
    out = []
    for item in data or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "")
            v = item.get("value")
        else:
            name, v = "", item
        fv = _to_float(v, None) if not isinstance(v, bool) else None
        if fv is None or fv < 0:
            continue
        out.append((name, fv))
    return out


# ---------------------------------------------------------------------------
# 1. pie 饼 / 环形 / 南丁格尔玫瑰
# ---------------------------------------------------------------------------


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
            color = QColor(sec["color"])
            alpha = self.itemOpacity(sec["index"])
            border_color, border_w = self.itemBorder(sec["index"])
            if hovered is not None:
                if sec["index"] == hovered:
                    emphasis = self.emphasisColor(sec["index"])
                    color = emphasis if emphasis is not None else color.lighter(112)
                else:
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
        font = _label_font(label_opt.get("fontSize"))
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
        p.setFont(chartFont(T("font.title.md"), T("font.weight.semibold")))
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


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------


def _dist(a, b):
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _dist_to_polygon_edge(p, pts) -> float:
    """点到闭合折线（多边形边界）的最近距离（雷达命中判定用）。"""
    n = len(pts)
    if n == 0:
        return float("inf")
    if n == 1:
        return _dist(p, pts[0])
    return min(dist_point_segment(p, pts[i], pts[(i + 1) % n]) for i in range(n))


# ---------------------------------------------------------------------------
# 2. radar 雷达（自绘蛛网，不用 PolarCoord）
# ---------------------------------------------------------------------------


class RadarSeriesRenderer(SeriesRenderer):
    """雷达图（自绘蛛网坐标：圈环 + 轴线 + 维度标签）。

    option 键：
    - ``indicator``: [{"name","max"}, ...]（维度定义，缺省 max 按数据）；
    - ``data``: [{"name": "系列A", "value": [v1, ...]}, ...]（每条一个多边形，
      也接受纯数值列表）；
    - ``shape``: "polygon" / "circle"；
    - ``areaStyle``: {"opacity": 0.25}（半透明填充，不给则不填充）；
    - ``splitNumber``: 圈环数（默认 5）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._center = QPointF()
        self._radius = 1.0
        self._indicators = []  # [{"name","max"}]
        self._polys = []  # [{"name","values","color","points":[QPointF]}]

    def layout(self, rect: QRectF) -> None:
        self._polys = []
        inds = []
        for item in self.opt.get("indicator") or []:
            if isinstance(item, dict):
                inds.append(
                    {"name": str(item.get("name") or ""), "max": item.get("max")}
                )
        entries = []
        for item in self.data():
            if isinstance(item, dict):
                name = str(item.get("name") or "")
                values = item.get("value")
            else:
                name, values = "", item
            if isinstance(values, (list, tuple)):
                vals = [_to_float(v, 0.0) for v in values]
            else:
                vals = [_to_float(values, 0.0)]
            entries.append((name, vals))
        if not inds and entries:
            n = max(len(v) for _, v in entries)
            inds = [{"name": f"dim{i + 1}", "max": None} for i in range(n)]
        if not inds:
            self._indicators = []
            return
        # 每维 max：缺省取全数据该维最大 * 1.1
        n = len(inds)
        for j in range(n):
            if inds[j]["max"] is None:
                col = [vals[j] for _, vals in entries if j < len(vals)]
                inds[j]["max"] = (max(col) * 1.1) if col else 1.0
            inds[j]["max"] = max(_to_float(inds[j]["max"], 1.0), 1e-6)
        self._indicators = inds
        self._center = rect.center()
        self._radius = max(12.0, min(rect.width(), rect.height()) / 2 - 34.0)
        base_idx = (
            self.chart.seriesRenderers.index(self)
            if self in self.chart.seriesRenderers
            else 0
        )
        for k, (name, vals) in enumerate(entries):
            pts = []
            for j in range(n):
                v = vals[j] if j < len(vals) else 0.0
                frac = _clamp(v / inds[j]["max"], 0.0, 1.0)
                theta = -math.pi / 2 + j / n * 2 * math.pi
                r = self._radius * frac
                pts.append(
                    QPointF(
                        self._center.x() + r * math.cos(theta),
                        self._center.y() + r * math.sin(theta),
                    )
                )
            self._polys.append(
                {
                    "name": name,
                    "values": vals,
                    "color": _series_palette_color(self.chart, base_idx + k),
                    "points": pts,
                }
            )

    def _ring_path(self, frac):
        n = len(self._indicators)
        path = QPainterPath()
        if str(self.opt.get("shape") or "polygon") == "circle":
            path.addEllipse(self._center, self._radius * frac, self._radius * frac)
            return path
        for j in range(n):
            theta = -math.pi / 2 + j / n * 2 * math.pi
            pt = QPointF(
                self._center.x() + self._radius * frac * math.cos(theta),
                self._center.y() + self._radius * frac * math.sin(theta),
            )
            if j == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        return path

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._indicators:
            return
        p.save()
        n = len(self._indicators)
        split = max(1, int(_to_float(self.opt.get("splitNumber"), 5)))
        c_grid = _text_color("color.border")
        c_axis = _text_color("color.border.strong")
        c_text = _text_color("color.text.secondary")
        # axisName / splitLine / axisLine（ECharts 键）
        axis_name_opt = dict(self.opt.get("axisName") or {})
        split_line_opt = dict(self.opt.get("splitLine") or {})
        axis_line_opt = dict(self.opt.get("axisLine") or {})
        if not bool(axis_name_opt.get("show", True)):
            axis_name_opt["_hide"] = True
        if isinstance(axis_name_opt.get("color"), str) and axis_name_opt["color"]:
            c_text = QColor(axis_name_opt["color"])
        if isinstance(split_line_opt.get("lineStyle"), dict):
            raw = split_line_opt["lineStyle"].get("color")
            if isinstance(raw, str) and raw:
                c_grid = QColor(raw)
        if isinstance(axis_line_opt.get("lineStyle"), dict):
            raw = axis_line_opt["lineStyle"].get("color")
            if isinstance(raw, str) and raw:
                c_axis = QColor(raw)
        font = _label_font(axis_name_opt.get("fontSize"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        # 圈环
        if bool(split_line_opt.get("show", True)):
            for k in range(1, split + 1):
                p.setPen(QPen(c_grid, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(self._ring_path(k / split))
        # 轴线 + 维度标签
        if bool(axis_line_opt.get("show", True)):
            for j in range(n):
                theta = -math.pi / 2 + j / n * 2 * math.pi
                outer = QPointF(
                    self._center.x() + self._radius * math.cos(theta),
                    self._center.y() + self._radius * math.sin(theta),
                )
                p.setPen(QPen(c_axis, 1))
                p.drawLine(self._center, outer)
        if not axis_name_opt.get("_hide"):
            for j, ind in enumerate(self._indicators):
                theta = -math.pi / 2 + j / n * 2 * math.pi
                lx = self._center.x() + (self._radius + 16) * math.cos(theta)
                ly = self._center.y() + (self._radius + 16) * math.sin(theta)
                p.setPen(c_text)
                p.drawText(
                    QRectF(lx - 48, ly - fm.height() / 2, 96, fm.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    ind["name"],
                )
        # 多边形系列（anim_t 由中心向外展开）
        area_opt = self.opt.get("areaStyle")
        opacity = 0.25
        if isinstance(area_opt, dict):
            opacity = _clamp(_to_float(area_opt.get("opacity"), 0.25), 0.0, 1.0)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        show_label = self.labelShown()
        for k, poly in enumerate(self._polys):
            pts = self._animated_polygon(poly, anim_t)
            qpoly = QPolygonF(pts)
            color = QColor(self.itemColor(k, default=poly["color"]))
            alpha = self.itemOpacity(k)
            if hovered is not None:
                if k == hovered:
                    emphasis = self.emphasisColor(k)
                    color = emphasis if emphasis is not None else color.lighter(112)
                else:
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.35
            if area_opt is not None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(with_alpha(color, opacity * 255 * alpha))
                p.drawPolygon(qpoly)
            pen = QPen(color, 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(qpoly)
            if pts:
                p.drawLine(pts[-1], pts[0])
            p.setBrush(color)
            for pt in pts:
                p.drawEllipse(pt, 2.5, 2.5)
            if show_label:
                p.setPen(self.labelColor())
                for j, pt in enumerate(pts):
                    value = poly["values"][j] if j < len(poly["values"]) else 0.0
                    text = self.labelText(j, value)
                    p.drawText(
                        QRectF(pt.x() - 30, pt.y() - fm.height() - 2, 60, fm.height()),
                        Qt.AlignmentFlag.AlignCenter,
                        text,
                    )
        p.restore()

    def _animated_polygon(self, poly, anim_t):
        """多边形在给定动画进度下的顶点（``paint`` 与 ``hitTest`` 共用）。

        入场动画把多边形从中心「张开」到最终形状，所以命中必须用同一份插值
        —— 否则动画进行中命中的是还没张开的那块区域。
        """
        return [
            QPointF(
                self._center.x() + (pt.x() - self._center.x()) * anim_t,
                self._center.y() + (pt.y() - self._center.y()) * anim_t,
            )
            for pt in poly["points"]
        ]

    def _hit_info(self, index: int, poly: dict) -> dict:
        """命中信息：带逐维度行与数据项颜色（tooltip 靠它们区分数据源）。"""
        inds = self._indicators
        vals = poly["values"]
        rows = [
            (
                inds[j]["name"] if j < len(inds) else f"dim{j + 1}",
                vals[j] if j < len(vals) else 0.0,
            )
            for j in range(len(inds))
        ]
        name = poly["name"] or self.name
        return {
            "name": name,
            "value": list(vals),
            "series": self.name,
            "dataIndex": index,
            # 数据项颜色（ECharts colorBy='data'）—— tooltip 圆点 / 事件 params
            # 都用它；拿系列色的话两条多边形会是同一个颜色，等于没区分。
            "color": self.itemColor(index, default=poly["color"]),
            # 标题 = 数据项名（ECharts radar formatTooltip 的 header）
            "title": name,
            # 逐维度 (指标名, 值)：Tooltip 渲染成多行，替代原来的 "[...]" 裸列表
            "rows": rows,
        }

    def hitTest(self, pos: QPointF):
        anim_t = self._anim_t
        # 多个多边形重叠时取**边界离光标最近**的那个。ECharts 是 z 序最上层，
        # 但雷达多边形大量重叠 / 包含，z 序会让后画的那条永远抢走命中 ——
        # 实测悬停在「预算」的边线上（离它 0.3px、离「实际」18.5px）仍报「实际」，
        # 用户无法用鼠标区分数据源。倒序遍历 + 严格小于：距离相同仍归最上层。
        best = None
        best_dist = float("inf")
        for k in range(len(self._polys) - 1, -1, -1):
            poly = self._polys[k]
            if len(poly["points"]) < 3:
                continue
            pts = self._animated_polygon(poly, anim_t)
            if not QPolygonF(pts).containsPoint(pos, Qt.FillRule.OddEvenFill):
                continue
            d = _dist_to_polygon_edge(pos, pts)
            if d < best_dist:
                best_dist = d
                best = (k, poly)
        if best is None:
            return None
        return self._hit_info(best[0], best[1])


# ---------------------------------------------------------------------------
# 3. gauge 仪表盘
# ---------------------------------------------------------------------------


class GaugeSeriesRenderer(SeriesRenderer):
    """仪表盘。

    option 键：
    - ``data``: [{"name","value"}]（取首项）；
    - ``min`` / ``max``: 量程（默认 0 / 100）；
    - ``startAngle`` / ``endAngle``: ECharts 角度约定——0° 在 3 点方向、
      逆时针为正（90° 为 12 点方向）；默认 225 / -45，即 270° 弧、
      **开口在底部**；
    - ``radius``: "75%" / px；
    - ``progress``: {"show": True, "width": px}（当前值进度弧）；
    - ``axisLine``: {"lineStyle": {"width": px, "color": [[frac, "#..."], ...]}}
      （分段色背景弧）；
    - ``pointer``: {"show": True, "length": "60%", "width": px}；
    - ``anchor``: {"show": True, "size": px}（中心小圆）；
    - ``detail``: {"show": True, "fontSize": px}（中央数值）；
    - ``title``: {"show": True, "fontSize": px}（名称，数值下方）。
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
        self._value = self._entries[0][1] if self._entries else self._vmin()

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
            prev_v = prev_entries[0][1]
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
                            QColor(str(item[1])),
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
            font = chartFont(
                detail_opt.get("fontSize") or T("font.title.md"),
                T("font.weight.semibold"),
            )
            p.setFont(font)
            fm = QFontMetricsF(font)
            fm_h = fm.height()
            p.setPen(_text_color("color.text.primary"))
            p.drawText(
                QRectF(
                    self._center.x() - r,
                    self._center.y() + r * 0.22,
                    2 * r,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                formatValue(cur_v),
            )
        title_opt = dict(self.opt.get("title") or {})
        name = self._entries[0][0] if self._entries else self.name
        if bool(title_opt.get("show", True)) and name:
            font = _label_font(title_opt.get("fontSize"))
            p.setFont(font)
            fm2 = QFontMetricsF(font)
            p.setPen(_text_color("color.text.secondary"))
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


# ---------------------------------------------------------------------------
# 4. funnel 漏斗
# ---------------------------------------------------------------------------


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

    def layout(self, rect: QRectF) -> None:
        self._layers = []
        raw_entries = _parse_named_values(self.data())
        if not raw_entries:
            return
        entries = [
            (index, name, value) for index, (name, value) in enumerate(raw_entries)
        ]
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
        vmax = max(value for _, _, value in entries) or 1.0
        min_frac = _clamp(_to_float(self.opt.get("minSize"), 0.12), 0.0, 1.0)
        max_w = max(20.0, rect.width() - margin_l - margin_r)
        cx = rect.left() + margin_l + max_w / 2
        # ECharts funnelAlign：left / center（默认）/ right
        align = str(self.opt.get("funnelAlign") or "center")

        def width_of(v):
            return max_w * (min_frac + (1 - min_frac) * v / vmax)

        for slot, (data_index, name, v) in enumerate(entries):
            top_w = width_of(v)
            bot_w = (
                width_of(entries[slot + 1][2])
                if slot + 1 < n
                else width_of(v) * min_frac / max(min_frac, 1e-6)
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
        font = _label_font(label_opt.get("fontSize"))
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
            color = QColor(layer["color"])
            alpha = self.itemOpacity(layer["index"])
            if hovered is not None:
                if layer["index"] == hovered:
                    emphasis = self.emphasisColor(layer["index"])
                    color = emphasis if emphasis is not None else color.lighter(112)
                else:
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
        for layer in self._layers:
            if layer["poly"].containsPoint(pos, Qt.FillRule.OddEvenFill):
                return {
                    "name": layer["name"],
                    "value": layer["value"],
                    "series": self.name,
                    "dataIndex": layer["index"],
                }
        return None


# ---------------------------------------------------------------------------
# 层级数据通用解析（sunburst / treemap / tree 共用）
# ---------------------------------------------------------------------------


class _HNode:
    """层级数据节点：name / value（含子级合计）/ children / depth / 颜色。"""

    __slots__ = (
        "name",
        "value",
        "children",
        "depth",
        "color",
        "a0",
        "a1",
        "level",
        "rect",
        "x",
        "y",
        "style_index",
        "path",
    )

    def __init__(self, name, value=0.0, depth=0):
        self.name = name
        self.value = value
        self.children = []
        self.depth = depth
        self.color = None
        self.a0 = 0.0  # sunburst 角区间
        self.a1 = 0.0
        self.level = 0  # sunburst 环层
        self.rect = QRectF()  # treemap 矩形
        self.x = 0.0  # tree 布局坐标（逻辑）
        self.y = 0.0


def _build_hierarchy(data):
    """[{"name","value","children"}] → [_HNode] 根列表；value 自动累计子级。"""
    roots = []

    def build(item, depth):
        if not isinstance(item, dict):
            return None
        node = _HNode(str(item.get("name") or ""), 0.0, depth)
        raw = item.get("value")
        own = _to_float(raw, 0.0) if raw is not None else 0.0
        for child in item.get("children") or []:
            c = build(child, depth + 1)
            if c is not None:
                node.children.append(c)
        node.value = (
            max(0.0, own) if raw is not None else sum(c.value for c in node.children)
        )
        if raw is not None and node.children:
            node.value = max(0.0, own)
        if node.value <= 0 and node.children:
            node.value = sum(c.value for c in node.children)
        return node

    for item in data or []:
        node = build(item, 0)
        if node is not None:
            roots.append(node)
    return roots


def _assign_branch_colors(chart, roots):
    """顶层分支取调色板色；子级同色相逐级递减明度。"""
    for i, root in enumerate(roots):
        base = _series_palette_color(chart, i)

        def rec(node, color):
            node.color = color
            lighter = color.lighter(115)
            for c in node.children:
                rec(c, lighter)

        rec(root, base)


# ---------------------------------------------------------------------------
# 5. sunburst 旭日图
# ---------------------------------------------------------------------------


class SunburstSeriesRenderer(SeriesRenderer):
    """旭日图（层级环形扇区，中心向外）。

    option 键：
    - ``data``: [{"name","value","children":[...]}]（层级；value 缺省累计子级）；
    - ``radius``: ["15%","90%"]（内孔 / 外半径，相对短边一半）；
    - ``label``: {"show": True, "minAngle": 8（小于该度数省略标签）,
      "fontSize": px}（标签沿角度旋转）；
    - 动画：anim_t 控制角扫掠展开。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []
        self._roots = []
        #: 下钻路径（子级下标序列；空 = 顶层）
        self._focus_path = []
        self._center = QPointF()
        self._r0 = 0.0
        self._r1 = 1.0
        self._max_depth = 1

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        roots = _build_hierarchy(self.data())
        if not roots:
            self._roots = []
            return
        _assign_branch_colors(self.chart, roots)
        # 下钻：按路径解析当前显示层级（路径失效时回到顶层）
        display = roots
        focus = None
        prefix: tuple = ()
        for idx in list(self._focus_path):
            if 0 <= idx < len(display):
                focus = display[idx]
                prefix = prefix + (idx,)
                display = focus.children
            else:
                self._focus_path = []
                focus = None
                prefix = ()
                display = roots
                break
        self._roots = display
        self._focus = focus
        self._max_depth = max((self._depth_of(r) - r.depth for r in display), default=1)
        self._center = rect.center()
        half = min(rect.width(), rect.height()) / 2 - 8
        radius_opt = self.opt.get("radius") or ["15%", "90%"]
        self._r0 = _clamp(
            _parse_pct(
                radius_opt[0] if len(radius_opt) > 0 else "15%", half, half * 0.15
            ),
            0.0,
            half,
        )
        self._r1 = _clamp(
            _parse_pct(
                radius_opt[1] if len(radius_opt) > 1 else "90%", half, half * 0.9
            ),
            self._r0 + 6.0,
            half,
        )
        total = sum(r.value for r in self._roots) or 1.0
        acc = 0.0
        for root in self._roots:
            span = root.value / total * 360.0
            self._assign_angles(root, acc, acc + span, 0)
            acc += span

        def collect(node, path=()):
            node.style_index = len(self._nodes)
            node.path = path
            self._nodes.append(node)
            for child_index, child in enumerate(node.children):
                collect(child, path + (child_index,))

        for root_index, root in enumerate(self._roots):
            collect(root, prefix + (root_index,))

    def _depth_of(self, node):
        if not node.children:
            return node.depth
        return max(self._depth_of(c) for c in node.children)

    def _assign_angles(self, node, a0, a1, level):
        node.a0, node.a1, node.level = a0, a1, level
        total = sum(c.value for c in node.children)
        if total <= 0:
            return
        acc = a0
        for c in node.children:
            span = (a1 - a0) * c.value / total
            self._assign_angles(c, acc, acc + span, level + 1)
            acc += span

    def _ring(self, level):
        """层号 → (内半径, 外半径)。"""
        band = (self._r1 - self._r0) / max(1, self._max_depth + 1)
        return self._r0 + band * level, self._r0 + band * (level + 1)

    def _pt(self, a_deg, r):
        rad = math.radians(a_deg)
        return QPointF(
            self._center.x() + r * math.sin(rad), self._center.y() - r * math.cos(rad)
        )

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        border = QColor(T("color.bg.base"))
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for node in self._nodes:
            span = (node.a1 - node.a0) * anim_t
            if span <= 0.05:
                continue
            r0, r1 = self._ring(node.level)
            rect_out = QRectF(
                self._center.x() - r1, self._center.y() - r1, 2 * r1, 2 * r1
            )
            rect_in = QRectF(
                self._center.x() - r0, self._center.y() - r0, 2 * r0, 2 * r0
            )
            qt_start = 90.0 - node.a0
            qt_span = -span
            path = QPainterPath()
            path.arcMoveTo(rect_out, qt_start)
            path.arcTo(rect_out, qt_start, qt_span)
            if r0 > 0.5:
                path.arcTo(rect_in, qt_start + qt_span, -qt_span)
            else:
                path.lineTo(self._center)
            path.closeSubpath()
            color = QColor(self.itemColor(node.style_index, default=node.color))
            alpha = self.itemOpacity(node.style_index)
            border_color, border_w = self.itemBorder(node.style_index)
            if hovered is not None:
                if node.style_index == hovered:
                    emphasis = self.emphasisColor(node.style_index)
                    color = emphasis if emphasis is not None else color.lighter(112)
                else:
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.35
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            p.setPen(QPen(border_color or border, border_w if border_w > 0 else 1.0))
            p.setBrush(color)
            p.drawPath(path)
        self._paint_labels(p, anim_t)
        p.restore()

    def onMousePress(self, pos: QPointF) -> bool:
        """下钻交互：点击有子级扇区进入；点击中心孔返回上级。"""
        center_dist = math.hypot(pos.x() - self._center.x(), pos.y() - self._center.y())
        if center_dist <= max(2.0, self._r0) and self._focus_path:
            self._focus_path.pop()
            self.chart.invalidateLayout()
            self.chart.update()
            return True
        hit = self.hitTest(pos)
        if hit is None:
            return False
        index = hit.get("dataIndex")
        if not isinstance(index, int) or not (0 <= index < len(self._nodes)):
            return False
        node = self._nodes[index]
        if not node.children:
            return False
        self._focus_path = list(node.path)
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def resetDrill(self) -> None:
        """返回顶层（ECharts sunburst 的返回根节点）。"""
        if self._focus_path:
            self._focus_path = []
            self.chart.invalidateLayout()
            self.chart.update()

    def _paint_labels(self, p, anim_t):
        label_opt = dict(self.opt.get("label") or {})
        if not bool(label_opt.get("show", True)):
            return
        min_angle = _to_float(label_opt.get("minAngle"), 8.0)
        font = _label_font(label_opt.get("fontSize"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        for node in self._nodes:
            if not node.name:
                continue
            span = (node.a1 - node.a0) * anim_t
            if span < min_angle:
                continue  # 角区过小省略标签
            r0, r1 = self._ring(node.level)
            mid = node.a0 + span / 2
            rm = (r0 + r1) / 2
            pt = self._pt(mid, rm)
            # 沿角度旋转标签；左半圈翻转防倒置
            deg = mid % 360.0
            flip = 90.0 < deg < 270.0
            p.save()
            p.translate(pt)
            p.rotate(deg + (180.0 if flip else 0.0))
            p.setPen(QColor(ON_FILL_WHITE))
            band_w = math.radians(span) * rm
            text = node.name
            tw = fm.horizontalAdvance(text)
            if tw <= max(band_w - 4, 12) or span >= 30:
                p.drawText(
                    QRectF(-tw / 2, -fm.height() / 2, tw + 2, fm.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )
            p.restore()

    def hitTest(self, pos: QPointF):
        if not self._nodes:
            return None
        dx = pos.x() - self._center.x()
        dy = pos.y() - self._center.y()
        r = math.hypot(dx, dy)
        a = math.degrees(math.atan2(dx, -dy)) % 360.0
        best = None
        for node in self._nodes:
            # 整圆特判见 ``PieSeriesRenderer.hitTest``（根因完全相同）
            a0 = float(node.a0) % 360.0
            a1 = float(node.a1) % 360.0
            if float(node.a1) - float(node.a0) >= 360.0:
                in_angle = True
            elif a0 <= a1:
                in_angle = a0 <= a < a1
            else:
                in_angle = a >= a0 or a < a1
            if not in_angle:
                continue
            r0, r1 = self._ring(node.level)
            if r0 - 1 <= r <= r1 + 1:
                if best is None or node.level > best.level:
                    best = node
        if best is None:
            return None
        return {
            "name": best.name,
            "value": best.value,
            "series": self.name,
            "depth": best.level,
            "dataIndex": getattr(best, "style_index", None),
        }


# ---------------------------------------------------------------------------
# 6. treemap 矩形树图（squarified）
# ---------------------------------------------------------------------------


def _squarify(items, rect):
    """squarified 布局：items [(key, value)] 按面积填充 rect。

    返回 {key: QRectF}。经典 Bruls 算法：按值降序沿短边分行，
    行内保持长宽比尽量接近 1。
    """
    result = {}
    if not items or rect.width() <= 0 or rect.height() <= 0:
        return result
    total = sum(v for _, v in items)
    if total <= 0:
        return result
    scale = rect.width() * rect.height() / total
    remaining = [
        (k, v * scale)
        for k, v in sorted(items, key=lambda kv: kv[1], reverse=True)
        if v > 0
    ]
    x, y = rect.left(), rect.top()
    w, h = rect.width(), rect.height()

    def worst(row, side):
        areas = [a for _, a in row]
        s = sum(areas)
        if s <= 0 or side <= 0:
            return float("inf")
        mx, mn = max(areas), min(areas)
        return max(side * side * mx / (s * s), s * s / (side * side * mn))

    while remaining:
        side = min(w, h)
        row = [remaining.pop(0)]
        while remaining:
            cand = row + [remaining[0]]
            if worst(cand, side) <= worst(row, side):
                row.append(remaining.pop(0))
            else:
                break
        row_area = sum(a for _, a in row)
        if w >= h:
            col_w = row_area / h if h > 0 else 0.0
            cy = y
            for key, area in row:
                rh = area / col_w if col_w > 0 else 0.0
                result[key] = QRectF(x, cy, col_w, rh)
                cy += rh
            x += col_w
            w -= col_w
        else:
            row_h = row_area / w if w > 0 else 0.0
            cx = x
            for key, area in row:
                rw = area / row_h if row_h > 0 else 0.0
                result[key] = QRectF(cx, y, rw, row_h)
                cx += rw
            y += row_h
            h -= row_h
    return result


class TreemapSeriesRenderer(SeriesRenderer):
    """矩形树图（squarified 布局，父子分层渲染）。

    option 键：
    - ``data``: [{"name","value","children":[...]}]；
    - ``breadcrumb``: {"show": True}：顶部路径条（ECharts 默认显示）；
    - ``label``: {"show": True, "fontSize": px}（名称标签，矩形过小省略）；
    - ``gapWidth``: 矩形间隙 px（默认 1）；
    - 颜色：顶层分支取调色板（``itemStyle.color`` 可覆盖），
      子级同色相逐级递减明度；
    - 交互：点击父块下钻，点击空白 / 面包屑返回上级（``resetDrill()`` 回顶层）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # 所有可见节点（父先子后，绘制时子覆盖父）
        self._crumb = ""
        self._crumb_y = 2.0
        #: 下钻路径（子级下标序列；空 = 顶层）
        self._focus_path = []
        self._crumb_rect = QRectF()

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        roots = _build_hierarchy(self.data())
        if not roots:
            self._crumb = ""
            return
        _assign_branch_colors(self.chart, roots)
        # 下钻：按路径解析当前显示层级（路径失效时回到顶层）
        display = roots
        focus_names = []
        prefix: tuple = ()
        for idx in list(self._focus_path):
            if 0 <= idx < len(display):
                focus_names.append(display[idx].name)
                prefix = prefix + (idx,)
                display = display[idx].children
            else:
                self._focus_path = []
                focus_names = []
                prefix = ()
                display = roots
                break
        crumb_opt = dict(self.opt.get("breadcrumb") or {})
        # ECharts 默认显示面包屑；顶部预留条带避免与内容重叠
        self._crumb_show = bool(crumb_opt.get("show", True))
        top_pad = 22.0 if self._crumb_show else 0.0
        area = QRectF(
            rect.left() + 2,
            rect.top() + top_pad + 2,
            max(4.0, rect.width() - 4),
            max(4.0, rect.height() - top_pad - 4),
        )
        self._crumb = " / ".join(r.name for r in roots if r.name)
        self._crumb_y = rect.top() + 3
        gap = _clamp(_to_float(self.opt.get("gapWidth"), 1.0), 0.0, 8.0)
        order = [0]

        def lay(node, r, path=()):
            node.rect = r
            node.style_index = order[0]
            node.path = path
            order[0] += 1
            self._nodes.append(node)  # 父先子后，绘制顺序正确（子覆盖父）
            if not node.children or r.width() < 10 or r.height() < 10:
                return
            inner = QRectF(r).adjusted(1, 1, -1, -1)
            # 父容器：顶部预留 header 条带（ECharts 父子分层观感）
            header_h = 16.0 if r.height() > 34 else 0.0
            inner.setTop(inner.top() + header_h)
            if inner.width() < 6 or inner.height() < 6:
                return
            items = [(id(c), c.value) for c in node.children]
            rects = _squarify(items, inner)
            for child_index, c in enumerate(node.children):
                cr = rects.get(id(c))
                if cr is None:
                    continue
                lay(
                    c,
                    cr.adjusted(gap / 2, gap / 2, -gap / 2, -gap / 2),
                    path + (child_index,),
                )

        items = [(id(r_), r_.value) for r_ in display]
        rects = _squarify(items, area)
        for root_index, root in enumerate(display):
            rr = rects.get(id(root))
            if rr is None:
                continue
            lay(
                root,
                rr.adjusted(gap / 2, gap / 2, -gap / 2, -gap / 2),
                prefix + (root_index,),
            )
        self._crumb = " / ".join(focus_names) if focus_names else ""

    def onMousePress(self, pos: QPointF) -> bool:
        """下钻交互：点击父块进入；点击空白 / 面包屑返回上级。"""
        hit = self.hitTest(pos)
        if hit is None:
            if self._focus_path:
                self._focus_path.pop()
                self.chart.invalidateLayout()
                self.chart.update()
                return True
            return False
        index = hit.get("dataIndex")
        if not isinstance(index, int) or not (0 <= index < len(self._nodes)):
            return False
        node = self._nodes[index]
        if not node.children:
            return False
        self._focus_path = list(node.path)
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def resetDrill(self) -> None:
        """返回顶层。"""
        if self._focus_path:
            self._focus_path = []
            self.chart.invalidateLayout()
            self.chart.update()

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        font = _label_font(label_opt.get("fontSize"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        border = QColor(T("color.bg.base"))
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for node in self._nodes:
            r = node.rect
            if r.width() <= 0.5 or r.height() <= 0.5:
                continue
            color = QColor(self.itemColor(node.style_index, default=node.color))
            alpha = self.itemOpacity(node.style_index)
            if hovered is not None:
                if node.style_index == hovered:
                    color = color.lighter(112)
                else:
                    alpha *= 0.35
            color = with_alpha(color, int((60 + 195 * anim_t) * alpha))
            border_color, border_w = self.itemBorder(node.style_index)
            p.setPen(QPen(border_color or border, border_w or 1.0))
            p.setBrush(color)
            p.drawRect(r)
            if not label_show or not node.name:
                continue
            is_parent = bool(node.children)
            if is_parent:
                # 父级标签画在 header 区（顶部）
                if r.height() < 20:
                    continue
                p.setPen(QColor(ON_FILL_WHITE))
                p.drawText(
                    QRectF(r.left() + 4, r.top() + 1, r.width() - 8, 15),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    node.name,
                )
                continue
            if (
                r.width() < fm.horizontalAdvance(node.name) * 0.9
                or r.height() < fm.height() + 2
            ):
                continue  # 矩形过小省略标签
            p.setPen(with_alpha(QColor(ON_FILL_WHITE), 230))
            p.drawText(
                QRectF(r.left() + 3, r.top() + 1, r.width() - 6, fm.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                node.name,
            )
        # 顶部面包屑（默认显示，drill 后为当前焦点路径）
        if getattr(self, "_crumb_show", False) and self._crumb:
            p.setFont(font)
            p.setPen(_text_color("color.text.secondary"))
            p.drawText(
                QRectF(
                    6,
                    self._crumb_y,
                    max(20.0, self.chart.width() - 12),
                    fm.height() + 2,
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._crumb,
            )
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        for node in self._nodes:
            if node.rect.contains(pos):
                if best is None or node.depth > best.depth:
                    best = node
        if best is None:
            return None
        return {
            "name": best.name,
            "value": best.value,
            "series": self.name,
            "depth": best.depth,
            "dataIndex": getattr(best, "style_index", None),
        }


# ---------------------------------------------------------------------------
# 7. tree 树图
# ---------------------------------------------------------------------------


class TreeSeriesRenderer(SeriesRenderer):
    """树图（按层级布局）。

    option 键：
    - ``data``: [根节点 {"name","children":[...]}]（多根取首个为主，其余并列显示）；
    - ``orient``: "LR"（默认，左根右叶）/ "TB"（上根下叶）；
    - ``edgeShape``: "polyline"（默认正交折线）/ "curve"（贝塞尔曲线）；
    - ``label``: {"show": True, "fontSize": px}（节点名称）；
    - ``symbolSize``: 节点圆点直径 px（默认 8）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [(node, QPointF)]
        self._edges = []  # [(QPointF parent, QPointF child)]

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        self._edges = []
        roots = _build_hierarchy(self.data())
        if not roots:
            return
        _assign_branch_colors(self.chart, roots)
        # 逻辑布局：x = 深度，y = 叶子序号（内部节点取子级均值）
        leaf_counter = [0]

        def place(node, depth):
            node.x = float(depth)
            if not node.children:
                node.y = float(leaf_counter[0])
                leaf_counter[0] += 1
            else:
                for c in node.children:
                    place(c, depth + 1)
                node.y = sum(c.y for c in node.children) / len(node.children)

        for root in roots:
            place(root, 0)
        max_depth = 0
        leaf_total = max(1, leaf_counter[0])

        def walk(node):
            nonlocal max_depth
            max_depth = max(max_depth, int(node.x))
            for c in node.children:
                walk(c)

        for root in roots:
            walk(root)
        orient = str(self.opt.get("orient") or "LR").upper()
        pad = 36.0
        span_x = max(1, max_depth)
        span_y = max(1, leaf_total - 1)
        usable_w = max(10.0, rect.width() - pad * 2)
        usable_h = max(10.0, rect.height() - pad * 2)

        def to_px(node):
            fx = node.x / span_x if span_x else 0.5
            fy = node.y / span_y if span_y else 0.5
            if orient == "TB":
                return QPointF(
                    rect.left() + pad + fy * usable_w,
                    rect.top() + pad * 0.5 + fx * (usable_h - pad * 0.5),
                )
            return QPointF(
                rect.left() + pad + fx * (usable_w - pad * 0.5),
                rect.top() + pad + fy * (usable_h - pad),
            )

        pos = {}

        def collect(node):
            pt = to_px(node)
            pos[id(node)] = pt
            self._nodes.append((node, pt))
            for c in node.children:
                collect(c)
                self._edges.append((pt, pos[id(c)]))

        for root in roots:
            collect(root)

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        orient = str(self.opt.get("orient") or "LR").upper()
        edge = str(self.opt.get("edgeShape") or "polyline")
        c_line = _text_color("color.border.strong")
        pen = QPen(c_line, 1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 边按 anim_t 逐层显现：以父→子中点裁剪
        for p0, p1 in self._edges:
            q1 = QPointF(
                p0.x() + (p1.x() - p0.x()) * anim_t, p0.y() + (p1.y() - p0.y()) * anim_t
            )
            if edge == "curve":
                path = QPainterPath(p0)
                if orient == "TB":
                    my = (p0.y() + q1.y()) / 2
                    path.cubicTo(QPointF(p0.x(), my), QPointF(q1.x(), my), q1)
                else:
                    mx = (p0.x() + q1.x()) / 2
                    path.cubicTo(QPointF(mx, p0.y()), QPointF(mx, q1.y()), q1)
                p.drawPath(path)
            else:  # polyline 正交折线
                if orient == "TB":
                    mid = QPointF(q1.x(), p0.y())
                else:
                    mid = QPointF(p0.x(), q1.y())
                p.drawLine(p0, mid)
                p.drawLine(mid, q1)
        # 节点 + 标签
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        font = _label_font(label_opt.get("fontSize"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        size = _to_float(self.opt.get("symbolSize"), 8.0)
        for node, pt in self._nodes:
            p.setPen(QPen(QColor(T("color.bg.elevated")), 1.5))
            p.setBrush(node.color or self.color())
            p.drawEllipse(pt, size / 2, size / 2)
            if not label_show or not node.name:
                continue
            p.setPen(_text_color("color.text.primary"))
            tw = fm.horizontalAdvance(node.name)
            if orient == "TB":
                p.drawText(
                    QRectF(pt.x() - tw / 2, pt.y() + size / 2 + 2, tw + 4, fm.height()),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    node.name,
                )
            else:
                is_leaf = not node.children
                if is_leaf:
                    p.drawText(
                        QRectF(
                            pt.x() + size / 2 + 3,
                            pt.y() - fm.height() / 2,
                            tw + 4,
                            fm.height(),
                        ),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        node.name,
                    )
                else:
                    p.drawText(
                        QRectF(
                            pt.x() - tw - size / 2 - 3,
                            pt.y() - fm.height() / 2,
                            tw + 4,
                            fm.height(),
                        ),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        node.name,
                    )
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = 12.0
        for node, pt in self._nodes:
            d = _dist(pos, pt)
            if d <= best_d:
                best_d = d
                best = node
        if best is None:
            return None
        return {
            "name": best.name,
            "value": best.value,
            "series": self.name,
            "depth": int(best.x),
        }


# ---------------------------------------------------------------------------
# 8. sankey 桑基图
# ---------------------------------------------------------------------------


class SankeySeriesRenderer(SeriesRenderer):
    """桑基图（节点矩形 + 贝塞尔流带）。

    option 键：
    - ``data`` / ``nodes``: [{"name"}]（节点，二者等价，data 优先）；
    - ``links``: [{"source","target","value"}]（source/target 为名称或下标）；
    - ``nodeWidth``: 节点矩形宽度 px（默认 14）；
    - ``nodeGap``: 同列节点间距 px（默认 10）；
    - ``layoutIterations``: 排序迭代轮数（默认 6，减少流带交叉）；
    - ``label``: {"show": True, "fontSize": px}（节点名称）；
    - 节点着色：调色板按下标循环；流带取源节点色半透明。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [dict(name,color,rect,value,depth)]
        self._bands = []  # [dict(path=QPainterPath,color,source,target,value)]
        self._name_index = {}

    # -- 数据解析 ----------------------------------------------------------
    def _parse(self):
        raw_nodes = self.opt.get("data")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raw_nodes = self.opt.get("nodes")
        nodes = []
        for i, item in enumerate(raw_nodes or []):
            if isinstance(item, dict):
                name = str(item.get("name") or f"node{i}")
            else:
                name = str(item)
            nodes.append({"name": name, "index": i})
        self._name_index = {}
        for nd in nodes:
            self._name_index.setdefault(nd["name"], nd["index"])
        links = []
        for item in self.opt.get("links") or []:
            if not isinstance(item, dict):
                continue
            s = self._node_index(item.get("source"))
            t = self._node_index(item.get("target"))
            v = _to_float(item.get("value"), 0.0)
            if s is None or t is None or s == t or v <= 0:
                continue
            links.append({"source": s, "target": t, "value": v})
        return nodes, links

    def _node_index(self, ref):
        if isinstance(ref, bool):
            return None
        if isinstance(ref, (int, float)):
            i = int(ref)
            return i if 0 <= i < len(self._name_index) else None
        return self._name_index.get(str(ref))

    # -- 布局 --------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        self._bands = []
        nodes, links = self._parse()
        if not nodes:
            return
        n = len(nodes)
        # 邻接表
        out_adj = [[] for _ in range(n)]
        in_adj = [[] for _ in range(n)]
        for lk in links:
            out_adj[lk["source"]].append(lk)
            in_adj[lk["target"]].append(lk)
        # 节点值 = max(入流, 出流)
        values = [0.0] * n
        for i in range(n):
            values[i] = max(
                sum(link["value"] for link in out_adj[i]),
                sum(link["value"] for link in in_adj[i]),
            )
        # BFS 分层（最长路径：深度 = 最远前置层 + 1）
        depth = [0] * n
        indeg = [len(in_adj[i]) for i in range(n)]
        queue = [i for i in range(n) if indeg[i] == 0]
        order = list(queue)
        head = 0
        while head < len(order):
            u = order[head]
            head += 1
            for lk in out_adj[u]:
                v = lk["target"]
                depth[v] = max(depth[v], depth[u] + 1)
                indeg[v] -= 1
                if indeg[v] == 0:
                    order.append(v)
                    queue.append(v)
        # 环 / 不可达节点兜底：按出边递增深度限幅
        for _ in range(n):
            changed = False
            for lk in links:
                if depth[lk["target"]] <= depth[lk["source"]]:
                    depth[lk["target"]] = depth[lk["source"]] + 1
                    changed = True
            if not changed:
                break
        max_depth = max(depth) if depth else 0
        columns = [[] for _ in range(max_depth + 1)]
        for i in range(n):
            columns[depth[i]].append(i)
        # 迭代排序减交叉：按对侧邻居重心排序（正反向各扫）
        iterations = max(0, int(_to_float(self.opt.get("layoutIterations"), 6)))
        pos_in_col = {i: k for col in columns for k, i in enumerate(col)}

        def barycenter(col, neighbors_fn, other_pos):
            def key(i):
                neigh = neighbors_fn(i)
                if not neigh:
                    return pos_in_col.get(i, 0)
                return sum(other_pos.get(j, 0) for j in neigh) / len(neigh)

            return key

        for _ in range(iterations):
            for d in range(1, max_depth + 1):  # 正向：按入边源排序
                col = columns[d]
                other = {i: pos_in_col[i] for i in columns[d - 1]}
                col.sort(
                    key=barycenter(
                        col, lambda i: [lk["source"] for lk in in_adj[i]], other
                    )
                )
                for k, i in enumerate(col):
                    pos_in_col[i] = k
            for d in range(max_depth - 1, -1, -1):  # 反向：按出边目标排序
                col = columns[d]
                other = {i: pos_in_col[i] for i in columns[d + 1]}
                col.sort(
                    key=barycenter(
                        col, lambda i: [lk["target"] for lk in out_adj[i]], other
                    )
                )
                for k, i in enumerate(col):
                    pos_in_col[i] = k
        # 几何：列 x 均布，列内按值纵向堆叠
        node_w = _clamp(_to_float(self.opt.get("nodeWidth"), 14.0), 4.0, 60.0)
        node_gap = _clamp(_to_float(self.opt.get("nodeGap"), 10.0), 0.0, 60.0)
        pad_x, pad_y = 56.0, 12.0
        plot = QRectF(
            rect.left() + pad_x,
            rect.top() + pad_y,
            max(20.0, rect.width() - pad_x * 2),
            max(20.0, rect.height() - pad_y * 2),
        )
        col_x = []
        for d in range(max_depth + 1):
            if max_depth == 0:
                col_x.append(plot.center().x() - node_w / 2)
            else:
                col_x.append(plot.left() + (plot.width() - node_w) * d / max_depth)
        node_rect = {}
        for d, col in enumerate(columns):
            total_v = sum(values[i] for i in col)
            avail_h = plot.height() - node_gap * max(0, len(col) - 1)
            scale = avail_h / total_v if total_v > 0 else 0.0
            y = plot.top()
            for i in col:
                h_i = max(3.0, values[i] * scale) if total_v > 0 else 6.0
                node_rect[i] = QRectF(col_x[d], y, node_w, h_i)
                y += h_i + node_gap
        # 流带偏移（源 / 目标各自的堆叠游标）
        src_off = {i: node_rect[i].top() for i in range(n)}
        tgt_off = {i: node_rect[i].top() for i in range(n)}
        for lk in sorted(links, key=lambda x: -x["value"]):
            s, t = lk["source"], lk["target"]
            rs, rt = node_rect[s], node_rect[t]
            band_scale = (rs.height() / values[s]) if values[s] > 0 else 0.0
            bh = max(1.5, lk["value"] * band_scale)
            y1 = src_off[s]
            y2 = tgt_off[t]
            src_off[s] += bh
            tgt_off[t] += bh
            x1 = rs.right()
            x2 = rt.left()
            path = QPainterPath()
            path.moveTo(x1, y1)
            mx = (x1 + x2) / 2
            path.cubicTo(mx, y1, mx, y2, x2, y2)
            path.lineTo(x2, y2 + bh)
            path.cubicTo(mx, y2 + bh, mx, y1 + bh, x1, y1 + bh)
            path.closeSubpath()
            self._bands.append(
                {
                    "path": path,
                    "source": nodes[s]["name"],
                    "target": nodes[t]["name"],
                    "value": lk["value"],
                    "source_color": _series_palette_color(self.chart, s),
                    "target_color": _series_palette_color(self.chart, t),
                    "color": _series_palette_color(self.chart, s),
                }
            )
        for i, nd in enumerate(nodes):
            self._nodes.append(
                {
                    "index": i,
                    "name": nd["name"],
                    "value": values[i],
                    "rect": node_rect[i],
                    "depth": depth[i],
                    "color": self.itemColor(
                        i, default=_series_palette_color(self.chart, i)
                    ),
                }
            )

    def _band_brush(self, band, anim_t):
        """流带画刷：``lineStyle.color`` 支持 source（默认）/ target / gradient / 色值。"""
        line_style = self.opt.get("lineStyle") or {}
        mode = line_style.get("color")
        opacity = 70.0
        if isinstance(line_style.get("opacity"), (int, float)):
            opacity = 255.0 * _clamp(float(line_style["opacity"]), 0.0, 1.0)
        if mode == "target":
            return with_alpha(band["target_color"], int(opacity * anim_t))
        if mode == "gradient":
            rect = band["path"].boundingRect()
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(
                0.0, with_alpha(band["source_color"], int(opacity * anim_t))
            )
            grad.setColorAt(
                1.0, with_alpha(band["target_color"], int(opacity * anim_t))
            )
            return grad
        if isinstance(mode, str) and mode not in ("source",):
            color = QColor(mode)
            if color.isValid():
                return with_alpha(color, int(opacity * anim_t))
        return with_alpha(band["source_color"], int(opacity * anim_t))

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        # 流带（默认源色半透明；anim_t 渐入）
        for band in self._bands:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._band_brush(band, anim_t))
            p.drawPath(band["path"])
        # 节点 + 标签
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        font = _label_font(label_opt.get("fontSize"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        c_text = _text_color("color.text.primary")
        max_depth = max((nd["depth"] for nd in self._nodes), default=0)
        for nd in self._nodes:
            r = nd["rect"]
            color = QColor(nd["color"])
            alpha = self.itemOpacity(nd["index"])
            if hovered is not None:
                if nd["index"] == hovered:
                    emphasis = self.emphasisColor(nd["index"])
                    color = emphasis if emphasis is not None else color.lighter(112)
                else:
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.4
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(with_alpha(color, int(255 * anim_t * alpha)))
            p.drawRect(r)
            if not label_show:
                continue
            p.setPen(c_text)
            tw = fm.horizontalAdvance(nd["name"])
            if nd["depth"] >= max_depth:  # 末列标签放左侧
                p.drawText(
                    QRectF(
                        r.left() - tw - 6,
                        r.center().y() - fm.height() / 2,
                        tw + 4,
                        fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    nd["name"],
                )
            else:
                p.drawText(
                    QRectF(
                        r.right() + 4,
                        r.center().y() - fm.height() / 2,
                        tw + 4,
                        fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    nd["name"],
                )
        p.restore()

    def hitTest(self, pos: QPointF):
        for nd in self._nodes:
            if nd["rect"].contains(pos):
                return {
                    "name": nd["name"],
                    "value": nd["value"],
                    "series": self.name,
                    "depth": nd["depth"],
                    "dataIndex": nd.get("index"),
                }
        for band in self._bands:
            if band["path"].contains(pos):
                return {
                    "name": f"{band['source']} → {band['target']}",
                    "value": band["value"],
                    "series": self.name,
                    "source": band["source"],
                    "target": band["target"],
                }
        return None


# ---------------------------------------------------------------------------
# 9. graph 关系图
# ---------------------------------------------------------------------------


class GraphSeriesRenderer(SeriesRenderer):
    """关系图（节点 + 边）。

    option 键：
    - ``data`` / ``nodes``: [{"name","symbolSize","value","category","itemStyle"}]；
    - ``categories``: ["分类"] 或 [{"name","itemStyle":{"color"}}]（节点分类着色）；
    - ``links``: [{"source","target"}]（名称或下标）；
    - ``layout``: "force"（默认，斥力 + 引力迭代 ~80 轮，确定性随机种子
      保证可复现）/ "circular"（均布圆环）；
    - ``force``: {"seed": 42, "iterations": 80, "repulsion": 1.0}；
    - ``label``: {"show": True, "fontSize": px}（节点名称）；
    - ``symbolSize``: 默认节点直径 px（节点级 symbolSize 优先）；
    - ``draggable``: True 时按住节点拖拽调整位置（拖拽后位置固定，布局重算
      不覆盖；ECharts 默认 False）；
    - ``roam``: True / "scale" / "move" 开启滚轮缩放 + 空白处拖拽平移，
      ``zoom`` 为初始缩放倍数，``resetRoam()`` 复位。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [dict(name,size,pos=QPointF,color)]
        self._edges = []  # [(i, j)]
        self._drag_index = None
        self._fixed: dict = {}  # 拖拽后的固定位置 {节点下标: QPointF}
        #: 力导布局记忆化（见 ``_force_positions``）。条目 ``(key, positions)``，
        #: ``positions`` 是**归一化 [0,1] 坐标**的 list，调用方只读。
        self._force_cache = None
        self._pan = QPointF()
        self._pan_start = None
        self._plot = QRectF()
        self._roam = self._parse_roam()
        try:
            self._zoom = max(0.2, min(5.0, float(opt.get("zoom") or 1.0)))
        except (TypeError, ValueError, OverflowError):
            self._zoom = 1.0

    def _parse_roam(self):
        """``roam`` → ``(scale 可否缩放, move 可否平移)``。共用 ``parse_roam``。"""
        return _parse_roam(self.opt.get("roam", False))

    def _parse(self):
        raw_nodes = self.opt.get("data")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raw_nodes = self.opt.get("nodes")
        categories = self.opt.get("categories") or []
        nodes = []
        name_index = {}
        for i, item in enumerate(raw_nodes or []):
            if isinstance(item, dict):
                name = str(item.get("name") or f"node{i}")
                size = item.get("symbolSize")
                category = item.get("category")
                item_style = self.itemStyleOf(item)
            else:
                name, size, category, item_style = str(item), None, None, {}
            nodes.append(
                {
                    "name": name,
                    "size": size,
                    "category": category,
                    "itemStyle": item_style,
                }
            )
            name_index.setdefault(name, i)
        edges = []

        def idx(ref):
            if isinstance(ref, bool):
                return None
            if isinstance(ref, (int, float)):
                k = int(ref)
                return k if 0 <= k < len(nodes) else None
            return name_index.get(str(ref))

        for item in self.opt.get("links") or []:
            if not isinstance(item, dict):
                continue
            s, t = idx(item.get("source")), idx(item.get("target"))
            if s is None or t is None or s == t:
                continue
            edges.append((s, t))
        return nodes, edges, categories

    def _category_color(self, category, categories):
        """分类着色：categories[category].itemStyle.color 优先，否则分类下标取色。"""
        if isinstance(category, bool) or category is None:
            return None
        if isinstance(category, (int, float)):
            index = int(category)
        else:
            index = None
            for i, cat in enumerate(categories):
                name = cat.get("name") if isinstance(cat, dict) else cat
                if str(name) == str(category):
                    index = i
                    break
        if index is None or not (0 <= index < len(categories)):
            return None
        cat = categories[index]
        if isinstance(cat, dict):
            item_style = cat.get("itemStyle") or {}
            raw = item_style.get("color")
            if isinstance(raw, str) and raw:
                color = QColor(raw)
                if color.isValid():
                    return color
        return _series_palette_color(self.chart, index)

    # -- 布局 --------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        self._edges = []
        nodes, edges, categories = self._parse()
        if not nodes:
            return
        n = len(nodes)
        self._edges = edges
        mode = str(self.opt.get("layout") or "force")
        force_opt = dict(self.opt.get("force") or {})
        pad = 30.0
        plot = QRectF(
            rect.left() + pad,
            rect.top() + pad,
            max(20.0, rect.width() - pad * 2),
            max(20.0, rect.height() - pad * 2),
        )
        self._plot = QRectF(plot)
        if mode == "circular":
            positions = []
            cx, cy = plot.center().x(), plot.center().y()
            r = min(plot.width(), plot.height()) / 2
            for i in range(n):
                theta = -math.pi / 2 + i / n * 2 * math.pi
                positions.append([cx + r * math.cos(theta), cy + r * math.sin(theta)])
        else:
            positions = self._force_positions(nodes, edges, force_opt)
        default_size = _to_float(self.opt.get("symbolSize"), 14.0)
        for i, nd in enumerate(nodes):
            size = _to_float(nd["size"], default_size)
            fixed = self._fixed.get(i)
            if fixed is not None:
                pos = QPointF(fixed)
            else:
                # 力导结果在归一化 [0,1] 空间里，缩放到绘图区（circular 分支
                # 已经是像素坐标，故按模式区分）
                if mode == "circular":
                    pos = QPointF(positions[i][0], positions[i][1])
                else:
                    pos = QPointF(
                        plot.left() + positions[i][0] * plot.width(),
                        plot.top() + positions[i][1] * plot.height(),
                    )
            category_color = self._category_color(nd["category"], categories)
            self._nodes.append(
                {
                    "name": nd["name"],
                    "size": _clamp(size, 4.0, 60.0),
                    "pos": pos,
                    "color": category_color or _series_palette_color(self.chart, i),
                    "item_style": nd["itemStyle"],
                }
            )

    # -- 交互：节点拖拽 / roam ----------------------------------------------
    def _transform(self, pt: QPointF) -> QPointF:
        """布局坐标 → 屏幕坐标（roam 缩放 / 平移）。"""
        if self._zoom == 1.0 and self._pan.isNull():
            return QPointF(pt)
        c = self._plot.center()
        return QPointF(
            c.x() + (pt.x() - c.x()) * self._zoom + self._pan.x(),
            c.y() + (pt.y() - c.y()) * self._zoom + self._pan.y(),
        )

    def _inverse(self, pos: QPointF) -> QPointF:
        """屏幕坐标 → 布局坐标（拖拽时用）。"""
        if self._zoom == 1.0 and self._pan.isNull():
            return QPointF(pos)
        c = self._plot.center()
        return QPointF(
            c.x() + (pos.x() - c.x() - self._pan.x()) / self._zoom,
            c.y() + (pos.y() - c.y() - self._pan.y()) / self._zoom,
        )

    def onMousePress(self, pos: QPointF) -> bool:
        if bool(self.opt.get("draggable", False)):
            for i, nd in enumerate(self._nodes):
                if _dist(pos, self._transform(nd["pos"])) <= max(
                    nd["size"] / 2 + 2, 8.0
                ):
                    self._drag_index = i
                    return True
        if self._roam[1]:
            self._pan_start = QPointF(pos)
            return True
        return False

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._drag_index is not None:
            layout_pos = self._inverse(pos)
            self._fixed[self._drag_index] = layout_pos
            self._nodes[self._drag_index]["pos"] = layout_pos
            # 拖节点改的是**渲染器自己的几何**（``_nodes[i]["pos"]``），
            # 必须走 invalidateLayout 让布局缓存与系列层位图一起失效 ——
            # 只 update() 的话两个缓存都留着旧值，拖动看起来完全没反应。
            self.chart.invalidateLayout()
            self.chart.update()
            return True
        if self._pan_start is not None:
            self._pan = QPointF(pos) - self._pan_start
            self.chart.invalidateLayout()  # 同上：pan 改的是绘制变换
            self.chart.update()
            return True
        return False

    def onMouseRelease(self, pos: QPointF) -> bool:
        if self._drag_index is not None:
            layout_pos = self._inverse(pos)
            self._fixed[self._drag_index] = layout_pos
            self._drag_index = None
            return True
        if self._pan_start is not None:
            self._pan_start = None
            return True
        return False

    def onWheel(self, event) -> bool:
        if not self._roam[0]:
            return False
        delta = event.angleDelta().y()
        if delta == 0:
            return False
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.2, min(5.0, self._zoom * factor))
        self.chart.invalidateLayout()  # zoom 改的是绘制变换
        self.chart.update()
        return True

    def resetRoam(self) -> None:
        """复位 roam 缩放 / 平移（ECharts restore 语义）。"""
        self._pan = QPointF()
        self._pan_start = None
        self._zoom = 1.0
        self.chart.invalidateLayout()
        self.chart.update()

    def resetPositions(self) -> None:
        """清除拖拽固定位置，恢复自动布局。"""
        if self._fixed:
            self._fixed = {}
            self.chart.invalidateLayout()
            self.chart.update()

    def _force_positions(self, nodes, edges, force_opt):
        """力导布局结果（带记忆化）。

        ``_force_layout`` 是**纯函数**：随机种子固定，且全程在归一化 [0,1]
        空间里迭代（结果随后才按 ``plot`` 缩放），所以它的输出只取决于
        「节点数 + 边集合 + seed / iterations / repulsion」。

        而 ``layout`` 会被**每一次** ``_layout_all`` 调 —— resize、悬停引起的
        重排、主题切换、图例显隐……每次都把 O(n² × iterations) 的纯 Python
        双层循环重跑一遍。实测 400 节点 / 80 轮 ≈ **1.8 秒**，而这些场景
        根本没改数据。

        记忆化的键覆盖全部输入：节点数、边集合（``edges`` 是 ``(源下标, 目标下标)``
        元组的 list，**顺序敏感**）、三个参数。
        ``_fixed``（拖拽固定位置）在 ``_force_layout`` **之后**才应用，不进
        布局计算，所以拖拽节点不需要让缓存失效。
        """
        seed = int(_to_float(force_opt.get("seed"), 42))
        iterations = max(10, int(_to_float(force_opt.get("iterations"), 80)))
        repulsion = _clamp(_to_float(force_opt.get("repulsion"), 1.0), 0.1, 10.0)
        key = (
            len(nodes),
            tuple(edges),
            seed,
            iterations,
            repulsion,
        )
        hit = self._force_cache
        if hit is not None and hit[0] == key:
            return hit[1]
        positions = self._force_layout(
            nodes, edges, force_opt, seed, iterations, repulsion
        )
        self._force_cache = (key, positions)
        return positions

    def _force_layout(self, nodes, edges, force_opt, seed, iterations, repulsion):
        """Fruchterman-Reingold 简化力导布局（确定性随机种子）。

        在归一化 [0,1] 空间内迭代；输出与 ``plot`` 无关（缩放由调用方做），
        这正是 :meth:`_force_positions` 能记忆化的前提。
        """
        n = len(nodes)
        rng = random.Random(seed)
        # 归一化 [0,1] 空间内迭代
        pos = [[rng.random(), rng.random()] for _ in range(n)]
        area = 1.0
        k = math.sqrt(area / max(1, n)) * repulsion
        temp = 0.12
        for it in range(iterations):
            disp = [[0.0, 0.0] for _ in range(n)]
            # 斥力（全对）
            for i in range(n):
                for j in range(i + 1, n):
                    dx = pos[i][0] - pos[j][0]
                    dy = pos[i][1] - pos[j][1]
                    d2 = dx * dx + dy * dy
                    d = math.sqrt(d2) if d2 > 1e-9 else 1e-4
                    if d2 <= 1e-9:
                        dx, dy = rng.random() - 0.5, rng.random() - 0.5
                        d = math.hypot(dx, dy) or 1e-4
                    f = k * k / d
                    disp[i][0] += dx / d * f
                    disp[i][1] += dy / d * f
                    disp[j][0] -= dx / d * f
                    disp[j][1] -= dy / d * f
            # 引力（沿边）
            for s, t in edges:
                dx = pos[s][0] - pos[t][0]
                dy = pos[s][1] - pos[t][1]
                d = math.hypot(dx, dy) or 1e-4
                f = d * d / k
                disp[s][0] -= dx / d * f
                disp[s][1] -= dy / d * f
                disp[t][0] += dx / d * f
                disp[t][1] += dy / d * f
            # 向心重力
            for i in range(n):
                disp[i][0] += (0.5 - pos[i][0]) * 0.02
                disp[i][1] += (0.5 - pos[i][1]) * 0.02
            cool = temp * (1.0 - it / iterations)
            for i in range(n):
                d = math.hypot(disp[i][0], disp[i][1])
                if d <= 1e-9:
                    continue
                step = min(d, cool)
                pos[i][0] = _clamp(pos[i][0] + disp[i][0] / d * step, 0.0, 1.0)
                pos[i][1] = _clamp(pos[i][1] + disp[i][1] / d * step, 0.0, 1.0)
        return pos

    def _node_centroid(self):
        """所有节点的质心（动画收缩的锚点）。

        **必须挡空列表**：``paint`` 侧有 ``if not self._nodes: return`` 兜着，
        而 ``hitTest`` 没有这层 —— 空节点集（data 为空 / layout 还没跑）会
        直接 ``ZeroDivisionError``。而 ``hitTest`` 的异常被
        ``_hitItemWithSeries`` 的 try/except 吞掉，症状是「静默命中不到任何
        节点」，排查时完全看不出是被零除吃掉了。
        """
        n = len(self._nodes)
        if not n:
            return QPointF()
        return QPointF(
            sum(nd["pos"].x() for nd in self._nodes) / n,
            sum(nd["pos"].y() for nd in self._nodes) / n,
        )

    def _animated_points(self, anim_t):
        """动画进度下的屏幕坐标（``paint`` 与 ``hitTest`` 共用）。

        入场动画把每个节点从质心处「张开」到最终位置，所以命中必须用同一
        份插值 —— 否则动画进行中悬停命中的是还没飞到那儿的节点。
        """
        center = self._node_centroid()
        out = []
        for nd in self._nodes:
            pt = nd["pos"]
            out.append(
                self._transform(
                    QPointF(
                        center.x() + (pt.x() - center.x()) * anim_t,
                        center.y() + (pt.y() - center.y()) * anim_t,
                    )
                )
            )
        return out

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        pts = self._animated_points(anim_t)
        # 边
        p.setPen(QPen(with_alpha(_text_color("color.border.strong"), 160), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for s, t in self._edges:
            if 0 <= s < len(pts) and 0 <= t < len(pts):
                p.drawLine(pts[s], pts[t])
        # 节点 + 标签
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        font = _label_font(label_opt.get("fontSize"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for i, (nd, pt) in enumerate(zip(self._nodes, pts)):
            r = nd["size"] / 2
            style = nd.get("item_style") or {}
            raw = style.get("color")
            color = QColor(raw) if isinstance(raw, str) and raw else QColor(nd["color"])
            alpha = self.itemOpacity(i)
            if hovered is not None:
                if i == hovered or i == self._drag_index:
                    if i == hovered:
                        emphasis = self.emphasisColor(i)
                        if emphasis is not None:
                            color = emphasis
                        else:
                            color = color.lighter(112)
                elif i != self._drag_index:
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.4
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            p.setPen(QPen(QColor(T("color.bg.elevated")), 1.5))
            p.setBrush(color)
            p.drawEllipse(pt, r, r)
            if label_show and nd["name"]:
                p.setPen(_text_color("color.text.primary"))
                tw = fm.horizontalAdvance(nd["name"])
                p.drawText(
                    QRectF(pt.x() - tw / 2, pt.y() + r + 2, tw + 4, fm.height()),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    nd["name"],
                )
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = 1e9
        if not self._nodes:
            return None
        # 入场动画里节点向质心收缩（``paint`` 的 ``anim_pos``），命中必须用
        # 同一份公式，否则动画期悬停会命中一个「还没到那儿」的节点。
        pts = self._animated_points(self._anim_t)
        for i, nd in enumerate(self._nodes):
            d = _dist(pos, pts[i])
            if d <= nd["size"] / 2 + 4 and d < best_d:
                best_d = d
                best = (i, nd)
        if best is None:
            return None
        i, nd = best
        return {"name": nd["name"], "value": i, "series": self.name, "dataIndex": i}


# ---------------------------------------------------------------------------
# 10. lines 线图（Grid 直角坐标 + effect 移动亮点）
# ---------------------------------------------------------------------------


class LinesSeriesRenderer(SeriesRenderer):
    """线图（起终点坐标对，Grid 直角坐标系下绘制）。

    option 键：
    - ``coordinateSystem``: "cartesian2d"（默认，需配 xAxis/yAxis）；
    - ``data``: [{"coords": [[x1, y1], [x2, y2]]}, ...]；
    - ``lineStyle``: {"width": px, "color": "#..."（缺省取系列色）,
      "curveness": 0.0（>0 时二次贝塞尔弯曲）}；
    - ``effect``: {"show": True, "period": 4（秒 / 全程）,
      "symbolSize": 6, "color": "#..."}（QTimer 驱动移动亮点，生命周期挂
      ChartWidget，渲染器替换时自动停止，不泄漏）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._segments = []  # [dict(p0,p1,value)]
        self._phase = 0.0  # 亮点进度 [0,1)
        self._timer = None
        effect = self._effect_opt()
        if bool(effect.get("show", False)) and QApplication.instance() is not None:
            timer = QTimer(chart)  # 生命周期挂 ChartWidget
            timer.timeout.connect(self._on_tick)
            # 持续动效：Reduced/Disabled 下高亮不流动（相位冻结即静态态）。
            # 间隔只在这里出现一次 —— ``start_idle_loop`` 无论启不启动都会写
            # ``setInterval``，所以**不要**在前面再 ``setInterval(40)``：
            # 那是第二处魔数，改令牌时必然漏掉其中之一。
            start_idle_loop(timer, EFFECT_TICK_MS)
            self._timer = timer

    def _effect_opt(self):
        eff = self.opt.get("effect")
        return dict(eff or {})

    def _on_tick(self):
        """亮点推进。仅可见时 tick（渲染器替换自动停止；legend 隐藏暂停）。

        整个回调包裹：Qt 定时器回调中抛出的异常会终止进程。
        """
        timer = self._timer
        if timer is None:
            return
        try:
            alive = self in self.chart.seriesRenderers
        except RuntimeError:
            alive = False  # chart 已销毁
        if not alive:
            timer.stop()
            timer.deleteLater()
            self._timer = None
            return
        if not self.visible:
            if timer.isActive():
                timer.stop()
            return
        if not timer.isActive():
            timer.start()
        try:
            effect = self._effect_opt()
            period = max(0.5, _to_float(effect.get("period"), 4.0))
            # 步长按**实际 tick 间隔**算，别写死 0.04：那个魔数隐含「每 40ms
            # 走 4%」，一旦 ``start_idle_loop`` 因动效策略改了间隔（或者将来
            # 调 EFFECT_TICK_MS），亮点速度就与配置无关地错了 —— 而
            # ``period`` 是用户可见的 option，错的是「用户设的周期不生效」。
            step = max(1, int(timer.interval())) / 1000.0 / period
            self._phase = (self._phase + step) % 1.0
            self.chart.update()
        except RuntimeError:
            timer.stop()
            timer.deleteLater()
            self._timer = None
        except Exception:
            timer.stop()
            timer.deleteLater()
            self._timer = None

    def _on_visible_changed(self):
        """显隐变化钩子（core 图例显隐调用）：显示恢复时重启定时器。

        **必须走 ``start_idle_loop`` 而不是裸 ``timer.start()``**：裸 start
        绕过动效策略，于是「Reduced/Disabled 下持续动效停掉」被图例切换重新
        打开 —— 无障碍用户看到移动亮点照常流动。``start_idle_loop`` 幂等
        （内部先查 ``isActive()``）、守策略、且总会重写 interval。
        """
        if self.visible and self._timer is not None and not self._timer.isActive():
            start_idle_loop(self._timer, EFFECT_TICK_MS)

    def layout(self, rect: QRectF) -> None:
        self._segments = []
        coord = self.chart.coordFor(self.opt)
        if coord is None or not hasattr(coord, "mapPoint"):
            return
        for item in self.data():
            if not isinstance(item, dict):
                continue
            coords = item.get("coords")
            if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                continue
            c0, c1 = coords[0], coords[1]
            if (
                not isinstance(c0, (list, tuple))
                or len(c0) < 2
                or not isinstance(c1, (list, tuple))
                or len(c1) < 2
            ):
                continue
            try:
                p0 = coord.mapPoint(c0[0], c0[1])
                p1 = coord.mapPoint(c1[0], c1[1])
            except Exception:
                continue
            self._segments.append(
                {
                    "p0": p0,
                    "p1": p1,
                    "name": str(item.get("name") or ""),
                    "value": item.get("value"),
                }
            )

    def _curve_path(self, p0, p1, curveness):
        """直线 / 二次贝塞尔曲线路径。"""
        path = QPainterPath(p0)
        if abs(curveness) > 1e-6:
            mx, my = (p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2
            dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
            # 法向偏移控制点
            cx, cy = mx - dy * curveness, my + dx * curveness
            path.quadTo(QPointF(cx, cy), p1)
        else:
            path.lineTo(p1)
        return path

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._segments:
            return
        p.save()
        ls = dict(self.opt.get("lineStyle") or {})
        width = _to_float(ls.get("width"), 2.0)
        color = QColor(str(ls.get("color"))) if ls.get("color") else self.color()
        curveness = _to_float(ls.get("curveness"), 0.0)
        pen = QPen(with_alpha(color, int(220 * anim_t)), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for seg in self._segments:
            p.drawPath(self._curve_path(seg["p0"], seg["p1"], curveness))
        # 端点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(color, int(200 * anim_t)))
        for seg in self._segments:
            p.drawEllipse(seg["p0"], 2.5, 2.5)
            p.drawEllipse(seg["p1"], 2.5, 2.5)
        # effect 移动亮点
        effect = self._effect_opt()
        if bool(effect.get("show", False)) and anim_t > 0.5:
            dot_size = _to_float(effect.get("symbolSize"), 6.0)
            dot_color = (
                QColor(str(effect.get("color")))
                if effect.get("color")
                else QColor(ON_FILL_WHITE)
            )
            n = len(self._segments)
            for i, seg in enumerate(self._segments):
                phase = (self._phase + i / max(1, n)) % 1.0
                path = self._curve_path(seg["p0"], seg["p1"], curveness)
                pt = path.pointAtPercent(phase)
                # 光晕 + 亮点
                p.setBrush(with_alpha(dot_color, 60))
                p.drawEllipse(pt, dot_size, dot_size)
                p.setBrush(dot_color)
                p.drawEllipse(pt, dot_size / 2, dot_size / 2)
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = 8.0
        for i, seg in enumerate(self._segments):
            d = dist_point_segment(pos, seg["p0"], seg["p1"])
            if d <= best_d:
                best_d = d
                best = (i, seg)
        if best is None:
            return None
        i, seg = best
        return {
            "name": seg["name"] or self.name,
            "value": seg["value"],
            "series": self.name,
            "dataIndex": i,
        }


registerSeries("pie", PieSeriesRenderer)
registerSeries("radar", RadarSeriesRenderer)
registerSeries("gauge", GaugeSeriesRenderer)
registerSeries("funnel", FunnelSeriesRenderer)
registerSeries("sunburst", SunburstSeriesRenderer)
registerSeries("treemap", TreemapSeriesRenderer)
registerSeries("tree", TreeSeriesRenderer)
registerSeries("sankey", SankeySeriesRenderer)
registerSeries("graph", GraphSeriesRenderer)
registerSeries("lines", LinesSeriesRenderer)
