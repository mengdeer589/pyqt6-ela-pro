"""数据缩放组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._tokens import T
from .._utils import clamp as _clamp
from .._utils import merged_text_style, text_italic, text_weight
from .._utils import to_float as _to_float
from .._utils import warn_once
from .._utils import parse_color
from ..axes import GridCoord, chartFont
from ._shared import _axis_index_list


class DataZoomComponent(QObject):
    """区域缩放：inside（滚轮 + 拖拽平移）/ slider（底部双把手滑块）。

    option::

        "dataZoom": [{"type": "inside"|"slider", "xAxisIndex": 0,
                      "yAxisIndex": 0, "start": 0, "end": 100,
                      "yStart": 0, "yEnd": 100}]

    start / end 为 X 轴 0-100 百分比窗口，yStart / yEnd 为 Y 轴窗口（自动
    滚轮 / 框选组件默认同时启用 XY；显式 dataZoom 给了 yAxisIndex 或在
    框选 / 滚轮时首次启用 Y，``yZoom: false`` 可禁用）。category 轴以类别
    子窗口替换 ``axis.categories``，value / log 轴调整 ``vmin/vmax`` 并重算
    刻度；均为幂等修改（基于缓存的全量数据计算），每次布局重放，不污染原始
    option。

    inside 的滚轮经 chart 上的事件过滤器拦截（core 未提供 wheel 钩子，
    重建时旧过滤器会被移除，不会累积）。toolbox 的 dataZoom 开关经
    ``chart._dataZoomEnabled`` 属性关闭 inside 交互（slider 常可用）。

    **与 brush 共存时的显式优先级**：option 同时配置 brush 时，plot 内
    左键拖拽归 brush（矩形刷选），inside 仅保留滚轮缩放（见
    ``onMousePress`` 的 ``_brush_active`` 判断）。
    """

    optionKey = "dataZoom"

    #: 滑块条带高度
    SLIDER_H = 24.0

    def __init__(self, chart, opt):
        super().__init__()
        self.chart = chart
        entries = opt if isinstance(opt, list) else [opt]
        self.entries = [e for e in entries if isinstance(e, dict)]
        first = self.entries[0] if self.entries else {}
        self.init_start = _clamp(_to_float(first.get("start"), 0.0), 0, 100)
        self.init_end = _clamp(_to_float(first.get("end"), 100.0), 0, 100)
        if self.init_end < self.init_start:
            self.init_start, self.init_end = self.init_end, self.init_start
        self.start = self.init_start
        self.end = self.init_end
        # y 轴窗口（框选 / 滚轮同时缩放 XY；显式 dataZoom 需给 yAxisIndex 才启用）
        self.y_init_start = _clamp(_to_float(first.get("yStart"), 0.0), 0, 100)
        self.y_init_end = _clamp(_to_float(first.get("yEnd"), 100.0), 0, 100)
        if self.y_init_end < self.y_init_start:
            self.y_init_start, self.y_init_end = self.y_init_end, self.y_init_start
        self.y_start = self.y_init_start
        self.y_end = self.y_init_end
        raw_y = first.get("yAxisIndex")
        self._y_axis_indices = _axis_index_list(raw_y)
        self._y_zoom_enabled = (
            raw_y is not None
            or first.get("yStart") is not None
            or first.get("yEnd") is not None
        )
        self._y_zoom_allowed = first.get("yZoom", True) is not False
        #: ``zoomLock``：锁定窗口大小（滚轮不缩放，只能平移）
        self.zoom_lock = first.get("zoomLock") is True
        #: ``filterMode``：``"filter"`` / ``"none"`` 都只改**轴窗口**，系列数据
        #: 一条不删（类目轴用 ``_all_categories`` + ``windowOffset`` 保留全局下标）
        #: —— 这正是 ``"none"`` 的语义；``"weakFilter"`` / ``"empty"`` 未实现，
        #: 按 filter 处理并留一条告警。
        mode = str(first.get("filterMode") or "filter").strip().lower()
        if mode not in ("filter", "none"):
            warn_once(
                "datazoom-filter-mode",
                f"dataZoom.filterMode={mode!r} 暂未实现，按 filter 处理",
            )
            mode = "filter"
        self.filter_mode = mode
        self.has_inside = any(str(e.get("type")) == "inside" for e in self.entries)
        self.has_slider = any(str(e.get("type")) == "slider" for e in self.entries)
        if not self.has_inside and not self.has_slider and self.entries:
            self.has_inside = True  # 未指明类型时按 inside 处理
        # 全量范围缓存：``apply`` 懒捕 / ``captureExtent`` 重捕都会写这里。
        # 必须在构造时初始化 —— host 自动滚轮组件在 ``_rebuild`` 的捕获循环
        # 之后才创建，首次 ``refreshValueExtent`` 可能早于 ``captureExtent``。
        self._full_cats = {}
        self._full_range = {}
        self._full_y_cats = {}
        self._full_y_range = {}
        self._applied_cats_window = {}
        self._applied_y_cats_window = {}
        self._extent_epochs = {}
        self._x_axis_indices = None
        for entry in self.entries:
            if entry.get("xAxisIndex") is not None:
                self._x_axis_indices = _axis_index_list(entry.get("xAxisIndex"))
                break
        # 完整轴数据缓存（首次布局时捕获）：按 x 轴索引分桶
        self._full_cats: dict = {}  # index -> category 轴完整类别
        self._full_range: dict = {}  # index -> value/log 轴 (vmin, vmax)
        self._full_y_cats: dict = {}
        self._full_y_range: dict = {}
        #: 上一次写进 category 轴的 (i0, i1) 窗口（apply 幂等跳过用）
        self._applied_cats_window: dict = {}
        self._applied_y_cats_window: dict = {}
        # 拖拽状态：("start"|"end"|"move"|"pan", last_x)
        self._drag = None
        self._track = QRectF()
        self._h_start = QRectF()
        self._h_end = QRectF()
        # 滚轮事件过滤器（core 无 wheel 钩子）。
        # **解挂旧实例必须放在 ``has_inside`` 判断之外**：只在 ``has_inside`` 为真时
        # 清理的话，``inside -> slider`` 的切换会留下一个仍挂在 chart 上的孤儿过滤器
        # —— 它不在 ``chart.components`` 里，UI 的滑块不知道它的存在，但它继续
        # 拦截滚轮并用**陈旧的** ``_full_cats`` / ``_full_range`` 改坐标轴，实测
        # 滑块显示 0-100% 而实际窗口已缩到 10-90%，此后两者每帧互相覆盖。
        # ``dataZoom`` 整块从 option 里删掉时同样要靠 ``dispose()`` 解挂。
        prev = getattr(chart, "_datazoom_filter", None)
        if prev is not None and prev is not self:
            try:
                chart.removeEventFilter(prev)
            except Exception:
                pass
        chart._datazoom_filter = None
        if self.has_inside:
            chart.installEventFilter(self)
            chart._datazoom_filter = self

    def dispose(self) -> None:
        """从 chart 上解挂（``core._rebuild`` 丢弃旧组件时调用）。"""
        if getattr(self.chart, "_datazoom_filter", None) is self:
            self.chart._datazoom_filter = None
        try:
            self.chart.removeEventFilter(self)
        except Exception:
            pass
        self._drag = None
        #: 起手平移所属网格的绘图区（多网格）
        self._pan_plot = None

    # -- 轴窗口 ------------------------------------------------------------
    def _axes(self):
        """受本组件控制的 x 轴 ``[(index, AxisModel)]``（``xAxisIndex`` 缺省=全部）。"""
        coord = self.chart.primaryCoord()
        if not isinstance(coord, GridCoord):
            return []
        axes = list(enumerate(coord.x_axes))
        if self._x_axis_indices is None:
            return axes
        chosen = set(self._x_axis_indices)
        return [(i, axis) for i, axis in axes if i in chosen]

    def _axis(self):
        axes = self._axes()
        return axes[0][1] if axes else None

    def _y_axes(self):
        """受本组件控制的 y 轴（仅 ``yAxisIndex`` 或自动 XY 缩放时）。"""
        if not self._y_zoom_enabled:
            return []
        coord = self.chart.primaryCoord()
        if not isinstance(coord, GridCoord):
            return []
        axes = list(enumerate(coord.y_axes))
        if self._y_axis_indices is None:
            return axes
        chosen = set(self._y_axis_indices)
        return [(i, axis) for i, axis in axes if i in chosen]

    def enableYAxisZoom(self) -> None:
        """启用 Y 轴窗口（框选 / 滚轮 / 缩放按钮首次使用时）。"""
        if not self._y_zoom_allowed or self._y_zoom_enabled:
            return
        self._y_zoom_enabled = True
        self._y_axis_indices = None
        for index, axis in self._y_axes():
            self._capture_full_y(index, axis)

    def captureExtent(self) -> None:
        """重捕「全量范围」（``_rebuild`` 在 ``setSeries`` 之后调用，幂等）。

        ``apply()`` 的窗口是相对**全量范围**算的，而全量范围原先只在首次
        ``apply()`` 时懒捕一次 —— 「空数据起步」的图表会把 ``0~1`` 当全量钉死：
        数据到了、``setSeries`` 也重算了轴范围，但 dataZoom 随即又把它改回
        ``0~1``（默认滚轮缩放组件跨 ``setOption`` 存活，必中；症状是「生成 30 万点
        后图里只有两个点、缩放也没反应」）。数据增长（``appendData`` / 周期
        ``setOption``）同理。

        类别轴用 ``_all_categories``（全量类别）—— ``categories`` 此时可能已被
        窗口替换成子集。多 x / 多 y 轴时按索引分桶。
        """
        self._full_cats = {}
        self._full_range = {}
        self._full_y_cats = {}
        self._full_y_range = {}
        self._applied_cats_window = {}
        self._applied_y_cats_window = {}
        self._extent_epochs = {}
        for index, axis in self._axes():
            if axis.type == "category":
                full = list(
                    getattr(axis, "_all_categories", None) or axis.categories or []
                )
                if full:
                    self._full_cats[index] = full
            else:
                full = getattr(axis, "_data_extent", None) or (
                    float(axis.vmin),
                    float(axis.vmax),
                )
                self._full_range[index] = (float(full[0]), float(full[1]))
        for index, axis in self._y_axes():
            if axis.type == "category":
                full = list(
                    getattr(axis, "_all_categories", None) or axis.categories or []
                )
                if full:
                    self._full_y_cats[index] = full
            else:
                full = getattr(axis, "_data_extent", None) or (
                    float(axis.vmin),
                    float(axis.vmax),
                )
                self._full_y_range[index] = (float(full[0]), float(full[1]))
        for index, axis in self._axes():
            if axis.type != "category":
                self._extent_epochs[("x", index)] = int(
                    getattr(axis, "_extent_epoch", 0)
                )
        for index, axis in self._y_axes():
            if axis.type != "category":
                self._extent_epochs[("y", index)] = int(
                    getattr(axis, "_extent_epoch", 0)
                )

    def refreshValueExtent(self) -> bool:
        """系列 layout 修正轴范围后，只重捕**变过**的 value/log 全量范围。

        ``layout_all`` 的顺序是「写回窗口 → 坐标系 → 系列」。横向柱 / 堆叠柱 /
        K 线 / 箱线图的真实值域要到系列 ``layout`` 里才算得出来，所以这里必须
        在系列之后补一次 —— 否则 dataZoom 会拿「未修正的范围」当全量，把轴
        改回去（默认自动滚轮组件必中：横向柱三根柱子一样长、堆叠柱上层被裁）。

        只认 ``_extent_epoch`` 变化过的轴，避免每帧复制 1M 个类别列表。
        """
        changed = False
        for index, axis in self._axes():
            if axis.type == "category":
                continue
            epoch = int(getattr(axis, "_extent_epoch", 0))
            key = ("x", index)
            if self._extent_epochs.get(key) == epoch:
                continue
            full = getattr(axis, "_data_extent", None) or (
                float(axis.vmin),
                float(axis.vmax),
            )
            self._full_range[index] = (float(full[0]), float(full[1]))
            self._extent_epochs[key] = epoch
            changed = True
        for index, axis in self._y_axes():
            if axis.type == "category":
                continue
            epoch = int(getattr(axis, "_extent_epoch", 0))
            key = ("y", index)
            if self._extent_epochs.get(key) == epoch:
                continue
            full = getattr(axis, "_data_extent", None) or (
                float(axis.vmin),
                float(axis.vmax),
            )
            self._full_y_range[index] = (float(full[0]), float(full[1]))
            self._extent_epochs[key] = epoch
            changed = True
        return changed

    def _capture_full(self, index: int, axis) -> None:
        if axis.type == "category":
            if index not in self._full_cats:
                self._full_cats[index] = list(axis.categories)
        else:
            if index not in self._full_range:
                full = getattr(axis, "_data_extent", None) or (
                    float(axis.vmin),
                    float(axis.vmax),
                )
                self._full_range[index] = (float(full[0]), float(full[1]))

    def _capture_full_y(self, index: int, axis) -> None:
        if axis.type == "category":
            if index not in self._full_y_cats:
                self._full_y_cats[index] = list(axis.categories)
        else:
            if index not in self._full_y_range:
                full = getattr(axis, "_data_extent", None) or (
                    float(axis.vmin),
                    float(axis.vmax),
                )
                self._full_y_range[index] = (float(full[0]), float(full[1]))

    @staticmethod
    def _apply_axis_window(
        axis,
        index: int,
        start: float,
        end: float,
        full_cats: dict,
        full_range: dict,
        applied_cats: dict,
    ) -> None:
        """把 0-100 窗口写到单根轴（category 切片 / value-log 重算刻度）。"""
        if axis.type == "category":
            full = full_cats.get(index) or []
            n = len(full)
            if n == 0:
                return
            # 百分比 → 下标必须带 epsilon：``i0/n*100`` 再乘回去常有 1ulp
            # 误差（n=3, i0=1 得 0.9999999999999999，int() 退一格）。
            i0 = int(math.floor(start / 100.0 * n + 1e-9))
            i1 = int(math.ceil(end / 100.0 * n - 1e-9))
            i0 = _clamp(i0, 0, n - 1)
            i1 = _clamp(max(i1, i0 + 1), 1, n)
            # 幂等快速路径：窗口没变、且轴内容仍是上一次写的窗口时跳过 ——
            # 每次布局 apply 会跑两次（applyWindow + 组件 layout），而
            # 重建类目列表在 1M 个字符串上是 O(n) 复制（实测是 category
            # 1M 帧的头号开销）。len 检查兜住外部改写 categories 的情况。
            if (i0, i1) != applied_cats.get(index) or len(axis.categories) != i1 - i0:
                axis.categories = full[i0:i1]  # 切片本身就是新 list，别再包一层
                applied_cats[index] = (i0, i1)
        else:
            full = full_range.get(index)
            if full is None:
                return
            axis.setWindow(full[0], full[1], start, end)

    def apply(self) -> None:
        """按 start/end（x）与 yStart/yEnd（y）幂等重放轴窗口。"""
        for index, axis in self._axes():
            self._capture_full(index, axis)
            self._apply_axis_window(
                axis,
                index,
                self.start,
                self.end,
                self._full_cats,
                self._full_range,
                self._applied_cats_window,
            )
        if not self._y_zoom_enabled:
            return
        for index, axis in self._y_axes():
            self._capture_full_y(index, axis)
            self._apply_axis_window(
                axis,
                index,
                self.y_start,
                self.y_end,
                self._full_y_cats,
                self._full_y_range,
                self._applied_y_cats_window,
            )

    def restore(self) -> None:
        """还原初始窗口（toolbox restore 调用）。"""
        before = (float(self.start), float(self.end))
        self.start = self.init_start
        self.end = self.init_end
        self.y_start = self.y_init_start
        self.y_end = self.y_init_end
        self.apply()
        self.chart.invalidateLayout()  # 窗口变化 → 失效布局缓存
        self.chart.update()
        self._emit_changed(before)

    def snapshotWindow(self) -> dict:
        """当前窗口快照（``_rebuild`` 保留用户缩放用）。"""
        return {
            "start": float(self.start),
            "end": float(self.end),
            "y_start": float(self.y_start),
            "y_end": float(self.y_end),
            "y_zoom": bool(self._y_zoom_enabled),
        }

    def adoptWindow(self, state: dict) -> None:
        """沿用上一次的窗口（option 里的 dataZoom 段没变时调用）。"""
        if not isinstance(state, dict):
            return
        try:
            self.start = _clamp(float(state.get("start", self.start)), 0.0, 100.0)
            self.end = _clamp(float(state.get("end", self.end)), 0.0, 100.0)
            self.y_start = _clamp(float(state.get("y_start", self.y_start)), 0.0, 100.0)
            self.y_end = _clamp(float(state.get("y_end", self.y_end)), 0.0, 100.0)
            if state.get("y_zoom"):
                self.enableYAxisZoom()
        except (TypeError, ValueError, OverflowError):
            return

    def reserveBottom(self) -> float:
        """底部滑块条带高度：轨道 + 百分比标签（无 slider 时为 0）。"""
        if self.has_slider:
            return self.SLIDER_H + 20.0
        return 0.0

    # -- 布局 / 绘制（slider） ---------------------------------------------
    def applyWindow(self) -> None:
        """布局**前置**钩子：把窗口写回坐标轴（``_layout_all`` 在排系列前调用）。

        顺序是硬要求：系列按当前轴窗口采样（``_window``）、按窗口做
        坐标映射。放在组件 ``layout()``（系列之后）里 apply 会得到「轴已缩放、
        曲线仍是**旧窗口**的采样」的错配 —— 而那一帧结束时布局缓存键（含
        dataZoom 窗口）已经命中，下一次布局直接 early-return，错配**永久留下**，
        表现就是「缩放后曲线变稀、窗口里只剩几个点」。
        """
        self.apply()

    def layout(self, rect: QRectF) -> None:
        if self.has_slider:
            h = self.SLIDER_H
            # 底部预留 20px 给百分比标签（reserveBottom 与之匹配）
            y = rect.bottom() - h - 20
            band = QRectF(rect.left() + 16, y, max(40.0, rect.width() - 32), h)
            track_h = 8.0
            self._track = QRectF(
                band.left(), y + (h - track_h) / 2, band.width(), track_h
            )
            self._update_handles()
        self.apply()

    def _x_of(self, pct: float) -> float:
        return self._track.left() + _clamp(pct, 0, 100) / 100.0 * self._track.width()

    def _update_handles(self) -> None:
        hw, hh = 10.0, 16.0
        cy = self._track.center().y()
        self._h_start = QRectF(self._x_of(self.start) - hw / 2, cy - hh / 2, hw, hh)
        self._h_end = QRectF(self._x_of(self.end) - hw / 2, cy - hh / 2, hw, hh)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self.has_slider or self._track.isNull():
            return
        p.save()
        # 轨道
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T("color.bg.muted")))
        p.drawRoundedRect(self._track, 4, 4)
        # 选中区间
        sel = QRectF(
            self._x_of(self.start),
            self._track.top(),
            max(2.0, self._x_of(self.end) - self._x_of(self.start)),
            self._track.height(),
        )
        fill = QColor(T("color.primary"))
        fill.setAlpha(70)
        p.setBrush(fill)
        p.drawRoundedRect(sel, 4, 4)
        # 把手
        for r in (self._h_start, self._h_end):
            p.setPen(QPen(QColor(T("color.border.strong")), 1))
            p.setBrush(QColor(T("color.bg.elevated")))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QPen(QColor(T("color.text.tertiary")), 1))
            cx = r.center().x()
            p.drawLine(QPointF(cx - 2, r.top() + 4), QPointF(cx - 2, r.bottom() - 4))
            p.drawLine(QPointF(cx + 2, r.top() + 4), QPointF(cx + 2, r.bottom() - 4))
        # 百分比 / 自定义标签（``showDetail: false`` 可关；``textStyle`` 可改外观）
        first = self.entries[0] if self.entries else {}
        if first.get("showDetail", True) is not False:
            style = self.detailStyle()
            font = chartFont(
                style.get("fontSize", T("font.xs")),
                text_weight(style.get("fontWeight")),
                style.get("fontFamily"),
                text_italic(style.get("fontStyle")),
            )
            p.setFont(font)
            fm = QFontMetricsF(font)
            p.setPen(parse_color(style.get("color") or T("color.text.tertiary")))
            ly = self._track.bottom() + 1
            p.drawText(
                QRectF(self._track.left(), ly, 40, fm.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                self._slider_label(self.start),
            )
            p.drawText(
                QRectF(self._track.right() - 40, ly, 40, fm.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                self._slider_label(self.end),
            )
        p.restore()

    def detailStyle(self) -> dict:
        """滑块两端文案样式（``textStyle``，含顶层 ``textStyle`` 兜底）。"""
        first = self.entries[0] if self.entries else {}
        return merged_text_style(self.chart, first.get("textStyle"))

    def _slider_label(self, pct: float) -> str:
        """滑块两端文案（``labelFormatter`` 可定制，缺省 ``NN%``）。"""
        formatter = self.entries[0].get("labelFormatter") if self.entries else None
        if callable(formatter):
            try:
                out = formatter(pct)
                if out is not None:
                    return str(out)
            except Exception:
                pass
        elif isinstance(formatter, str):
            try:
                return formatter.format_map({"value": pct})
            except Exception:
                pass
        return f"{pct:.0f}%"

    # -- inside 交互 ---------------------------------------------------------
    def _inside_move_enabled(self) -> bool:
        """``inside`` 的拖拽平移是否可用（ECharts ``moveOnMouseMove``，默认 True）。

        实例属性优先：``ElaChartWidget.setDragMode`` 用它把同一个拖拽手势在
        「平移 / 刷选」之间切换；默认开启的那个滚轮缩放组件则显式关掉它
        （滚轮缩放不该顺带把拖拽也拿走）。
        """
        override = getattr(self, "moveOnMouseMove", None)
        if isinstance(override, bool):
            return override
        for entry in self.entries:
            value = entry.get("moveOnMouseMove")
            if isinstance(value, bool):
                return value
        return True

    def _inside_wheel_enabled(self, event=None) -> bool:
        """``inside`` 的滚轮缩放是否可用（ECharts ``zoomOnMouseWheel``）。

        支持 ``True`` / ``False`` / ``"shift"`` / ``"ctrl"`` / ``"alt"`` ——
        字符串形态要求对应修饰键按下（ECharts 同款），没有事件对象时按
        「只要不是 False 就允许」处理。
        """
        override = getattr(self, "zoomOnMouseWheel", None)
        if isinstance(override, bool):
            return override
        raw = override
        for entry in self.entries:
            value = entry.get("zoomOnMouseWheel")
            if isinstance(value, (bool, str)):
                raw = value
                break
        if isinstance(raw, bool):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return True
        if event is None:
            return True
        mods = event.modifiers()
        want = raw.strip().lower()
        mapping = {
            "shift": Qt.KeyboardModifier.ShiftModifier,
            "ctrl": Qt.KeyboardModifier.ControlModifier,
            "alt": Qt.KeyboardModifier.AltModifier,
        }
        flag = mapping.get(want)
        return bool(flag is not None and (mods & flag))

    def _inside_enabled(self) -> bool:
        return (
            self.has_inside
            and bool(getattr(self.chart, "_dataZoomEnabled", True))
            and bool(
                getattr(self.chart, "isInteractionEnabled", lambda _f: True)("dataZoom")
            )
        )

    # -- 窗口约束 / 程序化动作 --------------------------------------------
    def _span_limits(self):
        """``minSpan`` / ``maxSpan``：取**所有** dataZoom 条目的约束交集。

        ECharts 是「每个 ``dataZoom[i]`` 各有各的 minSpan/maxSpan」，而本引擎只有
        一个共享窗口（``self.start`` / ``self.end``，两个条目共用），所以唯一自洽的
        语义就是取交集：``minSpan`` 取最大、``maxSpan`` 取最小。

        原先只读 ``entries[0]``，于是约束挂在 slider 上而 inside 排在前面时
        （``[{"type": "inside"}, {"type": "slider", "minSpan": 40}]``）``minSpan``
        被整条丢掉 —— 实测滑块能一路拖到 10% 窗口；反过来的组合里 slider 自己的
        ``maxSpan`` 也会被 inside 的 ``maxSpan`` 顶掉。两条都只影响同一条 option
        里同时配 inside + slider 的场景（单条目时行为不变）。

        约束自相矛盾（``minSpan > maxSpan``）时由 ``_clamp_span`` 的应用顺序决定：
        先抬到 minSpan 再压到 maxSpan，即 maxSpan 胜出。
        """
        min_span = None
        max_span = None
        for e in self.entries:
            lo = _to_float(e.get("minValueSpan", e.get("minSpan")), None)
            if lo is not None:
                min_span = lo if min_span is None else max(min_span, lo)
            hi = _to_float(e.get("maxValueSpan", e.get("maxSpan")), None)
            if hi is not None:
                max_span = hi if max_span is None else min(max_span, hi)
        return min_span, max_span

    def _clamp_span(self, start: float, end: float):
        """按 ``minSpan`` / ``maxSpan`` 约束窗口并收敛回 [0, 100]。"""
        min_span, max_span = self._span_limits()
        span = max(0.0, float(end) - float(start))
        if min_span is not None and span < min_span:
            span = min_span
        if max_span is not None and span > max_span:
            span = max_span
        span = _clamp(span, 1.0, 100.0)
        center = (float(start) + float(end)) / 2.0
        start = _clamp(center - span / 2.0, 0.0, max(0.0, 100.0 - span))
        return start, start + span

    def reset_window(self) -> bool:
        """把缩放窗口还原到全量（``resetView`` / 双击复位用）。"""
        started, ended = self.start, self.end
        y_started, y_ended = self.y_start, self.y_end
        changed = started != 0.0 or ended != 100.0
        payload = {"type": "dataZoom", "start": 0, "end": 100}
        if self._y_zoom_enabled:
            changed = changed or y_started != 0.0 or y_ended != 100.0
            payload["yStart"] = 0
            payload["yEnd"] = 100
        return self.applyAction(payload) or changed

    def applyAction(self, payload: dict) -> bool:
        """``dispatchAction({"type": "dataZoom", ...})``：

        支持 ``start`` / ``end``（百分比）与 ``startValue`` / ``endValue``
        （category 轴为类别名或下标，value 轴为数值）；可选 ``zoomLock``
        保持窗口跨度；``dataZoomIndex`` 仅支持 0（单窗口引擎）。
        """
        if not isinstance(payload, dict):
            return False
        index = payload.get("dataZoomIndex")
        if index is not None:
            try:
                if int(index) != 0:
                    return False
            except (TypeError, ValueError, OverflowError):
                return False
        axes = self._axes()
        if not axes:
            return False
        axis_index, axis = axes[0]
        self._capture_full(axis_index, axis)
        start = _to_float(payload.get("start"), None)
        end = _to_float(payload.get("end"), None)
        if start is None and end is None:
            sv = payload.get("startValue")
            ev = payload.get("endValue")
            if sv is None and ev is None:
                return False
            if axis.type == "category":
                full = self._full_cats.get(axis_index) or []
                n = len(full)
                if n == 0:
                    return False

                def _index_of(value):
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        return _clamp(int(value), 0, n - 1)
                    try:
                        return full.index(str(value))
                    except ValueError:
                        return None

                i0 = _index_of(sv) if sv is not None else 0
                i1 = _index_of(ev) if ev is not None else n - 1
                if i0 is None or i1 is None:
                    return False
                if i1 < i0:
                    i0, i1 = i1, i0
                start = i0 / n * 100.0
                end = (i1 + 1) / n * 100.0
            else:
                full = self._full_range.get(axis_index)
                if full is None:
                    return False
                lo, hi = full

                def _pct(value):
                    num = _to_float(value, None)
                    if num is None:
                        return None
                    if axis.type == "log":
                        if lo <= 0.0 or hi <= 0.0 or num <= 0.0:
                            return None
                        l0, l1 = math.log(lo), math.log(hi)
                        return (math.log(num) - l0) / (l1 - l0) * 100.0
                    span = hi - lo or 1.0
                    return (num - lo) / span * 100.0

                start = _pct(sv) if sv is not None else 0.0
                end = _pct(ev) if ev is not None else 100.0
                if start is None or end is None:
                    return False
        if start is None:
            start = self.start
        if end is None:
            end = self.end
        if end < start:
            start, end = end, start
        if bool(payload.get("zoomLock")):
            span = self.end - self.start
            end = start + span
        before = (float(self.start), float(self.end))
        self.start, self.end = self._clamp_span(
            _clamp(float(start), 0.0, 100.0), _clamp(float(end), 0.0, 100.0)
        )
        if payload.get("yStart") is not None or payload.get("yEnd") is not None:
            self.enableYAxisZoom()
        if self._y_zoom_enabled:
            y_start = _to_float(payload.get("yStart"), None)
            y_end = _to_float(payload.get("yEnd"), None)
            if y_start is not None or y_end is not None:
                if y_start is None:
                    y_start = self.y_start
                if y_end is None:
                    y_end = self.y_end
                if y_end < y_start:
                    y_start, y_end = y_end, y_start
                span = _clamp(float(y_end) - float(y_start), 1.0, 100.0)
                center = (float(y_start) + float(y_end)) / 2.0
                y_start = _clamp(center - span / 2.0, 0.0, 100.0 - span)
                self.y_start, self.y_end = y_start, y_start + span
        self.apply()
        self.chart.invalidateLayout()
        self.chart.update()
        self._emit_changed(before)
        return True

    def _plot(self) -> QRectF:
        """绘图区 rect（主坐标系）。"""
        coord = self.chart.primaryCoord()
        if isinstance(coord, GridCoord):
            return coord.plot
        return QRectF()

    def _plot_at(self, pos: QPointF) -> QRectF:
        """光标所在网格的绘图区（多网格；不在任何网格时退回主坐标系）。"""
        coord = self.chart.coordAt(pos)
        if isinstance(coord, GridCoord):
            return coord.plot
        return self._plot()

    def _wheel_hit(self, pos: QPointF) -> bool:
        """滚轮缩放命中区域：绘图区 plot 内，或 slider 轨道上（ECharts 习惯）。"""
        if self._plot_at(pos).contains(pos):
            return True
        if self.has_slider and not self._track.isNull():
            return self._track.adjusted(-4, -4, 4, 4).contains(pos)
        return False

    def onWheel(self, event) -> bool:
        """chart.wheelEvent 钩子：消费滚轮缩放并返回 True。

        事件到达 chart 的 ``wheelEvent`` 时由 ``ElaChartWidget`` 调用；
        命中（plot 内 / slider 轨道）则缩放并返回 True，由 chart 层
        ``event.accept()`` 显式消费 —— 祖先滚动区不会再滚动（页面
        滚轮与图表缩放同时触发的修复核心）。
        """
        if not self._inside_enabled() or self.zoom_lock:
            return False
        try:
            pos = (
                event.position()
                if hasattr(event, "position")
                else QPointF(event.position().toPoint())
            )
        except Exception:  # noqa: BLE001
            pos = QPointF()
        if not self._wheel_hit(pos):
            return False
        # ``zoomOnMouseWheel`` 只管 plot 内的滚轮；slider 轨道上滚轮是滑块自身
        # 的行为（ECharts 同款），不受该键影响。
        if self._plot_at(pos).contains(pos) and not self._inside_wheel_enabled(event):
            return False
        try:
            self._wheel_zoom(event.angleDelta().y(), pos)
        except Exception as exc:  # noqa: BLE001
            warn_once(
                f"datazoom-wheel:{type(exc).__name__}",
                f"dataZoom 滚轮处理异常: {exc!r}",
            )
        return True

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.chart and ev.type() == QEvent.Type.Wheel:
            if self.onWheel(ev):
                # 显式 accept + 返回 True：事件既不再向 widget 传递，
                # 状态也为「已消费」（防止祖先滚动区据此滚动）
                try:
                    ev.accept()
                except Exception:  # noqa: BLE001
                    pass
                return True
        return False

    def _wheel_zoom(self, delta_y: float, pos: QPointF) -> None:
        before = (float(self.start), float(self.end))
        plot = self._plot_at(pos)
        if plot.width() <= 0:
            return
        factor = 0.8 if delta_y > 0 else 1.25
        coord = self.chart.coordAt(pos)
        x_axis = getattr(coord, "x_axis", None) if isinstance(coord, GridCoord) else None
        old_span = self.end - self.start
        if old_span > 0:
            new_span = _clamp(old_span * factor, 4.0, 100.0)
            frac = _clamp((pos.x() - plot.left()) / plot.width(), 0.0, 1.0)
            # inverse 轴的像素方向与数据方向相反：不翻转锚点，鼠标下的
            # 数据点在缩放时会漂走。
            if x_axis is not None and getattr(x_axis, "inverse", False):
                frac = 1.0 - frac
            anchor = self.start + frac * old_span
            self.start = anchor - frac * new_span
            self.end = self.start + new_span
            self.start, self.end = self._clamp_span(self.start, self.end)
        if plot.contains(pos) and isinstance(coord, GridCoord) and coord.y_axes:
            self.enableYAxisZoom()
        if self._y_zoom_enabled and plot.height() > 0:
            old_y_span = self.y_end - self.y_start
            if old_y_span > 0:
                new_y_span = _clamp(old_y_span * factor, 4.0, 100.0)
                frac_y = _clamp((plot.bottom() - pos.y()) / plot.height(), 0.0, 1.0)
                if isinstance(coord, GridCoord) and getattr(
                    coord.y_axis, "inverse", False
                ):
                    frac_y = 1.0 - frac_y
                anchor_y = self.y_start + frac_y * old_y_span
                self.y_start = anchor_y - frac_y * new_y_span
                self.y_end = self.y_start + new_y_span
                span = _clamp(self.y_end - self.y_start, 1.0, 100.0)
                self.y_start = _clamp(self.y_start, 0.0, 100.0 - span)
                self.y_end = self.y_start + span
        self.apply()
        self.chart.invalidateLayout()  # 窗口变化 → 失效布局缓存
        self.chart.update()
        self._emit_changed(before)

    def _emit_changed(self, before) -> None:
        """窗口变化 → ``chart.dataZoomChanged(start, end)``（滚轮 / 拖拽 / 平移共用）。"""
        if before is None:
            return
        after = (float(self.start), float(self.end))
        if after != before:
            self.chart.dataZoomChanged.emit(after[0], after[1])

    def _pan(self, dx_px: float) -> None:
        plot = self._pan_plot or self._plot()
        if plot.width() <= 0:
            return
        shift = -dx_px / plot.width() * 100.0
        # inverse 轴：内容跟手的方向相反
        if getattr(self._axis(), "inverse", False):
            shift = -shift
        shift = _clamp(shift, -self.start, 100.0 - self.end)
        self.start += shift
        self.end += shift
        self.apply()
        self.chart.invalidateLayout()  # 窗口变化 → 失效布局缓存
        self.chart.update()

    # -- 鼠标钩子 ------------------------------------------------------------
    def _brush_active(self) -> bool:
        """brush 是否正在接管拖拽（``setDragMode`` 按模式开关它的 ``enabled``）。

        只看「组件存在」会让 ``setDragMode("pan")`` 失效：dataZoom 会永远给刷选
        让位，而刷选自己又因为 ``enabled=False`` 不起手 —— 拖拽两边都不响应。
        """
        for comp in self.chart.components:
            if getattr(comp, "optionKey", "") == "brush":
                return bool(getattr(comp, "enabled", True))
        return False

    def onMousePress(self, pos: QPointF) -> bool:
        if self.has_slider and not self._track.isNull():
            grab = 6.0
            if self._h_start.adjusted(-grab, -grab, grab, grab).contains(pos):
                self._drag = ("start", pos.x())
                return True
            if self._h_end.adjusted(-grab, -grab, grab, grab).contains(pos):
                self._drag = ("end", pos.x())
                return True
            mid = QRectF(
                self._h_start.right(),
                self._track.top() - 4,
                max(0.0, self._h_end.left() - self._h_start.right()),
                self._track.height() + 8,
            )
            if mid.contains(pos):
                self._drag = ("move", pos.x())
                return True
        if (
            self._inside_enabled()
            and self._inside_move_enabled()
            and not self._brush_active()
            and self._plot_at(pos).contains(pos)
        ):
            self._pan_plot = self._plot_at(pos)
            self._drag = ("pan", pos.x())
            return True
        return False

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._drag is None:
            return False
        before = (float(self.start), float(self.end))
        kind, last_x = self._drag
        if kind in ("start", "end"):
            pct = (pos.x() - self._track.left()) / max(1.0, self._track.width()) * 100.0
            pct = _clamp(pct, 0.0, 100.0)
            if kind == "start":
                self.start = min(pct, self.end - 2.0)
            else:
                self.end = max(pct, self.start + 2.0)
            self.start, self.end = self._clamp_span(self.start, self.end)
            self._update_handles()
            self.apply()
            self.chart.invalidateLayout()
            self.chart.update()
        elif kind == "move":
            dx = pos.x() - last_x
            span = self.end - self.start
            shift = dx / max(1.0, self._track.width()) * 100.0
            shift = _clamp(shift, -self.start, 100.0 - self.end)
            self.start += shift
            self.end = self.start + span
            self._update_handles()
            self.apply()
            self.chart.invalidateLayout()
            self.chart.update()
        elif kind == "pan":
            self._pan(pos.x() - last_x)
        self._drag = (kind, pos.x())
        self._emit_changed(before)
        return True

    def onMouseRelease(self, pos: QPointF) -> bool:
        if self._drag is not None:
            self._drag = None
            self._pan_plot = None
            return True
        return False

    def hitTest(self, pos: QPointF):
        return None
