"""折线 / 面积系列（含采样、断点、符号与标签）。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import bisect
import math
from collections import OrderedDict

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
)

from .._tokens import T
from .. import _downsample as _ds
from .._symbol import symbolPixmap
from .._utils import clamp as _clamp
from .._utils import merged_text_style, parse_color, text_italic, text_weight
from .._utils import to_float as _to_float
from .._utils import with_alpha
from ..axes import GridCoord, chartFont, formatValue
from ..core import SeriesRenderer, parseDataPoint
from .line_sampling import _LineSamplingMixin
from .line_symbols import _LineSymbolMixin

from ._shared import (
    _draw_symbol,
    _fix_value_axis,
    _label_placement,
    _lerp,
    _monotone_path,
    _smooth_path,
    _win_span,
    label_align,
    label_anchor_offset,
    label_rotate,
    label_rotated_bounds,
    paint_label_at,
)


class LineSeriesRenderer(_LineSamplingMixin, _LineSymbolMixin, SeriesRenderer):
    """折线 / 面积系列（含采样、断点、符号与标签）。

    option 键：``mode``（``lines`` / ``markers`` / ``lines+markers``）、
    ``smooth``、``areaStyle``、``step``、``symbol`` / ``symbolSize``、
    ``lineStyle``、``connectNulls``、``sampling``（True / False / dict：
    algorithm / threshold / pointsPerPixel）。支持 grid / polar（闭合）/
    singleAxis 坐标系；过渡动画按原始下标对齐旧数据。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._points = []  # [QPointF|None]（采样或全量点集）
        self._point_idx = []  # 与 _points 平行的原始数据下标
        self._prev_points = []  # 上一次布局的点（全量路径兜底插值）
        self._prev_pts_map = None  # {orig_index: QPointF}（采样路径动画）
        self._sampled = False  # 本次布局是否降采样
        self._symbol_items = []  # [(orig_index, QPointF)]：布局期算好的符号清单
        self._end_label = None  # (text, rect)：最近一次绘制的 endLabel
        self._py_x_sorted = False  # 兜底路径的 x 是否单调（窗口裁剪用 bisect）
        self._py_window_key = None  # 兜底路径窗口缓存键（数据身份 + 轴范围）
        self._py_window_cache = None  # 缓存值：range | list[int] | None
        self._data_len = 0
        # numpy 快速路径（仅当数据可数值化且 tsdownsample 可用）
        self._np_x = None  # [x, y] 数据形式时非空
        self._np_y = None
        self._y_vals = []  # Python 回退路径的 y 值（含 None）
        self._x_vals = []  # Python 回退路径的 x 原始值
        self._np_cache_key = None  # (id(data), len(data))
        #: ``_stacked_data`` 的结果缓存：``(key, own, srcs, base, out)``，
        #: ``own`` / ``srcs`` 是**强引用**，复核时做 ``is`` 比较兼杜绝 id 复用。
        self._stacked_cache = None
        # 缓存所依据的数据对象（**强引用**）：裸 id 会因对象回收被复用，
        # 持引用才能用 ``data is self._data_ref`` 精确判身份。
        self._data_ref = None
        self._cached_len = -1  # ``_data_ref`` 生效时的长度（检测原地增长）
        # 采样结果 LRU（键 = 数据身份 + 窗口 + 预算 + 算法）+ 全景常驻槽
        # （全景最贵且是缩放往返的必经点，淘汰时跳过）。
        self._sample_lru: OrderedDict = OrderedDict()
        self._full_sample_key = None
        # 乱序 x 的窗口缓存（单调 x 走 searchsorted，无需缓存），数据身份变更时作废。
        self._win_cache_key = None
        self._win_cache = None
        # x 时间基一次性分析（见 ``_downsample.analyze_x``）：
        self._np_x_monotone = False  # 非降且全有限 → searchsorted 窗口 / 切片视图
        self._np_x_strict = False  # 严格递增 → tsdownsample / 记录中断检测可用
        self._np_step = 0.0  # 正差中位数（中断判定的基准步长）
        self._np_gap_pos = None  # 记录中断位置（int64 ndarray）
        self._np_gap_dur = None  # 记录中断时长（float64 ndarray）
        # 乱序 x 的「按 x 找最近点」排序缓存（数据身份变化时作废）
        self._nearest_x_sorted = None
        self._nearest_index_sorted = None

    # -- 布局 -------------------------------------------------------------
    def plotMode(self) -> str:
        """折线绘制模式（Plotly 语义）：``lines`` / ``markers`` / ``lines+markers``。

        默认 ``lines``；显式 ``showSymbol: true`` 或 ``symbol``（非 none）
        视作 ``lines+markers``。
        """
        raw = self.opt.get("mode")
        if isinstance(raw, str) and raw.strip():
            name = raw.strip().lower().replace("-", "+").replace(" ", "+")
            has_line = "line" in name
            has_marker = "marker" in name
            if has_line and has_marker:
                return "lines+markers"
            if has_marker:
                return "markers"
            return "lines"
        if "showSymbol" in self.opt:
            return "lines+markers" if bool(self.opt.get("showSymbol")) else "lines"
        symbol = self.opt.get("symbol")
        if symbol is not None:
            return "lines" if str(symbol).strip().lower() == "none" else "lines+markers"
        return "lines"

    def showLine(self) -> bool:
        """是否绘制折线本身。"""
        return self.plotMode() != "markers"

    def showMarkers(self) -> bool:
        """是否绘制数据点符号。"""
        return self.plotMode() != "lines"

    def layout(self, rect: QRectF) -> None:
        coord = self.chart.coordFor(self.opt)
        self._prev_points = list(self._points)
        self._points = []
        self._point_idx = []
        if coord is None:
            return
        # 堆叠折线的值域必须含堆叠和（``setSeries`` 只按单值算），否则上层系列被裁。
        # 只有 stack 走这里：普通折线的范围已由 numpy 快路径算好。
        if isinstance(coord, GridCoord) and self.opt.get("stack"):
            if coord.y_axis.type in ("value", "log"):
                _fix_value_axis(coord.y_axis, self.chart, self.opt, "y")
            elif coord.x_axis.type in ("value", "log"):
                _fix_value_axis(coord.x_axis, self.chart, self.opt, "x")
        self._load_data()
        single = getattr(coord, "kind", "") == "singleAxis"

        # 采样对所有轴类型生效：三层兜底 tsdownsample → numpy 按桶 min/max →
        # 纯 Python 等距抽稀。
        enabled, threshold, ppb, algo = self._sampling_params()
        plot_w = self._plot_pixel_width(coord)
        n_out = max(_ds.min_out_for(algo), int(plot_w * ppb))
        # ``sel``：None = 全量｜(start, stop) 连续窗口｜ndarray 绝对下标
        sel = None
        window = None

        if self._np_y is not None and _ds.np is not None:
            window = self._window(coord)
            first, last, n_win = _win_span(window, self._data_len)
            sampled = None
            if enabled and n_win > threshold and n_win > 0:
                # 缓存键必须含两项身份信息：① 数据身份（否则换成等长的另一份
                # 数据会命中旧采样下标）；② 窗口范围（缩放后窗口内点数可能不变，
                # 但采样点集必须按新窗口重算）。
                cache_key = (
                    self._np_cache_key,
                    self._data_len,
                    n_out,
                    algo,
                    threshold,
                    first,
                    last,
                    n_win,
                )
                sampled = self._sample_cache_get(cache_key)
                if sampled is None:
                    if window is None:
                        x_win, y_win = self._np_x, self._np_y
                    elif isinstance(window, tuple):
                        start, stop = window
                        x_win = self._np_x[start:stop]
                        y_win = self._np_y[start:stop]
                    else:
                        x_win = self._np_x[window]
                        y_win = self._np_y[window]
                    local = self._decimate(
                        y_win, x_win, n_out, algo, assume_sorted=self._np_x_strict
                    )
                    if local is not None:
                        sampled = self._win_abs(window, local)
                        self._sample_cache_put(
                            cache_key, sampled, full=(n_win == self._data_len)
                        )
                self._sampled = sampled is not None and sampled.size < n_win
            sel = sampled if sampled is not None else window
        elif enabled and self._data_len > threshold:
            # 纯 Python 兜底路径（dict 项 / 混合类型 / 含 None）：先按窗口裁剪，
            # 再在窗口内等距抽稀；不裁剪的话缩放后曲线只覆盖窗口一小段。
            axis = coord.x_axis if isinstance(coord, GridCoord) else None
            window = self._py_window(axis)
            base = range(self._data_len) if window is None else window
            span = len(base)
            stride = max(1, int(span / max(2.0, plot_w * ppb)))
            if stride > 1:
                sel = [base[i] for i in range(0, span, stride)]
                self._sampled = True
            elif window is not None:
                # 窗口内点数已不多：全画窗口（仍要裁掉窗口外的点）
                sel = list(base)

        if sel is None and self._np_y is None:
            sel = list(range(self._data_len))

        # 向量化快路径：一次算完窗口内所有点的屏幕坐标（逐点 mapPoint 每点 ~6µs）。
        # 仅 numpy 路径 + grid 直角坐标可用；连续窗口 / 全量走切片视图。
        px = py = None
        abs_idx = None
        base = 0
        if _ds.np is not None and self._np_y is not None:
            try:
                np_ = _ds.np
                if isinstance(sel, tuple):
                    start, stop = sel
                    xs_arr = self._np_x[start:stop]
                    ys_arr = self._np_y[start:stop]
                    base = start
                elif sel is None:
                    xs_arr = self._np_x
                    ys_arr = self._np_y
                else:
                    abs_idx = np_.asarray(sel, dtype=np_.int64)
                    xs_arr = self._np_x[abs_idx]
                    ys_arr = self._np_y[abs_idx]
                mapped = coord.mapArrays(xs_arr, ys_arr)
                if mapped is not None:
                    px, py = mapped
            except Exception:
                px = py = None
                abs_idx = None
                base = 0

        if px is not None and py is not None:
            np_ = _ds.np
            # 非有限（NaN / inf）→ None 断点，与逐点路径的 ``_y_at`` 语义一致
            ok = np_.isfinite(px) & np_.isfinite(py)
            px_list = px.tolist()
            py_list = py.tolist()
            ok_list = ok.tolist()
            points = self._points
            point_idx = self._point_idx
            append_point = points.append
            append_idx = point_idx.append
            if abs_idx is None:
                # 连续段 / 全量：原始下标 = base + i（不物化下标数组）
                for i in range(len(px_list)):
                    if ok_list[i]:
                        append_point(QPointF(px_list[i], py_list[i]))
                    else:
                        append_point(None)
                    append_idx(base + i)
            else:
                idx_list = abs_idx.tolist()
                for i in range(len(px_list)):
                    if ok_list[i]:
                        append_point(QPointF(px_list[i], py_list[i]))
                    else:
                        append_point(None)
                    append_idx(idx_list[i])
        else:
            if isinstance(sel, tuple):
                iterable = range(sel[0], sel[1])
            elif sel is None:
                iterable = range(self._data_len)
            elif isinstance(sel, list):
                iterable = sel  # 纯 Python 兜底路径的下标本就是 list
            else:
                iterable = sel.tolist()
            for orig in iterable:
                yi = self._y_at(orig)
                if yi is None:
                    self._points.append(None)
                    self._point_idx.append(orig)
                    continue
                try:
                    if single:
                        pt = coord.mapPoint(yi)
                    else:
                        pt = coord.mapPoint(self._x_at(orig), yi)
                    if not (math.isfinite(pt.x()) and math.isfinite(pt.y())):
                        pt = None
                    self._points.append(pt)
                except Exception:
                    self._points.append(None)
                self._point_idx.append(orig)

        self._apply_gap_breaks(coord, plot_w)

        # 符号的屏幕坐标在布局期算一次（每次 paint 重映射在 1M 采样态每帧 ~11ms），
        # 点数量再按像素密度抽稀（相邻至少 ~10px）。
        self._symbol_items = self._build_symbol_items(coord, single, plot_w)
        self._build_prev_map(coord, single, ppb, algo, threshold)

    def _build_prev_map(self, coord, single, ppb, algo, threshold):
        """采样路径动画：按原始下标对齐旧数据采样点（过渡动画用）。"""
        self._prev_pts_map = None
        if not self._sampled or self.prev_data is None:
            return
        if len(self.prev_data) != self._data_len:
            return
        px, py = self._to_arrays(self.prev_data)
        if px is None:
            if py is None:
                return
            px = _ds.np.arange(len(py), dtype=_ds.np.float64)
        if not isinstance(coord, GridCoord) or coord.x_axis.type != "value":
            return
        lo, hi = coord.x_axis.vmin, coord.x_axis.vmax
        mask = (px >= lo) & (px <= hi)
        w_idx = _ds.np.flatnonzero(mask)
        if len(w_idx) == 0:
            return
        n_out = max(_ds.min_out_for(algo), int(coord.plot.width() * ppb))
        if len(w_idx) > threshold:
            idx_local = _ds.downsample_indices(px[w_idx], py[w_idx], n_out, algo)
            if idx_local is None:
                return
            w_idx = w_idx[idx_local]
        prev_map = {}
        for orig in w_idx:
            o = int(orig)
            v = py[o]
            if not math.isfinite(float(v)):
                continue
            try:
                prev_map[o] = coord.mapPoint(float(px[o]), float(v))
            except Exception:
                pass
        self._prev_pts_map = prev_map

    def _animated_points(self, anim_t):
        """旧→新插值：采样路径按原始下标对齐，全量路径逐点 lerp。"""
        cur = self._points
        if self._sampled:
            pm = self._prev_pts_map or {}
            out = []
            for pt, orig in zip(cur, self._point_idx):
                if pt is None:
                    out.append(None)
                    continue
                pp = pm.get(orig)
                if pp is None:
                    out.append(pt)
                else:
                    out.append(
                        QPointF(
                            _lerp(pp.x(), pt.x(), anim_t), _lerp(pp.y(), pt.y(), anim_t)
                        )
                    )
            return out
        prev_src = self._prev_points
        if self.prev_data is not None and len(self.prev_data) == self._data_len:
            coord = self.chart.coordFor(self.opt)
            single = getattr(coord, "kind", "") == "singleAxis" if coord else False
            prev = []
            for i, item in enumerate(self.prev_data):
                x, y = parseDataPoint(item, i)
                if y is None or coord is None:
                    prev.append(None)
                    continue
                try:
                    prev.append(coord.mapPoint(y) if single else coord.mapPoint(x, y))
                except Exception:
                    prev.append(None)
            prev_src = prev
        if len(prev_src) != len(cur):
            return cur
        out = []
        for a, b in zip(prev_src, cur):
            if a is None or b is None:
                out.append(b)
            else:
                out.append(
                    QPointF(_lerp(a.x(), b.x(), anim_t), _lerp(a.y(), b.y(), anim_t))
                )
        return out

    # -- 路径构建 ---------------------------------------------------------
    def _line_path(self, seg):
        """按 smooth / step 构建一段折线几何。

        返回 ``(path, pts)``：``path is None`` 表示纯折线（直线段 / step），
        调用方批量 ``drawPolyline(QPolygonF(pts))``；非空只在 ``smooth``
        （贝塞尔）时出现。
        """
        step = self.opt.get("step") or ""
        if isinstance(step, (list, tuple)):
            # ECharts ``step: [start, end]``：两端是否踏步
            first = bool(step[0]) if len(step) > 0 else False
            second = bool(step[1]) if len(step) > 1 else False
            if first and second:
                step = "middle"
            elif first:
                step = "start"
            elif second:
                step = "end"
            else:
                step = ""
        step = str(step)
        smooth = self.opt.get("smooth", False)
        if step in ("start", "middle", "end") and len(seg) >= 2:
            pts = [seg[0]]
            for a, b in zip(seg, seg[1:]):
                if step == "start":
                    pts.append(QPointF(a.x(), b.y()))
                elif step == "end":
                    pts.append(QPointF(b.x(), a.y()))
                else:  # middle
                    pts.append(QPointF((a.x() + b.x()) / 2, a.y()))
                    pts.append(QPointF((a.x() + b.x()) / 2, b.y()))
                pts.append(b)
            return None, pts
        if smooth and len(seg) >= 2:
            if bool(self.opt.get("smoothMonotone", False)):
                return _monotone_path(seg), seg
            k = (
                smooth
                if isinstance(smooth, (int, float)) and not isinstance(smooth, bool)
                else 0.5
            )
            return _smooth_path(seg, k), seg
        return None, seg

    def _baseline_y(self, coord, area=None):
        """面积填充基线（``areaStyle.origin``：auto / start / end / 数值）。"""
        if isinstance(coord, GridCoord):
            ax = coord.y_axis
            if ax.type == "log":
                return coord.plot.bottom()
            origin = (area or {}).get("origin") if isinstance(area, dict) else None
            if origin == "start":
                value = ax.vmin
            elif origin == "end":
                value = ax.vmax
            elif isinstance(origin, (int, float)) and not isinstance(origin, bool):
                value = float(origin)
            else:
                value = min(max(0.0, ax.vmin), ax.vmax) if ax.type == "value" else 0.0
            return ax.map(value, coord.plot.bottom(), coord.plot.top())
        return None

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        pts = self._animated_points(anim_t)
        valid = [pt for pt in pts if pt is not None]
        if not valid:
            return
        self._label_rects = []
        self._end_label = None
        mode = self.plotMode()
        draw_line = mode != "markers"
        draw_markers = mode != "lines"
        coord = self.chart.coordFor(self.opt)
        color = self.color()
        ls = self.opt.get("lineStyle") or {}
        width = _to_float(ls.get("width"), 2.0)
        if isinstance(ls.get("color"), str) and ls["color"]:
            color = parse_color(ls["color"])
        polar = getattr(coord, "kind", "") == "polar"
        # 大数据（超采样阈值）：陡峭线段序列的光栅化会让 polyline / path 退化到
        # 每段 ~1ms；smooth / step 在 heavy 时退化为直线（ECharts 大数据同策略）。
        _, heavy_threshold, _, _ = self._sampling_params()
        heavy = self._data_len > heavy_threshold

        # 分段（None 断点切开）；stack 模式同时准备逐点基线
        base_pts = None
        if getattr(self, "_stack_base", None) and not polar and not heavy:
            base_pts = []
            for orig in self._point_idx:
                try:
                    base_pts.append(
                        coord.mapPoint(
                            self._x_at(orig), self._stack_base.get(orig, 0.0)
                        )
                    )
                except Exception:
                    base_pts.append(None)
        segs = []
        seg = []
        seg_base = []
        # ``connectNulls``：断点（None / NaN）不切开线段；默认 False 时按断点分段。
        connect_nulls = bool(self.opt.get("connectNulls", False))
        for pos, pt in enumerate(pts):
            if pt is None:
                if connect_nulls:
                    continue
                if seg:
                    segs.append((seg, seg_base))
                    seg, seg_base = [], []
            else:
                seg.append(pt)
                seg_base.append(base_pts[pos] if base_pts is not None else None)
        if seg:
            segs.append((seg, seg_base))
        if not draw_line:
            segs = []

        p.save()
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)

        # 面积填充（先填充后描线）
        area = self.opt.get("areaStyle") if draw_line else None
        if area:
            opacity = 0.22
            if isinstance(area, dict):
                opacity = _to_float(area.get("opacity"), 0.22)
            base_y = self._baseline_y(coord, area)
            for seg_pts, seg_bases in segs:
                if len(seg_pts) < 2:
                    continue
                # 几何点直接来自 ``_line_path``：填充走 QPolygonF + drawPolygon
                # （单次 C++ 调用）。
                _path, geom_pts = self._line_path(seg_pts)
                fill = QPolygonF(list(geom_pts))
                if polar:
                    fill.append(QPointF(coord.center))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(with_alpha(color, 255 * opacity))
                    p.drawPolygon(fill)
                    continue
                if seg_bases and all(b is not None for b in seg_bases):
                    # stack：沿基线曲线回填（ECharts 堆叠面积语义）
                    fill.append(QPointF(seg_bases[-1]))
                    for base_pt in reversed(seg_bases[:-1]):
                        fill.append(QPointF(base_pt))
                    bottom = max(pt.y() for pt in seg_bases)
                elif base_y is not None:
                    fill.append(QPointF(seg_pts[-1].x(), base_y))
                    fill.append(QPointF(seg_pts[0].x(), base_y))
                    bottom = base_y
                else:
                    continue
                top = min(pt.y() for pt in seg_pts)
                raw_area_color = area.get("color") if isinstance(area, dict) else None
                if isinstance(raw_area_color, dict):
                    grad = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
                    for stop in raw_area_color.get("colorStops") or []:
                        try:
                            grad.setColorAt(
                                _clamp(_to_float(stop.get("offset"), 0.0), 0.0, 1.0),
                                parse_color(stop.get("color")),
                            )
                        except Exception:
                            continue
                    brush = grad
                elif isinstance(raw_area_color, str) and raw_area_color:
                    brush = with_alpha(parse_color(raw_area_color), 255 * opacity)
                else:
                    grad = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
                    grad.setColorAt(0.0, with_alpha(color, 255 * opacity))
                    grad.setColorAt(1.0, with_alpha(color, 0))
                    brush = grad
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(brush)
                p.drawPolygon(fill)

        # 折线本体
        line_opacity = _to_float(ls.get("opacity"), 1.0)
        pen_color = parse_color(color)
        if line_opacity < 1.0:
            pen_color.setAlphaF(max(0.0, min(1.0, line_opacity)))
        pen = QPen(pen_color, width)
        if heavy:
            # 大数据：RoundCap 每段圆头光栅化慢 5 倍且密集下不可见，
            # 改用默认 FlatCap / BevelJoin
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.BevelJoin)
        else:
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        cap_name = str(ls.get("cap") or "").strip().lower()
        if cap_name in ("butt", "flat"):
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        elif cap_name == "square":
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        elif cap_name == "round":
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        join_name = str(ls.get("join") or "").strip().lower()
        if join_name == "bevel":
            pen.setJoinStyle(Qt.PenJoinStyle.BevelJoin)
        elif join_name == "miter":
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        elif join_name == "round":
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        # 宽笔（>1px）在**自重叠折线**上会踩 Qt stroker 的爆炸路径：
        # ``drawPolyline`` / ``QPainterPath`` 单帧可达数秒，``drawLines`` 批量只要
        # 20ms；细笔（≤1px）三者都在 10ms 量级，用更省的 drawPolyline。
        wide_pen = float(pen.widthF()) > 1.0 + 1e-6
        lt = str(ls.get("type") or "solid")
        if lt in ("dashed", "dash"):
            pen.setStyle(Qt.PenStyle.DashLine)
        elif lt in ("dotted", "dot"):
            pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for seg_pts, _seg_bases in segs:
            if len(seg_pts) < 2:
                continue
            path, geom_pts = self._line_path(seg_pts)
            # smooth 的贝塞尔同样是「宽笔 + 稠密自重叠」高危几何，点太多时
            # 退化成直线段（ECharts 大数据下 smooth 同样退化）。
            if path is not None and not (wide_pen and len(geom_pts) > 2000):
                if polar:
                    path.closeSubpath()
                p.drawPath(path)
                continue
            points = list(geom_pts)
            if polar:
                points.append(points[0])
            if wide_pen and len(points) >= 32:
                # 批量单次调用，逐段走 Qt 的快速光栅路径（不经过 stroker 求并）
                p.drawLines([QLineF(a, b) for a, b in zip(points, points[1:])])
            else:
                p.drawPolyline(QPolygonF(points))

        # 数据点符号 / 标签：小数据全画，大数据用布局期算好的像素密度抽稀清单。
        symbol_name = str(self.opt.get("symbol") or "emptyCircle")
        symbol_rotate = _to_float(self.opt.get("symbolRotate"), 0.0)
        show_label = self.labelShown()
        end_cfg = self.opt.get("endLabel")
        show_end_label = isinstance(end_cfg, dict) and end_cfg.get("show", True)
        selected = self.chart.selectedIndices(self)
        if not draw_markers and not show_label and not selected and not show_end_label:
            p.restore()
            return
        r = max(1.0, _to_float(self.opt.get("symbolSize"), 6.0) / 2)
        r *= max(0.2, anim_t)
        emphasized = self.chart.emphasizedIndices(self)
        if heavy:
            sym_items = self._symbol_items
        else:
            sym_items = [
                (orig, pt)
                for pt, orig in zip(self._points, self._point_idx)
                if pt is not None
            ]
        if draw_markers and symbol_name != "none":
            hollow = symbol_name == "emptyCircle"
            kind = "circle" if symbol_name == "circle" else symbol_name
            # 循环外解析一次统一外观（None = 存在 per-item itemStyle）
            uni = self.uniformItemStyleResolved()
            uni_color = (
                (uni["color"] or self.chart.colorForSeries(self)) if uni else None
            )
            # 统一外观 + 无 hover 强调 + 无标签：位图贴图（比逐点 drawEllipse
            # 快一个量级，合并 QPainterPath 反而最慢）
            if (
                uni is not None
                and not emphasized
                and not selected
                and not show_label
                and r > 0
                and not symbol_rotate
            ):
                alpha = uni["opacity"]
                border_color, border_w = uni["borderColor"], uni["borderWidth"]
                if hollow:
                    sprite = symbolPixmap(
                        "circle",
                        r * 2,
                        QColor(T("color.bg.elevated")),
                        border_color
                        or with_alpha(parse_color(uni_color), int(235 * alpha)),
                        border_w or 1.5,
                        self.chart.getDevicePixelRatio(),
                    )
                else:
                    sprite = symbolPixmap(
                        kind,
                        r * 2,
                        with_alpha(parse_color(uni_color), int(235 * alpha)),
                        border_color
                        or with_alpha(parse_color(uni_color), int(235 * alpha)),
                        border_w or 1.0,
                        self.chart.getDevicePixelRatio(),
                    )
                half = r + 1.0
                for _orig, pt in sym_items:
                    p.drawPixmap(QPointF(pt.x() - half, pt.y() - half), sprite)
                p.restore()
                return
            for orig, pt in sym_items:
                if uni is not None:
                    item_color = parse_color(uni_color)
                    alpha = uni["opacity"]
                    border_color, border_w = uni["borderColor"], uni["borderWidth"]
                else:
                    item_color = parse_color(self.itemColor(orig))
                    alpha = self.itemOpacity(orig)
                    border_color, border_w = self.itemBorder(orig)
                rr = r
                if orig in selected:
                    select_style = self.selectItemStyle(orig)
                    select_color = self.selectColor(orig)
                    if select_color is not None:
                        item_color = select_color
                    border_color = select_style.get("borderColor") or border_color
                    border_w = max(
                        border_w, _to_float(select_style.get("borderWidth"), 1.5)
                    )
                    rr = max(rr, r * 1.15)
                if emphasized:
                    if orig in emphasized:
                        rr = r * 1.3
                        emphasis = self.emphasisColor(orig)
                        if emphasis is not None:
                            item_color = emphasis
                        if border_color is None:
                            border_color = item_color.lighter(115)
                            border_w = max(border_w, 1.5)
                    elif self.blursOtherItems():
                        blur = self.blurOpacity()
                        alpha *= blur if blur is not None else 0.35
                if hollow:
                    p.setPen(
                        QPen(
                            border_color or with_alpha(item_color, int(235 * alpha)),
                            border_w or 1.5,
                        )
                    )
                    p.setBrush(QColor(T("color.bg.elevated")))
                    p.drawEllipse(pt, rr, rr)
                else:
                    p.setPen(
                        QPen(
                            border_color or with_alpha(item_color, int(235 * alpha)),
                            border_w or 1.0,
                        )
                    )
                    p.setBrush(with_alpha(item_color, int(235 * alpha)))
                    _draw_symbol(p, kind, pt, rr * 2, symbol_rotate)
        # 选中点：``mode="lines"`` 也要看得见（ECharts 选中会强制显示符号）
        if selected:
            sel_kind = symbol_name if symbol_name != "none" else "circle"
            sel_r = max(2.4, r * 1.15)
            for orig in sorted(selected)[:2000]:
                info = self.valueAtIndex(orig)
                if not info or info.get("pos") is None:
                    continue
                pt = QPointF(info["pos"])
                style = self.selectItemStyle(orig)
                fill = self.selectColor(orig) or self.itemColor(orig)
                border = style.get("borderColor") or T("color.bg.elevated")
                width = _to_float(style.get("borderWidth"), 1.6)
                p.setPen(QPen(parse_color(border), width))
                p.setBrush(fill)
                _draw_symbol(p, sel_kind, pt, sel_r * 2, symbol_rotate)
        if show_label:
            font = self.labelFont()
            p.setFont(font)
            fm = QFontMetricsF(font)
            marker_r = r if draw_markers and symbol_name != "none" else 0.0
            label_opt = self.labelOption()
            position = str(label_opt.get("position") or "top")
            distance = _to_float(label_opt.get("distance"), 4.0)
            rotate = label_rotate(label_opt)
            align = label_align(label_opt)
            hide_overlap = False
            layout = self.opt.get("labelLayout")
            if isinstance(layout, dict):
                hide_overlap = bool(layout.get("hideOverlap", False))
            drawn = []
            for orig, pt in sym_items:
                if orig is None:
                    continue
                text = self.labelText(orig, self._raw_value(orig), self._x_at(orig))
                anchor, rect = _label_placement(
                    pt, text, fm, position, distance, marker_r
                )
                if position in ("top", "bottom", "inside"):
                    offset = label_anchor_offset(align, rect.width())
                    if offset:
                        anchor = QPointF(anchor.x() + offset, anchor.y())
                        rect = rect.translated(offset, 0.0)
                hit = label_rotated_bounds(rect, rotate)
                if hide_overlap and any(hit.intersects(r) for r in drawn):
                    continue
                p.setPen(self.labelColorFor(orig))
                paint_label_at(p, anchor, text, fm, rotate)
                rect = hit
                if marker_r > 0:
                    rect = rect.united(
                        QRectF(
                            pt.x() - marker_r - 2,
                            pt.y() - marker_r - 2,
                            marker_r * 2 + 4,
                            marker_r * 2 + 4,
                        )
                    )
                drawn.append(rect)
                self._label_rects.append((orig, rect, text))
        end_label = self.opt.get("endLabel")
        if isinstance(end_label, dict) and end_label.get("show", True):
            self._paint_end_label(p, coord, end_label)
        p.restore()

    def _paint_end_label(self, p: QPainter, coord, cfg: dict) -> None:
        """线端数值标签（``series.endLabel``）。"""
        last = None
        for k in range(len(self._points) - 1, -1, -1):
            if self._points[k] is not None and k < len(self._point_idx):
                last = (self._point_idx[k], self._points[k])
                break
        if last is None:
            return
        index, pt = last
        if index is None or index < 0:
            return
        value = self._raw_value(index)
        if value is None:
            return
        name = self._x_at(index)
        params = {
            "a": self.name,
            "b": name,
            "c": value,
            "value": value,
            "name": name,
            "series": self.name,
            "dataIndex": index,
        }
        text = self._apply_label_formatter(
            cfg.get("formatter"), params, formatValue(value)
        )
        if not text:
            return
        style = merged_text_style(self.chart, cfg)
        try:
            size = max(6.0, float(style.get("fontSize", T("font.xs"))))
        except (TypeError, ValueError, OverflowError):
            size = float(T("font.xs"))
        font = chartFont(
            size,
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )
        p.setFont(font)
        fm = QFontMetricsF(font)
        color = style.get("color")
        p.setPen(
            parse_color(color) if isinstance(color, str) and color else self.color()
        )
        distance = _to_float(cfg.get("distance"), 6.0)
        tw = fm.horizontalAdvance(text)
        box = getattr(coord, "plot", None)
        x = pt.x() + distance
        if box is not None and x + tw > box.right():
            x = pt.x() - distance - tw
        baseline = pt.y() + (fm.ascent() - fm.descent()) / 2.0
        p.drawText(QPointF(x, baseline), text)
        self._end_label = (
            text,
            QRectF(x, baseline - fm.ascent(), tw, fm.height() + 2.0),
        )

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        best = None
        best_d = self.chart.hitRadius()  # 命中半径 px（tooltip.hitRadius）
        # 动画期用画出来的那份折线点，否则会命中动画终点位置上的点。
        pts = (
            self._points if self._anim_t >= 1.0 else self._animated_points(self._anim_t)
        )
        for i, pt in enumerate(pts):
            if pt is None:
                continue
            d = math.hypot(pt.x() - pos.x(), pt.y() - pos.y())
            if d <= best_d:
                best_d = d
                best = i
        if best is None:
            return None
        orig = self._point_idx[best] if best < len(self._point_idx) else best
        return {
            "name": self.name,
            "value": self._raw_value(orig),
            "series": self.name,
            "dataIndex": orig,
            "x": self._x_at(orig),
        }

    def samplingStats(self) -> dict:
        """采样统计（公开 API）：原始点数 / 绘制点数 / 是否降采样。"""
        return {
            "dataLen": int(self._data_len),
            "drawn": len(self._points),
            "sampled": bool(self._sampled),
        }

    def valueAtIndex(self, index: int):
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        if not isinstance(idx, int) or not (0 <= idx < self._data_len):
            return None
        y = self._raw_value(idx)
        if y is None:
            return None
        # 命中点坐标：精确下标优先，否则取采样集中最近的原始下标
        # （``_point_idx`` 升序，二分即可）。
        pos = None
        if self._point_idx:
            ids = self._point_idx
            at = bisect.bisect_left(ids, idx)
            best = None
            # 断点占位是「重复前一下标 + None 点」，会紧邻在 at 两侧：
            # 多扫两格并跳过 None，避免把命中点吸到断点上。
            for k in range(max(0, at - 2), min(len(ids), at + 2)):
                if self._points[k] is None:
                    continue
                orig = ids[k]
                if orig < 0:
                    continue
                distance = abs(orig - idx)
                if best is None or distance < best[0]:
                    best = (distance, k)
            if best is not None:
                pos = self._points[best[1]]
        return {
            "name": self.name,
            "value": y,
            "series": self.name,
            "dataIndex": idx,
            "pos": pos,
        }

    def valueStats(self) -> dict:
        """有限 y 值统计（numpy 快路径；markLine / markPoint 用）。"""
        data = self.dataView()
        key = (id(data), len(data))
        if self._stats_ref is data and self._stats_key == key:
            return self._stats_cache
        np_ = _ds.np
        if np_ is not None:
            try:
                _x_arr, y_arr = self._to_arrays(data)
            except Exception:
                y_arr = None
            if y_arr is not None and y_arr.ndim == 1:
                mask = np_.isfinite(y_arr)
                if bool(mask.any()):
                    valid = y_arr[mask]
                    indices = np_.flatnonzero(mask)
                    lo_at = int(np_.argmin(valid))
                    hi_at = int(np_.argmax(valid))
                    stats = {
                        "min": float(valid[lo_at]),
                        "max": float(valid[hi_at]),
                        "minIndex": int(indices[lo_at]),
                        "maxIndex": int(indices[hi_at]),
                        "sum": float(valid.sum()),
                        "count": int(valid.size),
                    }
                    self._stats_key = key
                    self._stats_ref = data
                    self._stats_cache = stats
                    return stats
        return super().valueStats()

    def nearestIndexAt(self, x):
        """按 x 值找最近的原始数据下标（axis tooltip / 数值 x 轴）。"""
        try:
            xv = float(x)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(xv) or self._data_len <= 0:
            return None
        np_ = _ds.np
        if self._np_x is not None and np_ is not None:
            xs = self._np_x
            if self._np_x_monotone:
                pos = int(np_.searchsorted(xs, xv, side="left"))
                best = None
                for idx in (pos - 1, pos):
                    if not (0 <= idx < xs.size):
                        continue
                    value = float(xs[idx])
                    if not math.isfinite(value):
                        continue
                    distance = abs(value - xv)
                    if best is None or distance < best[0]:
                        best = (distance, idx)
                return int(best[1]) if best is not None else None
            # 乱序：按 x 排序一次（数据身份变化时作废），之后二分
            if self._nearest_x_sorted is None:
                order = np_.argsort(xs, kind="stable")
                sorted_x = xs[order]
                finite = np_.isfinite(sorted_x)
                if not finite.all():
                    sorted_x = sorted_x[finite]
                    order = order[finite]
                self._nearest_x_sorted = sorted_x
                self._nearest_index_sorted = order
            sorted_x = self._nearest_x_sorted
            order = self._nearest_index_sorted
            if sorted_x is None or sorted_x.size == 0:
                return None
            pos = int(np_.searchsorted(sorted_x, xv, side="left"))
            best = None
            for at in (pos - 1, pos):
                if not (0 <= at < sorted_x.size):
                    continue
                distance = abs(float(sorted_x[at]) - xv)
                if best is None or distance < best[0]:
                    best = (distance, int(order[at]))
            return best[1] if best is not None else None
        xs = self._x_vals
        if not xs:
            return None
        if self._py_x_sorted:
            at = bisect.bisect_left(xs, xv)
            best = None
            for idx in (at - 1, at):
                if not (0 <= idx < len(xs)):
                    continue
                value = xs[idx]
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                distance = abs(float(value) - xv)
                if best is None or distance < best[0]:
                    best = (distance, idx)
            return best[1] if best is not None else None
        best = None
        for idx, value in enumerate(xs):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if not math.isfinite(value):
                continue
            distance = abs(float(value) - xv)
            if best is None or distance < best[0]:
                best = (distance, idx)
        return best[1] if best is not None else None
