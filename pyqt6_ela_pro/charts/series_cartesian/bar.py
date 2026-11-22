"""柱状图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._style import BAR_GROUP_RATIO, BAR_RADIUS
from .._utils import to_float as _to_float
from .._utils import parse_color, warn_once
from ..axes import GridCoord, PolarCoord, formatValue
from ..core import SeriesRenderer, parseDataPoint
from ._shared import (
    _finite,
    _fix_value_axis,
    _lerp,
    _numeric_xy,
    label_align,
    label_anchor_offset,
    label_rotate,
    paint_label_at,
    paint_label_in,
)


class BarSeriesRenderer(SeriesRenderer):
    """柱状图：``stack`` 同名堆叠（正值向上、负值向下），yAxis 为 ``category`` 时自动水平。

    ``barWidth`` 为像素（>1）或占槽比例（0~1]；``itemStyle.borderRadius`` 圆角 px（列表取最大）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._bars = []  # [dict]，最终几何（anim_t=1）
        self._horizontal = False
        self._polar = False
        self._plot = QRectF()

    def layout(self, rect: QRectF) -> None:
        self._bars = []
        self._polar = False
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, PolarCoord):
            self._layout_polar(coord)
            return
        if not isinstance(coord, GridCoord):
            warn_once(
                "bar-coord",
                f"bar 只支持 grid 坐标系（当前 {getattr(coord, 'kind', '?')}），已跳过",
            )
            return
        self._horizontal = coord.y_axis.type == "category"
        cat_axis = coord.y_axis if self._horizontal else coord.x_axis
        val_axis = coord.x_axis if self._horizontal else coord.y_axis
        _fix_value_axis(
            val_axis,
            self.chart,
            self.opt,
            "x" if self._horizontal else "y",
        )
        self._plot = coord.plot

        # 槽位：同一 grid / 同一对轴上的 bar 系列按 stack 名 / 自身序号分槽
        slot_keys = []
        series_opts = self.chart._option_ref().get("series") or []
        my_scope = self._axis_scope(self.opt)
        for idx, s in enumerate(series_opts):
            if not isinstance(s, dict) or str(s.get("type") or "") not in (
                "bar",
                "pictorialBar",
            ):
                continue
            if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
                continue
            if self._axis_scope(s) != my_scope:
                continue
            key = ("stack", str(s.get("stack"))) if s.get("stack") else ("own", idx)
            if key not in slot_keys:
                slot_keys.append(key)
        my_index = getattr(self, "_series_index", None)
        if not isinstance(my_index, int) or not (0 <= my_index < len(series_opts)):
            my_index = 0
            for idx, s in enumerate(series_opts):
                if isinstance(s, dict) and s == self.opt:
                    my_index = idx
                    break
        my_key = (
            ("stack", str(self.opt.get("stack")))
            if self.opt.get("stack")
            else ("own", my_index)
        )
        slot_idx = slot_keys.index(my_key) if my_key in slot_keys else 0
        n_slots = max(1, len(slot_keys))

        if self._horizontal:
            c0, c1 = coord.plot.top(), coord.plot.bottom()
        else:
            c0, c1 = coord.plot.left(), coord.plot.right()
        band = cat_axis.bandWidth(c0, c1)
        if band <= 0:
            band = abs(c1 - c0) / max(1, len(self.data()))
        group_w = band * BAR_GROUP_RATIO
        # barCategoryGap：组间距（百分比 / 0~1 比例 / 像素）
        cat_gap_raw = self.opt.get("barCategoryGap")
        if cat_gap_raw is not None:
            gap = self._resolve_gap(cat_gap_raw, band)
            group_w = max(2.0, band - gap)
        slot_w = group_w / n_slots
        bar_w = self._resolve_bar_width(slot_w)
        # barGap：组内柱间距（百分比 / 0~1 比例 / 像素；默认 0）
        bar_gap_raw = self.opt.get("barGap")
        if bar_gap_raw is not None and n_slots > 1:
            inner_gap = self._resolve_gap(bar_gap_raw, slot_w)
            bar_w = max(2.0, bar_w - inner_gap * (n_slots - 1) / n_slots)

        # 堆叠基线：同 stack 且排在本系列前面的可见 bar 系列按 stackStrategy 累加
        pos_bases, neg_bases, all_bases, stack_strategy = self._stack_bases()
        prev = self.prev_data if isinstance(self.prev_data, list) else None
        radius = self.itemStyle().get("borderRadius", BAR_RADIUS)
        if isinstance(radius, (list, tuple)):
            radius = max((_to_float(r, 0.0) for r in radius), default=0.0)
        radius = _to_float(radius, BAR_RADIUS)

        # numpy 快路径：数值 / [x, y] 序列向量化取值（逐项 parseDataPoint 是布局热点）
        data = self.data()
        np_x, np_y = _numeric_xy(data)
        if np_x is not None:
            xs_all = np_x.tolist()
            ys_all = np_y.tolist()
            labels = self._cat_labels_bulk(cat_axis, xs_all)
        else:
            xs_all = ys_all = labels = None
        # 预取映射端点：逐柱重复调 coord.plot.left() 等是 8 万次属性访问
        if self._horizontal:
            a0, a1 = coord.plot.left(), coord.plot.right()
        else:
            a0, a1 = coord.plot.bottom(), coord.plot.top()
        half_gw = group_w / 2
        half_bw = bar_w / 2
        n_prev = len(prev) if prev is not None else 0
        for i, (x, y) in enumerate(
            zip(xs_all, ys_all)
            if ys_all is not None
            else (
                (px, py)
                for j, item in enumerate(data)
                for px, py in (parseDataPoint(item, j),)
            )
        ):
            if not _finite(y):
                continue
            key = self._stack_key(x, i)
            if stack_strategy == "all":
                v0 = all_bases.get(key, 0.0)
            elif stack_strategy == "positive":
                v0 = pos_bases.get(key, 0.0) if y >= 0 else 0.0
            elif stack_strategy == "negative":
                v0 = neg_bases.get(key, 0.0) if y < 0 else 0.0
            else:
                v0 = (pos_bases if y >= 0 else neg_bases).get(key, 0.0)
            v1 = v0 + y
            if val_axis.type == "log":
                # log 轴没有 0 基线：底边就是 vmin；负值 / 0 无法映射，跳过。
                v0 = max(v0, float(val_axis.vmin))
                if v1 <= 0.0:
                    continue
            center = cat_axis.map(x, c0, c1)
            slot_center = center - half_gw + slot_w * (slot_idx + 0.5)
            pa = val_axis.map(v0, a0, a1)
            pb = val_axis.map(v1, a0, a1)
            if self._horizontal:
                r = QRectF(min(pa, pb), slot_center - half_bw, abs(pb - pa), bar_w)
            else:
                r = QRectF(slot_center - half_bw, min(pa, pb), bar_w, abs(pb - pa))
            prev_y = None
            if prev is not None and i < n_prev:
                _, prev_y = parseDataPoint(prev[i], i)
            label = labels[i] if labels is not None else self._cat_label(cat_axis, x, i)
            self._bars.append(
                {
                    "index": i,
                    "rect": r,
                    "v0": v0,
                    "y": y,
                    "x": x,
                    "prev_y": prev_y,
                    "center": slot_center,
                    "w": bar_w,
                    "label": label,
                    "radius": radius,
                }
            )

    def _layout_polar(self, coord) -> None:
        """极坐标柱：类目角轴 + 数值半径轴，按扇环绘制。"""
        self._polar = True
        self._horizontal = False
        angle = coord.angle_axis
        radius = coord.radius_axis
        data = self.data()
        n = max(1, len(angle.categories), len(data))
        width = _to_float(self.opt.get("barWidth"), 0.6)
        if not 0.0 < width <= 1.0:
            width = 0.6
        rmin, rmax = float(radius.vmin), float(radius.vmax)
        if rmax <= rmin:
            rmax = rmin + 1.0
        for i, item in enumerate(data):
            x, y = parseDataPoint(item, i)
            if y is None or not _finite(y):
                continue
            idx = angle.categoryIndex(x) if angle.type == "category" else i
            idx = max(0, min(n - 1, int(idx)))
            center = (idx + 0.5) / n
            half = width / (2.0 * n)
            r0 = 0.0
            r1 = max(0.0, min(1.0, (y - rmin) / (rmax - rmin)))
            self._bars.append(
                {
                    "index": i,
                    "label": self._cat_label(angle, x, i),
                    "x": x,
                    "y": y,
                    "cat_index": idx,
                    "a0": center - half,
                    "a1": center + half,
                    "r0": r0,
                    "r1": r1,
                    "r0_val": rmin + r0 * (rmax - rmin),
                    "r1_val": rmin + r1 * (rmax - rmin),
                }
            )

    def _resolve_bar_width(self, slot_w):
        bw = _to_float(self.opt.get("barWidth"), None)
        if bw is None:
            return max(2.0, slot_w * 0.75)
        if 0 < bw <= 1:
            return max(2.0, slot_w * bw)
        return max(2.0, min(bw, slot_w))

    @staticmethod
    def _resolve_gap(raw, band: float) -> float:
        """barGap / barCategoryGap → 像素（支持 "30%" / 0.3 比例 / 像素值）。"""
        if isinstance(raw, str) and raw.strip().endswith("%"):
            try:
                return max(0.0, band * float(raw.strip()[:-1]) / 100.0)
            except ValueError:
                return 0.0
        value = _to_float(raw, None)
        if value is None:
            return 0.0
        if 0 < value <= 1:
            return max(0.0, band * value)
        return max(0.0, value)

    @staticmethod
    def _stack_key(x, index):
        """堆叠对齐键：优先 x（类别名 / 数值），不可哈希时退回下标。"""
        if isinstance(x, (str, int, float)) and not isinstance(x, bool):
            return x
        return index

    def _axis_scope(self, option):
        """系列所属的 (grid, xAxis, yAxis) 作用域；跨作用域不能共用槽位 / 堆叠。"""
        coord = self.chart.coordFor(option)
        if coord is None:
            return None
        return (
            getattr(coord, "grid_index", 0),
            getattr(coord, "x_axis_index", 0),
            getattr(coord, "y_axis_index", 0),
        )

    def _stack_bases(self):
        """同 stack 前序可见 bar 系列的逐点基线（按 ``stackStrategy`` 分桶）。"""
        pos, neg, all_bases = {}, {}, {}
        stack = self.opt.get("stack")
        strategy = str(self.opt.get("stackStrategy") or "samesign").strip().lower()
        if strategy not in ("samesign", "all", "positive", "negative"):
            strategy = "samesign"
        if not stack:
            return pos, neg, all_bases, strategy
        my_scope = self._axis_scope(self.opt)
        for r in self.chart.seriesRenderers:
            if r is self:
                break
            if not isinstance(r, BarSeriesRenderer) or not r.visible:
                continue
            if str(r.opt.get("stack") or "") != str(stack):
                continue
            if self._axis_scope(r.opt) != my_scope:
                continue
            for i, item in enumerate(r.data()):
                x, y = parseDataPoint(item, i)
                if y is None:
                    continue
                key = self._stack_key(x, i)
                all_bases[key] = all_bases.get(key, 0.0) + y
                bucket = pos if y >= 0 else neg
                bucket[key] = bucket.get(key, 0.0) + y
        return pos, neg, all_bases, strategy

    @staticmethod
    def _cat_label(cat_axis, x, i):
        if cat_axis.type == "category" and cat_axis.categories:
            idx = cat_axis.localIndex(x)
            if 0 <= idx < len(cat_axis.categories):
                return cat_axis.categories[idx]
            all_cats = getattr(cat_axis, "_all_categories", None) or []
            if 0 <= idx < len(all_cats):
                return all_cats[idx]
        return formatValue(x)

    def _cat_labels_bulk(self, cat_axis, xs):
        """批量取类别标签（``xs`` 为 x 序列）：等价于逐项 ``_cat_label``，但把
        「是否 category 轴」的判断提到循环外。
        """
        is_cat = cat_axis.type == "category" and bool(cat_axis.categories)
        if not is_cat:
            return [formatValue(x) for x in xs]
        cats = cat_axis.categories
        n_cats = len(cats)
        all_cats = getattr(cat_axis, "_all_categories", None) or []
        n_all = len(all_cats)
        out = []
        for x in xs:
            idx = cat_axis.localIndex(x)
            if 0 <= idx < n_cats:
                out.append(cats[idx])
            elif 0 <= idx < n_all:
                out.append(all_cats[idx])
            else:
                out.append(formatValue(x))
        return out

    def _animated_value(self, bar, anim_t):
        y, prev_y = bar["y"], bar["prev_y"]
        if prev_y is not None and anim_t < 1.0:
            return _lerp(prev_y, y, anim_t)
        if anim_t < 1.0 and prev_y is None:
            return y * anim_t
        return y

    def _animated_rect(self, bar, anim_t, coord):
        """柱在给定动画进度下的矩形（``paint`` 与 ``hitTest`` 共用）。

        命中必须用画出来的那份几何：动画期柱高还在生长，用终态矩形会点错柱。
        """
        y_t = self._animated_value(bar, anim_t)
        v1 = bar["v0"] + y_t
        w = bar["w"]
        val_axis = coord.x_axis if self._horizontal else coord.y_axis
        if self._horizontal:
            pa = val_axis.map(bar["v0"], coord.plot.left(), coord.plot.right())
            pb = val_axis.map(v1, coord.plot.left(), coord.plot.right())
            return QRectF(min(pa, pb), bar["center"] - w / 2, abs(pb - pa), w)
        pa = val_axis.map(bar["v0"], coord.plot.bottom(), coord.plot.top())
        pb = val_axis.map(v1, coord.plot.bottom(), coord.plot.top())
        return QRectF(bar["center"] - w / 2, min(pa, pb), w, abs(pb - pa))

    def paint(self, p: QPainter, anim_t: float) -> None:
        self._label_rects = []
        if not self._bars:
            return
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, PolarCoord):
            self._paint_polar(p, coord, anim_t)
            return
        if not isinstance(coord, GridCoord):
            return
        p.save()
        p.setClipRect(coord.plot)
        emphasized = self.chart.emphasizedIndices(self)
        hovered = next(iter(emphasized), None) if emphasized else None
        show_label = self.labelShown()
        if show_label:
            font = self.labelFont()
            p.setFont(font)
            p.setPen(self.labelColor())
            fm = QFontMetricsF(font)
        # 外观在循环外解析一次（uniformItemStyleResolved 是 O(1) 快路径）；
        # None = 存在 per-item itemStyle，退回逐项查找。
        uni = self.uniformItemStyleResolved()
        if uni is not None:
            uni_color = uni["color"] or self.chart.colorForSeries(self)
        else:
            uni_color = None
        bars = self.progressiveSelect(self._bars)
        for bar in bars:
            index = bar["index"]
            r = self._animated_rect(bar, anim_t, coord)
            if r.width() <= 0 or r.height() <= 0:
                # 0 值柱不画柱体，但标签仍应画在基线上（ECharts 语义）。
                if show_label:
                    label_hit = self._paint_bar_label(
                        p, r, bar, fm, self.dataColor(index)
                    )
                    if label_hit is not None:
                        self._label_rects.append((index, label_hit[0], label_hit[1]))
                continue
            if uni is not None:
                # 颜色逐柱拷贝（下面会改 alpha），其余外观整段复用
                color = parse_color(uni_color)
                alpha = uni["opacity"]
                border_color, border_w = uni["borderColor"], uni["borderWidth"]
                raw_r = uni["borderRadius"]
                radius = (
                    BAR_RADIUS
                    if raw_r is None
                    else max(0.0, min(raw_r, r.width() / 2, r.height() / 2))
                )
            else:
                color = parse_color(self.dataColor(index))
                alpha = self.itemOpacity(index)
                border_color, border_w = self.itemBorder(index)
                radius = self._bar_radius(index, r)
            color, alpha, border_color, border_w = self.stateStyle(
                index, hovered, color, alpha, border_color, border_w
            )
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            p.setBrush(color)
            if border_color is not None and border_w > 0:
                p.setPen(QPen(border_color, border_w))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            if radius > 0.5:
                p.drawRoundedRect(r, radius, radius)
            else:
                p.drawRect(r)
            if show_label:
                label_hit = self._paint_bar_label(p, r, bar, fm, color)
                if label_hit is not None:
                    self._label_rects.append((index, label_hit[0], label_hit[1]))
        p.restore()

    def _paint_polar(self, p: QPainter, coord, anim_t: float) -> None:
        p.save()
        emphasized = self.chart.emphasizedIndices(self)
        hovered = next(iter(emphasized), None) if emphasized else None
        show_label = self.labelShown()
        font = self.labelFont() if show_label else None
        fm = QFontMetricsF(font) if font is not None else None
        if font is not None:
            p.setFont(font)
        bars = self.progressiveSelect(self._bars)
        for bar in bars:
            r1 = bar["r0"] + (bar["r1"] - bar["r0"]) * max(0.0, min(1.0, anim_t))
            path = coord.sector_path(bar["a0"], bar["a1"], bar["r0"], r1)
            if path.isEmpty():
                continue
            color = self.dataColor(bar["index"])
            alpha = self.itemOpacity(bar["index"])
            border_color, border_w = self.itemBorder(bar["index"])
            color, alpha, border_color, border_w = self.stateStyle(
                bar["index"], hovered, color, alpha, border_color, border_w
            )
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            p.setBrush(color)
            if border_color is not None and border_w > 0:
                p.setPen(QPen(border_color, border_w))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(path)
            if show_label and fm is not None:
                frac = (bar["a0"] + bar["a1"]) / 2.0
                rr = coord.radius * (bar["r0"] + r1) / 2.0
                theta = -math.pi / 2 + frac * 2.0 * math.pi
                pt = QPointF(
                    coord.center.x() + rr * math.cos(theta),
                    coord.center.y() + rr * math.sin(theta),
                )
                text = self.labelText(bar["index"], bar["y"], bar["label"])
                if text:
                    rect = QRectF(
                        pt.x() - 48.0,
                        pt.y() - fm.height() / 2.0,
                        96.0,
                        fm.height(),
                    )
                    hit = self.paintLabelIn(
                        p,
                        rect,
                        text,
                        index=bar["index"],
                        align=Qt.AlignmentFlag.AlignCenter,
                        color=self.contrastLabelColor(color, bar["index"]),
                    )
                    if hit.isNull():
                        continue
                    self._label_rects.append(
                        (bar["index"], hit.adjusted(-2, -2, 2, 2), text)
                    )
        p.restore()

    def _bar_radius(self, index: int, rect: QRectF) -> float:
        """柱圆角：数据项 → 系列 ``itemStyle.borderRadius``。"""
        raw = self._itemStyleFor(index).get("borderRadius")
        if raw is None:
            raw = self.itemStyle().get("borderRadius")
        if isinstance(raw, (list, tuple)):
            raw = max((_to_float(v, 0.0) for v in raw), default=0.0)
        radius = _to_float(raw, BAR_RADIUS)
        return max(0.0, min(radius, rect.width() / 2, rect.height() / 2))

    def _paint_bar_label(self, p: QPainter, rect: QRectF, bar: dict, fm, fill):
        """柱数据标签（默认柱顶 / 横条右端）；返回 ``(labelRect, text)`` 供双击编辑命中。"""
        text = self.labelText(bar["index"], bar["y"], bar["label"])
        if not text:
            return None
        label_opt = self.labelOption()
        position = str(label_opt.get("position") or "")
        if not position:
            position = "right" if self._horizontal else "top"
        rotate = label_rotate(label_opt)
        align = label_align(label_opt)
        inside_positions = {
            "inside",
            "insideTop",
            "insideBottom",
            "insideLeft",
            "insideRight",
        }
        inside = position in inside_positions
        p.setPen(
            self.contrastLabelColor(fill, bar["index"])
            if inside
            else self.labelColorFor(bar["index"])
        )
        if inside:
            box = rect.adjusted(2, 2, -2, -2)
            h_align = {
                "left": Qt.AlignmentFlag.AlignLeft,
                "right": Qt.AlignmentFlag.AlignRight,
            }.get(align, Qt.AlignmentFlag.AlignHCenter)
            v_align = (
                Qt.AlignmentFlag.AlignVCenter
                if self._horizontal
                else Qt.AlignmentFlag.AlignTop
            )
            if position == "insideLeft":
                h_align = Qt.AlignmentFlag.AlignLeft
            elif position == "insideRight":
                h_align = Qt.AlignmentFlag.AlignRight
            elif position == "insideTop":
                v_align = Qt.AlignmentFlag.AlignTop
            elif position == "insideBottom":
                v_align = Qt.AlignmentFlag.AlignBottom
            hit = paint_label_in(
                p,
                box,
                text,
                rotate,
                h_align | v_align,
                series=self,
                index=bar["index"],
            )
            if hit.isNull():
                return None
            return hit.adjusted(-2, -2, 2, 2), text
        tw = fm.horizontalAdvance(text)
        if self._horizontal:
            if position == "left":
                anchor = QPointF(
                    rect.left() - 4 - tw, rect.center().y() + fm.ascent() / 3
                )
            elif position == "top":
                anchor = QPointF(rect.center().x() - tw / 2, rect.top() - 3)
            elif position == "bottom":
                anchor = QPointF(
                    rect.center().x() - tw / 2,
                    rect.bottom() + fm.ascent() + 3,
                )
            else:
                anchor = QPointF(rect.right() + 4, rect.center().y() + fm.height() / 4)
        else:
            if position == "left":
                anchor = QPointF(
                    rect.left() - 4 - tw, rect.center().y() + fm.ascent() / 3
                )
            elif position == "right":
                anchor = QPointF(rect.right() + 4, rect.center().y() + fm.ascent() / 3)
            elif position == "bottom":
                anchor = QPointF(
                    rect.center().x() - tw / 2,
                    rect.bottom() + fm.ascent() + 3,
                )
            else:
                anchor = QPointF(rect.center().x() - tw / 2, rect.top() - 3)
        if position in ("top", "bottom"):
            offset = label_anchor_offset(align, tw)
            if offset:
                anchor = QPointF(anchor.x() + offset, anchor.y())
        hit = paint_label_at(
            p,
            anchor,
            text,
            fm,
            rotate,
            series=self,
            index=bar["index"],
        )
        if hit.isNull():
            return None
        return hit.adjusted(-2, -2, 2, 2), text

    def hitTest(self, pos: QPointF):
        """柱命中检测：命中框（外扩 2px）内第一根柱。
        线性扫描是刻意的：柱数与绘图区宽度同量级，语义是「第一根」而非最近者；
        二分会让重叠柱与跨轴判定不一致。
        """
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, PolarCoord):
            if coord.angle_axis.type != "category":
                return None
            inv = coord.invertPoint(pos)
            if inv is None:
                return None
            angle_index, radius_value = inv
            for bar in reversed(self._bars):
                if bar["cat_index"] != angle_index:
                    continue
                lo = min(bar["r0_val"], bar["r1_val"])
                hi = max(bar["r0_val"], bar["r1_val"])
                if lo - 1e-9 <= radius_value <= hi + 1e-9:
                    return {
                        "name": bar["label"],
                        "value": bar["y"],
                        "color": self.dataColor(bar["index"]),
                        "series": self.name,
                        "dataIndex": bar["index"],
                    }
            return None
        if not isinstance(coord, GridCoord):
            return None
        anim_t = self._anim_t
        for bar in self._bars:
            if anim_t >= 1.0:
                rect = bar["rect"]
            else:
                rect = self._animated_rect(bar, anim_t, coord)
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            if rect.adjusted(-2, -2, 2, 2).contains(pos):
                return {
                    "name": bar["label"],
                    "value": bar["y"],
                    "color": self.dataColor(bar["index"]),
                    "series": self.name,
                    "dataIndex": bar["index"],
                }
        return None

    def morphSnapshot(self):
        if self._polar:
            return None
        items = []
        for bar in self._bars:
            rect = bar.get("rect")
            if not isinstance(rect, QRectF) or rect.isNull():
                continue
            items.append(
                {
                    "rect": QRectF(rect),
                    "color": self.dataColor(bar["index"]),
                    "radius": float(bar.get("radius") or 0.0),
                    "key": self.morphKey(bar["index"]),
                }
            )
        return {"kind": "bar", "items": items}

    def valueAtIndex(self, index: int):
        idx = index
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, PolarCoord):
            for bar in self._bars:
                if bar["index"] == idx:
                    frac = (bar["a0"] + bar["a1"]) / 2.0
                    rr = coord.radius * (bar["r0"] + bar["r1"]) / 2.0
                    theta = -math.pi / 2 + frac * 2.0 * math.pi
                    pos = QPointF(
                        coord.center.x() + rr * math.cos(theta),
                        coord.center.y() + rr * math.sin(theta),
                    )
                    return {
                        "name": bar["label"],
                        "value": bar["y"],
                        "color": self.dataColor(bar["index"]),
                        "series": self.name,
                        "dataIndex": bar["index"],
                        "pos": pos,
                    }
            return None
        for bar in self._bars:
            if bar["index"] == idx:
                r = bar["rect"]
                if self._horizontal:
                    pos = QPointF(r.right(), r.center().y())
                else:
                    pos = QPointF(r.center().x(), r.top())
                return {
                    "name": bar["label"],
                    "value": bar["y"],
                    "color": self.dataColor(bar["index"]),
                    "series": self.name,
                    "dataIndex": bar["index"],
                    "pos": pos,
                }
        return None

    def nearestIndexAt(self, x):
        """按 x 值找最近的柱（value x 轴的 axis tooltip；category 走调用方）。"""
        try:
            xv = float(x)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(xv):
            return None
        best = None
        for bar in self._bars:
            raw = bar.get("x")
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                continue
            distance = abs(float(raw) - xv)
            if best is None or distance < best[0]:
                best = (distance, bar["index"])
        return best[1] if best is not None else None
