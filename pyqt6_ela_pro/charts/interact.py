"""
图表交互组件。

本模块提供：

- ``DataZoomComponent``（optionKey="dataZoom"）：inside（滚轮缩放 +
  按住拖拽平移）与 slider（底部双把手滑块，自绘）两种区域缩放；
  通过修改 GridCoord 主轴（x 轴）的可视范围实现（category 轴替换
  类别窗口、value 轴调整 vmin/vmax 并重算 nice ticks）；``restore()``
  还原初始窗口。
- ``BrushComponent``（optionKey="brush"）：矩形刷选，半透明选框，
  命中数据点存入 ``self.selected_items`` 并发出 ``selected(list)`` 信号；
  支持 option ``brush.outOfBrush`` 框外降透明样式。
- ``VisualMapComponent``（optionKey="visualMap"）：连续值→颜色映射，
  右下 / 底部渐变条 + 两端数值标签；``mapColor(v)`` 供系列（如 map）
  经 chart.components 查找调用。
- ``ChartTimeline``（optionKey="timeline"）：底部时间轴（节点圆点 +
  年份标签 + 播放 / 暂停按钮），切换帧以 ``baseOption`` 深合并
  ``options[i]`` 后 notMerge 应用；autoPlay 经 QTimer。
- ``ToolboxComponent``（optionKey="toolbox"）：右上角自绘图标按钮组
  （saveAsImage / restore / dataZoom 开关）。

移植自 InstructionX_UIKit.charts.interact（原库为 PyQt6；主题令牌
经 charts._tokens 适配到 eTheme / ElaThemeType，原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6ElaWidgetTools import ElaIconButton, ElaIconType
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from .._internal import is_deleted
from .._motion import start_idle_loop
from .._styles import coerceElaIcon
from ._tokens import T
from ._utils import clamp as _clamp
from ._utils import to_float as _to_float
from ._utils import warn_key, warn_once
from .axes import GridCoord, chartFont, formatValue
from .core import parseDataPoint, registerComponent

__all__ = [
    "DataZoomComponent",
    "BrushComponent",
    "VisualMapComponent",
    "ChartTimeline",
    "ToolboxComponent",
]


def _axis_index_list(raw):
    """dataZoom ``xAxisIndex`` → 索引列表；None 表示「全部 x 轴」。"""
    if raw is None:
        return None
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for value in values:
        try:
            out.append(int(value))
        except (TypeError, ValueError, OverflowError):
            continue
    return out or None


# ---------------------------------------------------------------------------
# dataZoom
# ---------------------------------------------------------------------------


class DataZoomComponent(QObject):
    """区域缩放：inside（滚轮 + 拖拽平移）/ slider（底部双把手滑块）。

    option::

        "dataZoom": [{"type": "inside"|"slider", "xAxisIndex": 0,
                      "start": 0, "end": 100}]

    start / end 为 0-100 的百分比窗口。缩放作用于主 GridCoord 的 x 轴：
    category 轴以类别子窗口替换 ``axis.categories``，value 轴调整
    ``vmin/vmax`` 并经 niceTicks 重算刻度；均为幂等修改（基于缓存的
    完整数据计算），每次布局重放，不污染原始 option。

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
        self.init_start = _clamp(_to_float(first.get("start"), 0.0) or 0.0, 0, 100)
        self.init_end = _clamp(_to_float(first.get("end"), 100.0) or 100.0, 0, 100)
        if self.init_end < self.init_start:
            self.init_start, self.init_end = self.init_end, self.init_start
        self.start = self.init_start
        self.end = self.init_end
        self.has_inside = any(str(e.get("type")) == "inside" for e in self.entries)
        self.has_slider = any(str(e.get("type")) == "slider" for e in self.entries)
        if not self.has_inside and not self.has_slider and self.entries:
            self.has_inside = True  # 未指明类型时按 inside 处理
        self._x_axis_indices = None
        for entry in self.entries:
            if entry.get("xAxisIndex") is not None:
                self._x_axis_indices = _axis_index_list(entry.get("xAxisIndex"))
                break
        # 完整轴数据缓存（首次布局时捕获）：按 x 轴索引分桶
        self._full_cats: dict = {}  # index -> category 轴完整类别
        self._full_range: dict = {}  # index -> value/log 轴 (vmin, vmax)
        #: 上一次写进 category 轴的 (i0, i1) 窗口（apply 幂等跳过用）
        self._applied_cats_window: dict = {}
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

    def captureExtent(self) -> None:
        """重捕「全量范围」（``_rebuild`` 在 ``setSeries`` 之后调用，幂等）。

        ``apply()`` 的窗口是相对**全量范围**算的，而全量范围原先只在首次
        ``apply()`` 时懒捕一次 —— 「空数据起步」的图表会把 ``0~1`` 当全量钉死：
        数据到了、``setSeries`` 也重算了轴范围，但 dataZoom 随即又把它改回
        ``0~1``（默认滚轮缩放组件跨 ``setOption`` 存活，必中；症状是「生成 30 万点
        后图里只有两个点、缩放也没反应」）。数据增长（``appendData`` / 周期
        ``setOption``）同理。

        类别轴用 ``_all_categories``（全量类别）—— ``categories`` 此时可能已被
        窗口替换成子集。多 x 轴时按索引分桶。
        """
        self._full_cats = {}
        self._full_range = {}
        self._applied_cats_window = {}
        for index, axis in self._axes():
            if axis.type == "category":
                full = list(
                    getattr(axis, "_all_categories", None) or axis.categories or []
                )
                if full:
                    self._full_cats[index] = full
            else:
                self._full_range[index] = (float(axis.vmin), float(axis.vmax))

    def _capture_full(self, index: int, axis) -> None:
        if axis.type == "category":
            if index not in self._full_cats:
                self._full_cats[index] = list(axis.categories)
        else:
            if index not in self._full_range:
                self._full_range[index] = (float(axis.vmin), float(axis.vmax))

    def apply(self) -> None:
        """按 start/end 幂等重放轴窗口（每次布局调用；多 x 轴各写一份）。"""
        start, end = self.start, self.end
        for index, axis in self._axes():
            self._capture_full(index, axis)
            if axis.type == "category":
                full = self._full_cats.get(index) or []
                n = len(full)
                if n == 0:
                    continue
                i0 = int(start / 100.0 * n)
                i1 = int(-(-end / 100.0 * n // 1))  # ceil
                i0 = _clamp(i0, 0, n - 1)
                i1 = _clamp(max(i1, i0 + 1), 1, n)
                # 幂等快速路径：窗口没变、且轴内容仍是上一次写的窗口时跳过 ——
                # 每次布局 apply 会跑两次（applyWindow + 组件 layout），而
                # 重建类目列表在 1M 个字符串上是 O(n) 复制（实测是 category
                # 1M 帧的头号开销）。len 检查兜住外部改写 categories 的情况。
                if (i0, i1) != self._applied_cats_window.get(index) or len(
                    axis.categories
                ) != i1 - i0:
                    axis.categories = full[i0:i1]  # 切片本身就是新 list，别再包一层
                    self._applied_cats_window[index] = (i0, i1)
            else:
                full = self._full_range.get(index)
                if full is None:
                    continue
                axis.setWindow(full[0], full[1], start, end)

    def restore(self) -> None:
        """还原初始窗口（toolbox restore 调用）。"""
        before = (float(self.start), float(self.end))
        self.start = self.init_start
        self.end = self.init_end
        self.apply()
        self.chart.invalidateLayout()  # 窗口变化 → 失效布局缓存
        self.chart.update()
        self._emit_changed(before)

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
        # 百分比标签
        font = chartFont(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QColor(T("color.text.tertiary")))
        ly = self._track.bottom() + 1
        p.drawText(
            QRectF(self._track.left(), ly, 40, fm.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            f"{self.start:.0f}%",
        )
        p.drawText(
            QRectF(self._track.right() - 40, ly, 40, fm.height()),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            f"{self.end:.0f}%",
        )
        p.restore()

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

    def _inside_wheel_enabled(self) -> bool:
        """``inside`` 的滚轮缩放是否可用（ECharts ``zoomOnMouseWheel``，默认 True）。"""
        override = getattr(self, "zoomOnMouseWheel", None)
        if isinstance(override, bool):
            return override
        for entry in self.entries:
            value = entry.get("zoomOnMouseWheel")
            if isinstance(value, bool):
                return value
        return True

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
            lo = _to_float(e.get("minSpan"), None)
            if lo is not None:
                min_span = lo if min_span is None else max(min_span, lo)
            hi = _to_float(e.get("maxSpan"), None)
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
        return self.applyAction({"type": "dataZoom", "start": 0, "end": 100}) or (
            started != 0.0 or ended != 100.0
        )

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
        self.apply()
        self.chart.invalidateLayout()
        self.chart.update()
        self._emit_changed(before)
        return True

    def _plot(self) -> QRectF:
        coord = self.chart.primaryCoord()
        if isinstance(coord, GridCoord):
            return coord.plot
        return QRectF()

    def _wheel_hit(self, pos: QPointF) -> bool:
        """滚轮缩放命中区域：绘图区 plot 内，或 slider 轨道上（ECharts 习惯）。"""
        if self._plot().contains(pos):
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
        if not self._inside_enabled():
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
        if self._plot().contains(pos) and not self._inside_wheel_enabled():
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
        plot = self._plot()
        if plot.width() <= 0:
            return
        old_span = self.end - self.start
        if old_span <= 0:
            return
        new_span = old_span * (0.8 if delta_y > 0 else 1.25)
        new_span = _clamp(new_span, 4.0, 100.0)
        frac = _clamp((pos.x() - plot.left()) / plot.width(), 0.0, 1.0)
        anchor = self.start + frac * old_span
        self.start = anchor - frac * new_span
        self.end = self.start + new_span
        self.start, self.end = self._clamp_span(self.start, self.end)
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
        plot = self._plot()
        if plot.width() <= 0:
            return
        shift = -dx_px / plot.width() * 100.0
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
            and self._plot().contains(pos)
        ):
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
            return True
        return False

    def hitTest(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# brush
# ---------------------------------------------------------------------------


class BrushComponent(QObject):
    """矩形刷选：Grid 上拖出半透明框，命中数据点集合并高亮。

    option::

        "brush": {"toolbox": ["rect", "clear"], "outOfBrush": {"opacity": 0.4}}

    松开后命中点列表存入 ``self.selected_items``（元素为
    {"series", "dataIndex", "value", "x"}），并发出 ``selected(list)``
    信号；配置了 ``outOfBrush`` 时框外区域以背景色降透明遮罩。
    再次按下开始新一次刷选并清空旧选区。选中点由 ``paint`` 绘制高亮环。

    **与 dataZoom inside 共存时的显式优先级**：本组件配置后 plot 内左键
    拖拽归刷选，dataZoom inside 仅保留滚轮缩放。
    """

    optionKey = "brush"

    #: 刷选完成信号：list[{"series","dataIndex","value","x"}]
    selected = pyqtSignal(list)

    #: 选中点高亮环半径（px）
    HIGHLIGHT_R = 7.0

    def __init__(self, chart, opt):
        super().__init__()
        self.chart = chart
        self.opt = dict(opt or {})
        self._rect = None  # 当前选框 QRectF（None 表示无选区）
        self._anchor = None  # 拖拽起点
        #: lasso（套索）轨迹点；``brush.type == "lasso"`` 时使用
        self._poly = []
        #: 是否接管拖拽（``setDragMode`` 用；``False`` 时 onMouse* 一律放行）
        self.enabled = True
        self.selected_items = []

    def _plot(self) -> QRectF:
        coord = self.chart.primaryCoord()
        if isinstance(coord, GridCoord):
            return coord.plot
        return QRectF()

    def brush_type(self) -> str:
        """刷选形态：``rect``（默认，框选）/ ``lasso``（套索，Plotly 同款）。"""
        raw = self.opt.get("type", self.opt.get("brushType", "rect"))
        name = str(raw or "rect").strip().lower()
        return "lasso" if name in ("lasso", "free", "polygon") else "rect"

    def onMousePress(self, pos: QPointF) -> bool:
        if not self.enabled:
            return False
        plot = self._plot()
        if plot.isNull() or not plot.contains(pos):
            # 绘图区外按下：把已有选框收掉（框选是「框不消失」，但点出去该让它走）。
            # 返回 False 不消费事件，别的组件 / 宿主照常拿到这次按下。
            if self._rect is not None or self._poly:
                self.clear()
            return False
        self._anchor = QPointF(pos)
        self._poly = [QPointF(pos)]
        self._rect = QRectF(pos, pos)
        self.selected_items = []
        self.chart.update()
        return True

    def onMouseMove(self, pos: QPointF) -> bool:
        if not self.enabled or self._anchor is None:
            return False
        if self.brush_type() == "lasso":
            # 采样点距 <2px 不记，套索轨迹不必要地密集会拖慢 containsPoint
            if not self._poly or (
                math.hypot(self._poly[-1].x() - pos.x(), self._poly[-1].y() - pos.y())
                >= 2.0
            ):
                self._poly.append(QPointF(pos))
            self._rect = QRectF(self._anchor, pos).normalized()
        else:
            self._rect = QRectF(self._anchor, pos).normalized()
        self.chart.update()
        return True

    def onMouseRelease(self, pos: QPointF) -> bool:
        if not self.enabled or self._anchor is None:
            return False
        self._rect = QRectF(self._anchor, pos).normalized()
        if self.brush_type() == "lasso":
            self._poly.append(QPointF(pos))
        self._anchor = None
        too_small = (
            self._rect is not None
            and self._rect.width() < 3
            and self._rect.height() < 3
        ) or (self.brush_type() == "lasso" and len(self._poly) < 4)
        if too_small:
            self.clear()  # 视为单击：清除选区
        elif str(getattr(self.chart, "_drag_mode", "")) == "zoom":
            # 框选缩放（Plotly ``dragmode="zoom"``）：选框是**一次性手势** ——
            # 缩放落地后主动消失；「框选」（select / lasso）才把选框与选中集
            # 留在画面上（直到下一次点击 / 重新框选）。
            self._zoom_to_rect()
            self.clear()
        else:
            self._collect()
        self.chart.update()
        if self._rect is not None:
            self.selected.emit(list(self.selected_items))
        return True

    def clear(self) -> None:
        """清除选框与选中集（框选缩放完成后 / 宿主 ``brush clear`` 动作）。"""
        self._rect = None
        self._poly = []
        self.selected_items = []
        self.chart.update()

    def _zoom_to_rect(self) -> None:
        """把当前选框映射成 dataZoom 窗口（``dragmode="zoom"``）。

        比例直接按**当前 dataZoom 窗口**换算：``start/end`` 是相对全量范围的
        百分比，先缩到 20-80 再框一小块时必须叠加，否则会跳回全量。
        """
        coord = self.chart.primaryCoord()
        rect = self._rect
        if rect is None or not isinstance(coord, GridCoord) or rect.width() <= 0:
            return
        comp = self.chart._component("dataZoom")
        if comp is None:
            comp = self.chart._ensure_zoom_component()
        if comp is None:
            return
        plot = coord.plot
        if plot.width() <= 0:
            return
        span = float(comp.end) - float(comp.start)
        if span <= 0:
            return
        frac0 = _clamp((rect.left() - plot.left()) / plot.width(), 0.0, 1.0)
        frac1 = _clamp((rect.right() - plot.left()) / plot.width(), 0.0, 1.0)
        start = float(comp.start) + min(frac0, frac1) * span
        end = float(comp.start) + max(frac0, frac1) * span
        if end - start < 0.5:
            return
        self.chart.dispatchAction(
            {"type": "dataZoom", "start": start, "end": end, "fromBrush": True}
        )

    def _collect(self) -> None:
        """统计选框内的数据点（经 parseDataPoint + coord 映射，通用各系列）。"""
        self.selected_items = []
        coord = self.chart.primaryCoord()
        polygon = None
        if self.brush_type() == "lasso":
            if len(self._poly) < 3:
                return
            polygon = QPolygonF([QPointF(pt) for pt in self._poly])
        elif self._rect is None:
            return
        if not isinstance(coord, GridCoord):
            return
        for r in self.chart.seriesRenderers:
            if not r.visible:
                continue
            series_coord = self.chart.coordFor(r.opt)
            if not isinstance(series_coord, GridCoord):
                continue
            for i, item in enumerate(r.data()):
                x, y = parseDataPoint(item, i)
                if y is None:
                    continue
                if series_coord.x_axis.type == "category":
                    idx = series_coord.x_axis.localIndex(x)
                    n = len(series_coord.x_axis.categories)
                    if not (0 <= idx < n):
                        continue  # 窗口外数据点跳过（不映射，防坍缩误选）
                try:
                    pt = series_coord.mapPoint(x, y)
                except Exception:
                    continue
                inside = (
                    polygon.containsPoint(pt, Qt.FillRule.OddEvenFill)
                    if polygon is not None
                    else self._rect.contains(pt)
                )
                if inside:
                    self.selected_items.append(
                        {"series": r.name, "dataIndex": i, "value": y, "x": x}
                    )

    def _highlight_points(self) -> list:
        """选中点像素位置列表 [(QPointF, QColor)]（绘制高亮用）。"""
        out = []
        coord = self.chart.primaryCoord()
        if not isinstance(coord, GridCoord):
            return out
        renderers = {r.name: r for r in self.chart.seriesRenderers}
        for item in self.selected_items:
            r = renderers.get(item.get("series"))
            if r is None or not r.visible:
                continue
            y = item.get("value")
            if y is None:
                continue
            series_coord = self.chart.coordFor(r.opt)
            if not isinstance(series_coord, GridCoord):
                continue
            try:
                pt = series_coord.mapPoint(item.get("x"), y)
            except Exception:
                continue
            if not series_coord.plot.adjusted(-2, -2, 2, 2).contains(pt):
                continue
            out.append((pt, r.color()))
        return out

    def _paint_lasso(self, p: QPainter) -> None:
        """套索轨迹：半透明填充 + 描边（矩形刷选的同一套强调色语义）。"""
        accent = QColor(T("color.primary"))
        fill = QColor(accent)
        fill.setAlpha(30)
        stroke = QColor(accent)
        stroke.setAlpha(140)
        polygon = QPolygonF([QPointF(pt) for pt in self._poly])
        p.save()
        p.setBrush(fill)
        pen = QPen(stroke, 1.2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolygon(polygon)
        p.restore()

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        # 选中点高亮（无论选框是否仍在，选中集持续可见）
        if self.selected_items:
            self._paint_highlight(p)
        if self.brush_type() == "lasso" and len(self._poly) >= 2:
            self._paint_lasso(p)
            return
        if self._rect is None or self._rect.isNull():
            return
        plot = self._plot()
        rect = self._rect.intersected(plot) if not plot.isNull() else self._rect
        p.save()
        # outOfBrush：框外降透明遮罩
        if self.opt.get("outOfBrush") and not plot.isNull():
            mask = QColor(T("color.bg.base"))
            op = _to_float((self.opt.get("outOfBrush") or {}).get("opacity"), 0.45)
            mask.setAlpha(int(255 * _clamp(op if op is not None else 0.45, 0.0, 1.0)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mask)
            p.drawRect(
                QRectF(
                    plot.left(),
                    plot.top(),
                    max(0.0, rect.left() - plot.left()),
                    plot.height(),
                )
            )
            p.drawRect(
                QRectF(
                    rect.right(),
                    plot.top(),
                    max(0.0, plot.right() - rect.right()),
                    plot.height(),
                )
            )
            p.drawRect(
                QRectF(
                    rect.left(),
                    plot.top(),
                    rect.width(),
                    max(0.0, rect.top() - plot.top()),
                )
            )
            p.drawRect(
                QRectF(
                    rect.left(),
                    rect.bottom(),
                    rect.width(),
                    max(0.0, plot.bottom() - rect.bottom()),
                )
            )
        fill = QColor(T("color.primary"))
        fill.setAlpha(36)
        p.setBrush(fill)
        pen = QPen(QColor(T("color.primary")), 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(rect)
        p.restore()

    def _paint_highlight(self, p: QPainter) -> None:
        """绘制选中点高亮：系列色描边环 + 亮色内芯。"""
        p.save()
        r = self.HIGHLIGHT_R
        for pt, color in self._highlight_points():
            ring = QColor(color)
            ring.setAlpha(200)
            pen = QPen(ring, 1.8)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(pt, r, r)
            core = QColor(color).lighter(140)
            core.setAlpha(120)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(core)
            p.drawEllipse(pt, r * 0.45, r * 0.45)
        p.restore()

    def layout(self, rect: QRectF) -> None:
        pass

    def hitTest(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# visualMap
# ---------------------------------------------------------------------------


class VisualMapComponent:
    """连续视觉映射：值 → 颜色，右下 / 底部渐变条 + 两端数值标签。

    option::

        "visualMap": {"min": 0, "max": 100,
                      "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]},
                      "orient": "vertical"|"horizontal"}

    ``mapColor(v)`` 为公共方法：系列（map / heatmap 等）经
    ``chart.components`` 查找本组件调用。colors 缺省为
    primary.subtle → primary（T() 实时取，主题感知）。

    **绑定**：``seriesIndex``（int）或 ``seriesId``（str）把本 visualMap
    限定给某一个系列（ECharts 语义）；两者都不给就是「通用」，任何系列都能用。
    没有绑定语义时，多个 map / heatmap 系列会**全部拿到同一个** visualMap
    （原先是「谁排在前面谁赢」），于是给第二个系列配的独立色带永远不生效。
    """

    optionKey = "visualMap"
    #: 顶层数组要为每个元素各建一个实例（ECharts 的 visualMap 就是数组语义）。
    #: 不声明的话 ``visualMap: [{...}, {...}]`` 会把整个 list 塞进
    #: ``dict(opt or {})`` 抛 ``ValueError``，被 ``_spawn_component`` 吞掉 ——
    #: **一个 visualMap 都建不起来**。
    spawnPerItem = True

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = dict(opt or {})
        self.min = _to_float(self.opt.get("min"), 0.0) or 0.0
        self.max = _to_float(self.opt.get("max"), 100.0)
        if self.max is None:
            self.max = 100.0
        if self.max <= self.min:
            self.max = self.min + 1.0
        self.orient = (
            "horizontal" if str(self.opt.get("orient")) == "horizontal" else "vertical"
        )
        self._bar = QRectF()

    # -- 绑定 ---------------------------------------------------------------
    def bindsTo(self, series_index: int, series_id: str = "") -> bool:
        """本 visualMap 是否服务于给定系列。

        判定顺序（与 ECharts 一致）：显式绑定优先，其次「未绑定的通用
        visualMap」，都不匹配才算不适用。**通用件必须排在显式绑定之后** ——
        反过来的话一个都没绑定的 visualMap 会把所有系列都抢走。
        """
        idx = self.opt.get("seriesIndex")
        sid = self.opt.get("seriesId")
        if isinstance(idx, int) and not isinstance(idx, bool):
            return idx == series_index
        if sid is not None and str(sid):
            return bool(series_id) and str(sid) == str(series_id)
        return True

    @property
    def isGeneric(self) -> bool:
        """未绑定任何系列的通用 visualMap。"""
        idx = self.opt.get("seriesIndex")
        sid = self.opt.get("seriesId")
        if isinstance(idx, int) and not isinstance(idx, bool):
            return False
        return not (sid is not None and str(sid))

    # -- 公共 API ----------------------------------------------------------
    def colors(self) -> list:
        """生效色带（inRange.colors 覆盖；缺省 primary.subtle→primary）。"""
        in_range = self.opt.get("inRange") or {}
        cols = in_range.get("colors") if isinstance(in_range, dict) else None
        if isinstance(cols, list) and len(cols) >= 2:
            return [str(c) for c in cols]
        return [T("color.primary.subtle"), T("color.primary")]

    def reserveRight(self) -> float:
        """右侧需预留的宽度（竖直色带 + 两端数值标签）；横向为 0。"""
        if self.orient == "vertical":
            return 50.0
        return 0.0

    def reserveBottom(self) -> float:
        """底部需预留的高度（横向色带 + 标签）；竖直为 0（占右侧）。"""
        if self.orient == "horizontal":
            return 30.0
        return 0.0

    def mapColor(self, v) -> QColor:
        """值 → 颜色（按 min..max 归一后在色带上分段线性插值）。"""
        fv = _to_float(v, None)
        if fv is None:
            return QColor(T("color.bg.muted"))
        frac = _clamp((fv - self.min) / (self.max - self.min), 0.0, 1.0)
        cols = [QColor(c) for c in self.colors()]
        if len(cols) == 1:
            return cols[0]
        seg = frac * (len(cols) - 1)
        i = min(int(seg), len(cols) - 2)
        t = seg - i
        a, b = cols[i], cols[i + 1]
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        )

    # -- 布局 / 绘制 ---------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        if self.orient == "vertical":
            w, h = 12.0, min(120.0, max(40.0, rect.height() * 0.4))
            # 右侧预留 38px：色带 12 + 右侧数值标签 34（避免标签越界被裁剪）
            x = rect.right() - w - 38
            y = rect.bottom() - h - 12
        else:
            w, h = min(140.0, max(60.0, rect.width() * 0.35)), 12.0
            x = rect.center().x() - w / 2
            # 底部预留 30px：标签在色带上方，整条落在专属条带内
            y = rect.bottom() - h - 4
        self._bar = QRectF(x, y, w, h)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if self._bar.isNull():
            return
        p.save()
        cols = self.colors()
        if self.orient == "vertical":
            grad = QLinearGradient(self._bar.bottomLeft(), self._bar.topLeft())
        else:
            grad = QLinearGradient(self._bar.topLeft(), self._bar.topRight())
        n = len(cols)
        for i, c in enumerate(cols):
            grad.setColorAt(i / (n - 1) if n > 1 else 0.0, QColor(c))
        path = QPainterPath()
        path.addRoundedRect(self._bar, 3, 3)
        p.setPen(QPen(QColor(T("color.border")), 1))
        p.setBrush(grad)
        p.drawPath(path)
        # 两端数值标签
        font = chartFont(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QColor(T("color.text.secondary")))
        hi, lo = formatValue(self.max), formatValue(self.min)
        if self.orient == "vertical":
            p.drawText(
                QRectF(
                    self._bar.right() + 4,
                    self._bar.top() - fm.height() / 2,
                    34,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                hi,
            )
            p.drawText(
                QRectF(
                    self._bar.right() + 4,
                    self._bar.bottom() - fm.height() / 2,
                    34,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                lo,
            )
        else:
            p.drawText(
                QRectF(self._bar.left() - 38, self._bar.top() - 2, 34, fm.height() + 4),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                lo,
            )
            p.drawText(
                QRectF(self._bar.right() + 4, self._bar.top() - 2, 34, fm.height() + 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                hi,
            )
        p.restore()

    def hitTest(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------


class ChartTimeline(QObject):
    """图表时间轴：底部轴（节点圆点 + 标签）+ 播放 / 暂停按钮。

    option::

        "timeline": {"data": ["2024", "2025", "2026"], "currentIndex": 0,
                     "autoPlay": False, "playInterval": 1500}
        "baseOption": {基础 option}          # 顶层（可选）
        "options": [帧0 option, 帧1 option, ...]   # 顶层

    切换帧：``goto(i)`` → ``baseOption`` 深合并 ``options[i]`` 后
    ``setOption(..., notMerge=True)``（保留过渡动画与时间轴结构）。
    当前帧下标与播放状态挂在 chart 上（``_timeline_index`` /
    ``_timeline_playing``），重建组件后状态不丢；重建时旧 QTimer 会被
    停止并删除，不会累积。
    """

    optionKey = "timeline"

    #: 底部条带高度
    BAND_H = 44.0

    def __init__(self, chart, opt):
        super().__init__()
        self.chart = chart
        self.opt = dict(opt or {})
        self.labels = [str(d) for d in (self.opt.get("data") or [])]
        if "currentIndex" in self.opt:
            current = int(_to_float(self.opt.get("currentIndex"), 0) or 0)
        else:
            current = int(getattr(chart, "_timeline_index", 0) or 0)
        self.current = _clamp(current, 0, max(0, len(self.labels) - 1))
        chart._timeline_index = self.current
        playing = getattr(chart, "_timeline_playing", None)
        if playing is None:
            playing = bool(self.opt.get("autoPlay", False))
        self._playing = bool(playing)
        chart._timeline_playing = self._playing
        # 定时器（父对象 chart；重建时清理旧实例防累积）
        prev = getattr(chart, "_timeline_timer", None)
        if prev is not None:
            try:
                prev.stop()
                prev.deleteLater()
            except Exception:
                pass
        self._timer = QTimer(chart)
        play_interval_ms = int(_to_float(self.opt.get("playInterval"), 1500) or 1500)
        self._timer.setInterval(play_interval_ms)
        self._timer.timeout.connect(self._advance)
        chart._timeline_timer = self._timer
        if self._playing:
            # 持续动效：Reduced/Disabled 下 timeline 不自动推进（当前帧照常显示，
            # 用户仍可 goto / 点播放按钮手动切帧）。
            start_idle_loop(self._timer, play_interval_ms)
        self._band = QRectF()
        self._play_rect = QRectF()
        self._node_pts = []  # [QPointF]

    def dispose(self) -> None:
        """停表并从 chart 上解挂（``core._rebuild`` 丢弃旧组件时调用）。

        必须连 ``deleteLater()`` 一起做：定时器的 parent 是 chart，光 ``stop()``
        会让它变成一个挂在 chart 上的停摆 QObject —— 每次 ``setOption`` 泄一个。
        注意 ``goto()`` 是从本组件的 ``_advance``（定时器回调）里进来的，此时
        ``_rebuild`` 会 dispose 到自己 —— ``deleteLater`` 是延迟投递，qt 派发完
        当前事件才落地，所以不会在发射过程中析构。
        """
        if getattr(self.chart, "_timeline_timer", None) is self._timer:
            self.chart._timeline_timer = None
        try:
            self._timer.stop()
            self._timer.deleteLater()
        except Exception:
            pass

    # -- 帧切换 --------------------------------------------------------------
    def goto(self, index: int) -> None:
        """切换到第 index 帧（经 chart 刷新：``baseOption`` 深合并 ``options[i]``）。"""
        n = max(1, len(self.labels))
        index = int(index) % n
        self.current = index
        self.chart._timeline_index = index
        opt = getattr(self.chart, "_option", None)
        if isinstance(opt, dict) and isinstance(opt.get("timeline"), dict):
            # 同步 currentIndex：帧合并时以 timeline.currentIndex 为准
            opt["timeline"]["currentIndex"] = index
        refresh = getattr(self.chart, "_refresh", None)
        if callable(refresh):
            refresh()
        else:
            self.chart.update()
        self.chart.timelineChanged.emit(index)

    def _advance(self) -> None:
        # Qt 定时器回调中抛出的异常会终止进程：整体包裹并停表
        try:
            if self.labels:
                self.goto(self.current + 1)
        except Exception:
            timer = getattr(self, "_timer", None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass

    def togglePlay(self) -> None:
        """播放 / 暂停切换。"""
        self._playing = not self._playing
        self.chart._timeline_playing = self._playing
        if self._playing:
            self._timer.start()
        else:
            self._timer.stop()
        self.chart.update()

    @property
    def playing(self) -> bool:
        return self._playing

    def reserveBottom(self) -> float:
        """底部时间轴条带高度（含间距；无标签时为 0）。"""
        if self.labels:
            return self.BAND_H + 4.0
        return 0.0

    # -- 布局 / 绘制 ---------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        h = self.BAND_H
        self._band = QRectF(
            rect.left() + 8, rect.bottom() - h - 2, max(60.0, rect.width() - 16), h
        )
        btn = 22.0
        self._play_rect = QRectF(
            self._band.left(), self._band.center().y() - btn / 2, btn, btn
        )
        # 节点均匀分布于按钮右侧区域
        self._node_pts = []
        n = len(self.labels)
        if n:
            x0 = self._play_rect.right() + 24
            x1 = self._band.right() - 16
            cy = self._band.center().y() - 6
            for i in range(n):
                x = x0 if n == 1 else x0 + (x1 - x0) * i / (n - 1)
                self._node_pts.append(QPointF(x, cy))

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self.labels or not self._node_pts:
            return
        p.save()
        font = chartFont(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        primary = QColor(T("color.primary"))
        c_line = QColor(T("color.border.strong"))
        c_text = QColor(T("color.text.secondary"))
        # 轴线
        p.setPen(QPen(c_line, 1))
        p.drawLine(self._node_pts[0], self._node_pts[-1])
        # 节点 + 标签
        for i, (pt, label) in enumerate(zip(self._node_pts, self.labels)):
            cur = i == self.current
            p.setPen(QPen(primary if cur else c_line, 1.6))
            p.setBrush(primary if cur else QColor(T("color.bg.elevated")))
            r = 5.0 if cur else 4.0
            p.drawEllipse(pt, r, r)
            p.setPen(primary if cur else c_text)
            p.drawText(
                QRectF(pt.x() - 40, pt.y() + 8, 80, fm.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                label,
            )
        # 播放 / 暂停按钮
        p.setPen(QPen(c_line, 1.2))
        p.setBrush(QColor(T("color.bg.elevated")))
        p.drawEllipse(self._play_rect)
        c = self._play_rect.center()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T("color.text.secondary")))
        if self._playing:
            # 暂停：双竖条
            p.drawRect(QRectF(c.x() - 5, c.y() - 5, 3.4, 10))
            p.drawRect(QRectF(c.x() + 1.6, c.y() - 5, 3.4, 10))
        else:
            # 播放：三角
            path = QPainterPath()
            path.moveTo(QPointF(c.x() - 3.5, c.y() - 5.5))
            path.lineTo(QPointF(c.x() - 3.5, c.y() + 5.5))
            path.lineTo(QPointF(c.x() + 5.5, c.y()))
            path.closeSubpath()
            p.drawPath(path)
        p.restore()

    # -- 交互 ---------------------------------------------------------------
    def onMousePress(self, pos: QPointF) -> bool:
        if self._play_rect.adjusted(-3, -3, 3, 3).contains(pos):
            self.togglePlay()
            return True
        for i, pt in enumerate(self._node_pts):
            if (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2 <= 100:
                if i != self.current:
                    self.goto(i)
                return True
        return False

    def hitTest(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# toolbox
# ---------------------------------------------------------------------------


class ToolboxComponent:
    """右上角图标按钮组（**真实 ``ElaIconButton`` 子控件**，不再自绘）。

    option::

        "toolbox": {"feature": ["saveAsImage", "saveAsSvg", "dataZoom", "restore", "zoomIn", "zoomOut"]}

    - saveAsImage / saveAsSvg：``chart.saveImage()`` / ``saveImage(format="svg")``；
    - restore：重置全部 dataZoom 组件窗口 + 恢复所有系列显隐；
    - dataZoom：切换 inside 缩放可用状态（``chart._dataZoomEnabled``，按钮
      ``IsSelected`` 反映「缩放开着」）；
    - zoomIn / zoomOut：``chart.zoomStep(0.7)`` / ``chart.zoomStep(1 / 0.7)``。

    按钮是 chart 的子控件：悬停 / 按下 / 禁用 / 深浅主题全交给 ``ElaIconButton``
    （图标来自 Ela 图标字体，配色跟 ``eTheme``），组件只负责摆放与动作分发 ——
    ``layout()`` 每帧幂等 ``move()``，不重建控件。可注入
    ``comp.on_action = fn(name)`` 回调观察点击。
    """

    optionKey = "toolbox"

    #: 按钮边长 / 间隙 / 图标像素尺寸 / 距绘图区右上角的边距
    BTN = 26.0
    GAP = 4.0
    ICON_PX = 15
    MARGIN = 8.0
    TOP = 4.0

    _KNOWN = (
        "saveAsImage",
        "saveAsSvg",
        "dataZoom",
        "restore",
        "zoomIn",
        "zoomOut",
    )

    #: 功能 → Ela 图标（``ElaIconType.IconName``）
    ICONS = {
        "saveAsImage": ElaIconType.IconName.Image,
        "saveAsSvg": ElaIconType.IconName.FileVector,
        "dataZoom": ElaIconType.IconName.MagnifyingGlass,
        "restore": ElaIconType.IconName.ArrowRotateRight,
        "zoomIn": ElaIconType.IconName.MagnifyingGlassPlus,
        "zoomOut": ElaIconType.IconName.MagnifyingGlassMinus,
    }

    #: 功能 → 提示文案（``toolTip`` 与 ``accessibleName`` 共用）
    TIPS = {
        "saveAsImage": "导出 PNG",
        "saveAsSvg": "导出 SVG 矢量图",
        "dataZoom": "缩放开关",
        "restore": "还原视图",
        "zoomIn": "放大",
        "zoomOut": "缩小",
    }

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = dict(opt or {})
        feat = self.opt.get("feature")
        names = []
        if isinstance(feat, dict):
            names = [k for k, v in feat.items() if v]
        elif isinstance(feat, (list, tuple)):
            names = [str(f) for f in feat]
        else:
            names = list(self._KNOWN)
        self.features = [n for n in names if n in self._KNOWN] or list(self._KNOWN)
        #: 动作回调（可注入）：fn(feature_name)
        self.on_action = None
        #: 最近一次 saveAsImage / saveAsSvg 的保存路径
        self.last_saved = None
        #: 几何镜像 ``[(name, QRectF)]``（与子控件同步；定位与测试用）
        self._buttons = []
        #: ``{name: ElaIconButton}``（chart 的子控件）
        self._widgets: dict = {}

    # -- 布局 ---------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        """把按钮摆到绘图区右上角（每次布局幂等重放，不重建控件）。"""
        self._buttons = []
        count = len(self.features)
        if count <= 0:
            return
        enabled = bool(
            getattr(self.chart, "isInteractionEnabled", lambda _f: True)("toolbox")
        )
        zoom_on = bool(getattr(self.chart, "_dataZoomEnabled", True))
        x = rect.right() - self.MARGIN - count * self.BTN - (count - 1) * self.GAP
        y = rect.top() + self.TOP
        for name in self.features:
            self._buttons.append((name, QRectF(x, y, self.BTN, self.BTN)))
            button = self._ensure_button(name)
            if button is not None:
                button.move(int(round(x)), int(round(y)))
                button.setVisible(True)
                button.setEnabled(enabled)
                if name == "dataZoom":
                    button.setIsSelected(zoom_on)
            x += self.BTN + self.GAP

    def buttonRect(self, name: str) -> QRectF:
        """指定功能按钮的矩形（未找到返回空矩形）。"""
        for n, r in self._buttons:
            if n == name:
                return QRectF(r)
        return QRectF()

    def buttonWidget(self, name: str):
        """指定功能的 ``ElaIconButton`` 子控件（未创建返回 ``None``）。"""
        return self._widgets.get(name)

    def _ensure_button(self, name: str):
        button = self._widgets.get(name)
        if button is not None and not is_deleted(button):
            return button
        icon = self.ICONS.get(name)
        if icon is None:
            return None
        try:
            button = ElaIconButton(
                coerceElaIcon(icon),
                self.ICON_PX,
                int(round(self.BTN)),
                int(round(self.BTN)),
                self.chart,
            )
        except Exception as exc:  # 图标字体 / 绑定异常不拖垮整图
            warn_once(
                warn_key("toolbox-icon", name, type(exc).__name__),
                f"工具条按钮创建失败（{name}）: {exc!r}",
            )
            return None
        # 图表是「画布型」控件：按钮不参与 Tab 焦点链（键盘交互归宿主）
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip(self.TIPS.get(name, name))
        button.setAccessibleName(self.TIPS.get(name, name))
        button.clicked.connect(lambda _checked=False, n=name: self.trigger(n))
        self._widgets[name] = button
        return button

    def dispose(self) -> None:
        """丢弃子控件（``core`` 重建组件 / 图表析构路径）。"""
        for button in list(self._widgets.values()):
            if not is_deleted(button):
                button.setParent(None)
                button.deleteLater()
        self._widgets.clear()
        self._buttons = []

    def onInteractionChanged(self) -> None:
        """交互开关变化：立即同步按钮启用态（子控件不跟 chart 的重绘走）。"""
        enabled = bool(
            getattr(self.chart, "isInteractionEnabled", lambda _f: True)("toolbox")
        )
        for button in self._widgets.values():
            if not is_deleted(button):
                button.setEnabled(enabled)

    # -- 动作 ---------------------------------------------------------------
    def trigger(self, name: str) -> None:
        """执行指定功能（按钮点击或外部调用）。"""
        if callable(self.on_action):
            try:
                self.on_action(name)
            except Exception:
                pass
        if name == "saveAsImage":
            self._save_image()
        elif name == "saveAsSvg":
            self._save_image(svg=True)
        elif name == "restore":
            self._restore()
        elif name == "zoomIn":
            self.chart.zoomStep(0.7)
        elif name == "zoomOut":
            self.chart.zoomStep(1.0 / 0.7)
        elif name == "dataZoom":
            cur = bool(getattr(self.chart, "_dataZoomEnabled", True))
            self.chart._dataZoomEnabled = not cur
            # 按钮是子控件，外观不跟 chart 的重绘走：状态要当场同步
            button = self._widgets.get("dataZoom")
            if button is not None and not is_deleted(button):
                button.setIsSelected(not cur)
                button.setToolTip(
                    f"{self.TIPS['dataZoom']}（当前：{'开' if not cur else '关'}）"
                )
            self.chart.update()

    def _save_image(self, svg: bool = False) -> None:
        if svg:
            path = self.chart.saveImage(format="svg")
        else:
            path = self.chart.saveImage()
        self.last_saved = path or None

    def _restore(self) -> None:
        """恢复初始状态（经 chart._restore_state 统一复位并发出 restore 事件）。"""
        restore_state = getattr(self.chart, "_restore_state", None)
        if callable(restore_state):
            restore_state()
            return
        for comp in self.chart.components:
            restore = getattr(comp, "restore", None)
            if callable(restore) and comp is not self:
                try:
                    restore()
                except Exception:
                    pass
        self.chart.update()

    # -- 绘制 ---------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        """无绘制：按钮是真实子控件，外观由 ``ElaIconButton`` 负责。"""


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

registerComponent("dataZoom", DataZoomComponent)
registerComponent("brush", BrushComponent)
registerComponent("visualMap", VisualMapComponent)
registerComponent("timeline", ChartTimeline)
registerComponent("toolbox", ToolboxComponent)
