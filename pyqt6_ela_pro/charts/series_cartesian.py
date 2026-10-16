"""
直角坐标系列（完整 10 个：bar / pictorialBar / line / scatter /
effectScatter / candlestick / boxplot / heatmap / parallel / themeRiver）。

本模块导入时经 ``registerSeries`` 注册全部系列（line 为完整版，覆盖
core 兜底版）。

通用约定：
- 坐标映射经 ``self.chart.coordFor(self.opt)``；柱 / 热力支持
  「yAxis 为 category」，直接用 AxisModel 双向映射。
- 数值轴范围：core 只按单点值统计，stack 柱 / K线高低 / 箱线极值会溢出，
  故这些渲染器在 ``layout`` 中用 ``_grid_value_extent`` 重设数值轴范围（幂等）。
- 涨跌配色（candlestick）遵循 A 股习惯：红涨绿跌 —— 涨用
  ``color.danger``、跌用 ``color.success``，可用 option 的
  ``colorUp`` / ``colorDown`` 覆盖。
- 全部配色经 ``T()`` 实时取（Ela 主题令牌）；空数据 / None 不崩溃。

移植自 InstructionX_UIKit.charts.series_cartesian（原库为 PyQt6；
主题令牌经 charts._tokens 适配到 eTheme / ElaThemeType，原库无 LICENSE，
保留出处）。
"""

from __future__ import annotations

import math

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

from .._motion import start_idle_loop
from ._tokens import T
from . import _downsample as _ds
from ._symbol import drawSymbol
from ._utils import dist_point_segment
from ._utils import clamp as _clamp
from ._utils import to_float as _to_float
from ._utils import with_alpha
from .axes import CalendarCoord, GridCoord, chartFont, formatValue
from .core import SeriesRenderer, parseDataPoint, registerSeries

__all__ = [
    "BarSeriesRenderer",
    "PictorialBarSeriesRenderer",
    "LineSeriesRenderer",
    "ScatterSeriesRenderer",
    "EffectScatterSeriesRenderer",
    "CandlestickSeriesRenderer",
    "BoxplotSeriesRenderer",
    "HeatmapSeriesRenderer",
    "ParallelSeriesRenderer",
    "ThemeRiverSeriesRenderer",
]


# ---------------------------------------------------------------------------
# 小工具（数值 / 几何工具统一见 charts._utils）
# ---------------------------------------------------------------------------


def _lerp(a, b, t):
    return a + (b - a) * t


def _ramp_color(colors, t):
    """多色带插值：colors 为颜色列表，t∈[0,1] → QColor。"""
    cols = [QColor(c) for c in (colors or []) if c]
    if not cols:
        return QColor(T("color.primary"))
    if len(cols) == 1:
        return cols[0]
    t = max(0.0, min(1.0, float(t)))
    pos = t * (len(cols) - 1)
    i = min(int(pos), len(cols) - 2)
    f = pos - i
    a, b = cols[i], cols[i + 1]
    return QColor(
        int(_lerp(a.red(), b.red(), f)),
        int(_lerp(a.green(), b.green(), f)),
        int(_lerp(a.blue(), b.blue(), f)),
        int(_lerp(a.alpha(), b.alpha(), f)),
    )


def _smooth_path(points, smooth=0.5):
    """Catmull-Rom → 三次贝塞尔平滑路径。points: [QPointF]（≥2）。"""
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    path.moveTo(points[0])
    if n == 1:
        return path
    k = max(0.0, min(1.0, float(smooth)))
    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(i + 2, n - 1)]
        c1 = QPointF(
            p1.x() + (p2.x() - p0.x()) * k / 6.0,
            p1.y() + (p2.y() - p0.y()) * k / 6.0,
        )
        c2 = QPointF(
            p2.x() - (p3.x() - p1.x()) * k / 6.0,
            p2.y() - (p3.y() - p1.y()) * k / 6.0,
        )
        path.cubicTo(c1, c2, p2)
    return path


def _datum_list(item):
    """取数据项的数值列表：[...] 或 {"value": [...]} → list[float]|None。"""
    v = item.get("value") if isinstance(item, dict) else item
    if not isinstance(v, (list, tuple)):
        return None
    out = []
    for x in v:
        f = _to_float(x, None)
        if f is None:
            return None
        out.append(f)
    return out


def _grid_series_opts(chart):
    """当前 option 中落在 grid 坐标系的系列 option 列表（内部引用，零拷贝）。"""
    out = []
    for s in chart._option_ref().get("series") or []:
        if not isinstance(s, dict):
            continue
        if s.get("coordinateSystem") in (None, "cartesian2d", "grid"):
            out.append(s)
    return out


def _finite(v) -> bool:
    """是否为有限数值（None / NaN / inf 一律 False）。"""
    try:
        return math.isfinite(v)
    except TypeError:
        return False


def _numeric_xy(data):
    """数值化 ``[(x, y), ...]`` → numpy 数组；不可数值化返回 ``(None, None)``。

    折线已有这套快路径（``LineSeriesRenderer._to_arrays``），但 bar /
    candlestick / boxplot 的 ``layout`` 仍在逐项调 ``parseDataPoint``
    ——本优化的先冲来自「逐项调
    ``parseDataPoint``」（cProfile 下 tottime 前三），而不是柱的绝对数量。

    纯数值序列（x 取下标）与 ``[x, y]`` 对序列走 numpy；含 dict / None /
    混合形态返回 ``(None, None)``，调用方回退 Python 循环（数据量通常较小）。
    """
    if _ds.np is None:
        return None, None
    n = len(data) if hasattr(data, "__len__") else 0
    if not n:
        return None, None
    np_ = _ds.np
    # **必须先抽样确认元素类型**：``asarray`` 对 ``[1.0, None]`` 会把 None
    # 变成 NaN 并成功返回（ndim==1），对 ``[[1,2,3]]`` 也会成功返回
    # （ndim==2, shape[1]==3）。若直接信任返回值，这两种结构型数据会被
    # 误当数值序列 —— ``[x, y, z]`` 的第三列被静默丢弃、None 间隙被
    # 当成 NaN 跳过（后者恰好正确，但前者是错误）。
    step = max(1, n // 64)
    probes = set(range(0, n, step))
    probes.update(range(min(24, n)))
    probes.update(range(max(0, n - 24), n))
    for i in probes:
        item = data[i]
        if isinstance(item, bool):
            return None, None
        if isinstance(item, (int, float)):
            continue
        if isinstance(item, (list, tuple)):
            # 只接受长度恰为 2 的 [x, y]
            if len(item) == 2 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in item
            ):
                continue
            return None, None
        return None, None
    try:
        arr = np_.asarray(data, dtype=np_.float64)
    except (TypeError, ValueError, OverflowError):
        return None, None
    if arr.ndim == 1:
        return np_.arange(n, dtype=np_.float64), arr
    if arr.ndim == 2 and arr.shape[1] == 2:
        return arr[:, 0], arr[:, 1]
    return None, None


#: ``_grid_value_extent`` 的结果缓存：(数据对象身份, 长度) → (dmin, dmax)。
#:
#: **必须缓存**：本函数被 ``_fix_value_axis`` 在**每个** bar / candlestick /
#: boxplot 系列的 ``layout()`` 里各调一次，而它要遍历**全部** grid 系列的
#: 全部数据。6 条折线 + 1 条柱的实测：布局 29.7 ms → 597.6 ms（20 倍），
#: 因为 7 个系列各扫一遍 120 万个点，且每次 ``_layout_all(force=True)``
#: 都会重来一遍。
#:
#: 值只取决于数据内容，与窗口 / 尺寸无关，故按「数据对象身份 + 长度」缓存
#: 安全；缓存值**持有数据强引用**（tuple 第一项），防 id 复用串数据。
_GRID_EXTENT_CACHE: dict = {}
_GRID_EXTENT_CACHE_LIMIT = 32


def _seq_len(value) -> int:
    """序列长度，非序列 / 无长度返回 0。

    **别写 ``len(v or ())``**：``v`` 是裸 ndarray 时 ``or`` 会对它求真值，
    numpy 抛 ``ValueError: The truth value of an array with more than one
    element is ambiguous``。这条路径的后果特别隐蔽 —— 异常被 ``_paint_series``
    的 ``warn_once`` 吞掉（且去重后只报一次），表现为 **bar / candlestick /
    boxplot 一根都不画、没有任何报错**。而「可直接传 numpy 数组」是本模块
    明文承诺的用法（``data`` 模块 docstring），短数组（< 256）不包装成
    ``ElaNumericBuffer``，所以裸 ndarray 确实会走到这里。
    """
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0


def _grid_value_extent(chart):
    """grid 数值轴真实范围（类型感知）：stack 柱按堆叠和。返回 (dmin, dmax) 或 None。

    带缓存（见 ``_GRID_EXTENT_CACHE``）：逐系列 ``layout`` 都会调它，
    百万点下每次全量遍历会让布局时间放大一个数量级。
    """
    opts = _grid_series_opts(chart)
    key = tuple((id(s), id(s.get("data")), _seq_len(s.get("data"))) for s in opts)
    hit = _GRID_EXTENT_CACHE.get(key)
    # 命中时复核 series 对象仍是同一批（key 里只有 id，靠强引用 + is 兜底）
    if hit is not None:
        cached_ext, cached_opts = hit
        if len(cached_opts) == len(opts) and all(
            a is b for a, b in zip(cached_opts, opts)
        ):
            return cached_ext
    ext = _grid_value_extent_uncached(chart, opts)
    if len(_GRID_EXTENT_CACHE) >= _GRID_EXTENT_CACHE_LIMIT:
        _GRID_EXTENT_CACHE.clear()
    _GRID_EXTENT_CACHE[key] = (ext, tuple(opts))
    return ext


def _grid_value_extent_uncached(chart, opts) -> tuple:
    """``_grid_value_extent`` 的实际计算（无缓存）。"""
    dmin = None
    dmax = None

    def feed(v):
        """喂一个候选极值；**非有限值必须拒收**（后果见 AGENTS.md「charts」）。"""
        nonlocal dmin, dmax
        if v is None or not math.isfinite(v):
            return
        dmin = v if dmin is None else min(dmin, v)
        dmax = v if dmax is None else max(dmax, v)

    stack_pos = {}
    stack_neg = {}
    for s in opts:
        stype = str(s.get("type") or "line")
        data = s.get("data")
        if data is None:
            data = []
        if stype == "bar" and s.get("stack"):
            key = str(s.get("stack"))
            for i, item in enumerate(data):
                _, y = parseDataPoint(item, i)
                if y is None:
                    continue
                if y >= 0:
                    stack_pos[(key, i)] = stack_pos.get((key, i), 0.0) + y
                else:
                    stack_neg[(key, i)] = stack_neg.get((key, i), 0.0) + y
        elif stype == "candlestick":
            for item in data:
                nums = _datum_list(item)
                if nums and len(nums) >= 4:
                    feed(min(nums[2], nums[0], nums[1]))
                    feed(max(nums[3], nums[0], nums[1]))
        elif stype == "boxplot":
            for item in data:
                nums = _datum_list(item)
                if nums and len(nums) >= 5:
                    feed(nums[0])
                    feed(nums[4])
        else:
            for i, item in enumerate(data):
                _, y = parseDataPoint(item, i)
                feed(y)
    for v in stack_pos.values():
        feed(v)
    for v in stack_neg.values():
        feed(v)
    if dmin is None:
        return None
    return dmin, dmax


def _axis_label(axis, x):
    """类别轴标签（x 为类别名或下标）；数值轴退回 formatValue。"""
    if axis is not None and axis.type == "category" and axis.categories:
        idx = axis.categoryIndex(x)
        if 0 <= idx < len(axis.categories):
            return axis.categories[idx]
        all_cats = getattr(axis, "_all_categories", None) or []
        if 0 <= idx < len(all_cats):
            return all_cats[idx]
    return formatValue(x)


def _fix_value_axis(axis, chart):
    """按 ``_grid_value_extent`` 重设数值轴范围（category 轴自动跳过）。"""
    if axis is None or axis.type != "value":
        return
    ext = _grid_value_extent(chart)
    if ext is not None:
        axis.setExtent(ext[0], ext[1])


# ---------------------------------------------------------------------------
# bar 柱状图
# ---------------------------------------------------------------------------


class BarSeriesRenderer(SeriesRenderer):
    """柱状图。

    option 键：
    - ``stack``: str，同名堆叠（正值向上累加、负值向下累加）；
    - ``barWidth``: 像素（>1）或占槽位比例（0~1]）；
    - ``itemStyle.borderRadius``: 圆角 px（数值或数值列表，取最大）；
    - yAxis 为 ``category`` 时自动切换为水平条形；
    - ``anim_t`` 高度生长动画；setOption 时 prev_data 逐柱插值。
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
        _fix_value_axis(val_axis, self.chart)
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

        # numpy 快路径：数值 / [x, y] 序列向量化取值。逐项 parseDataPoint
        # cProfile 下是 bar 布局的主要 tottime 项。
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
            v0 = (pos_bases if y >= 0 else neg_bases).get(i, 0.0)
            v1 = v0 + y
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
                _, y = parseDataPoint(item, i)
                if y is None:
                    continue
                bucket = pos if y >= 0 else neg
                bucket[i] = bucket.get(i, 0.0) + y
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
        """批量取类别标签（``xs`` 为 x 序列）。

        与逐项 ``_cat_label`` 等价，但把「类别轴有无标签」这个判断提到
        循环外 —— 逐项判断是逐图元重复的属性访问与
        ``formatValue`` 调用（cProfile 下合计占 tottime 约 8%）；
        ``formatValue``（实测占 bar 布局 tottime 8%）。

        ``cat_axis`` 不是 category 轴时（即数值轴）：逐项结果只取决于 x，
        仍逐项走 ``formatValue``，只是省掉了重复的类型判断。
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

        命中必须用**画出来的那份**几何：动画期柱高还在生长，用终态矩形去
        命中就会「点低处的柱、亮高处的柱」。
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
        if not self._bars:
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        p.save()
        p.setClipRect(coord.plot)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        show_label = self.labelShown()
        if show_label:
            font = chartFont(self.labelFontSize())
            p.setFont(font)
            p.setPen(self.labelColor())
            fm = QFontMetricsF(font)
        # 外观在循环外解析一次（uniformItemStyleResolved 走 O(1) 快路径）。
        # 逐图元调 itemColor / itemOpacity / itemBorder / _bar_radius 时，
        # 逐图元调四个方法 = 4 次属性查找，实测合计占单帧 tottime
        # 约 25%。为 None 时
        # 说明存在 per-item itemStyle，退回逐项查找。
        uni = self.uniformItemStyleResolved()
        # 统一外观下的主色与 pen 也提到循环外：colorForSeries 会走
        # palette()（带缓存但仍有 dict 查找），材料多时是 tottime 前三。
        # 颜色仍逐柱拷贝（下面要 setAlphaF），pen / brush 可整段复用。
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
                # 统一外观：直接取循环外解析好的值（颜色仍需逐项拷贝，
                # 因为下面会 setAlphaF 改它）
                color = QColor(uni_color)
                alpha = uni["opacity"]
                border_color, border_w = uni["borderColor"], uni["borderWidth"]
                raw_r = uni["borderRadius"]
                radius = (
                    0.0
                    if raw_r is None
                    else max(0.0, min(raw_r, r.width() / 2, r.height() / 2))
                )
            else:
                color = QColor(self.itemColor(index))
                alpha = self.itemOpacity(index)
                border_color, border_w = self.itemBorder(index)
                radius = self._bar_radius(index, r)
            if hovered is not None:
                if index != hovered:
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
                # 统一描边：pen 已在循环外建好，逐柱新建 QPen 是纯浪费
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
                self._paint_bar_label(p, r, bar, fm)
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

    def _paint_bar_label(self, p: QPainter, rect: QRectF, bar: dict, fm) -> None:
        """柱数据标签（默认柱顶 / 横条右端，``label.position`` 可改）。"""
        text = self.labelText(bar["index"], bar["y"], bar["label"])
        if not text:
            return
        position = str(self.labelOption().get("position") or "")
        if not position:
            position = "right" if self._horizontal else "top"
        if position == "inside":
            box = rect.adjusted(2, 2, -2, -2)
            p.drawText(
                box,
                (
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if self._horizontal
                    else Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                ),
                text,
            )
            return
        if self._horizontal:
            anchor = QPointF(rect.right() + 4, rect.center().y() + fm.height() / 4)
            p.drawText(anchor, text)
        else:
            anchor = QPointF(
                rect.center().x() - fm.horizontalAdvance(text) / 2, rect.top() - 3
            )
            p.drawText(anchor, text)

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        """柱命中检测：命中框（外扩 2px）内**第一根**柱，命中则返回 None。

        线性扫描是正确实现：柱数量与绘制区宽度同量级（几十至几百根），
        扫描成本可忽略，且语义唯一（返回第一根而不是最层或最近者）。

        **曾为二分索引，已撤回**：它是为「2 万根柱」这个**不存在的**
        场景写的（实测 2 万根的 hitTest 占 2330ms/200 次，但真实业务不会给
        几十根柱实时悬停）。为它引入了两处非饱定性：柱可能**互相重叠**（
        实测 74/200 与线性扫描不一致）、且**二分后还要再检另一轴**（
        实测 1095/3000 不一致）。特别住：它会把「为不存在的问题优化得很
        优雅」变成一段难以验证的代码，而且下一次改动柱宽下限就可能静默改坏它。

        要真正优化柱命中，先用 ``benchmark()`` 确认柱数量是真实需求（见 AGENTS.md
        「大数据性能」小节）。

        动画期用 ``_animated_rect`` 现算几何（与 ``paint`` 同一份公式），
        而不是 ``bar["rect"]``（终态）—— 否则点动画中尚未长到的那根柱会
        命中旁边的柱。
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
                    "pos": pos,
                }
        return None


# ---------------------------------------------------------------------------
# line 折线（完整版，覆盖 core 兜底版）
# ---------------------------------------------------------------------------


class LineSeriesRenderer(SeriesRenderer):
    """折线图（完整版，内置 tsdownsample 动态降采样）。

    option 键：
    - ``smooth``: bool 或 0~1 平滑系数（Catmull-Rom → 贝塞尔）；
    - ``areaStyle``: dict 或真值，面积填充（透明渐变），
      ``areaStyle.opacity`` 可调（默认 0.22）；
    - ``step``: "start" | "middle" | "end" 阶梯线；
    - ``showSymbol``: 是否绘制数据点（默认 True）；
    - ``symbolSize``: 数据点直径 px（默认 6）；
    - ``lineStyle``: {"type": "solid|dashed|dotted", "width": px, "color": ...}；
    - ``sampling``: True（默认）/ False / dict：
      {"algorithm": "minmax"|"m4"|"lttb"|"minmaxLTTB",
       "threshold": 启用采样的点数下限（默认 2000），
       "pointsPerPixel": 每像素目标点数（默认 2）}；
      大数据时按「当前绘图范围（x 轴数值窗口）× 画布像素宽度」动态采样，
      只渲染窗口内数据，范围 / 尺寸 / 数据变化时自动重采样；
    - 支持 grid / polar（闭合）/ singleAxis 坐标系；
    - 过渡动画：旧→新数据插值（采样路径按原始下标对齐）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._points = []  # [QPointF|None]（采样或全量点集）
        self._point_idx = []  # 与 _points 平行的原始数据下标
        self._prev_points = []  # 上一次布局的点（全量路径兜底插值）
        self._prev_pts_map = None  # {orig_index: QPointF}（采样路径动画）
        self._sampled = False  # 本次布局是否降采样
        self._data_len = 0
        # numpy 快速路径（仅当数据可数值化且 tsdownsample 可用）
        self._np_x = None  # [x, y] 数据形式时非空
        self._np_y = None
        self._y_vals = []  # Python 回退路径的 y 值（含 None）
        self._x_vals = []  # Python 回退路径的 x 原始值
        self._np_cache_key = None  # (id(data), len(data))
        #: ``_stacked_data`` 的结果缓存（见该方法）。条目形如
        #: ``(key, own, srcs, base, out)``，``own`` / ``srcs`` 是**强引用**，
        #: 用来在复核时做 ``is`` 比较兼杜绝 id 复用。
        self._stacked_cache = None
        # 当前缓存所依据的数据对象（**强引用**）。裸 id 单独用不可靠：对象被
        # 回收后 id 会被复用，可能把上一份数据的 numpy 视图当成当前的。持引用
        # 既保证 id 有效，也让 `data is self._data_ref` 成为精确的身份判据。
        self._data_ref = None
        self._cached_len = -1  # ``_data_ref`` 生效时的长度（检测原地增长）
        self._sample_cache_key = None  # (数据身份, n, n_out, algo, threshold, lo, hi)
        self._sample_indices = None  # 采样点全局下标（np 数组或 list）

    # -- 数据解析 ---------------------------------------------------------
    def _stacked_data(self):
        """stack 模式：叠加前序同名 stack 可见系列的值（不影响原始 opt）。

        返回叠加后的 data；无 stacking 时返回 ``None``。基线存于
        ``self._stack_base``（index -> 基线值），tooltip / 标签按原始值展示。

        **结果必须缓存**：本方法每次都新建一整份 list（dict 项还要 ``{**item}``
        逐个复制），而 ``layout`` 每次 ``_layout_all`` 都会调它一次。下游的
        采样缓存键里含 data 的**身份**，每次换一份新 list 就永不命中 ——
        实测 stack 折线的布局耗时差 **22 倍**。
        """
        stack = self.opt.get("stack")
        if not stack:
            self._stack_base = None
            return None
        contributors = []
        for r in self.chart.seriesRenderers:
            if r is self:
                break
            if not isinstance(r, LineSeriesRenderer) or not r.visible:
                continue
            if str(r.opt.get("stack") or "") != str(stack):
                continue
            contributors.append(r)

        own = self.dataView()
        srcs = [r.data() for r in contributors]
        key = (id(own), tuple((id(s), len(s)) for s in srcs))
        hit = self._stacked_cache
        # ``is`` 复核不能省：缓存条目**不持有**源数据（``out`` 里全是新算的
        # 标量），而 ``setOption`` 换数据后旧对象会被释放，新对象完全可能拿到
        # 同一个 ``id`` 且长度相同 —— 只比 key 就会把上一份叠加值当成当前的。
        # 持强引用同时杜绝 id 复用。
        if hit is not None and hit[0] == key and hit[1] is own and hit[2] == srcs:
            self._stack_base = hit[3]
            return hit[4]

        base: dict = {}
        for src in srcs:
            for i, item in enumerate(src):
                _, y = parseDataPoint(item, i)
                if y is not None:
                    base[i] = base.get(i, 0.0) + y
        self._stack_base = base or None
        if not base:
            self._stacked_cache = (key, own, srcs, self._stack_base, None)
            return None
        out = []
        for i, item in enumerate(own):
            _x, y = parseDataPoint(item, i)
            if y is None:
                out.append(item)
                continue
            stacked = y + base.get(i, 0.0)
            if isinstance(item, dict):
                value = item.get("value")
                if isinstance(value, (list, tuple)) and len(value) >= 2:
                    merged = dict(item)
                    merged["value"] = [value[0], stacked] + list(value[2:])
                    out.append(merged)
                else:
                    out.append({**item, "value": stacked})
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                out.append([item[0], stacked] + list(item[2:]))
            else:
                out.append(stacked)
        self._stacked_cache = (key, own, srcs, self._stack_base, out)
        return out

    def _raw_value(self, index):
        """原始值（stack 模式下由叠加值还原）。"""
        y = self._y_at(index)
        if y is None:
            return None
        base = getattr(self, "_stack_base", None) or {}
        return y - base.get(index, 0.0)

    def _to_arrays(self, data):
        """数值化 data → (x_arr|None, y_arr)；x_arr=None 表示纯数值（x=下标）。

        纯数值列表 / [x, y] 列表走 numpy 快速路径；含字典 / None / 混合
        等复杂形式返回 (None, None)，由调用方回退 Python 路径。
        """
        n = len(data)
        if n == 0 or _ds.np is None:
            return None, None
        try:
            arr = _ds.np.asarray(data, dtype=_ds.np.float64)
        except (TypeError, ValueError, OverflowError):
            return None, None
        if arr.ndim == 1:
            return None, arr
        if arr.ndim == 2 and arr.shape[1] >= 2:
            return arr[:, 0], arr[:, 1]
        return None, None

    def _load_data(self):
        """解析当前 data 到 numpy / Python 双路径，并填充取值缓存。"""
        data = self._stacked_data() or self.dataView()
        self._data_len = len(data)
        # 身份判据：``is``（配合 ``_data_ref`` 强引用）+ **长度**。两者都要：
        # - 只比 ``is``：原地增长（appendData 之类先 extend 同一 list）会漏判，
        #   numpy 视图停留在旧长度上，新点画不出来；
        # - 只比 ``(id, len)``：id 在对象回收后会被复用，可能把上一份数据的
        #   numpy 视图当成当前的（``_data_ref`` 强引用从根上排除这一类）。
        if data is not self._data_ref or self._data_len != self._cached_len:
            self._np_x = self._np_y = None
            self._y_vals = []
            self._x_vals = []
            x_arr, y_arr = self._to_arrays(data)
            if y_arr is not None and x_arr is None:
                # 纯数值数据：x = 下标（供窗口过滤 / 采样使用）
                x_arr = _ds.np.arange(len(data), dtype=_ds.np.float64)
            self._np_x, self._np_y = x_arr, y_arr
            if self._np_y is None:
                # 回退：逐项解析（数据量通常较小）
                for i, item in enumerate(data):
                    x, y = parseDataPoint(item, i)
                    self._x_vals.append(x)
                    self._y_vals.append(y)
            self._np_cache_key = (id(data), len(data))
            self._data_ref = data
            self._cached_len = self._data_len
        self._sampled = False
        self._prev_pts_map = None

    def _y_at(self, i):
        """原始第 i 个数据的 y 值（None 表示缺失）。"""
        if i < 0 or i >= self._data_len:
            return None
        if self._np_y is not None:
            v = float(self._np_y[i])
            return v if math.isfinite(v) else None
        return self._y_vals[i]

    def _x_at(self, i):
        """原始第 i 个数据的 x 值。"""
        if i < 0 or i >= self._data_len:
            return None
        if self._np_x is not None:
            return float(self._np_x[i])
        if self._np_y is not None:
            return float(i)  # 纯数值：x = 下标
        return self._x_vals[i]

    # -- 采样参数 ---------------------------------------------------------
    def _sampling_params(self):
        """``sampling``：ECharts 字符串（``lttb`` / ``average`` / ``min`` /
        ``max`` / ``minmax`` / ``sum``）或扩展 dict
        {``algorithm``, ``threshold``, ``pointsPerPixel``}；False 关闭。"""
        sopt = self.opt.get("sampling", True)
        enabled = bool(sopt) and _ds.available()
        threshold = 2000.0
        ppb = 2.0
        algo = "minmax"
        if isinstance(sopt, str):
            name = sopt.strip().lower()
            if name in ("false", "none", "off"):
                enabled = False
            elif name:
                algo = name
        elif isinstance(sopt, dict):
            threshold = _to_float(sopt.get("threshold"), threshold)
            ppb = _to_float(sopt.get("pointsPerPixel"), ppb)
            algo = str(sopt.get("algorithm") or algo)
        return enabled, max(2.0, threshold), max(0.5, ppb), algo

    def _window_indices(self, coord, x_arr):
        """当前绘图范围（x 数值轴窗口）内的原始下标数组。

        仅 grid 直角坐标 + value 型 x 轴支持范围裁剪；其余返回全量下标。
        """
        if (
            x_arr is None
            or not isinstance(coord, GridCoord)
            or coord.x_axis.type != "value"
        ):
            return None
        lo, hi = coord.x_axis.vmin, coord.x_axis.vmax
        return _ds.np.flatnonzero((x_arr >= lo) & (x_arr <= hi))

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        coord = self.chart.coordFor(self.opt)
        self._prev_points = list(self._points)
        self._points = []
        self._point_idx = []
        if coord is None:
            return
        self._load_data()
        single = getattr(coord, "kind", "") == "singleAxis"

        # 采样决策：grid value-x + numpy 数据 + 启用 + 超阈值
        enabled, threshold, ppb, algo = self._sampling_params()
        plot_w = coord.plot.width() if isinstance(coord, GridCoord) else 0.0
        window_idx = (
            self._window_indices(coord, self._np_x) if self._np_x is not None else None
        )

        if window_idx is not None:
            n_win = len(window_idx)
            # 下界按算法取（``_ds.min_out_for``）：``max(2, ...)`` 造出的
            # ``n_out == 2`` 会让 minmax / m4 / lttb 全部 Rust panic。
            n_out = max(_ds.min_out_for(algo), int(plot_w * ppb))
            # 缓存键必须包含两项身份信息：
            # ① **数据身份** —— 否则「换成等长的另一份数据」会得到完全相同的键
            #    而跳过重算，用旧数据的采样下标去画新数据（尖峰错位 / 漏点）。
            #    这里用 ``_load_data`` 刚刷新过的 ``_np_cache_key``（含 id+len）。
            # ② **窗口范围** —— 缩放 / 平移后窗口内点数可能不变（n_win 相同），
            #    但采样点集必须按新窗口重新计算。
            lo, hi = coord.x_axis.vmin, coord.x_axis.vmax
            cache_key = (
                self._np_cache_key,
                self._data_len,
                n_out,
                algo,
                threshold,
                lo,
                hi,
            )
            if self._sample_cache_key != cache_key:
                yf = self._np_y[window_idx]
                if enabled and n_win > threshold:
                    idx_local = _ds.downsample_indices(
                        self._np_x[window_idx], yf, n_out, algo
                    )
                    if idx_local is not None:
                        self._sample_indices = window_idx[idx_local]
                    else:
                        self._sample_indices = window_idx
                else:
                    self._sample_indices = window_idx
                self._sample_cache_key = cache_key
            sel = self._sample_indices
            if sel is not None:
                sel = sel.tolist()
            self._sampled = (enabled and n_win > threshold and sel is not None) and len(
                sel
            ) < n_win
        else:
            # 无范围裁剪（category / polar / singleAxis / 非数值数据）：
            # 数据量=类别数的场景不采样，全量映射
            sel = None

        if sel is None:
            sel = list(range(self._data_len))

        for orig in sel:
            yi = self._y_at(orig)
            if yi is None:
                self._points.append(None)
                self._point_idx.append(orig)
                continue
            try:
                if single:
                    self._points.append(coord.mapPoint(yi))
                else:
                    self._points.append(coord.mapPoint(self._x_at(orig), yi))
            except Exception:
                self._points.append(None)
            self._point_idx.append(orig)

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
        """按 smooth / step 构建一段折线路径。seg: [QPointF]（≥1）。"""
        step = str(self.opt.get("step") or "")
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
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            return path, pts
        if smooth and len(seg) >= 2:
            k = (
                smooth
                if isinstance(smooth, (int, float)) and not isinstance(smooth, bool)
                else 0.5
            )
            return _smooth_path(seg, k), seg
        path = QPainterPath(seg[0])
        for pt in seg[1:]:
            path.lineTo(pt)
        return path, seg

    def _baseline_y(self, coord):
        """面积填充基线（grid：0 值线收敛到 plot 内）。"""
        if isinstance(coord, GridCoord):
            ax = coord.y_axis
            v = min(max(0.0, ax.vmin), ax.vmax) if ax.type == "value" else 0.0
            return ax.map(v, coord.plot.bottom(), coord.plot.top())
        return None

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        pts = self._animated_points(anim_t)
        valid = [pt for pt in pts if pt is not None]
        if not valid:
            return
        coord = self.chart.coordFor(self.opt)
        color = self.color()
        ls = self.opt.get("lineStyle") or {}
        width = _to_float(ls.get("width"), 2.0)
        if isinstance(ls.get("color"), str) and ls["color"]:
            color = QColor(ls["color"])
        polar = getattr(coord, "kind", "") == "polar"
        # 大数据（超采样阈值）：QPainterPath / drawPolyline 对陡峭线段序列
        # （minmax 保形锯齿）的光栅化会退化到每段 ~1ms（1856 段可达秒级），
        # 逐条 drawLine 仅 ~10ms —— 此处对 heavy 数据改用逐段直线绘制；
        # smooth / step 在 heavy 时退化为直线（ECharts 大数据同策略）
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
        for pos, pt in enumerate(pts):
            if pt is None:
                if seg:
                    segs.append((seg, seg_base))
                    seg, seg_base = [], []
            else:
                seg.append(pt)
                seg_base.append(base_pts[pos] if base_pts is not None else None)
        if seg:
            segs.append((seg, seg_base))

        p.save()
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)

        # 面积填充（先填充后描线）
        area = self.opt.get("areaStyle")
        if area:
            opacity = 0.22
            if isinstance(area, dict):
                opacity = _to_float(area.get("opacity"), 0.22)
            base_y = self._baseline_y(coord)
            for seg_pts, seg_bases in segs:
                if len(seg_pts) < 2:
                    continue
                if heavy:
                    # 逐段直线构成的多边形填充
                    fill = QPainterPath(seg_pts[0])
                    for pt in seg_pts[1:]:
                        fill.lineTo(pt)
                else:
                    fill = QPainterPath(self._line_path(seg_pts)[0])
                if polar:
                    fill.lineTo(coord.center)
                    fill.closeSubpath()
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(with_alpha(color, 255 * opacity))
                    p.drawPath(fill)
                    continue
                if seg_bases and all(b is not None for b in seg_bases):
                    # stack：沿基线曲线回填（ECharts 堆叠面积语义）
                    fill.lineTo(seg_bases[-1])
                    for base_pt in reversed(seg_bases[:-1]):
                        fill.lineTo(base_pt)
                    bottom = max(pt.y() for pt in seg_bases)
                elif base_y is not None:
                    fill.lineTo(QPointF(seg_pts[-1].x(), base_y))
                    fill.lineTo(QPointF(seg_pts[0].x(), base_y))
                    bottom = base_y
                else:
                    continue
                fill.closeSubpath()
                top = min(pt.y() for pt in seg_pts)
                raw_area_color = area.get("color") if isinstance(area, dict) else None
                if isinstance(raw_area_color, dict):
                    grad = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
                    for stop in raw_area_color.get("colorStops") or []:
                        try:
                            grad.setColorAt(
                                _clamp(_to_float(stop.get("offset"), 0.0), 0.0, 1.0),
                                QColor(stop.get("color")),
                            )
                        except Exception:
                            continue
                    brush = grad
                elif isinstance(raw_area_color, str) and raw_area_color:
                    brush = with_alpha(QColor(raw_area_color), 255 * opacity)
                else:
                    grad = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
                    grad.setColorAt(0.0, with_alpha(color, 255 * opacity))
                    grad.setColorAt(1.0, with_alpha(color, 0))
                    brush = grad
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(brush)
                p.drawPath(fill)

        # 折线本体
        pen = QPen(color, width)
        if heavy:
            # 大数据逐段 drawLine：RoundCap 每段圆头光栅化慢 5 倍，
            # 密集线段下不可见，改用默认 FlatCap / BevelJoin
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.BevelJoin)
        else:
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
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
            if heavy:
                for a, b in zip(seg_pts, seg_pts[1:]):
                    p.drawLine(a, b)
            else:
                path, _ = self._line_path(seg_pts)
                if polar:
                    path.closeSubpath()
                p.drawPath(path)

        # 数据点符号：小数据全画；大数据（超阈值）时隔点绘制形状，
        # 避免逐点椭圆开销（ECharts 大数据下同样会退化符号绘制）。
        # ECharts 语义：``circle`` 为实心、``emptyCircle``（默认）为空心。
        symbol_name = str(self.opt.get("symbol") or "emptyCircle")
        if symbol_name != "none" and bool(self.opt.get("showSymbol", True)):
            r = max(1.0, _to_float(self.opt.get("symbolSize"), 6.0) / 2)
            r *= max(0.2, anim_t)
            hover = self.chart.hoverInfo()
            hovered = (
                hover[1].get("dataIndex")
                if hover is not None and hover[0] is self
                else None
            )
            show_label = self.labelShown()
            if show_label:
                font = chartFont(self.labelFontSize())
                p.setFont(font)
                fm = QFontMetricsF(font)
            if heavy:
                interval = 500
                single = getattr(coord, "kind", "") == "singleAxis"
                sym_items = [
                    (None, pt) for pt in self._symbol_points(coord, single, interval)
                ]
            else:
                sym_items = [
                    (orig, pt)
                    for pt, orig in zip(self._points, self._point_idx)
                    if pt is not None
                ]
            hollow = symbol_name in ("emptyCircle", "circle")
            kind = "circle" if hollow else symbol_name
            # 循环外解析一次统一外观（None = 存在 per-item itemStyle）
            uni = self.uniformItemStyleResolved()
            uni_color = (
                (uni["color"] or self.chart.colorForSeries(self)) if uni else None
            )
            for orig, pt in sym_items:
                if uni is not None:
                    item_color = QColor(uni_color)
                    alpha = uni["opacity"]
                    border_color, border_w = uni["borderColor"], uni["borderWidth"]
                else:
                    item_color = QColor(self.itemColor(orig))
                    alpha = self.itemOpacity(orig)
                    border_color, border_w = self.itemBorder(orig)
                rr = r
                if hovered is not None:
                    if orig == hovered:
                        rr = r * 1.3
                        emphasis = self.emphasisColor(orig)
                        if emphasis is not None:
                            item_color = emphasis
                        if border_color is None:
                            border_color = item_color.lighter(115)
                            border_w = max(border_w, 1.5)
                    else:
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
                    drawSymbol(p, kind, pt, rr * 2)
                if show_label and orig is not None:
                    text = self.labelText(orig, self._raw_value(orig), self._x_at(orig))
                    p.setPen(self.labelColor())
                    p.drawText(
                        QPointF(
                            pt.x() - fm.horizontalAdvance(text) / 2, pt.y() - rr - 4
                        ),
                        text,
                    )
        p.restore()

    def _symbol_points(self, coord, single, interval: int):
        """按原始数据下标间隔取符号点（对齐「每 N 个点画一个形状」）。

        从原始序列每 ``interval`` 个数据点取一个并映射到屏幕坐标；
        数值 x 轴仅保留当前绘图窗口（vmin..vmax）内的点。
        """
        pts = []
        lo = hi = None
        if isinstance(coord, GridCoord) and coord.x_axis.type == "value":
            lo, hi = coord.x_axis.vmin, coord.x_axis.vmax
        for i in range(0, self._data_len, interval):
            yi = self._y_at(i)
            if yi is None:
                continue
            xi = self._x_at(i)
            if lo is not None:
                if not isinstance(xi, (int, float)) or not (lo <= xi <= hi):
                    continue
            try:
                pts.append(coord.mapPoint(yi) if single else coord.mapPoint(xi, yi))
            except Exception:
                continue
        return pts

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        best = None
        best_d = 10.0  # 命中半径 px
        # 动画期用「画出来的那份」折线点（与 ``paint`` 同一份插值），
        # 否则会命中动画终点位置上的点 —— 视觉上完全对不上。
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

    def valueAtIndex(self, index: int):
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        if not isinstance(idx, int) or not (0 <= idx < self._data_len):
            return None
        y = self._raw_value(idx)
        if y is None:
            return None
        # 命中点坐标：精确下标优先，否则取采样集中最近的原始下标
        pos = None
        if self._point_idx:
            try:
                best_i = min(
                    range(len(self._point_idx)),
                    key=lambda k: abs(self._point_idx[k] - idx),
                )
                pos = self._points[best_i]
            except Exception:
                pos = None
        return {"name": self.name, "value": y, "series": self.name, "pos": pos}


# ---------------------------------------------------------------------------
# scatter 散点
# ---------------------------------------------------------------------------


class ScatterSeriesRenderer(SeriesRenderer):
    """散点图。

    option 键：
    - ``symbolSize``: 数值 → 固定直径 px；缺省且数据带第三维时按第三维
      在本系列内线性映射到 6~24px；否则默认 8px。
    数据项：数值 / [x, y] / [x, y, size] / {"value": [...]}。
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

    def layout(self, rect: QRectF) -> None:
        self._dots = []
        coord = self.chart.coordFor(self.opt)
        if coord is None:
            return
        single = getattr(coord, "kind", "") == "singleAxis"
        fixed = _to_float(self.opt.get("symbolSize"), None)
        thirds = [self._third_dim(it) for it in self.data()]
        known = [t for t in thirds if t is not None]
        zmin = min(known) if known else 0.0
        zmax = max(known) if known else 1.0
        for i, item in enumerate(self.data()):
            x, y = parseDataPoint(item, i)
            if y is None:
                continue
            try:
                pt = coord.mapPoint(y) if single else coord.mapPoint(x, y)
            except Exception:
                continue
            if fixed is not None:
                r = max(1.0, fixed / 2)
            elif thirds[i] is not None:
                span = zmax - zmin
                f = 0.5 if span == 0 else (thirds[i] - zmin) / span
                r = _lerp(6.0, 24.0, f) / 2
            else:
                r = 4.0
            self._dots.append({"pt": pt, "r": r, "value": y, "index": i, "x": x})

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._dots:
            return
        p.save()
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        kind = str(self.opt.get("symbol") or "circle")
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        show_label = self.labelShown()
        if show_label:
            font = chartFont(self.labelFontSize())
            p.setFont(font)
            p.setPen(self.labelColor())
            fm = QFontMetricsF(font)
        scale = max(0.0, anim_t)
        # 循环外解析一次统一外观（None = 存在 per-item itemStyle，走逐项查找）
        uni = self.uniformItemStyleResolved()
        uni_color = (uni["color"] or self.chart.colorForSeries(self)) if uni else None
        for d in self._dots:
            index = d["index"]
            r = d["r"] * scale
            if r <= 0:
                continue
            if uni is not None:
                color = QColor(uni_color)
                alpha = uni["opacity"]
                border_color, border_w = uni["borderColor"], uni["borderWidth"]
            else:
                color = QColor(self.itemColor(index))
                alpha = self.itemOpacity(index)
                border_color, border_w = self.itemBorder(index)
            if hovered is not None:
                if index == hovered:
                    r *= 1.25
                    emphasis = self.emphasisColor(index)
                    if emphasis is not None:
                        color = emphasis
                    if border_color is None:
                        border_color = color.lighter(115)
                        border_w = max(border_w, 1.4)
                else:
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.35
            p.setBrush(with_alpha(color, int(190 * alpha)))
            p.setPen(
                QPen(border_color or with_alpha(color, int(230 * alpha)), border_w or 1)
            )
            if alpha <= 0.02:
                continue
            drawSymbol(p, kind, d["pt"], r * 2)
            if show_label:
                text = self.labelText(index, d["value"], formatValue(d["x"]))
                anchor = QPointF(
                    d["pt"].x() - fm.horizontalAdvance(text) / 2,
                    d["pt"].y() - r - 4,
                )
                p.setPen(self.labelColor())
                p.drawText(anchor, text)
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        best = None
        best_d = 1e9
        # 散点的入场动画只缩半径、不挪位置（见 ``paint`` 的 ``r = d["r"] * scale``），
        # 所以命中位置始终正确；这里只把半径也按同一系数缩，让命中范围与
        # 画出来的大小一致（否则动画中「点得到但看不见」）。
        scale = max(0.0, self._anim_t)
        for d in self._dots:
            dist = math.hypot(d["pt"].x() - pos.x(), d["pt"].y() - pos.y())
            if dist <= max(d["r"] * scale, 4.0) + 3 and dist < best_d:
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
        for d in self._dots:
            if d["index"] == idx:
                return {
                    "name": self.name,
                    "value": d["value"],
                    "series": self.name,
                    "pos": d["pt"],
                }
        return None


# ---------------------------------------------------------------------------
# heatmap 热力图
# ---------------------------------------------------------------------------


class HeatmapSeriesRenderer(SeriesRenderer):
    """热力图。

    - Grid 直角热力：xAxis / yAxis 均为 category，数据项 [x, y, value]
      （x/y 为类别名或下标），按 band 填格；
    - 日历热力：``coordinateSystem: "calendar"``，数据项 [日期, value]，
      GitHub 风格逐格填充（无数据日也铺浅色底格，属引擎扩展）。
      ``calendar.itemStyle``（color / borderColor / borderWidth / borderRadius）
      控制空日底色与格子间距圆角。

    数据项可携带 ECharts 风格 tooltip：``{"value": [日期, 值],
    "tooltip": {"formatter": "557万 tokens · 4轮消息"}}``（formatter 支持
    字符串模板或 callable(params)，命中时优先于系列 ``tooltip.formatter``）。

    色带：默认 ``color.primary.subtle`` → ``color.primary`` 按值线性插值；
    option 含 ``visualMap``（顶层）时按 ``visualMap.min/max`` 与
    ``visualMap.inRange.colors`` 映射。
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
        """→ (colors, vmin, vmax)：visualMap 优先，否则默认色带 + 数据范围。"""
        vm = self.chart._option_ref().get("visualMap")
        colors = None
        vmin = vmax = None
        if isinstance(vm, dict):
            in_range = vm.get("inRange") or {}
            if isinstance(in_range.get("colors"), list) and in_range["colors"]:
                colors = in_range["colors"]
            vmin = _to_float(vm.get("min"), None)
            vmax = _to_float(vm.get("max"), None)
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
            color = QColor(raw_empty)
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
        data_index = 0
        for day in coord.iterDates():
            rect = coord.cellRect(day)
            if rect.isNull():
                continue
            cell = rect.adjusted(gap, gap, -gap, -gap)
            entry = data_map.get(day)
            if entry is None:
                cells.append(
                    {
                        "index": data_index,
                        "rect": cell,
                        "value": None,
                        "label": day.isoformat(),
                        "color": self._empty_color,
                        "title": day.isoformat(),
                        "tooltipFormatter": None,
                        "empty": True,
                    }
                )
                data_index += 1
                continue
            value, text, item_style = entry
            t = 0.5 if span == 0 else (value - vmin) / span
            raw = item_style.get("color")
            color = (
                QColor(raw) if isinstance(raw, str) and raw else _ramp_color(colors, t)
            )
            border_color, border_w = self.itemBorder(data_index)
            if border_color is None and border_w <= 0:
                raw_border = item_style.get("borderColor")
                try:
                    raw_width = float(item_style.get("borderWidth", 0))
                except (TypeError, ValueError, OverflowError):
                    raw_width = 0.0
                if isinstance(raw_border, str) and raw_border:
                    border_color = QColor(raw_border)
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
            for x, _y, val, text, style in items:
                day = coord._parse_date(x)
                if day is not None:
                    data_map[day] = (val, text, style)
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
            font = chartFont(self.labelFontSize())
            p.setFont(font)
            fm = QFontMetricsF(font)
            label_color = self.labelColor()
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
                    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def _cell_fill_color(self, cell: dict, hovered, anim_t: float) -> QColor:
        """单元格填充色：仅命中格加亮，其余保持原样（不做整图淡化）。

        ``emphasis.itemStyle.color`` 可覆盖命中格颜色（ECharts 语义）。
        """
        index = cell.get("index")
        if hovered is not None and index == hovered:
            emphasis = self.emphasisColor(index)
            color = (
                QColor(emphasis)
                if emphasis is not None
                else QColor(cell["color"]).lighter(112)
            )
        else:
            color = QColor(cell["color"])
            blur = self.blurOpacity()
            if hovered is not None and blur is not None:
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


# ---------------------------------------------------------------------------
# pictorialBar 象形柱图
# ---------------------------------------------------------------------------


class PictorialBarSeriesRenderer(BarSeriesRenderer):
    """象形柱图：以小图形（symbol）填充柱体。

    option 键：
    - ``symbol``: "rect" | "circle" | "pin"（默认 "rect"）；
    - ``symbolRepeat``: True 时按 symbolSize 沿柱方向重复堆叠小图形直至
      柱顶；整数时为固定重复次数（在柱长内均布）；
    - ``symbolSize``: 数值（边长）或 [宽, 高]。
    不支持 stack（同名槽位逻辑退化为各占一槽）。
    """

    def _stack_bases(self):  # 象形柱不堆叠
        return {}, {}

    def _symbol_size(self):
        ss = self.opt.get("symbolSize", 10)
        if isinstance(ss, (list, tuple)) and ss:
            w = _to_float(ss[0], 10.0)
            h = _to_float(ss[1], w) if len(ss) > 1 else w
            return max(2.0, w), max(2.0, h)
        v = _to_float(ss, 10.0)
        return max(2.0, v), max(2.0, v)

    def _draw_symbol(self, p, cx, cy, w, h):
        """以 (cx, cy) 为中心绘制一个小图形（w×h 外接框）。"""
        kind = str(self.opt.get("symbol") or "rect")
        r = min(w, h) / 2
        if kind == "circle":
            p.drawEllipse(QPointF(cx, cy), w / 2, h / 2)
        elif kind == "pin":
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy - h * 0.12), r, r)
            path.moveTo(cx - r * 0.55, cy + h * 0.12)
            path.lineTo(cx, cy + h * 0.52)
            path.lineTo(cx + r * 0.55, cy + h * 0.12)
            path.closeSubpath()
            p.drawPath(path)
        else:  # rect
            p.drawRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), 2, 2)

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._bars:
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        val_axis = coord.x_axis if self._horizontal else coord.y_axis
        sw, sh = self._symbol_size()
        repeat = self.opt.get("symbolRepeat", False)
        p.save()
        p.setClipRect(coord.plot)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color())
        for bar in self._bars:
            y_t = self._animated_value(bar, anim_t)
            v1 = bar["v0"] + y_t
            if self._horizontal:
                pa = val_axis.map(bar["v0"], coord.plot.left(), coord.plot.right())
                pb = val_axis.map(v1, coord.plot.left(), coord.plot.right())
                along, cross = sw, sh
            else:
                pa = val_axis.map(bar["v0"], coord.plot.bottom(), coord.plot.top())
                pb = val_axis.map(v1, coord.plot.bottom(), coord.plot.top())
                along, cross = sh, sw
            direction = 1.0 if pb >= pa else -1.0
            total = abs(pb - pa)
            if total <= 0:
                continue
            if repeat is True:
                n = max(1, int(total // max(1.0, along)))
                offsets = [(k + 0.5) * along for k in range(n)]
                offsets = [o for o in offsets if o <= total] or [total / 2]
            elif repeat:
                n = max(1, int(_to_float(repeat, 1)))
                offsets = [(k + 0.5) * total / n for k in range(n)]
            else:
                offsets = [max(along / 2, total - along / 2)]
            for off in offsets:
                d = pa + direction * off
                if self._horizontal:
                    self._draw_symbol(p, d, bar["center"], along, cross)
                else:
                    self._draw_symbol(p, bar["center"], d, cross, along)
        p.restore()


# ---------------------------------------------------------------------------
# effectScatter 涟漪散点
# ---------------------------------------------------------------------------


class EffectScatterSeriesRenderer(ScatterSeriesRenderer):
    """涟漪散点：散点 + QTimer 驱动的扩散圆动画。

    option 键：
    - ``rippleEffect``: {``period`` 秒（默认 3）、``scale`` 扩散倍数（默认 2.6）、
      ``brushType``（``"fill"`` 默认 / ``"stroke"``）、``number`` 同时可见环数}；
    - 其余同 scatter（symbolSize / 第三维映射）。

    动画生命周期：QTimer 以 chart 为 parent，随控件销毁；回调经 weakref
    持有渲染器，渲染器被替换（setOption 重建）后回调自动停止并
    deleteLater，不泄漏。仅系列可见时推进（隐藏后定时器暂停、重新显示时
    经 ``_on_visible_changed`` 恢复，不空转）。
    """

    _TICK_MS = 40

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._phase = 0.0
        ripple = self.opt.get("rippleEffect") or {}
        if not isinstance(ripple, dict):
            ripple = {}
        self._period = max(0.2, _to_float(ripple.get("period"), 3.0))
        self._scale = max(1.2, _to_float(ripple.get("scale"), 2.6))
        #: 每点同时可见的涟漪环数（ECharts rippleEffect.number，默认 3）
        self._number = max(1, min(8, int(_to_float(ripple.get("number"), 3))))
        #: 波纹绘制方式：fill（默认）/ stroke（ECharts brushType）
        brush = str(ripple.get("brushType") or "fill").lower()
        self._brush = "stroke" if brush == "stroke" else "fill"
        timer = QTimer(chart)  # parent 挂 ChartWidget，随控件销毁
        timer.setInterval(self._TICK_MS)
        # 绑定方法插槽：不用 lambda（闭包签名 / 引用存活都要自己盯，而槽内异常
        # 在 Qt 回调里就是 0xC0000409 静默终止）
        timer.timeout.connect(self._on_timer)
        # 持续动效：Reduced/Disabled 下不扩散。相位冻结在当前值 —— 点仍在、
        # 只是不扩散，所以不需要摆姿态钩子。
        start_idle_loop(timer, self._TICK_MS)
        self._timer = timer

    def _stop_timer(self) -> None:
        """停止并释放定时器（渲染器被替换 / 图表销毁 / 异常时调用）。"""
        timer = getattr(self, "_timer", None)
        self._timer = None
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass

    def _on_timer(self) -> None:
        """定时器回调（整体包裹：Qt 回调中的异常会终止进程）。"""
        timer = self._timer
        if timer is None:
            return
        try:
            alive = self in self.chart.seriesRenderers
        except RuntimeError:
            alive = False  # chart 已销毁
        if not alive:
            self._stop_timer()
            return
        if not self.visible:
            if timer.isActive():
                timer.stop()  # 隐藏不空转；重新显示经 _on_visible_changed 恢复
            return
        if not timer.isActive():
            timer.start()
        try:
            self._tick()
        except Exception:
            self._stop_timer()

    def _tick(self):
        """推进涟漪相位并请求重绘（测试可手动调用）。"""
        self._phase = (self._phase + self._TICK_MS / (self._period * 1000.0)) % 1.0
        self.chart.update()

    def stopAnimation(self) -> None:
        """停止涟漪定时器并释放（渲染器不再需要动画时调用，如测试收尾）。

        定时器 parent 为 chart，chart 销毁时自动释放；本方法用于 chart
        仍存活但渲染器不再需要动画的场景，避免活动 QTimer 在事件循环
        处理时对已删除对象发起重绘。
        """
        self._stop_timer()

    def _on_visible_changed(self):
        """显隐变化钩子（core 内部调用）：显示恢复时重启定时器。

        **必须走 ``start_idle_loop`` 而不是裸 ``timer.start()``**：裸 start
        绕过动效策略，于是「Reduced/Disabled 下持续动效停掉」被图例切换
        重新打开 —— 无障碍用户看到涟漪照常扩散。而 ``start_idle_loop`` 是幂等的
        （内部先查 ``isActive()``）、守策略、且无论启不启动都会写 interval。
        """
        if self.visible and self._timer is not None and not self._timer.isActive():
            start_idle_loop(self._timer, self._TICK_MS)

    def paint(self, p: QPainter, anim_t: float) -> None:
        super().paint(p, anim_t)
        if not self._dots:
            return
        p.save()
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        # 多环涟漪：相位错开（首帧即有可见扩散环），ECharts rippleEffect 语义
        for d in self._dots:
            color = self.itemColor(d["index"])
            opacity = self.itemOpacity(d["index"])
            r0 = max(d["r"], 3.0)
            for k in range(self._number):
                phase = (self._phase + k / self._number) % 1.0
                rr = r0 * (1.0 + phase * (self._scale - 1.0))
                alpha = 140 * (1.0 - phase) * opacity
                if alpha <= 2:
                    continue
                if self._brush == "stroke":
                    p.setPen(QPen(with_alpha(color, int(alpha)), 1.6))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                else:  # fill（ECharts brushType 默认）
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(with_alpha(color, int(alpha * 0.55)))
                p.drawEllipse(d["pt"], rr, rr)
        p.restore()


# ---------------------------------------------------------------------------
# candlestick K线
# ---------------------------------------------------------------------------


class CandlestickSeriesRenderer(SeriesRenderer):
    """K线（OHLC）。数据项：[开, 收, 最低, 最高]（或 {"value": [...]}）。

    配色遵循 ECharts 默认（红涨绿跌）：``itemStyle.color``（涨）/ ``color0``（跌）、
    ``itemStyle.borderColor`` / ``borderColor0``；缺省涨用 ``color.danger``、
    跌用 ``color.success``（与库主题语义一致）。

    option 键：``barWidth``（实体宽 px，缺省为 band 的 60%，上限 24）；
    setOption 同长度数据逐值插值。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._items = []  # [dict(cx, open, close, low, high, w, x, index, prev)]

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._items = []
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        _fix_value_axis(coord.y_axis, self.chart)
        band = coord.x_axis.bandWidth(coord.plot.left(), coord.plot.right())
        if band <= 0:
            band = coord.plot.width() / max(1, len(self.data()))
        w = _to_float(self.opt.get("barWidth"), None)
        w = max(3.0, min(w, band * 0.9)) if w else min(band * 0.6, 24.0)
        prev = self.prev_data if isinstance(self.prev_data, list) else None
        for i, item in enumerate(self.data()):
            nums = _datum_list(item)
            if not nums or len(nums) < 4:
                continue
            o, c, lo, hi = nums[0], nums[1], nums[2], nums[3]
            x = i  # OHLC 数组不含类别，按下标对位 xAxis 类别
            cx = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
            prev_nums = None
            if prev is not None and i < len(prev):
                prev_nums = _datum_list(prev[i])
            self._items.append(
                {
                    "cx": cx,
                    "open": o,
                    "close": c,
                    "low": lo,
                    "high": hi,
                    "w": w,
                    "x": x,
                    "index": i,
                    "prev": prev_nums[:4]
                    if prev_nums and len(prev_nums) >= 4
                    else None,
                }
            )

    # -- 配色（ECharts itemStyle 语义：color=涨 / color0=跌） ---------------
    def _up_color(self):
        style = self.itemStyle()
        c = style.get("color") or style.get("borderColor")
        return QColor(c) if isinstance(c, str) and c else QColor(T("color.danger"))

    def _down_color(self):
        style = self.itemStyle()
        c = style.get("color0") or style.get("borderColor0")
        return QColor(c) if isinstance(c, str) and c else QColor(T("color.success"))

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._items:
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        ax = coord.y_axis
        up, down = self._up_color(), self._down_color()
        p.save()
        p.setClipRect(coord.plot)
        for it in self._items:
            if it["prev"] is not None and anim_t < 1.0:
                o, c, lo, hi = (
                    _lerp(it["prev"][k], v, anim_t)
                    for k, v in enumerate(
                        (it["open"], it["close"], it["low"], it["high"])
                    )
                )
            elif anim_t < 1.0:
                # 入场：自开盘价向四周生长
                o = it["open"]
                c = _lerp(it["open"], it["close"], anim_t)
                lo = _lerp(it["open"], it["low"], anim_t)
                hi = _lerp(it["open"], it["high"], anim_t)
            else:
                o, c, lo, hi = it["open"], it["close"], it["low"], it["high"]
            yo = ax.map(o, coord.plot.bottom(), coord.plot.top())
            yc = ax.map(c, coord.plot.bottom(), coord.plot.top())
            yl = ax.map(lo, coord.plot.bottom(), coord.plot.top())
            yh = ax.map(hi, coord.plot.bottom(), coord.plot.top())
            rising = c >= o
            color = up if rising else down
            cx, w = it["cx"], it["w"]
            # 影线
            p.setPen(QPen(color, 1.2))
            p.drawLine(QPointF(cx, yh), QPointF(cx, yl))
            # 实体
            body = QRectF(cx - w / 2, min(yo, yc), w, max(1.0, abs(yc - yo)))
            p.setPen(QPen(color, 1))
            p.setBrush(color)
            p.drawRect(body)
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        ax = coord.y_axis
        for it in self._items:
            yl = ax.map(it["low"], coord.plot.bottom(), coord.plot.top())
            yh = ax.map(it["high"], coord.plot.bottom(), coord.plot.top())
            if (
                abs(pos.x() - it["cx"]) <= max(it["w"] / 2, 4.0) + 2
                and yh - 3 <= pos.y() <= yl + 3
            ):
                return {
                    "name": _axis_label(coord.x_axis, it["x"]),
                    "value": [it["open"], it["close"], it["low"], it["high"]],
                    "series": self.name,
                    "dataIndex": it["index"],
                }
        return None

    def valueAtIndex(self, index: int):
        coord = self.chart.coordFor(self.opt)
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        for it in self._items:
            if it["index"] == idx:
                pos = None
                if isinstance(coord, GridCoord):
                    yc = coord.y_axis.map(
                        it["close"], coord.plot.bottom(), coord.plot.top()
                    )
                    pos = QPointF(it["cx"], yc)
                return {
                    "name": _axis_label(coord.x_axis, it["x"]),
                    "value": it["close"],
                    "series": self.name,
                    "pos": pos,
                }
        return None


# ---------------------------------------------------------------------------
# boxplot 箱线
# ---------------------------------------------------------------------------


class BoxplotSeriesRenderer(SeriesRenderer):
    """箱线图。数据项：[min, Q1, 中位, Q3, max]（或 {"value": [...]}）。

    option 键：``barWidth``（箱体宽 px，缺省 band 的 50%，上限 28）；
    ``itemStyle``：``color``（箱体填充，缺省系列色 24% 透明）、
    ``borderColor``（描边 / 须线）、``borderWidth``。
    绘制：箱体（Q1~Q3 填充 + 描边）、中位线 + 上下须线（含端帽）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._items = []  # [dict(cx, w, vals=[5], x, index)]

    def layout(self, rect: QRectF) -> None:
        self._items = []
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        _fix_value_axis(coord.y_axis, self.chart)
        band = coord.x_axis.bandWidth(coord.plot.left(), coord.plot.right())
        if band <= 0:
            band = coord.plot.width() / max(1, len(self.data()))
        w = _to_float(self.opt.get("barWidth"), None)
        w = max(4.0, min(w, band * 0.9)) if w else min(band * 0.5, 28.0)
        for i, item in enumerate(self.data()):
            nums = _datum_list(item)
            if not nums or len(nums) < 5:
                continue
            x = i  # 五元数组不含类别，按下标对位 xAxis 类别
            cx = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
            self._items.append({"cx": cx, "w": w, "vals": nums[:5], "x": x, "index": i})

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._items:
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        ax = coord.y_axis
        color = self.color()
        style = self.itemStyle()
        fill_raw = style.get("color")
        stroke_raw = style.get("borderColor")
        stroke = (
            QColor(stroke_raw) if isinstance(stroke_raw, str) and stroke_raw else color
        )
        try:
            stroke_w = max(0.5, float(style.get("borderWidth", 1.4)))
        except (TypeError, ValueError, OverflowError):
            stroke_w = 1.4
        fill = QColor(fill_raw) if isinstance(fill_raw, str) and fill_raw else None
        if fill is not None:
            fill.setAlphaF(fill.alphaF() * 0.35)
        else:
            fill = with_alpha(color, 60)
        p.save()
        p.setClipRect(coord.plot)
        for it in self._items:
            vmin, q1, med, q3, vmax = it["vals"]
            mid = (q1 + q3) / 2
            if anim_t < 1.0:  # 入场：自箱体中线向两端展开
                vmin = _lerp(mid, vmin, anim_t)
                vmax = _lerp(mid, vmax, anim_t)
                q1 = _lerp(mid, q1, anim_t)
                q3 = _lerp(mid, q3, anim_t)
                med = _lerp(mid, med, anim_t)
            y_min = ax.map(vmin, coord.plot.bottom(), coord.plot.top())
            y_q1 = ax.map(q1, coord.plot.bottom(), coord.plot.top())
            y_med = ax.map(med, coord.plot.bottom(), coord.plot.top())
            y_q3 = ax.map(q3, coord.plot.bottom(), coord.plot.top())
            y_max = ax.map(vmax, coord.plot.bottom(), coord.plot.top())
            cx, w = it["cx"], it["w"]
            # 须线 + 端帽
            p.setPen(QPen(stroke, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(cx, y_max), QPointF(cx, y_min))
            p.drawLine(QPointF(cx - w / 4, y_min), QPointF(cx + w / 4, y_min))
            p.drawLine(QPointF(cx - w / 4, y_max), QPointF(cx + w / 4, y_max))
            # 箱体
            box = QRectF(cx - w / 2, min(y_q1, y_q3), w, max(1.0, abs(y_q3 - y_q1)))
            p.setPen(QPen(stroke, stroke_w))
            p.setBrush(fill)
            p.drawRect(box)
            # 中位线
            p.setPen(QPen(stroke, 2))
            p.drawLine(QPointF(cx - w / 2, y_med), QPointF(cx + w / 2, y_med))
        p.restore()

    def hitTest(self, pos: QPointF):
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        ax = coord.y_axis
        for it in self._items:
            y_min = ax.map(it["vals"][0], coord.plot.bottom(), coord.plot.top())
            y_max = ax.map(it["vals"][4], coord.plot.bottom(), coord.plot.top())
            if (
                abs(pos.x() - it["cx"]) <= it["w"] / 2 + 3
                and y_max - 3 <= pos.y() <= y_min + 3
            ):
                return {
                    "name": formatValue(it["x"]),
                    "value": it["vals"],
                    "series": self.name,
                    "dataIndex": it["index"],
                }
        return None

    def valueAtIndex(self, index: int):
        coord = self.chart.coordFor(self.opt)
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        for it in self._items:
            if it["index"] == idx:
                pos = None
                if isinstance(coord, GridCoord):
                    y_med = coord.y_axis.map(
                        it["vals"][2], coord.plot.bottom(), coord.plot.top()
                    )
                    pos = QPointF(it["cx"], y_med)
                return {
                    "name": _axis_label(coord.x_axis, it["x"]),
                    "value": it["vals"][2],
                    "series": self.name,
                    "pos": pos,
                }
        return None


# ---------------------------------------------------------------------------
# parallel 平行坐标
# ---------------------------------------------------------------------------


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
                        }
                    )
                else:
                    dims.append({"name": str(d), "min": None, "max": None})
            return dims, rows
        if rows and all(isinstance(x, str) for x in rows[0]):
            names = rows[0]
            return [{"name": n, "min": None, "max": None} for n in names], rows[1:]
        n = max((len(r) for r in rows), default=0)
        return [{"name": f"dim{i}", "min": None, "max": None} for i in range(n)], rows

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
            self._axes.append({"name": dim["name"], "x": x, "vmin": lo, "vmax": hi})
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
            color = QColor(line_style["color"])
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
        # 轴 + 标签
        c_axis = QColor(T("color.border.strong"))
        c_text = QColor(T("color.text.secondary"))
        font = chartFont(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        for ax in self._axes:
            p.setPen(QPen(c_axis, 1))
            p.drawLine(
                QPointF(ax["x"], self._area.top()),
                QPointF(ax["x"], self._area.bottom()),
            )
            p.setPen(c_text)
            p.drawText(
                QRectF(
                    ax["x"] - 50, self._area.top() - fm.height() - 6, 100, fm.height()
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                ax["name"],
            )
            p.drawText(
                QRectF(ax["x"] - 50, self._area.top() + 2, 100, fm.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                formatValue(ax["vmax"]),
            )
            p.drawText(
                QRectF(
                    ax["x"] - 50,
                    self._area.bottom() - fm.height() - 2,
                    100,
                    fm.height(),
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


# ---------------------------------------------------------------------------
# themeRiver 主题河
# ---------------------------------------------------------------------------


class ThemeRiverSeriesRenderer(SeriesRenderer):
    """主题河：时间 × 系列的流带图。

    数据：``[[时间, 值, 系列名], ...]``（时间为字符串，ISO 日期可排序）。
    流带平滑（贝塞尔）、居中基线（各时刻总宽关于绘图区中线对称），
    自带底部时间轴标签（约 5 个均布刻度）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._streams = []  # [dict(name, top=[QPointF], bot=[QPointF], color_idx)]
        self._times = []
        self._matrix = {}  # (name, t_idx) -> value
        self._area = QRectF()

    # -- 数据 -------------------------------------------------------------
    def _parse(self):
        times = []
        names = []
        matrix = {}
        for item in self.data():
            v = item.get("value") if isinstance(item, dict) else item
            if not isinstance(v, (list, tuple)) or len(v) < 3:
                continue
            t, val, name = v[0], _to_float(v[1], None), str(v[2])
            if val is None:
                continue
            t = str(t)
            if t not in times:
                times.append(t)
            if name not in names:
                names.append(name)
            matrix[(name, t)] = matrix.get((name, t), 0.0) + val
        times.sort()
        return times, names, matrix

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._streams = []
        self._times = []
        self._matrix = {}
        times, names, matrix = self._parse()
        if not times or not names:
            return
        self._times = times
        self._matrix = matrix
        self._area = QRectF(
            rect.left() + 24,
            rect.top() + 20,
            max(40.0, rect.width() - 48),
            max(30.0, rect.height() - 20 - 30),
        )
        n = len(times)
        xs = [self._area.left() + self._area.width() * (i + 0.5) / n for i in range(n)]
        totals = [sum(matrix.get((name, t), 0.0) for name in names) for t in times]
        max_total = max(totals) if totals else 1.0
        scale = (self._area.height() * 0.9) / max(1e-9, max_total)
        cy = self._area.center().y()
        for k, name in enumerate(names):
            top = []
            bot = []
            for i, t in enumerate(times):
                base_cum = sum(matrix.get((names[j], t), 0.0) for j in range(k))
                v = matrix.get((name, t), 0.0)
                y0 = cy - totals[i] * scale / 2 + base_cum * scale
                y1 = y0 + v * scale
                top.append(QPointF(xs[i], y0))
                bot.append(QPointF(xs[i], y1))
            self._streams.append({"name": name, "top": top, "bot": bot, "color_idx": k})

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._streams:
            return
        p.save()
        # 覆盖兜底 grid 轴线背景
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T("color.bg.base")))
        p.drawRect(
            QRectF(
                self._area.left() - 24,
                self._area.top() - 20,
                self._area.width() + 48,
                self._area.height() + 50,
            )
        )
        palette = self.chart.palette()
        grow = max(0.0, min(1.0, anim_t))
        for s in self._streams:
            color = QColor(palette[s["color_idx"] % len(palette)])
            top = []
            bot = []
            for a, b in zip(s["top"], s["bot"]):
                mid = (a.y() + b.y()) / 2
                top.append(QPointF(a.x(), mid + (a.y() - mid) * grow))
                bot.append(QPointF(b.x(), mid + (b.y() - mid) * grow))
            if len(top) >= 2:
                path = _smooth_path(top, 0.5)
                bottom_path = _smooth_path(bot, 0.5)
                # 反向拼接下缘
                rev = QPainterPath()
                elems = [
                    bottom_path.elementAt(i) for i in range(bottom_path.elementCount())
                ]
                rev.moveTo(elems[-1].x, elems[-1].y)
                i = len(elems) - 1
                while i >= 3:  # 贝塞尔段逆放（控制点交换）
                    rev.cubicTo(
                        QPointF(elems[i - 1].x, elems[i - 1].y),
                        QPointF(elems[i - 2].x, elems[i - 2].y),
                        QPointF(elems[i - 3].x, elems[i - 3].y),
                    )
                    i -= 3
                path.connectPath(rev)
                path.closeSubpath()
            else:
                path = QPainterPath()
            p.setPen(QPen(with_alpha(color, 200), 1))
            p.setBrush(with_alpha(color, 150))
            if not path.isEmpty():
                p.drawPath(path)
        # 底部时间轴标签（约 5 个均布）
        n = len(self._times)
        font = chartFont(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QColor(T("color.text.secondary")))
        tick_n = min(5, n)
        for k in range(tick_n):
            i = round(k * (n - 1) / max(1, tick_n - 1))
            x = self._area.left() + self._area.width() * (i + 0.5) / n
            p.drawText(
                QRectF(x - 60, self._area.bottom() + 8, 120, fm.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._times[i],
            )
        # 流带标签（ECharts themeRiver label：带端显示系列名）
        label_opt = dict(self.opt.get("label") or {})
        if bool(label_opt.get("show", True)) and n:
            label_font = chartFont(self.labelFontSize())
            p.setFont(label_font)
            label_fm = QFontMetricsF(label_font)
            p.setPen(self.labelColor())
            last = n - 1
            for s in self._streams:
                y0 = s["top"][last].y()
                y1 = s["bot"][last].y()
                if y1 - y0 < label_fm.height() * 0.9:
                    continue
                text = (
                    str(label_opt.get("formatter") or "").replace("{b}", s["name"])
                    or s["name"]
                )
                p.drawText(
                    QRectF(
                        self._area.left() + self._area.width() * (last + 0.5) / n - 60,
                        (y0 + y1) / 2 - label_fm.height() / 2,
                        120,
                        label_fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    text,
                )
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        if not self._streams or not self._times:
            return None
        n = len(self._times)
        # 最近时间列
        best_i = None
        best_dx = 1e9
        for i in range(n):
            x = self._area.left() + self._area.width() * (i + 0.5) / n
            if abs(pos.x() - x) < best_dx:
                best_dx = abs(pos.x() - x)
                best_i = i
        if best_i is None or best_dx > self._area.width() / n:
            return None
        for s in self._streams:
            y0 = s["top"][best_i].y()
            y1 = s["bot"][best_i].y()
            if min(y0, y1) - 2 <= pos.y() <= max(y0, y1) + 2 and y1 > y0:
                return {
                    "name": s["name"],
                    "value": self._matrix.get((s["name"], self._times[best_i]), 0.0),
                    "series": self.name,
                    "x": self._times[best_i],
                }
        return None


registerSeries("bar", BarSeriesRenderer)
registerSeries("pictorialBar", PictorialBarSeriesRenderer)
registerSeries("line", LineSeriesRenderer)
registerSeries("scatter", ScatterSeriesRenderer)
registerSeries("effectScatter", EffectScatterSeriesRenderer)
registerSeries("candlestick", CandlestickSeriesRenderer)
registerSeries("boxplot", BoxplotSeriesRenderer)
registerSeries("heatmap", HeatmapSeriesRenderer)
registerSeries("parallel", ParallelSeriesRenderer)
registerSeries("themeRiver", ThemeRiverSeriesRenderer)
