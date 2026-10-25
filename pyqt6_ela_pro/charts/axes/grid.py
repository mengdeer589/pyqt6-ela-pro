"""直角坐标系与多轴视图。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen

from .._tokens import T
from .._utils import grid_options
from .._utils import parse_color
from .. import _downsample as _ds
from .. import data as _cdata
from ._shared import (
    _EXTENT_CACHE,
    _EXTENT_CACHE_LIMIT,
    _axis_index,
    _axis_options,
    _datum_x,
    _datum_y,
    _line_pen,
    _margin_px,
    _parse_margin,
    _to_float,
)
from .base import AxisModel, Coord


class GridCoord(Coord):
    """直角坐标系：grid 边距 + 多 x/y 轴 + 网格 / 区域 / 刻度 / 标签。

    option 键：``grid``（left/right/top/bottom 默认 48/24/40/36、``show``、
    ``containLabel``、``borderColor`` / ``borderWidth`` / ``backgroundColor``）、
    ``xAxis`` / ``yAxis``（单个 dict 或数组，见 AxisModel）。边距支持数值 px
    或 ``"N%"``。``mapPoint(x, y)``：x 为类别名/下标或数值，y 为数值；
    可选 ``x_axis_index`` / ``y_axis_index`` 指定轴。

    多轴通过 :meth:`axis_view` 返回绑定到某对轴的轻量视图；系列渲染器继续
    读 ``coord.x_axis`` / ``coord.y_axis``，无需逐个改。
    """

    kind = "grid"

    def __init__(
        self,
        chart=None,
        option: dict = None,
        grid_index: int = 0,
        axes: tuple = None,
    ):
        super().__init__(chart, option)
        self.grid_index = max(0, int(grid_index))
        grid_list = grid_options(self.option.get("grid"))
        grid = (
            grid_list[self.grid_index]
            if self.grid_index < len(grid_list)
            else {}
        )
        if axes is not None:
            # 多网格：各网格**共享同一批 AxisModel**（轴窗口 / dataZoom 只写一份）
            self.x_axes, self.y_axes = axes
        else:
            xopts = _axis_options(self.option.get("xAxis"))
            yopts = _axis_options(self.option.get("yAxis"))
            if not xopts:
                xopts = [{}]
            if not yopts:
                yopts = [{}]
            self.x_axes = [
                AxisModel(o, "category" if o.get("data") else "value", self.chart)
                for o in xopts
            ]
            self.y_axes = [AxisModel(o, "value", self.chart) for o in yopts]
            for i, axis in enumerate(self.x_axes):
                if axis.position not in ("top", "bottom"):
                    axis.position = "bottom" if i == 0 else "top"
            for i, axis in enumerate(self.y_axes):
                if axis.position not in ("left", "right"):
                    axis.position = "left" if i == 0 else "right"
        #: ``(x_axis_index, y_axis_index)`` → 轴对视图缓存
        self._axis_views: dict = {}
        self._m_left = _parse_margin(grid.get("left"), 48)
        self._m_right = _parse_margin(grid.get("right"), 24)
        self._m_top = _parse_margin(grid.get("top"), 40)
        self._m_bottom = _parse_margin(grid.get("bottom"), 36)
        #: 显式宽 / 高（``grid.width`` / ``grid.height``）；None = 由边距撑满
        self._w_opt = grid.get("width")
        self._h_opt = grid.get("height")
        self.m_left = self.m_right = self.m_top = self.m_bottom = 0.0
        self.plot = QRectF()  # 绘图区（扣除边距）
        self.grid_show = bool(grid.get("show", False))
        self.grid_border_color = grid.get("borderColor")
        self.grid_bg = grid.get("backgroundColor")
        try:
            self.grid_border_width = max(0.0, float(grid.get("borderWidth", 0)))
        except (TypeError, ValueError, OverflowError):
            self.grid_border_width = 0.0
        self.contain_label = bool(grid.get("containLabel", False))

    @property
    def x_axis(self) -> AxisModel:
        """本网格的主 x 轴；多轴请用 :meth:`axis_view` 或直接读 ``x_axes``。"""
        for axis in self.x_axes:
            if axis.grid_index == self.grid_index:
                return axis
        return self.x_axes[0]

    @property
    def y_axis(self) -> AxisModel:
        """本网格的主 y 轴。"""
        for axis in self.y_axes:
            if axis.grid_index == self.grid_index:
                return axis
        return self.y_axes[0]

    def _series_axes(self, series_opt: dict):
        """系列 → ``(x_axis_index, y_axis_index)``（越界静默收敛）。"""
        s = series_opt if isinstance(series_opt, dict) else {}
        return (
            _axis_index(s.get("xAxisIndex"), len(self.x_axes)),
            _axis_index(s.get("yAxisIndex"), len(self.y_axes)),
        )

    def axis_view_for_indices(self, x_axis_index=0, y_axis_index=0):
        """取绑定到某对轴的视图（同一个 GridCoord 共享绘图区）。"""
        xi = _axis_index(x_axis_index, len(self.x_axes))
        yi = _axis_index(y_axis_index, len(self.y_axes))
        key = (xi, yi)
        view = self._axis_views.get(key)
        if view is None:
            view = _GridAxisView(self, xi, yi)
            self._axis_views[key] = view
        return view

    def axis_view(self, series_opt: dict = None):
        """按系列 ``xAxisIndex`` / ``yAxisIndex`` 取轴对视图。"""
        xi, yi = self._series_axes(series_opt)
        return self.axis_view_for_indices(xi, yi)

    # -- 数据范围 ---------------------------------------------------------
    def _extent(self, data, positive_x: bool = False, positive_y: bool = False):
        """带缓存的数值范围 ``(x0, x1, y0, y1)``（缺失维度为 ``None``）。

        缓存是**缩放 / 平移流畅度的关键**：``setSeries`` 在每次重建
        （缩放、平移、数据更新、图例切换都会触发）时都重算全量范围，
        百万点逐点扫描要 400 ms 以上。范围只取决于数据本身，与窗口无关，
        因此按「数据对象身份 + 长度 + 正值过滤」缓存后，缩放时这一步接近零成本。

        缓存值同时**持有数据对象的强引用**（见 ``_EXTENT_CACHE`` 的说明），
        否则对象被回收后 ``id`` 会被复用，把别的数据的范围当成自己的。
        """
        if data is None:
            return None
        if _cdata.isBufferLike(data) or _ds.np is not None:
            try:
                n = len(data)
                key = (
                    (id(data), n)
                    if not positive_x and not positive_y
                    else (id(data), n, int(bool(positive_x)), int(bool(positive_y)))
                )
            except TypeError:
                return self._numpy_extent(data, positive_x, positive_y)
            hit = _EXTENT_CACHE.get(key)
            if hit is not None and hit[0] is data:
                return hit[1]
            ext = self._numpy_extent(data, positive_x, positive_y)
            if len(_EXTENT_CACHE) >= _EXTENT_CACHE_LIMIT:
                _EXTENT_CACHE.clear()
            _EXTENT_CACHE[key] = (data, ext)
            return ext
        return self._numpy_extent(data, positive_x, positive_y)

    def _numpy_extent(self, data, positive_x: bool = False, positive_y: bool = False):
        """numpy 快速路径：返回 ``(x0, x1, y0, y1)``（缺失维度为 ``None``）或 None。

        纯数值列表：x 按下标语义（0 .. n-1）；[x, y] 列表：取两列；
        含字典 / None / 混合形式返回 None（调用方回退 Python 循环）。

        走 ``nanmin`` / ``nanmax``：``None`` 间隙在缓冲里是 NaN，用 ``min``/``max``
        会让整个轴范围变成 NaN。但**它们只跳 NaN 不跳 inf**，所以先把非有限值
        掩成 NaN —— 完整清单与后果见 AGENTS.md「charts」。
        """
        if data is None or _ds.np is None:
            return None
        try:
            n = len(data)
        except TypeError:
            return None
        if n == 0:
            return None
        try:
            arr = _ds.np.asarray(data, dtype=_ds.np.float64)
        except (TypeError, ValueError, OverflowError):
            return None
        np_ = _ds.np
        if arr.ndim == 1:
            if not arr.size:
                return None
            arr = np_.where(np_.isfinite(arr), arr, np_.nan)
            if positive_y:
                arr = np_.where(arr > 0.0, arr, np_.nan)
            if not np_.isfinite(arr).any():
                return None
            ymin, ymax = float(np_.nanmin(arr)), float(np_.nanmax(arr))
            x0 = 1.0 if positive_x and arr.size > 1 else 0.0
            if positive_x and arr.size <= 1:
                return None
            return x0, float(arr.size - 1), ymin, ymax
        if arr.ndim == 2 and arr.shape[1] >= 2 and arr.shape[0]:
            xcol = np_.where(np_.isfinite(arr[:, 0]), arr[:, 0], np_.nan)
            ycol = np_.where(np_.isfinite(arr[:, 1]), arr[:, 1], np_.nan)
            if positive_x:
                xcol = np_.where(xcol > 0.0, xcol, np_.nan)
            if positive_y:
                ycol = np_.where(ycol > 0.0, ycol, np_.nan)
            xpair = (
                (float(np_.nanmin(xcol)), float(np_.nanmax(xcol)))
                if np_.isfinite(xcol).any()
                else None
            )
            ypair = (
                (float(np_.nanmin(ycol)), float(np_.nanmax(ycol)))
                if np_.isfinite(ycol).any()
                else None
            )
            if ypair is None and not (positive_x or positive_y):
                return None
            if xpair is None and ypair is None:
                return None
            return (
                xpair[0] if xpair else None,
                xpair[1] if xpair else None,
                ypair[0] if ypair else None,
                ypair[1] if ypair else None,
            )
        return None

    def setSeries(self, series_opts: list) -> None:
        xs = [[] for _ in self.x_axes]
        ys = [[] for _ in self.y_axes]
        for s in series_opts or []:
            if not isinstance(s, dict):
                continue
            if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
                continue
            xi, yi = self._series_axes(s)
            xaxis = self.x_axes[xi]
            yaxis = self.y_axes[yi]
            need_x = xaxis.type in ("value", "log")
            need_y = yaxis.type in ("value", "log")
            if not need_x and not need_y:
                continue
            positive_x = xaxis.type == "log"
            positive_y = yaxis.type == "log"
            data = s.get("data")
            # ``data: 5`` / ``3.5`` / ``True`` 这类**标量**不是合法序列（ECharts
            # 也不接受），但它此前一路走到下面的 ``enumerate(data)`` 抛 TypeError，
            # 而 ``_rebuild`` 调 ``setSeries`` 没有 try —— 异常直接冒给
            # ``setOption`` 的调用方。降级成空数据，与「数据为空」同路径。
            #
            # 注意判据不能用 ``isBufferLike``：它**故意不认** list / tuple
            # （逐元素拷贝对百万级列表是性能灾难，见 data.isBufferLike 的
            # docstring），那样会把正常数据全清空。
            if data is None:
                data = []
            elif not _cdata.isBufferLike(data) and not isinstance(data, (list, tuple)):
                data = []
            ext = self._extent(data, positive_x, positive_y)
            if ext is not None:
                x0, x1, y0, y1 = ext
                have_x = x0 is not None and x1 is not None
                have_y = y0 is not None and y1 is not None
                if need_x and have_x:
                    xs[xi].extend((x0, x1))
                if need_y and have_y:
                    ys[yi].extend((y0, y1))
                if (not need_x or have_x) and (not need_y or have_y):
                    continue
            for i, item in enumerate(data):
                # ``_datum_y`` / ``_datum_x`` 在入口已滤掉 NaN / inf
                y = _datum_y(item)
                if need_y and y is not None and (not positive_y or y > 0.0):
                    ys[yi].append(y)
                if need_x:
                    if xaxis.is_time:
                        raw = item.get("value") if isinstance(item, dict) else item
                        if isinstance(raw, (list, tuple)) and raw:
                            x = xaxis.toNumber(raw[0])
                        else:
                            x = None
                    else:
                        x = _datum_x(item)
                    if x is None:
                        if y is not None:
                            x = float(i)  # 纯数值数据：x 取下标（index 语义）
                        else:
                            continue
                    if positive_x and x <= 0.0:
                        continue
                    xs[xi].append(float(x))
        for i, axis in enumerate(self.y_axes):
            if axis.type in ("value", "log"):
                vals = ys[i]
                axis.setExtent(min(vals), max(vals)) if vals else axis.setExtent(
                    0.0, 1.0
                )
        for i, axis in enumerate(self.x_axes):
            if axis.type in ("value", "log"):
                vals = xs[i]
                axis.setExtent(min(vals), max(vals)) if vals else axis.setExtent(
                    0.0, 1.0
                )

    # -- 协议 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        # 百分比边距在此换算（左右相对宽、上下相对高）
        self.m_left = _margin_px(self._m_left, rect.width())
        self.m_right = _margin_px(self._m_right, rect.width())
        self.m_top = _margin_px(self._m_top, rect.height())
        self.m_bottom = _margin_px(self._m_bottom, rect.height())
        self._apply_axis_margins(rect)
        plot_w = max(10.0, rect.width() - self.m_left - self.m_right)
        plot_h = max(10.0, rect.height() - self.m_top - self.m_bottom)
        if self._w_opt is not None:
            plot_w = max(10.0, min(plot_w, _margin_px(self._w_opt, rect.width())))
        if self._h_opt is not None:
            plot_h = max(10.0, min(plot_h, _margin_px(self._h_opt, rect.height())))
        self.plot = QRectF(
            rect.left() + self.m_left,
            rect.top() + self.m_top,
            plot_w,
            plot_h,
        )

    def _axis_label_extent(self, axis: AxisModel, horizontal: bool) -> float:
        """轴标签在垂直轴方向（y 轴宽度 / x 轴高度）需要的像素。"""
        if axis.axisLabelOption().get("show", True) is False:
            return 0.0
        font = axis.labelFont()
        fm = QFontMetricsF(font)
        if horizontal:
            if axis.type == "category":
                values = axis.categories
            else:
                values = axis._ticks
            if not values:
                return 0.0
            step = max(1, len(values) // 64)
            width = 0.0
            for i in range(0, len(values), step):
                label = axis.formatTickLabel(values[i], i)
                width = max(width, float(fm.horizontalAdvance(label)))
            extra = (
                float(QFontMetricsF(axis.nameFont()).height()) + 6.0
                if axis.name
                else 0.0
            )
            return width + 12.0 + axis.offset + extra
        height = float(fm.height()) + 12.0 + axis.offset
        if axis.name:
            height += float(QFontMetricsF(axis.nameFont()).height()) + 4.0
        return height

    def _apply_axis_margins(self, rect: QRectF) -> None:
        """按轴位置预留标签空间（右侧 Y / 顶部 X 是新功能，必须自动留白）。"""
        left = [
            a
            for a in self.y_axes
            if a.position == "left" and a.grid_index == self.grid_index
        ]
        right = [
            a
            for a in self.y_axes
            if a.position == "right" and a.grid_index == self.grid_index
        ]
        bottom = [
            a
            for a in self.x_axes
            if a.position == "bottom" and a.grid_index == self.grid_index
        ]
        top = [
            a
            for a in self.x_axes
            if a.position == "top" and a.grid_index == self.grid_index
        ]
        left_need = sum(self._axis_label_extent(a, True) for a in left)
        right_need = sum(self._axis_label_extent(a, True) for a in right)
        bottom_need = sum(self._axis_label_extent(a, False) for a in bottom)
        top_need = sum(self._axis_label_extent(a, False) for a in top)
        grid_count = 0
        chart = getattr(self, "chart", None)
        if chart is not None:
            grid_count = sum(
                1
                for coord in getattr(chart, "_coords", ())
                if isinstance(coord, GridCoord)
            )
        if self.contain_label or grid_count > 1:
            # 多网格时不显式开 containLabel 也要按标签实际宽度留白：
            # 窄网格 + 长轴名会压到相邻网格（各网格共享默认边距 48/24）。
            self.m_left = max(self.m_left, left_need)
            self.m_right = max(self.m_right, right_need)
            self.m_bottom = max(self.m_bottom, bottom_need)
            self.m_top = max(self.m_top, top_need)
            return
        # 非 containLabel：主轴保持既有边距（向后兼容），副轴 / 右 / 上必须留白。
        if any(a is not self.y_axes[0] for a in left):
            self.m_left = max(self.m_left, left_need)
        if right:
            self.m_right = max(self.m_right, right_need)
        if any(a is not self.x_axes[0] for a in bottom):
            self.m_bottom = max(self.m_bottom, bottom_need)
        if top:
            self.m_top = max(self.m_top, top_need)

    def mapPoint(
        self,
        x,
        y=None,
        x_axis_index: int = 0,
        y_axis_index: int = 0,
    ) -> QPointF:
        xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
        ya = self.y_axes[_axis_index(y_axis_index, len(self.y_axes))]
        px = xa.map(x, self.plot.left(), self.plot.right())
        py = ya.map(_to_float(y), self.plot.bottom(), self.plot.top())
        return QPointF(px, py)

    def mapArrays(
        self,
        xs,
        ys,
        x_axis_index: int = 0,
        y_axis_index: int = 0,
    ):
        """批量映射（numpy 数组进 → ``(px, py)`` 两个数组）；不支持时返回 ``None``。

        与 :meth:`mapPoint` 逐点**同语义**，只是把「每点 ~6µs 的 Python 调用链」
        换成一次向量化运算（实测 1M 点 2.4s → 数十 ms；采样后 2.6k 点也从
        16ms 降到 <1ms）。以下情形返回 ``None`` 让调用方退回逐点：

        * 缺 numpy；
        * 轴类型不在 ``value`` / ``category`` / ``log`` 内；
        * category 轴的 x 不是数值（类别名无法向量化）。

        非有限坐标不做过滤：由调用方按 ``isfinite`` 决定是否断开（保持
        ``mapPoint`` 把 NaN 交给调用方处理的既有约定）。log 轴的非正值
        产出 NaN。
        """
        np_ = _ds.np
        if np_ is None or xs is None or ys is None:
            return None
        xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
        ya = self.y_axes[_axis_index(y_axis_index, len(self.y_axes))]
        left, right = self.plot.left(), self.plot.right()
        bottom, top = self.plot.bottom(), self.plot.top()

        if xa.type == "category":
            count = len(xa.categories)
            if count <= 0:
                return None
            try:
                idx = np_.asarray(xs, dtype=np_.float64) - float(xa.windowOffset())
            except (TypeError, ValueError, OverflowError):
                return None
            if xa.boundary_gap or count <= 1:
                frac = (idx + 0.5) / count
            else:
                frac = idx / (count - 1)
        elif xa.type == "value":
            values = np_.asarray(xs, dtype=np_.float64)
            span = xa.vmax - xa.vmin
            frac = np_.zeros_like(values) if span == 0 else (values - xa.vmin) / span
        elif xa.type == "log":
            values = np_.asarray(xs, dtype=np_.float64)
            frac = np_.full(values.shape, np_.nan, dtype=np_.float64)
            valid = values > 0.0
            if xa.vmin > 0.0 and xa.vmax > 0.0:
                lo, hi = math.log(xa.vmin), math.log(xa.vmax)
                if hi != lo:
                    frac[valid] = (np_.log(values[valid]) - lo) / (hi - lo)
                else:
                    frac[valid] = 0.0
        else:
            return None
        if xa.inverse:
            frac = 1.0 - frac
        px = left + (right - left) * frac

        if ya.type == "value":
            y_values = np_.asarray(ys, dtype=np_.float64)
            y_span = ya.vmax - ya.vmin
            y_frac = (
                np_.zeros_like(y_values)
                if y_span == 0
                else (y_values - ya.vmin) / y_span
            )
        elif ya.type == "log":
            y_values = np_.asarray(ys, dtype=np_.float64)
            y_frac = np_.full(y_values.shape, np_.nan, dtype=np_.float64)
            valid = y_values > 0.0
            if ya.vmin > 0.0 and ya.vmax > 0.0:
                lo, hi = math.log(ya.vmin), math.log(ya.vmax)
                if hi != lo:
                    y_frac[valid] = (np_.log(y_values[valid]) - lo) / (hi - lo)
                else:
                    y_frac[valid] = 0.0
        else:
            return None
        if ya.inverse:
            y_frac = 1.0 - y_frac
        py = bottom + (top - bottom) * y_frac
        return px, py

    def invertX(self, pos: QPointF, x_axis_index: int = 0):
        xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
        return xa.invert(pos.x(), self.plot.left(), self.plot.right())

    def invertPoint(self, pos: QPointF, x_axis_index: int = 0, y_axis_index: int = 0):
        """像素 → ``[x, y]``（category 轴返回窗口内下标）。"""
        xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
        ya = self.y_axes[_axis_index(y_axis_index, len(self.y_axes))]
        return [
            xa.invert(pos.x(), self.plot.left(), self.plot.right()),
            ya.invert(pos.y(), self.plot.bottom(), self.plot.top()),
        ]

    def containPoint(self, pos: QPointF) -> bool:
        return self.plot.contains(QPointF(pos))

    # -- 绘制 -------------------------------------------------------------
    def _interval_step(self, axis: AxisModel, horizontal: bool, option_key: str) -> int:
        """标签 / 刻度 / 网格线的抽稀步长（``interval: 'auto'`` 语义）。

        **为什么必须有**：坐标轴现在是「有多少刻度画多少」——1M 个类别的 x 轴
        会画 1M 个标签 + 1M 条刻度（实测单帧 11.8s + 3.5s，比系列绘制贵两个
        数量级）。抽稀后绘制量与像素宽度挂钩，与数据量解耦。

        判据：沿轴方向「一个标签占的像素」不够放时按倍数跳。显式 ``interval``
        （数字 / callable）优先，用户说了算。
        """
        opt = axis.axisLabelOption() if option_key == "axisLabel" else None
        if opt is None:
            if option_key == "axisTick":
                opt = axis.axisTickOption()
            elif option_key == "splitLine":
                opt = axis.splitLineOption()
            elif option_key == "splitArea":
                opt = axis.splitAreaOption()
            else:
                opt = {}
        interval = opt.get("interval")
        if isinstance(interval, bool):
            return 1
        if isinstance(interval, (int, float)):
            return max(1, int(interval) + 1)
        if callable(interval):
            return 1
        # 每次绘制只算一次：同一次 paintAxes 里标签 / 刻度 / 网格 / 分隔区
        # 会各问一次，样本量文本不能重复付（记忆化按轴 + 方向 + 画布尺寸）。
        memo = getattr(self, "_step_memo", None)
        if memo is None:
            memo = self._step_memo = {}
        memo_key = (id(axis), horizontal, option_key)
        if memo_key in memo:
            return memo[memo_key]
        step = self._compute_interval_step(axis, horizontal)
        memo[memo_key] = step
        return step

    def _compute_interval_step(self, axis: AxisModel, horizontal: bool) -> int:
        count = len(axis.categories) if axis.type == "category" else len(axis.ticks())
        if count <= 1:
            return 1
        span = self.plot.height() if horizontal else self.plot.width()
        if span <= 0:
            return 1
        spacing = span / float(count)
        font = axis.labelFont()
        fm = QFontMetricsF(font)
        if horizontal:
            # y 轴：沿轴方向是标签**高度**（一行）
            extent = float(fm.height())
        else:
            # x 轴：沿轴方向是标签**宽度**；量最多 32 个样本取最宽
            # （全量量文本会把「画不出来」换成「量不完」）
            extent = 0.0
            step_sample = max(1, count // 32)
            ticks = axis.ticks() if axis.type != "category" else None
            for i in range(0, count, step_sample):
                text = axis.formatTickLabel(
                    axis.categories[i] if axis.type == "category" else ticks[i], i
                )
                extent = max(extent, float(fm.horizontalAdvance(text)))
            if extent <= 0.0:
                extent = float(fm.height())
        need = extent + 6.0
        if need <= spacing:
            return 1
        return int(math.ceil(need / spacing))

    def _axis_positions(self, axis: AxisModel, horizontal: bool, step: int = 1):
        """轴刻度位置列表 ``[(px, py, label, index)]``（category 用本地下标映射）。

        ``step`` 是抽稀步长（``_interval_step``）：**category 轴按它跳着枚举**，
        1M 个类别的轴才不会在这里先造出 1M 个元组（光这一步就要 ~0.3s）。
        """
        out = []
        step = max(1, int(step))
        if axis.type == "category":
            categories = axis.categories
            for i in range(0, len(categories), step):
                label = axis.formatTickLabel(categories[i], i)
                if horizontal:
                    py = axis.map(i, self.plot.bottom(), self.plot.top(), local=True)
                    out.append((self.plot.left(), py, label, i))
                else:
                    px = axis.map(i, self.plot.left(), self.plot.right(), local=True)
                    out.append((px, self.plot.bottom(), label, i))
        else:
            ticks = axis.ticks()
            for i in range(0, len(ticks), step):
                tv = ticks[i]
                if horizontal:
                    py = axis.map(tv, self.plot.bottom(), self.plot.top())
                    out.append(
                        (self.plot.left(), py, axis.formatTickLabel(tv, i), tv)
                    )
                else:
                    px = axis.map(tv, self.plot.left(), self.plot.right())
                    out.append(
                        (px, self.plot.bottom(), axis.formatTickLabel(tv, i), tv)
                    )
        return out

    def _axis_sides(self):
        """``(axis, horizontal, primary)``：只含本网格的轴，y 轴 horizontal=True。"""
        out = []
        y_primary = None
        for axis in self.y_axes:
            if axis.grid_index != self.grid_index:
                continue
            out.append((axis, True, y_primary is None))
            y_primary = axis
        x_primary = None
        for axis in self.x_axes:
            if axis.grid_index != self.grid_index:
                continue
            out.append((axis, False, x_primary is None))
            x_primary = axis
        return out

    def _axis_line_pos(self, axis: AxisModel, horizontal: bool) -> float:
        """轴线所在像素（y 轴返回 x，x 轴返回 y）。"""
        if horizontal:
            if axis.position == "right":
                return self.plot.right() + axis.offset
            return self.plot.left() - axis.offset
        if axis.position == "top":
            return self.plot.top() - axis.offset
        return self.plot.bottom() + axis.offset

    def _paint_split_area(self, p: QPainter) -> None:
        for axis, horizontal, _primary in self._axis_sides():
            opt = axis.splitAreaOption()
            if not bool(opt.get("show", False)):
                continue
            area = opt.get("areaStyle")
            colors = (area or {}).get("color") if isinstance(area, dict) else None
            if not isinstance(colors, list) or not colors:
                colors = [T("color.bg.muted")]
            positions = self._axis_positions(
                axis, horizontal, self._interval_step(axis, horizontal, "splitArea")
            )
            spans = []
            for px, py, _label, _idx in positions:
                spans.append(py if horizontal else px)
            for i in range(len(spans) - 1):
                lo, hi = sorted((spans[i], spans[i + 1]))
                color = parse_color(colors[i % len(colors)])
                if not color.isValid():
                    continue
                if horizontal:
                    rect = QRectF(self.plot.left(), lo, self.plot.width(), hi - lo)
                else:
                    rect = QRectF(lo, self.plot.top(), hi - lo, self.plot.height())
                p.fillRect(rect, color)

    def _paint_split_lines(self, p: QPainter) -> None:
        for axis, horizontal, primary in self._axis_sides():
            opt = axis.splitLineOption()
            # ECharts 默认：value / log 轴显示网格线，category 轴不显示。
            # 副轴默认不画（否则两套网格叠在一起），显式 show 可开。
            default_show = axis.type in ("value", "log") and primary
            if not bool(opt.get("show", default_show)):
                continue
            p.setPen(_line_pen(opt, T("color.border")))
            for px, py, _label, _idx in self._axis_positions(
                axis, horizontal, self._interval_step(axis, horizontal, "splitLine")
            ):
                if horizontal:
                    p.drawLine(
                        QPointF(self.plot.left(), py), QPointF(self.plot.right(), py)
                    )
                else:
                    p.drawLine(
                        QPointF(px, self.plot.top()), QPointF(px, self.plot.bottom())
                    )

    def _paint_axis_lines(self, p: QPainter) -> None:
        for axis, horizontal, _primary in self._axis_sides():
            opt = axis.axisLineOption()
            if not bool(opt.get("show", True)):
                continue
            p.setPen(_line_pen(opt, T("color.border.strong")))
            if horizontal:
                x = self._axis_line_pos(axis, True)
                p.drawLine(QPointF(x, self.plot.bottom()), QPointF(x, self.plot.top()))
            else:
                y = self._axis_line_pos(axis, False)
                p.drawLine(QPointF(self.plot.left(), y), QPointF(self.plot.right(), y))

    def _paint_ticks(self, p: QPainter) -> None:
        for axis, horizontal, _primary in self._axis_sides():
            opt = axis.axisTickOption()
            if not bool(opt.get("show", True)):
                continue
            inside = bool(opt.get("inside", False))
            try:
                length = max(1.0, float(opt.get("length", 5)))
            except (TypeError, ValueError, OverflowError):
                length = 5.0
            p.setPen(_line_pen(opt, T("color.border.strong")))
            line = self._axis_line_pos(axis, horizontal)
            # 向外方向的符号：left=-1 / right=+1 / bottom=+1 / top=-1
            if horizontal:
                outward = 1.0 if axis.position == "right" else -1.0
            else:
                outward = 1.0 if axis.position == "bottom" else -1.0
            direction = -outward if inside else outward
            for px, py, _label, _idx in self._axis_positions(
                axis, horizontal, self._interval_step(axis, horizontal, "axisTick")
            ):
                if horizontal:
                    p.drawLine(
                        QPointF(line, py), QPointF(line + direction * length, py)
                    )
                else:
                    p.drawLine(
                        QPointF(px, line), QPointF(px, line + direction * length)
                    )

    def _paint_axis_labels(self, p: QPainter) -> None:
        # y 轴标签：left 右对齐到轴线左侧，right 左对齐到轴线右侧
        for axis in self.y_axes:
            if axis.grid_index != self.grid_index:
                continue
            font = axis.labelFont()
            p.setFont(font)
            fm = QFontMetricsF(font)
            color = axis.labelColor()
            line = self._axis_line_pos(axis, True)
            if axis.position == "right":
                left = line + 6
                right = max(left + 8, self.rect.right())
                align = Qt.AlignmentFlag.AlignLeft
            else:
                left = self.rect.left()
                right = max(left + 8, line - 6)
                align = Qt.AlignmentFlag.AlignRight
            for px, py, label, idx in self._axis_positions(
                axis, True, self._interval_step(axis, True, "axisLabel")
            ):
                if not axis.labelShownAt(idx, label):
                    continue
                p.setPen(color)
                p.drawText(
                    QRectF(
                        left, py - fm.height() / 2, max(8.0, right - left), fm.height()
                    ),
                    align | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
        # x 轴标签：bottom 在轴线下，top 在轴线上；可按 axisLabel.rotate 旋转
        for axis in self.x_axes:
            if axis.grid_index != self.grid_index:
                continue
            font = axis.labelFont()
            p.setFont(font)
            fm = QFontMetricsF(font)
            color = axis.labelColor()
            try:
                rotate = float(axis.axisLabelOption().get("rotate", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                rotate = 0.0
            line = self._axis_line_pos(axis, False)
            top_side = axis.position == "top"
            for px, py, label, idx in self._axis_positions(
                axis, False, self._interval_step(axis, False, "axisLabel")
            ):
                if not axis.labelShownAt(idx, label):
                    continue
                p.setPen(color)
                if abs(rotate) < 1e-6:
                    rect = (
                        QRectF(px - 40, line - 5 - fm.height(), 80, fm.height())
                        if top_side
                        else QRectF(px - 40, line + 5, 80, fm.height())
                    )
                    p.drawText(
                        rect,
                        Qt.AlignmentFlag.AlignHCenter
                        | (
                            Qt.AlignmentFlag.AlignBottom
                            if top_side
                            else Qt.AlignmentFlag.AlignTop
                        ),
                        label,
                    )
                else:
                    center_y = (
                        line - 5 - fm.height() / 2
                        if top_side
                        else line + 5 + fm.height() / 2
                    )
                    p.save()
                    p.translate(px, center_y)
                    p.rotate(rotate)
                    p.drawText(
                        QRectF(-60, -fm.height() / 2, 120, fm.height()),
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                        label,
                    )
                    p.restore()

    def _paint_axis_names(self, p: QPainter) -> None:
        for axis in self.x_axes:
            if axis.grid_index != self.grid_index or not axis.name:
                continue
            style = axis.nameTextStyle()
            p.setPen(parse_color(style.get("color") or T("color.text.tertiary")))
            font = axis.nameFont()
            p.setFont(font)
            fm = QFontMetricsF(font)
            gap = max(0.0, axis.name_gap)
            line = self._axis_line_pos(axis, False)
            if axis.position == "top":
                base_y = line - gap - fm.height() - fm.height() - 2
                align_v = Qt.AlignmentFlag.AlignBottom
            else:
                base_y = line + gap + fm.height() + 2
                align_v = Qt.AlignmentFlag.AlignTop
            if axis.name_location == "start":
                rect = QRectF(self.plot.left() - 40, base_y, 80, fm.height())
                align_h = Qt.AlignmentFlag.AlignLeft
            elif axis.name_location == "middle":
                rect = QRectF(self.plot.center().x() - 60, base_y, 120, fm.height())
                align_h = Qt.AlignmentFlag.AlignHCenter
            else:
                rect = QRectF(self.plot.right() - 80, base_y, 80, fm.height())
                align_h = Qt.AlignmentFlag.AlignRight
            p.drawText(rect, align_h | align_v, axis.name)
        for axis in self.y_axes:
            if axis.grid_index != self.grid_index or not axis.name:
                continue
            style = axis.nameTextStyle()
            p.setPen(parse_color(style.get("color") or T("color.text.tertiary")))
            font = axis.nameFont()
            p.setFont(font)
            fm = QFontMetricsF(font)
            gap = max(0.0, axis.name_gap)
            line = self._axis_line_pos(axis, True)
            if axis.position == "right":
                left = line + gap
                width = max(20.0, self.rect.right() - left)
                align_h = Qt.AlignmentFlag.AlignLeft
            else:
                left = self.rect.left()
                width = max(20.0, line - gap - left)
                align_h = Qt.AlignmentFlag.AlignRight
            if axis.name_location == "start":
                y = self.plot.bottom() - fm.height()
                align_v = Qt.AlignmentFlag.AlignBottom
            elif axis.name_location == "middle":
                y = self.plot.center().y() - fm.height() / 2
                align_v = Qt.AlignmentFlag.AlignVCenter
            else:
                y = self.plot.top() - fm.height() - 4
                align_v = Qt.AlignmentFlag.AlignBottom
            p.drawText(
                QRectF(left, y, width, fm.height()), align_h | align_v, axis.name
            )

    def paintAxes(self, p: QPainter) -> None:
        p.save()
        # 抽稀步长的记忆化按「一次绘制」为界：轴范围 / 画布尺寸变了要重算
        self._step_memo = {}
        # grid 背景 / 边框
        if self.grid_bg:
            p.fillRect(self.plot, parse_color(self.grid_bg))
        if self.grid_show and self.grid_border_width > 0:
            p.setPen(
                QPen(
                    parse_color(self.grid_border_color or T("color.border")),
                    self.grid_border_width,
                )
            )
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.plot)
        self._paint_split_area(p)
        self._paint_split_lines(p)
        self._paint_axis_lines(p)
        self._paint_ticks(p)
        self._paint_axis_labels(p)
        self._paint_axis_names(p)
        p.restore()

    def paintTooltipMarker(
        self,
        p: QPainter,
        pos: QPointF,
        kind: str = "cross",
        x_axis_index: int = 0,
        line_style: dict = None,
    ) -> None:
        if kind == "none":
            return
        p.save()
        style = line_style if isinstance(line_style, dict) else {}
        pen = _line_pen({"lineStyle": style}, T("color.border.strong"))
        if not isinstance(style.get("type"), str):
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        x = min(max(pos.x(), self.plot.left()), self.plot.right())
        y = min(max(pos.y(), self.plot.top()), self.plot.bottom())
        if kind == "shadow":
            xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
            band = xa.bandWidth(self.plot.left(), self.plot.right())
            width = band if band > 1.0 else 8.0
            shadow = QColor(T("color.bg.muted"))
            shadow.setAlpha(90)
            p.fillRect(
                QRectF(x - width / 2, self.plot.top(), width, self.plot.height()),
                shadow,
            )
        elif kind == "line":
            p.drawLine(QPointF(x, self.plot.top()), QPointF(x, self.plot.bottom()))
        else:  # cross（默认）
            p.drawLine(QPointF(x, self.plot.top()), QPointF(x, self.plot.bottom()))
            p.drawLine(QPointF(self.plot.left(), y), QPointF(self.plot.right(), y))
        p.restore()


class _GridAxisView(GridCoord):
    """绑定到一对 ``(xAxisIndex, yAxisIndex)`` 的 GridCoord 视图。

    共享 ``plot`` / ``rect``，只把 ``x_axis`` / ``y_axis`` 换成所选轴。
    继承 ``GridCoord`` 是为了让系列 / 组件里既有的
    ``isinstance(coord, GridCoord)`` 判断继续成立。
    """

    def __init__(self, owner: GridCoord, x_axis_index: int, y_axis_index: int):
        self._owner = owner
        self.chart = owner.chart
        self.option = owner.option
        self.x_axis_index = x_axis_index
        self.y_axis_index = y_axis_index
        self.x_axis = owner.x_axes[x_axis_index]
        self.y_axis = owner.y_axes[y_axis_index]

    #: 覆盖基类的只读 property，让实例可以指向所选轴
    x_axis = None
    y_axis = None

    @property
    def grid_index(self) -> int:  # type: ignore[override]
        return self._owner.grid_index

    @property
    def plot(self) -> QRectF:  # type: ignore[override]
        return self._owner.plot

    @property
    def rect(self) -> QRectF:  # type: ignore[override]
        return self._owner.rect

    def mapPoint(self, x, y=None, x_axis_index=None, y_axis_index=None) -> QPointF:
        return self._owner.mapPoint(
            x,
            y,
            self.x_axis_index if x_axis_index is None else x_axis_index,
            self.y_axis_index if y_axis_index is None else y_axis_index,
        )

    def mapArrays(self, xs, ys, x_axis_index=None, y_axis_index=None):
        return self._owner.mapArrays(
            xs,
            ys,
            self.x_axis_index if x_axis_index is None else x_axis_index,
            self.y_axis_index if y_axis_index is None else y_axis_index,
        )

    def invertX(self, pos: QPointF, x_axis_index=None):
        return self._owner.invertX(
            pos, self.x_axis_index if x_axis_index is None else x_axis_index
        )

    def invertPoint(self, pos: QPointF, x_axis_index=None, y_axis_index=None):
        return self._owner.invertPoint(
            pos,
            self.x_axis_index if x_axis_index is None else x_axis_index,
            self.y_axis_index if y_axis_index is None else y_axis_index,
        )

    def containPoint(self, pos: QPointF) -> bool:
        return self._owner.containPoint(pos)

    def paintTooltipMarker(
        self,
        p: QPainter,
        pos: QPointF,
        kind: str = "cross",
        x_axis_index=None,
        line_style: dict = None,
    ) -> None:
        return self._owner.paintTooltipMarker(
            p,
            pos,
            kind,
            self.x_axis_index if x_axis_index is None else x_axis_index,
            line_style,
        )
