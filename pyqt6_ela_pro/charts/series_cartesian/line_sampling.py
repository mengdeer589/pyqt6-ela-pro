"""折线采样 / 窗口 / 数据准备方法组（从 ``LineSeriesRenderer`` 拆出）。"""

from __future__ import annotations


import bisect
import math


from .. import _downsample as _ds
from ..axes import GridCoord
from ..core import parseDataPoint
from ._shared import (
    _GAP_MIN_PIXELS,
    _SAMPLE_CACHE_MAX,
    _has_explicit_x,
)


class _LineSamplingMixin:
    """方法组 mixin：状态由宿主类 ``__init__`` 建立。"""

    @staticmethod
    def _stack_key(x, index):
        """堆叠对齐键：优先 x（类别名 / 数值），不可哈希时退回下标。"""
        if isinstance(x, (str, int, float)) and not isinstance(x, bool):
            return x
        return index

    def _stacked_data(self):
        """stack 模式：叠加前序同名 stack 可见系列的值（不改原始 opt）；无 stacking 返回 None。

        基线存于 ``self._stack_base``（index -> 基线值），tooltip / 标签仍按原始值展示。
        结果必须缓存：每次新建整份 list 会让下游按数据身份命中的采样缓存永不命中。
        """
        stack = self.opt.get("stack")
        if not stack:
            self._stack_base = None
            return None
        contributors = []
        for r in self.chart.seriesRenderers:
            if r is self:
                break
            # 用 mixin 作「同实现」判据：宿主类会 import 本模块，不能反向 import 造成环。
            if not isinstance(r, _LineSamplingMixin) or not r.visible:
                continue
            if str(r.opt.get("stack") or "") != str(stack):
                continue
            contributors.append(r)

        own = self.dataView()
        srcs = [r.data() for r in contributors]
        strategy = str(self.opt.get("stackStrategy") or "samesign").strip().lower()
        if strategy not in ("samesign", "all", "positive", "negative"):
            strategy = "samesign"
        key = (id(own), tuple((id(s), len(s)) for s in srcs), strategy)
        hit = self._stacked_cache
        # ``is`` 复核不能省：缓存条目不持有源数据（out 里全是新算的标量），
        # setOption 换数据后旧对象释放，新对象可能拿到同一个 id 且长度相同。
        if hit is not None and hit[0] == key and hit[1] is own and hit[2] == srcs:
            self._stack_base = hit[3]
            return hit[4]

        # stackStrategy 默认 samesign：正负分别堆叠（无条件相加会把负值加到正值基线上）。
        all_base: dict = {}
        pos_base: dict = {}
        neg_base: dict = {}
        for src in srcs:
            for i, item in enumerate(src):
                x, y = parseDataPoint(item, i)
                if y is None:
                    continue
                key_i = self._stack_key(x, i)
                all_base[key_i] = all_base.get(key_i, 0.0) + y
                bucket = pos_base if y >= 0 else neg_base
                bucket[key_i] = bucket.get(key_i, 0.0) + y

        def base_for(key_i, y):
            if strategy == "all":
                return all_base.get(key_i, 0.0)
            if strategy == "positive":
                return pos_base.get(key_i, 0.0) if y >= 0 else 0.0
            if strategy == "negative":
                return neg_base.get(key_i, 0.0) if y < 0 else 0.0
            return (pos_base if y >= 0 else neg_base).get(key_i, 0.0)

        self._stack_base = {}
        if not all_base:
            self._stacked_cache = (key, own, srcs, self._stack_base, None)
            return None
        out = []
        for i, item in enumerate(own):
            x, y = parseDataPoint(item, i)
            if y is None:
                out.append(item)
                continue
            base = base_for(self._stack_key(x, i), y)
            if base:
                self._stack_base[i] = base
            stacked = y + base
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

        纯数值 / [x, y] 序列走 numpy，含字典 / None / 混合形态返回 (None, None)。
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
        # 身份判据 = ``is``（配 ``_data_ref`` 强引用）+ 长度：只比 is 会漏掉原地
        # 增长（numpy 视图停在旧长度），只比 (id, len) 会撞 id 复用。
        if data is not self._data_ref or self._data_len != self._cached_len:
            self._np_x = self._np_y = None
            self._y_vals = []
            self._x_vals = []
            pure_index = False
            x_arr, y_arr = self._to_arrays(data)
            if y_arr is not None and x_arr is None:
                # 纯数值数据：x = 下标（供窗口过滤 / 采样使用）
                x_arr = _ds.np.arange(len(data), dtype=_ds.np.float64)
                pure_index = True
            if y_arr is not None and _ds.available():
                # tsdownsample 只吃 C 连续数组：2D 输入取出的列视图会被静默拒绝，
                # 每次都掉进 numpy 兜底。按数据身份一次性转连续副本。
                if not x_arr.flags["C_CONTIGUOUS"]:
                    x_arr = _ds.np.ascontiguousarray(x_arr)
                if not y_arr.flags["C_CONTIGUOUS"]:
                    y_arr = _ds.np.ascontiguousarray(y_arr)
            self._np_x, self._np_y = x_arr, y_arr
            # x 时间基一次性分析（单调性 / 步长 / 记录中断位置），供 searchsorted
            # 窗口与 gap 插入使用；纯数值数据（x = 下标）无需扫描。
            self._np_x_monotone = self._np_x_strict = False
            self._np_step = 0.0
            self._np_gap_pos = None
            self._np_gap_dur = None
            if y_arr is not None and x_arr is not None:
                if pure_index:
                    self._np_x_monotone = self._np_x_strict = True
                    self._np_step = 1.0
                else:
                    (
                        self._np_x_monotone,
                        self._np_x_strict,
                        self._np_step,
                        self._np_gap_pos,
                        self._np_gap_dur,
                    ) = _ds.analyze_x(x_arr)
            if self._np_y is None:
                # 回退：逐项解析（数据量通常较小）
                coord = self.chart.coordFor(self.opt)
                axis = getattr(coord, "x_axis", None)
                time_axis = bool(getattr(axis, "is_time", False))
                for i, item in enumerate(data):
                    x, y = parseDataPoint(item, i)
                    if time_axis and _has_explicit_x(item):
                        x = axis.toNumber(x)
                    self._x_vals.append(x)
                    self._y_vals.append(y)
                # 全数值且有序时窗口裁剪走 bisect（O(log n)）。
                prev = None
                ordered = True
                for x in self._x_vals:
                    if not isinstance(x, (int, float)) or isinstance(x, bool):
                        ordered = False
                        break
                    if prev is not None and x < prev:
                        ordered = False
                        break
                    prev = x
                self._py_x_sorted = ordered
            self._py_window_key = None
            self._py_window_cache = None
            self._win_cache_key = None
            self._win_cache = None
            self._sample_lru.clear()
            self._full_sample_key = None
            self._nearest_x_sorted = None
            self._nearest_index_sorted = None
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

    def _plot_pixel_width(self, coord) -> float:
        """「每像素目标点数」用的像素宽度（非 grid 坐标退化为画布宽度）。"""
        if isinstance(coord, GridCoord):
            width = float(coord.plot.width())
            if width > 0:
                return width
        return float(max(1, self.chart.width()))

    def _window(self, coord):
        """当前可见窗口：``None``（全量）/ ``(start, stop)`` 连续段 / 下标数组。

        单调 x 或 category 轴给连续段（下游用切片视图，免掩码免拷贝）；乱序
        value 轴给 ``flatnonzero`` 掩码下标（按数据身份 + 范围缓存）。
        """
        if not isinstance(coord, GridCoord) or _ds.np is None:
            return None
        axis = coord.x_axis
        if axis.type == "category":
            count = len(getattr(axis, "categories", ()) or ())
            if count <= 0:
                return None
            window_offset = getattr(axis, "windowOffset", None)
            offset = int(window_offset()) if callable(window_offset) else 0
            offset = max(0, min(offset, self._data_len))
            stop = min(self._data_len, offset + count)
            if offset <= 0 and stop >= self._data_len:
                return None
            return (offset, stop)
        if axis.type != "value" or self._np_x is None:
            return None
        lo, hi = float(axis.vmin), float(axis.vmax)
        if not (lo <= hi):
            return (0, 0)  # 反向区间 = 空窗口（与掩码语义一致）
        x = self._np_x
        if self._np_x_monotone:
            np_ = _ds.np
            i0 = int(np_.searchsorted(x, lo, side="left"))
            i1 = int(np_.searchsorted(x, hi, side="right"))
            if i0 <= 0 and i1 >= x.size:
                return None
            return (i0, i1)
        key = (self._np_cache_key, self._data_len, lo, hi)
        if self._win_cache_key == key:
            return self._win_cache
        idx = _ds.np.flatnonzero((x >= lo) & (x <= hi))
        if idx.size >= self._data_len:
            idx = None  # 全量窗口不裁剪
        self._win_cache_key = key
        self._win_cache = idx
        return idx

    def _win_abs(self, window, local):
        """窗口内局部下标 → 全局下标（``local`` 来自 ``_decimate``）。"""
        if isinstance(window, tuple):
            return local + window[0]
        if window is None:
            return local
        return window[local]

    def _py_window(self, axis):
        """纯 Python 兜底路径的可见窗口下标（``None`` = 不做裁剪）。

        没有 numpy 快路径的数据（dict 项 / 混合类型 / 含 None）也要按窗口裁剪，
        否则缩放 / 平移后抽稀跑在全量上、绘制只覆盖窗口的一小段。返回 ``range``
        （有序 / category，O(log n)）或 ``list[int]``（无序），按数据身份 + 轴范围缓存。
        """
        n = self._data_len
        if axis is None or n <= 0:
            return None
        if axis.type == "category":
            count = len(getattr(axis, "categories", ()) or ())
            if count <= 0 or count >= n:
                return None
            window_offset = getattr(axis, "windowOffset", None)
            offset = int(window_offset()) if callable(window_offset) else 0
            offset = max(0, min(offset, n))
            return range(offset, min(n, offset + count))
        if axis.type != "value":
            return None
        lo, hi = float(axis.vmin), float(axis.vmax)
        key = (self._np_cache_key, self._data_len, round(lo, 6), round(hi, 6))
        if self._py_window_key == key:
            return self._py_window_cache
        xs = self._x_vals
        result = None
        if xs:
            if self._py_x_sorted:
                i0 = bisect.bisect_left(xs, lo)
                i1 = bisect.bisect_right(xs, hi)
                result = range(i0, max(i0, i1))
            else:
                picked = [i for i, x in enumerate(xs) if lo <= x <= hi]
                result = picked
            if result is not None and len(result) >= n:
                result = None  # 全量窗口不裁剪
        self._py_window_key = key
        self._py_window_cache = result
        return result

    def _decimate(self, y, x, n_out: int, algo: str, assume_sorted: bool = False):
        """按算法抽稀，返回局部下标数组；不可行时返回 ``None``。

        三层兜底：tsdownsample（要求 x 严格递增）→ numpy 按桶 min/max（不要求
        有序）→ 调用方等距抽稀。``assume_sorted`` 表示 x 已按数据身份验过严格递增。
        """
        if _ds.np is None or y is None or y.size == 0:
            return None
        if x is not None:
            local = _ds.downsample_indices(
                x, y, n_out, algo, assume_sorted=assume_sorted
            )
            if local is not None:
                return local
        return _ds.bucket_minmax_indices(y, n_out)

    def _sample_cache_get(self, key):
        """查 LRU；命中即刷新新旧顺序。"""
        hit = self._sample_lru.get(key)
        if hit is not None:
            self._sample_lru.move_to_end(key)
        return hit

    def _sample_cache_put(self, key, sel, *, full: bool):
        """写 LRU。全景视图最贵、又是缩放往返的必经点 —— 淘汰时跳过它。"""
        self._sample_lru[key] = sel
        self._sample_lru.move_to_end(key)
        if full:
            self._full_sample_key = key
        while len(self._sample_lru) > _SAMPLE_CACHE_MAX:
            victim = next(iter(self._sample_lru))
            if victim == self._full_sample_key:
                others = [k for k in self._sample_lru if k != victim]
                if not others:
                    break
                victim = others[0]
            del self._sample_lru[victim]

    def _apply_gap_breaks(self, coord, plot_w: float) -> None:
        """按预计算的记录中断位置在采样点之间插入 None 断点。

        数据侧：相邻时间差 > 4.1 × 步长即记录中断（一次性预计算）；屏幕侧：
        中断像素宽 ≥ ``_GAP_MIN_PIXELS`` 才断开（亚像素空洞照常连线，断开反而闪）。
        ``addGaps: false`` / ``connectNulls: true`` 关闭；仅数值 x 轴生效。
        """
        if not bool(self.opt.get("addGaps", True)):
            return
        if bool(self.opt.get("connectNulls", False)):
            return
        gap_pos = self._np_gap_pos
        if gap_pos is None or gap_pos.size == 0:
            return
        if not isinstance(coord, GridCoord) or coord.x_axis.type != "value":
            return
        if len(self._point_idx) < 2:
            return
        span = float(coord.x_axis.vmax) - float(coord.x_axis.vmin)
        if not (span > 0.0):
            return
        np_ = _ds.np
        arr = np_.asarray(self._point_idx, dtype=np_.int64)
        # 采样点原始下标严格升序：二分找中断右侧的第一个采样点，断点插在它前面。
        js = np_.searchsorted(arr, gap_pos, side="right")
        keep = (js > 0) & (js < arr.size)
        if not keep.any():
            return
        js = js[keep]
        px = self._np_gap_dur[keep] / span * plot_w
        js = js[px >= _GAP_MIN_PIXELS]
        if js.size == 0:
            return
        points = self._points
        idxs = self._point_idx
        for j in sorted(np_.unique(js).tolist(), reverse=True):
            points.insert(j, None)
            # 占位必须保持 `_point_idx` 升序（valueAtIndex 用二分查最近点，
            # 插 -1 会失序、命中点画到别处）：重复前一个下标即可，消费者跳过 None。
            idxs.insert(j, idxs[j - 1] if j > 0 else 0)
