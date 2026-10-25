"""折线符号清单构建方法组（从 ``LineSeriesRenderer`` 拆出）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF

from .. import _downsample as _ds
from ..axes import GridCoord


class _LineSymbolMixin:
    """方法组 mixin：状态由宿主类 ``__init__`` 建立。"""

    def _build_symbol_items(self, coord, single: bool, plot_w: float):
        """符号 / 标签绘制清单 ``[(原始下标, QPointF), ...]``（``plot()`` 用）。"""
        if str(self.opt.get("symbol") or "emptyCircle") == "none" and not (
            self.labelShown()
        ):
            return []
        if not self.showMarkers() and not self.labelShown():
            return []
        length = self._data_len
        if length <= 0:
            return []
        desired = max(8.0, float(plot_w) / 10.0)
        interval = max(1, int(length / desired)) if length > desired else 1
        if bool(self.opt.get("showAllSymbol", False)):
            # 显式要求全画：给一个 2 万点上限兜底，避免百万点建 100 万个 dict
            interval = 1 if length <= 20000 else int(math.ceil(length / 20000.0))
        indices = list(range(0, length, interval))
        if not indices:
            return []
        # 向量化映射（与折线点同一条快路径）：逐点 ``mapPoint`` 在 category 轴上
        # 每点 ~6µs 起（大类别数时更贵），几十上百个符号也要毫秒级
        np_ = _ds.np
        if not single and np_ is not None and self._np_y is not None:
            try:
                idx_arr = np_.asarray(indices, dtype=np_.int64)
                xs_arr = (
                    self._np_x[idx_arr]
                    if self._np_x is not None
                    else idx_arr.astype(np_.float64)
                )
                ys_arr = self._np_y[idx_arr]
                mapped = coord.mapArrays(xs_arr, ys_arr)
            except Exception:
                mapped = None
            if mapped is not None:
                px_arr, py_arr = mapped
                ok_arr = np_.isfinite(px_arr) & np_.isfinite(py_arr)
                lo = hi = None
                if isinstance(coord, GridCoord) and coord.x_axis.type == "value":
                    lo, hi = coord.x_axis.vmin, coord.x_axis.vmax
                px_list = px_arr.tolist()
                py_list = py_arr.tolist()
                ok_list = ok_arr.tolist()
                xs_list = xs_arr.tolist()
                items = []
                for slot, i in enumerate(indices):
                    if not ok_list[slot]:
                        continue
                    if lo is not None and not (lo <= xs_list[slot] <= hi):
                        continue
                    items.append((i, QPointF(px_list[slot], py_list[slot])))
                return items
        items = []
        for i in indices:
            yi = self._y_at(i)
            if yi is None:
                continue
            xi = self._x_at(i)
            if (
                isinstance(coord, GridCoord)
                and coord.x_axis.type == "value"
                and not (coord.x_axis.vmin <= xi <= coord.x_axis.vmax)
            ):
                continue
            try:
                pt = coord.mapPoint(yi) if single else coord.mapPoint(xi, yi)
            except Exception:
                continue
            items.append((i, pt))
        return items

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
