"""带纵向窗口的甘特容器：固定 x 轴，右侧滚动条切换可见任务行。"""

from __future__ import annotations


from datetime import datetime

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaPivot, ElaScrollBar, eTheme

from .._internal import connect_theme_signal
from .._styles import setSolidBackground
from .._theme import surface
from ..ela_button import ElaButton
from ._utils import warn_once
from .axes import GridCoord, _dt_to_ms, _to_timestamp
from .core import ElaChartWidget


class ElaGanttView(QWidget):
    """甘特纵向滚动容器。

    内嵌 ``ElaChartWidget``（``chart()`` 取句柄），x 轴固定在底部；
    右侧 ``ElaScrollBar`` 按行切换 ``dataZoom`` 的 y 窗口。任务数少于
    可见行数时滚动条自动隐藏。可选内置工具条（``ElaPivot``）：全量 / 日 /
    周 / 月 / 今天 / 适应行高。
    """

    #: 拖动甘特任务条结束（转发内嵌 chart 的信号）
    ganttTaskChanged = pyqtSignal(object)
    #: 任务点击 / 双击 / 右键
    ganttTaskClicked = pyqtSignal(object)
    ganttTaskDoubleClicked = pyqtSignal(object)
    ganttTaskContextMenuRequested = pyqtSignal(object)
    #: 进度手柄拖动结束
    ganttProgressChanged = pyqtSignal(object)

    _SCALE_DAYS = {"day": 14, "week": 56, "month": 183}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chart = ElaChartWidget(self)
        self._bar = ElaScrollBar(self)
        self._bar.setFixedWidth(10)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._toolbar = QWidget(self)
        toolbar = QHBoxLayout(self._toolbar)
        toolbar.setContentsMargins(4, 0, 4, 0)
        toolbar.setSpacing(8)
        self._scale_pivot = ElaPivot(self._toolbar)
        self._scale_pivot.setTextPixelSize(12)
        for title in ("全量", "日", "周", "月"):
            self._scale_pivot.appendPivot(title)
        self._scale_pivot.setCurrentIndex(0)
        self._scale_pivot.pivotClicked.connect(self._on_scale_pivot_clicked)
        toolbar.addWidget(self._scale_pivot, 0, Qt.AlignmentFlag.AlignVCenter)
        self._today_btn = ElaButton(
            "今天", variant="text", size="small", parent=self._toolbar
        )
        self._today_btn.setFixedSize(48, 24)
        self._today_btn.clicked.connect(lambda: self._safe(self.goToToday))
        toolbar.addWidget(self._today_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._fit_btn = ElaButton(
            "适应行高", variant="text", size="small", parent=self._toolbar
        )
        self._fit_btn.setFixedSize(72, 24)
        self._fit_btn.clicked.connect(lambda: self._safe(self.fitRows))
        toolbar.addWidget(self._fit_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        toolbar.addStretch(1)
        self._scale_name = ""
        self._toolbar.hide()
        self._sync_toolbar_theme()
        connect_theme_signal(self, self._sync_toolbar_theme)
        outer.addWidget(self._toolbar)
        body = QWidget(self)
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._chart, 1)
        row.addWidget(self._bar, 0)
        outer.addWidget(body, 1)
        self._row_height = 26.0
        self._total_rows = 0
        self._visible_rows = 1
        self._syncing = False
        self._refreshing = False
        self._bar.valueChanged.connect(self._on_scroll)
        self._chart.installEventFilter(self)
        self._chart.ganttTaskChanged.connect(self.ganttTaskChanged.emit)
        self._chart.ganttTaskClicked.connect(self.ganttTaskClicked.emit)
        self._chart.ganttTaskDoubleClicked.connect(self.ganttTaskDoubleClicked.emit)
        self._chart.ganttTaskContextMenuRequested.connect(
            self.ganttTaskContextMenuRequested.emit
        )
        self._chart.ganttProgressChanged.connect(self.ganttProgressChanged.emit)

    def chart(self) -> ElaChartWidget:
        """内嵌图表句柄（事件 / 主题 / 导出都用它）。"""
        return self._chart

    def setOption(self, option, notMerge: bool = False, lazyUpdate: bool = False):
        """同 ``ElaChartWidget.setOption``；纵向窗口由容器管理。

        ``lazyUpdate`` 在容器内忽略：必须立刻重建才能计算行数与滚动范围。
        """
        top = self._bar.value()
        opt = self._prepare_option(option)
        # 容器要在建图后立刻算行高；lazyUpdate 会推迟重建，直接忽略。
        self._chart.setOption(opt, notMerge=notMerge, lazyUpdate=False)
        self._refresh(top)
        return self

    def setRowHeight(self, height: float) -> None:
        """期望行高（px，默认 26）；可见行数 = 绘图区高度 // 行高。"""
        try:
            self._row_height = max(8.0, float(height))
        except (TypeError, ValueError, OverflowError):
            self._row_height = 26.0
        self._refresh(self._bar.value())

    def rowHeight(self) -> float:
        """当前期望行高（px）。"""
        return float(self._row_height)

    def refresh(self) -> None:
        """外部改过数据后重算滚动范围与可见行。"""
        self._refresh(self._bar.value())

    def scrollToRow(self, row: int) -> None:
        """滚动到指定展示行（超过范围会收敛）。"""
        try:
            value = int(row)
        except (TypeError, ValueError, OverflowError):
            return
        self._bar.setValue(value)

    def topRow(self) -> int:
        """当前窗口第一行。"""
        return int(self._bar.value())

    def visibleRows(self) -> int:
        """当前窗口可见行数。"""
        return int(self._visible_rows)

    def setChartTheme(self, name) -> "ElaGanttView":
        """切换内嵌图表的配色主题。"""
        self._chart.setChartTheme(name)
        return self

    def setToolbarVisible(self, visible: bool) -> "ElaGanttView":
        """显示 / 隐藏内置视图工具条（默认隐藏）。"""
        self._toolbar.setVisible(bool(visible))
        if visible:
            self._refresh(self._bar.value())
        return self

    def _sync_toolbar_theme(self, _mode=None) -> None:
        """工具条底色跟随应用明暗主题（按钮文字由 Ela 控件自己接管）。"""
        setSolidBackground(self._toolbar, surface(eTheme.getThemeMode()))

    def toolbarVisible(self) -> bool:
        """工具条是否可见。"""
        return not self._toolbar.isHidden()

    def setScale(self, name: str, anchor=None) -> "ElaGanttView":
        """按日 / 周 / 月切换横向窗口；``anchor`` 可指定中心日期。"""
        key = str(name).strip().lower()
        days = self._SCALE_DAYS.get(key)
        if days is None:
            return self
        full = self._x_full_range()
        if full is None:
            warn_once(
                "gantt-view-scale-time",
                "ElaGanttView.setScale 只支持时间轴甘特图",
            )
            self._sync_scale_pivot()
            return self
        center = self._x_center()
        if anchor is not None:
            stamp = _to_timestamp(anchor)
            if stamp is not None:
                center = stamp
        self._scale_name = key
        self._set_x_window(center, float(days) * 86400000.0)
        self._sync_scale_pivot()
        return self

    def scale(self) -> str:
        """当前缩放档位（``day`` / ``week`` / ``month``；未设置空串）。"""
        return self._scale_name

    def goToToday(self) -> "ElaGanttView":
        """把今天放到横向窗口中心（保持当前窗口跨度）。"""
        full = self._x_full_range()
        if full is None:
            return self
        lo, hi = full
        center = _dt_to_ms(datetime.now())
        center = max(lo, min(center, hi))
        span = self._x_window_span()
        self._set_x_window(center, span)
        return self

    def fitRows(self) -> "ElaGanttView":
        """按可见高度反推行高，让全部任务尽量落在一屏内。"""
        coord = self._chart.primaryCoord()
        if not isinstance(coord, GridCoord):
            return self
        total = self._total_rows
        height = float(coord.plot.height())
        if total <= 0 or height <= 0:
            return self
        self.setRowHeight(max(20.0, height / float(total)))
        return self

    def showFullRange(self) -> "ElaGanttView":
        """横向恢复全量范围（保留纵向窗口）。"""
        self._scale_name = ""
        self._set_x_percent(0.0, 100.0)
        self._sync_scale_pivot()
        return self

    def _x_full_range(self):
        coord = self._chart.primaryCoord()
        if not isinstance(coord, GridCoord) or not coord.x_axis.is_time:
            return None
        extent = getattr(coord.x_axis, "_data_extent", None)
        if extent is None:
            extent = (coord.x_axis.vmin, coord.x_axis.vmax)
        try:
            lo, hi = float(extent[0]), float(extent[1])
        except (TypeError, ValueError, OverflowError, IndexError):
            return None
        if not (lo < hi):
            return None
        return lo, hi

    def _x_center(self) -> float:
        coord = self._chart.primaryCoord()
        if isinstance(coord, GridCoord):
            return (float(coord.x_axis.vmin) + float(coord.x_axis.vmax)) / 2.0
        return 0.0

    def _x_window_span(self) -> float:
        full = self._x_full_range()
        comp = self._chart._component("dataZoom")
        if full is not None and comp is not None:
            pct = max(0.0, min(100.0, float(comp.end) - float(comp.start)))
            if pct > 0:
                return (full[1] - full[0]) * pct / 100.0
        coord = self._chart.primaryCoord()
        if isinstance(coord, GridCoord):
            span = float(coord.x_axis.vmax) - float(coord.x_axis.vmin)
            if span > 0:
                return span
        return (full[1] - full[0]) if full is not None else 86400000.0

    def _set_x_window(self, center: float, span: float) -> None:
        full = self._x_full_range()
        if full is None:
            return
        lo, hi = full
        total = hi - lo
        span = max(86400000.0, min(float(span), total))
        start = max(lo, min(float(center) - span / 2.0, hi - span))
        end = start + span
        self._set_x_percent((start - lo) / total * 100.0, (end - lo) / total * 100.0)

    def _set_x_percent(self, start: float, end: float) -> None:
        comp = self._chart._component("dataZoom")
        y0 = float(getattr(comp, "y_start", 0.0))
        y1 = float(getattr(comp, "y_end", 100.0))
        self._chart.dispatchAction(
            {
                "type": "dataZoom",
                "start": max(0.0, min(100.0, start)),
                "end": max(0.0, min(100.0, end)),
                "yStart": y0,
                "yEnd": y1,
            }
        )

    def _sync_scale_pivot(self) -> None:
        index = {"": 0, "day": 1, "week": 2, "month": 3}.get(self._scale_name, 0)
        if self._scale_pivot.getCurrentIndex() != index:
            self._scale_pivot.setCurrentIndex(index)

    def _on_scale_pivot_clicked(self, index: int) -> None:
        key = ("", "day", "week", "month")
        if not (0 <= index < len(key)):
            return
        if key[index]:
            self._safe(self.setScale, key[index])
        else:
            self._safe(self.showFullRange)

    def sizeHint(self) -> QSize:
        return QSize(800, 420)

    @staticmethod
    def _prepare_option(option):
        """保留第一条 dataZoom 的 x 窗口，强制成隐藏 inside + yAxisIndex。"""
        if not isinstance(option, dict):
            return option
        opt = dict(option)
        raw = option.get("dataZoom")
        entries = []
        if isinstance(raw, dict):
            entries = [dict(raw)]
        elif isinstance(raw, (list, tuple)):
            entries = [dict(entry) for entry in raw if isinstance(entry, dict)]
        first = entries[0] if entries else {}
        y_index = 0
        for series in option.get("series") or []:
            if isinstance(series, dict) and str(series.get("type") or "") == "gantt":
                try:
                    y_index = int(series.get("yAxisIndex", 0) or 0)
                except (TypeError, ValueError, OverflowError):
                    y_index = 0
                break
        first["type"] = "inside"
        first["yAxisIndex"] = max(0, y_index)
        first["yZoom"] = False
        first["zoomOnMouseWheel"] = False
        first["moveOnMouseMove"] = False
        first.pop("show", None)
        opt["dataZoom"] = [first]
        return opt

    def _safe(self, fn, *args) -> None:
        """按钮 / 滚动条回调统一异常边界（Qt 槽异常会终止进程）。"""
        try:
            fn(*args)
        except Exception as exc:
            warn_once(
                f"gantt-view:{getattr(fn, '__name__', fn)}",
                f"甘特容器动作失败: {exc!r}",
            )

    def _refresh(self, top=None) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._refresh_impl(top)
        except Exception as exc:
            warn_once(
                f"gantt-refresh:{type(exc).__name__}",
                f"甘特容器刷新失败: {exc!r}",
            )
        finally:
            self._refreshing = False

    def _refresh_impl(self, top=None) -> None:
        layout = self.layout()
        if layout is not None:
            # setOption 可能早于 show：先激活外层布局，让内嵌 chart 拿到真实尺寸。
            layout.activate()
        self._chart._layout_all(force=True)
        coord = self._chart.primaryCoord()
        if not isinstance(coord, GridCoord) or coord.y_axis.type != "category":
            self._total_rows = 0
            self._visible_rows = 1
            self._bar.hide()
            return
        full = getattr(coord.y_axis, "_all_categories", None) or coord.y_axis.categories
        total = len(full)
        self._total_rows = total
        if total <= 0:
            self._visible_rows = 1
            self._bar.setRange(0, 0)
            self._bar.hide()
            return
        height = max(0.0, coord.plot.height())
        visible = max(1, int(height // max(8.0, self._row_height)))
        visible = min(visible, total)
        self._visible_rows = visible
        if total <= visible:
            self._bar.setRange(0, 0)
            self._bar.setPageStep(max(1, visible))
            self._bar.hide()
            self._apply_window(0, total)
            return
        self._bar.show()
        self._bar.setRange(0, total - visible)
        self._bar.setPageStep(visible)
        self._bar.setSingleStep(1)
        value = 0 if top is None else top
        try:
            value = int(value)
        except (TypeError, ValueError, OverflowError):
            value = 0
        value = max(0, min(value, total - visible))
        self._syncing = True
        try:
            self._bar.setValue(value)
        finally:
            self._syncing = False
        self._apply_window(value, total)

    def _apply_window(self, top: int, total: int) -> None:
        if total <= 0:
            return
        visible = min(self._visible_rows, total)
        top = max(0, min(int(top), total - visible))
        start = top / float(total) * 100.0
        end = (top + visible) / float(total) * 100.0
        comp = self._chart._component("dataZoom")
        x0 = float(getattr(comp, "start", 0.0))
        x1 = float(getattr(comp, "end", 100.0))
        # applyAction 要求至少给 x 的 start/end 才会继续处理 yStart/yEnd。
        self._chart.dispatchAction(
            {
                "type": "dataZoom",
                "start": x0,
                "end": x1,
                "yStart": start,
                "yEnd": end,
            }
        )
        # dataZoom 改了可见类别后必须立刻重排：否则系列几何仍按旧行数算，
        # 首帧会出现「两行巨高任务条」。
        self._chart._layout_all(force=True)

    def _on_scroll(self, value: int) -> None:
        if self._syncing:
            return
        self._safe(self._apply_window, value, self._total_rows)

    def eventFilter(self, obj, event) -> bool:
        try:
            if obj is self._chart and event.type() == QEvent.Type.Resize:
                # 工具条 / 外层布局变化会先改 chart 高度；不重算可见行会留下
                # 「两行巨高任务条」的首帧。
                self._refresh(self._bar.value())
            if (
                obj is self._chart
                and event.type() == QEvent.Type.Wheel
                and self._bar.isVisible()
            ):
                angle = event.angleDelta().y()
                delta = angle or event.pixelDelta().y()
                if delta:
                    notches = max(1, abs(angle) // 120) if angle else 1
                    steps = max(1, self._visible_rows // 3) * notches
                    self._bar.setValue(
                        self._bar.value() + (-steps if delta > 0 else steps)
                    )
                    event.accept()
                    return True
        except Exception as exc:
            warn_once(
                f"gantt-filter:{type(exc).__name__}",
                f"甘特容器事件过滤失败: {exc!r}",
            )
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh(self._bar.value())
