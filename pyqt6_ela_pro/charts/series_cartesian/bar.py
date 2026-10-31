"""柱状图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._utils import to_float as _to_float
from .._utils import parse_color
from ..axes import GridCoord, formatValue
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
    """柱状图。

    ``stack``：同名堆叠（正值向上、负值向下累加）；``barWidth``：像素（>1）或
    占槽位比例（0~1]）；``itemStyle.borderRadius``：圆角 px（列表取最大）。
    yAxis 为 ``category`` 时自动切换为水平条形。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._bars = []  # [dict]，最终几何（anim_t=1）
        self._horizontal = False
        self._plot = QRectF()

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._bars = []
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
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

        # 槽位：grid 内全部 bar 系列按 stack 名 / 自身序号分槽
        slot_keys = []
        series_opts = self.chart._option_ref().get("series") or []
        for idx, s in enumerate(series_opts):
            if not isinstance(s, dict) or str(s.get("type") or "") != "bar":
                continue
            if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
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
        group_w = band * 0.8
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

        # 堆叠基线：同 stack 且排在我之前的可见 bar 系列按正负分桶累加
        pos_bases, neg_bases = self._stack_bases()
        prev = self.prev_data if isinstance(self.prev_data, list) else None
        radius = self.itemStyle().get("borderRadius", 0)
        if isinstance(radius, (list, tuple)):
            radius = max((_to_float(r, 0.0) for r in radius), default=0.0)
        radius = _to_float(radius, 0.0)

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

    def _stack_bases(self):
        """同 stack 前序可见 bar 系列的逐点基线 ``(pos, neg)`` 双桶。"""
        pos, neg = {}, {}
        stack = self.opt.get("stack")
        if not stack:
            return pos, neg
        for r in self.chart.seriesRenderers:
            if r is self:
                break
            if not isinstance(r, BarSeriesRenderer) or not r.visible:
                continue
            if str(r.opt.get("stack") or "") != str(stack):
                continue
            for i, item in enumerate(r.data()):
                x, y = parseDataPoint(item, i)
                if y is None:
                    continue
                key = self._stack_key(x, i)
                bucket = pos if y >= 0 else neg
                bucket[key] = bucket.get(key, 0.0) + y
        return pos, neg

    @staticmethod
    def _cat_label(cat_axis, x, i):
        if cat_axis.type == "category" and cat_axis.categories:
            idx = cat_axis.categoryIndex(x)
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
            idx = cat_axis.categoryIndex(x)
            if 0 <= idx < n_cats:
                out.append(cats[idx])
            elif 0 <= idx < n_all:
                out.append(all_cats[idx])
            else:
                out.append(formatValue(x))
        return out

    # -- 绘制 -------------------------------------------------------------
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
        if not isinstance(coord, GridCoord):
            return
        p.save()
        p.setClipRect(coord.plot)
        emphasized = self.chart.emphasizedIndices(self)
        selected = self.chart.selectedIndices(self)
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
            uni_has_border = uni["borderColor"] is not None and uni["borderWidth"] > 0
            uni_pen = (
                QPen(uni["borderColor"], uni["borderWidth"]) if uni_has_border else None
            )
        else:
            uni_color = None
            uni_has_border = False
            uni_pen = None
        for bar in self._bars:
            index = bar["index"]
            r = self._animated_rect(bar, anim_t, coord)
            if r.width() <= 0 or r.height() <= 0:
                continue
            if uni is not None:
                # 颜色逐柱拷贝（下面会改 alpha），其余外观整段复用
                color = parse_color(uni_color)
                alpha = uni["opacity"]
                border_color, border_w = uni["borderColor"], uni["borderWidth"]
                raw_r = uni["borderRadius"]
                radius = (
                    0.0
                    if raw_r is None
                    else max(0.0, min(raw_r, r.width() / 2, r.height() / 2))
                )
            else:
                color = parse_color(self.itemColor(index))
                alpha = self.itemOpacity(index)
                border_color, border_w = self.itemBorder(index)
                radius = self._bar_radius(index, r)
            if index in selected:
                style = self.selectItemStyle(index)
                select_color = self.selectColor(index)
                if select_color is not None:
                    color = select_color
                if style.get("borderColor"):
                    border_color = style["borderColor"]
                border_w = max(border_w, _to_float(style.get("borderWidth"), 1.4))
            if emphasized:
                if index not in emphasized and self.blursOtherItems():
                    # 未命中项：blur.itemStyle.opacity 优先，缺省淡化（扩展语义）
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.35
                else:
                    emphasis = self.emphasisColor(index)
                    color = emphasis if emphasis is not None else color.lighter(112)
                    emp_opacity = self.emphasisOpacity(index)
                    if emp_opacity is not None:
                        alpha = emp_opacity
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            p.setBrush(color)
            if uni is not None:
                # pen 已在循环外建好，逐柱新建 QPen 是纯浪费
                p.setPen(uni_pen if uni_has_border else Qt.PenStyle.NoPen)
            elif border_color is not None and border_w > 0:
                p.setPen(QPen(border_color, border_w))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            if radius > 0.5:
                p.drawRoundedRect(r, radius, radius)
            else:
                p.drawRect(r)
            if show_label:
                label_hit = self._paint_bar_label(p, r, bar, fm)
                if label_hit is not None:
                    self._label_rects.append((index, label_hit[0], label_hit[1]))
        p.restore()

    def _bar_radius(self, index: int, rect: QRectF) -> float:
        """柱圆角：数据项 → 系列 ``itemStyle.borderRadius``。"""
        raw = self._itemStyleFor(index).get("borderRadius")
        if raw is None:
            raw = self.itemStyle().get("borderRadius")
        if isinstance(raw, (list, tuple)):
            raw = max((_to_float(v, 0.0) for v in raw), default=0.0)
        radius = _to_float(raw, 0.0)
        return max(0.0, min(radius, rect.width() / 2, rect.height() / 2))

    def _paint_bar_label(self, p: QPainter, rect: QRectF, bar: dict, fm):
        """柱数据标签（默认柱顶 / 横条右端）；返回 ``(labelRect, text)`` 供双击编辑命中。"""
        text = self.labelText(bar["index"], bar["y"], bar["label"])
        if not text:
            return None
        p.setPen(self.labelColorFor(bar["index"]))
        label_opt = self.labelOption()
        position = str(label_opt.get("position") or "")
        if not position:
            position = "right" if self._horizontal else "top"
        rotate = label_rotate(label_opt)
        align = label_align(label_opt)
        if position == "inside":
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
            hit = paint_label_in(p, box, text, rotate, h_align | v_align)
            return hit.adjusted(-2, -2, 2, 2), text
        tw = fm.horizontalAdvance(text)
        if self._horizontal:
            anchor = QPointF(rect.right() + 4, rect.center().y() + fm.height() / 4)
            p.setPen(self.labelColorFor(bar["index"]))
            hit = paint_label_at(p, anchor, text, fm, rotate)
            return hit.adjusted(-2, -2, 2, 2), text
        anchor = QPointF(rect.center().x() - tw / 2, rect.top() - 3)
        offset = label_anchor_offset(align, tw)
        if offset:
            anchor = QPointF(anchor.x() + offset, anchor.y())
        p.setPen(self.labelColorFor(bar["index"]))
        hit = paint_label_at(p, anchor, text, fm, rotate)
        return hit.adjusted(-2, -2, 2, 2), text

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        """柱命中检测：命中框（外扩 2px）内第一根柱。

        线性扫描即正确实现：柱数与绘图区宽度同量级，且语义是「第一根」而非最近者；
        二分索引会让重叠柱与跨轴判定出现不一致。动画期用 ``_animated_rect`` 现算几何。
        """
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        anim_t = self._anim_t
        for bar in self._bars:
            if anim_t >= 1.0:
                rect = bar["rect"]
            else:
                rect = self._animated_rect(bar, anim_t, coord)
            if rect.adjusted(-2, -2, 2, 2).contains(pos):
                return {
                    "name": bar["label"],
                    "value": bar["y"],
                    "series": self.name,
                    "dataIndex": bar["index"],
                }
        return None

    def valueAtIndex(self, index: int):
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
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
