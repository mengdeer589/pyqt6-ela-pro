"""散点系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QFontMetricsF,
    QPainter,
    QPen,
    QPolygonF,
)

from .._tokens import T
from .. import _downsample as _ds
from .._symbol import symbolPixmap
from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_color
from ..axes import GridCoord, formatValue
from ..core import SeriesRenderer, parseDataPoint
from ._shared import (
    _draw_symbol,
    _label_placement,
    _lerp,
    label_align,
    label_anchor_offset,
    label_rotate,
    label_rotated_bounds,
    paint_label_at,
)


def _draw_emphasis_markers(
    renderer,
    p: QPainter,
    emphasized,
    *,
    uni_color,
    alpha: float,
    border_color,
    border_w,
    kind: str,
    scale: float,
    symbol_rotate: float,
) -> None:
    """快路径下把命中项按 emphasis 样式叠画在最上层（基础点保持同一张 sprite）。"""
    for dot in renderer._dots:
        index = dot["index"]
        if index not in emphasized:
            continue
        r = dot["r"] * scale
        if r <= 0:
            continue
        color = parse_color(uni_color)
        emphasis = renderer.emphasisColor(index)
        if emphasis is not None:
            color = emphasis
        pen_color = border_color
        pen_width = border_w
        if pen_color is None:
            pen_color = color.lighter(115)
            pen_width = max(pen_width, 1.4)
        p.setBrush(with_alpha(color, int(190 * alpha)))
        p.setPen(QPen(pen_color or with_alpha(color, int(230 * alpha)), pen_width or 1))
        _draw_symbol(p, kind, dot["pt"], r * 1.25 * 2, symbol_rotate)


class ScatterSeriesRenderer(SeriesRenderer):
    """散点图。

    ``mode``：``"markers"``（默认）/ ``"lines"`` / ``"lines+markers"``。
    ``symbolSize``：数值 → 固定直径 px；缺省且数据带第三维时按第三维在本系列内
    映射到 6~24px，否则 8px。数据项：数值 / [x, y] / [x, y, size] / {"value": [...]}。
    支持 grid / polar / singleAxis 坐标系。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._dots = []  # [dict(pt=QPointF, r=float, value, index, x)]

    # -- 布局 -------------------------------------------------------------
    def _third_dim(self, item):
        v = item.get("value") if isinstance(item, dict) else item
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            return _to_float(v[2], None)
        return None

    def _visual_value(self, item):
        """visualMap 取值的维度：``dimension`` 优先，缺省最后一维（气泡图 ``[x, y, value]``）。"""
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, (list, tuple)) and value:
            vm = self.visualMapComponent()
            dim = (getattr(vm, "opt", None) or {}).get("dimension") if vm else None
            if isinstance(dim, int) and not isinstance(dim, bool):
                index = dim if 0 <= dim < len(value) else len(value) - 1
            else:
                index = len(value) - 1
            return _to_float(value[index], None)
        return _to_float(value, None)

    def visualColor(self, index=None):
        """``visualMap`` 映射出的颜色；未绑定 / 取不到值返回 ``None``。"""
        vm = self.visualMapComponent()
        if vm is None or not isinstance(index, int):
            return None
        data = self.data()
        if not 0 <= index < len(data):
            return None
        value = self._visual_value(data[index])
        if value is None:
            return None
        try:
            color = parse_color(vm.mapColor(value))
        except Exception:
            return None
        return color if color.isValid() else None

    def _has_item_color(self, index) -> bool:
        """数据项自己配了 ``itemStyle.color``（优先级高于 visualMap 映射）。"""
        data = self.data()
        if not isinstance(index, int) or not 0 <= index < len(data):
            return False
        item = data[index]
        if not isinstance(item, dict):
            return False
        style = item.get("itemStyle")
        return isinstance(style, dict) and isinstance(style.get("color"), str)

    def itemColor(self, index=None, default=None):
        if default is None and not self._has_item_color(index):
            visual = self.visualColor(index)
            if visual is not None:
                return visual
        return super().itemColor(index, default)

    def uniformItemStyle(self):
        # 按值上色时「整条系列一个颜色」不成立（也禁用位图快路径）
        if self.visualMapComponent() is not None:
            return None
        return super().uniformItemStyle()

    def layout(self, rect: QRectF) -> None:
        self._dots = []
        coord = self.chart.coordFor(self.opt)
        if coord is None:
            return
        single = getattr(coord, "kind", "") == "singleAxis"
        fixed = _to_float(self.opt.get("symbolSize"), None)
        plot_w = (
            float(self.chart.width())
            if not isinstance(coord, GridCoord)
            else max(1.0, coord.plot.width())
        )
        # 候选下标：窗口裁剪 + 像素密度抽稀（numpy 不可用 / 小数据 → None 走全量）
        candidates = self._candidate_indices(coord, plot_w)
        data = self.data()
        indices = range(len(data)) if candidates is None else candidates.tolist()
        # 第三维只对候选点求值（全量推导在 1M 点上要 300ms+）
        thirds = {i: self._third_dim(data[i]) for i in indices}
        known = [v for v in thirds.values() if v is not None]
        zmin = min(known) if known else 0.0
        zmax = max(known) if known else 1.0
        span = zmax - zmin
        append = self._dots.append

        # 向量化映射（与折线同一快路径）：逐点 mapPoint 约 5µs，5 万点就是 0.25s。
        mapped = None
        if not single and candidates is not None:
            np_ = _ds.np
            try:
                arr = np_.asarray(data, dtype=np_.float64)
                index_array = np_.asarray(indices, dtype=np_.int64)
                if arr.ndim == 1:
                    xs_arr = index_array.astype(np_.float64)
                    ys_arr = arr[index_array]
                elif arr.ndim == 2 and arr.shape[1] >= 2:
                    xs_arr = arr[index_array, 0]
                    ys_arr = arr[index_array, 1]
                else:
                    xs_arr = ys_arr = None
                if xs_arr is not None:
                    mapped = coord.mapArrays(xs_arr, ys_arr)
            except Exception:
                mapped = None
        if mapped is not None:
            np_ = _ds.np
            px_arr, py_arr = mapped
            ok_arr = np_.isfinite(px_arr) & np_.isfinite(py_arr)
            px_list = px_arr.tolist()
            py_list = py_arr.tolist()
            ok_list = ok_arr.tolist()
            y_list = ys_arr.tolist()
            x_list = (
                xs_arr.tolist() if xs_arr is not None else [float(i) for i in indices]
            )
            for slot, i in enumerate(indices):
                if not ok_list[slot]:
                    continue
                y = y_list[slot]
                if fixed is not None:
                    r = max(1.0, fixed / 2)
                elif thirds[i] is not None:
                    f = 0.5 if span == 0 else (thirds[i] - zmin) / span
                    r = _lerp(6.0, 24.0, f) / 2
                else:
                    r = 4.0
                append(
                    {
                        "pt": QPointF(px_list[slot], py_list[slot]),
                        "r": r,
                        "value": y,
                        "index": i,
                        "x": x_list[slot],
                    }
                )
            return

        for i in indices:
            x, y = parseDataPoint(data[i], i)
            if y is None:
                continue
            try:
                pt = coord.mapPoint(y) if single else coord.mapPoint(x, y)
            except Exception:
                continue
            if not (math.isfinite(pt.x()) and math.isfinite(pt.y())):
                continue
            if fixed is not None:
                r = max(1.0, fixed / 2)
            elif thirds[i] is not None:
                f = 0.5 if span == 0 else (thirds[i] - zmin) / span
                r = _lerp(6.0, 24.0, f) / 2
            else:
                r = 4.0
            append({"pt": pt, "r": r, "value": y, "index": i, "x": x})

    # -- 绘制 -------------------------------------------------------------
    #: 散点抽稀的下限（点数低于它不做抽稀：小数据要全画）
    _LOD_MIN_POINTS = 4000
    #: 抽稀后每像素列保留的点数（2 点已看不出稀疏；窗口重建成本与点数成正比）
    _LOD_POINTS_PER_PX = 2.0

    def _candidate_indices(self, coord, plot_w: float):
        """散点绘制候选下标：窗口裁剪 + 像素密度抽稀；返回 ``ndarray`` 或 ``None``（= 全量循环）。"""
        np_ = _ds.np
        data = self.data()
        length = len(data)
        if np_ is None or length <= self._LOD_MIN_POINTS:
            return None
        enabled, threshold, _ppb, _algo = self._sampling_params()
        if not enabled or length <= threshold:
            return None
        try:
            arr = np_.asarray(data, dtype=np_.float64)
        except (TypeError, ValueError, OverflowError):
            return None
        if arr.ndim == 1:
            xs = np_.arange(length, dtype=np_.float64)
        elif arr.ndim == 2 and arr.shape[1] >= 2:
            xs = arr[:, 0]
        else:
            return None

        idx = None
        if isinstance(coord, GridCoord):
            axis = coord.x_axis
            if axis.type == "category":
                count = len(getattr(axis, "categories", ()) or ())
                if count > 0:
                    window_offset = getattr(axis, "windowOffset", None)
                    offset = int(window_offset()) if callable(window_offset) else 0
                    idx = np_.arange(offset, min(length, offset + count))
            elif axis.type == "value":
                idx = np_.flatnonzero((xs >= axis.vmin) & (xs <= axis.vmax))
        if idx is None:
            idx = np_.arange(length)
        target = max(64.0, float(plot_w) * self._LOD_POINTS_PER_PX)
        if idx.size > target:
            step = max(1, int(idx.size / target))
            idx = idx[::step]
        return idx

    def plotMode(self) -> str:
        """散点绘制模式：``markers``（默认）/ ``lines`` / ``lines+markers``。"""
        raw = self.opt.get("mode")
        if isinstance(raw, str) and raw.strip():
            name = raw.strip().lower().replace("-", "+").replace(" ", "+")
            has_line = "line" in name
            has_marker = "marker" in name
            if has_line and has_marker:
                return "lines+markers"
            if has_line:
                return "lines"
        return "markers"

    def showLine(self) -> bool:
        return self.plotMode() != "markers"

    def showMarkers(self) -> bool:
        return self.plotMode() != "lines"

    def paint(self, p: QPainter, anim_t: float) -> None:
        self._label_rects = []
        if not self._dots:
            return
        p.save()
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        draw_line = self.showLine()
        draw_markers = self.showMarkers()
        if draw_line:
            ls = self.opt.get("lineStyle") or {}
            line_color = self.color()
            if isinstance(ls.get("color"), str) and ls["color"]:
                line_color = parse_color(ls["color"])
            pen = QPen(line_color, _to_float(ls.get("width"), 1.5))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            points = [d["pt"] for d in self._dots]
            if len(points) >= 2:
                p.drawPolyline(QPolygonF(points))
        kind = str(self.opt.get("symbol") or "circle")
        symbol_rotate = _to_float(self.opt.get("symbolRotate"), 0.0)
        emphasized = self.chart.emphasizedIndices(self)
        selected = self.chart.selectedIndices(self)
        show_label = self.labelShown()
        if show_label:
            font = self.labelFont()
            p.setFont(font)
            p.setPen(self.labelColor())
            fm = QFontMetricsF(font)
        scale = max(0.0, anim_t)
        # 循环外解析一次统一外观（None = 存在 per-item itemStyle，走逐项查找）
        uni = self.uniformItemStyleResolved()
        uni_color = (uni["color"] or self.chart.colorForSeries(self)) if uni else None
        if not draw_markers and not show_label and not selected:
            p.restore()
            return
        # 统一外观 + 无标签 + 尺寸一致：所有点贴同一张 sprite（逐点矢量绘制在
        # 5 万点上 ~100ms）。hover 命中项不禁用快路径 —— 否则其余点外观会跳变。
        if (
            uni is not None
            and not selected
            and not show_label
            and draw_markers
            and not symbol_rotate
            and not (emphasized and self.blursOtherItems())
        ):
            radii = {round(d["r"] * scale, 1) for d in self._dots}
            if len(radii) == 1:
                r = next(iter(radii))
                if r > 0:
                    alpha = uni["opacity"]
                    border_color, border_w = uni["borderColor"], uni["borderWidth"]
                    sprite = symbolPixmap(
                        kind,
                        r * 2,
                        with_alpha(parse_color(uni_color), int(190 * alpha)),
                        border_color
                        or with_alpha(parse_color(uni_color), int(230 * alpha)),
                        border_w or 1,
                        self.chart.getDevicePixelRatio(),
                    )
                    half = r + 1.0
                    for d in self._dots:
                        pt = d["pt"]
                        p.drawPixmap(QPointF(pt.x() - half, pt.y() - half), sprite)
                    _draw_emphasis_markers(
                        self,
                        p,
                        emphasized,
                        uni_color=uni_color,
                        alpha=alpha,
                        border_color=border_color,
                        border_w=border_w,
                        kind=kind,
                        scale=scale,
                        symbol_rotate=symbol_rotate,
                    )
                    p.restore()
                    return
        if draw_markers:
            for d in self._dots:
                index = d["index"]
                r = d["r"] * scale
                if r <= 0:
                    continue
                if uni is not None:
                    color = parse_color(uni_color)
                    alpha = uni["opacity"]
                    border_color, border_w = uni["borderColor"], uni["borderWidth"]
                else:
                    color = parse_color(self.itemColor(index))
                    alpha = self.itemOpacity(index)
                    border_color, border_w = self.itemBorder(index)
                if index in selected:
                    style = self.selectItemStyle(index)
                    select_color = self.selectColor(index)
                    if select_color is not None:
                        color = select_color
                    if style.get("borderColor"):
                        border_color = style["borderColor"]
                    border_w = max(border_w, _to_float(style.get("borderWidth"), 1.4))
                    r = max(r, d["r"] * scale * 1.15)
                if emphasized:
                    if index in emphasized:
                        r *= 1.25
                        emphasis = self.emphasisColor(index)
                        if emphasis is not None:
                            color = emphasis
                        if border_color is None:
                            border_color = color.lighter(115)
                            border_w = max(border_w, 1.4)
                    elif self.blursOtherItems():
                        blur = self.blurOpacity()
                        alpha *= blur if blur is not None else 0.35
                p.setBrush(with_alpha(color, int(190 * alpha)))
                p.setPen(
                    QPen(
                        border_color or with_alpha(color, int(230 * alpha)),
                        border_w or 1,
                    )
                )
                if alpha <= 0.02:
                    continue
                _draw_symbol(p, kind, d["pt"], r * 2, symbol_rotate)
        if selected and not draw_markers:
            sel_kind = kind if kind != "none" else "circle"
            for index in sorted(selected)[:2000]:
                info = self.valueAtIndex(index)
                if not info or info.get("pos") is None:
                    continue
                style = self.selectItemStyle(index)
                fill = self.selectColor(index) or self.itemColor(index)
                border = style.get("borderColor") or T("color.bg.elevated")
                width = _to_float(style.get("borderWidth"), 1.6)
                p.setPen(QPen(parse_color(border), width))
                p.setBrush(fill)
                _draw_symbol(p, sel_kind, QPointF(info["pos"]), 10.0, symbol_rotate)
        if show_label:
            label_opt = self.labelOption()
            position = str(label_opt.get("position") or "top")
            distance = _to_float(label_opt.get("distance"), 4.0)
            rotate = label_rotate(label_opt)
            align = label_align(label_opt)
            layout = self.opt.get("labelLayout")
            hide_overlap = (
                bool(layout.get("hideOverlap", False))
                if isinstance(layout, dict)
                else False
            )
            drawn = []
            for d in self._dots:
                index = d["index"]
                text = self.labelText(index, d["value"], formatValue(d["x"]))
                marker_r = d["r"] * scale if draw_markers else 0.0
                anchor, rect = _label_placement(
                    d["pt"], text, fm, position, distance, marker_r
                )
                if position in ("top", "bottom", "inside"):
                    offset = label_anchor_offset(align, rect.width())
                    if offset:
                        anchor = QPointF(anchor.x() + offset, anchor.y())
                        rect = rect.translated(offset, 0.0)
                hit = label_rotated_bounds(rect, rotate)
                if hide_overlap and any(hit.intersects(r) for r in drawn):
                    continue
                p.setPen(self.labelColorFor(index))
                paint_label_at(p, anchor, text, fm, rotate)
                rect = hit
                if marker_r > 0:
                    rect = rect.united(
                        QRectF(
                            d["pt"].x() - marker_r - 2,
                            d["pt"].y() - marker_r - 2,
                            marker_r * 2 + 4,
                            marker_r * 2 + 4,
                        )
                    )
                drawn.append(rect)
                self._label_rects.append((index, rect, text))
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        best = None
        best_d = 1e9
        # 入场动画只缩半径、不挪位置：命中半径按同一系数缩，保持「看到的就能点到」。
        scale = max(0.0, self._anim_t)
        for d in self._dots:
            dist = math.hypot(d["pt"].x() - pos.x(), d["pt"].y() - pos.y())
            # 命中上限：不小于「点半径 + 3」，再放开到可配的 ``tooltip.hitRadius``
            limit = max(self.chart.hitRadius(), d["r"] * scale + 3.0)
            if dist <= limit and dist < best_d:
                best_d = dist
                best = d
        if best is None:
            return None
        return {
            "name": self.name,
            "value": best["value"],
            "series": self.name,
            "dataIndex": best["index"],
            "x": best["x"],
        }

    def valueAtIndex(self, index: int):
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        best = None
        for d in self._dots:
            if d["index"] == idx:
                return {
                    "name": self.name,
                    "value": d["value"],
                    "series": self.name,
                    "dataIndex": d["index"],
                    "pos": d["pt"],
                }
            # LOD 抽稀掉的下标：退化为最近一个仍画出来的点
            distance = abs(d["index"] - idx)
            if best is None or distance < best[0]:
                best = (distance, d)
        if best is None:
            return None
        d = best[1]
        return {
            "name": self.name,
            "value": d["value"],
            "series": self.name,
            "dataIndex": d["index"],
            "pos": d["pt"],
        }

    def nearestIndexAt(self, x):
        """按 x 值找最近的散点（axis tooltip / 数值 x 轴）。"""
        coord = self.chart.coordFor(self.opt)
        axis = getattr(coord, "x_axis", None)
        if getattr(axis, "is_time", False):
            x = axis.toNumber(x)
        try:
            xv = float(x)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(xv):
            return None
        best = None
        for d in self._dots:
            raw = d.get("x")
            if getattr(axis, "is_time", False):
                raw = axis.toNumber(raw)
            if not isinstance(raw, (int, float)) or isinstance(raw, bool):
                continue
            distance = abs(float(raw) - xv)
            if best is None or distance < best[0]:
                best = (distance, d["index"])
        return best[1] if best is not None else None
