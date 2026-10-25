"""图表鼠标交互协调器（点击 / 悬停 / 图例 / 双击复位 / 滚轮）。"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtWidgets import QWidget

from .axes import GridCoord


class ChartInteraction:
    """把画布的鼠标事件行为从 ``ElaChartWidget`` 中拆出来。"""

    def __init__(self, chart) -> None:
        self._chart = chart

    def _cursor_shape(self, pos: QPointF):
        """按悬停目标 / 拖拽模式给出光标形状。"""
        chart = self._chart
        if getattr(chart, "_press_ctx", None) is not None and chart.dragMode() == "pan":
            return Qt.CursorShape.ClosedHandCursor
        zoom = chart._component("dataZoom")
        if zoom is not None and getattr(zoom, "has_slider", False):
            handles = (
                getattr(zoom, "_h_start", None),
                getattr(zoom, "_h_end", None),
            )
            for handle in handles:
                if handle is not None and handle.adjusted(-2, -2, 2, 2).contains(pos):
                    return Qt.CursorShape.SizeHorCursor
            track = getattr(zoom, "_track", None)
            if track is not None and track.contains(pos):
                return Qt.CursorShape.PointingHandCursor
        legend = chart.legendAt(pos)
        if legend is not None and chart.isInteractionEnabled("legend"):
            if legend.hitTest(pos) is not None or legend.pageHitTest(pos):
                return Qt.CursorShape.PointingHandCursor
        if chart._hitItemWithSeries(pos) is not None:
            return Qt.CursorShape.PointingHandCursor
        coord = chart.primaryCoord()
        if isinstance(coord, GridCoord) and coord.plot.contains(pos):
            mode = chart.dragMode()
            if mode == "pan":
                return Qt.CursorShape.OpenHandCursor
            if mode in ("zoom", "select", "lasso"):
                return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.ArrowCursor

    def _sync_cursor(self, pos: QPointF) -> None:
        shape = self._cursor_shape(pos)
        chart = self._chart
        if chart.cursor().shape() != shape:
            chart.setCursor(shape)

    def mouse_press(self, event) -> None:
        chart = self._chart
        if chart._loading:
            return
        pos = event.position()
        consumed = chart._dispatch_hook("onMousePress", pos)
        # 拖拽类组件会吞掉按下事件；按下→原地松开仍是点击，记下上下文在松开时补发。
        chart._press_ctx = (QPointF(pos), bool(consumed))
        if consumed:
            if (
                chart.dragMode() == "pan"
                and chart.cursor().shape() != Qt.CursorShape.ClosedHandCursor
            ):
                chart.setCursor(Qt.CursorShape.ClosedHandCursor)
            QWidget.mousePressEvent(chart, event)
            return
        legend = chart.legendAt(pos)
        if legend is not None and chart.isInteractionEnabled("legend"):
            page = legend.pageHitTest(pos)
            if page:
                legend.setPage(page)
                QWidget.mousePressEvent(chart, event)
                return
            name = legend.hitTest(pos)
            if name is not None:
                legend.toggle(name)
                QWidget.mousePressEvent(chart, event)
                return
        self.emit_click_at(pos, event)
        self._sync_cursor(pos)
        QWidget.mousePressEvent(chart, event)

    def emit_click_at(self, pos: QPointF, event=None) -> None:
        """命中数据点 → ``itemClicked``；空区且开 ``clickanywhere`` → 数据坐标载荷。"""
        chart = self._chart
        if not chart._interactive:
            return
        found = chart._hitItemWithSeries(pos)
        if found is not None:
            renderer, hit = found
            chart.itemClicked.emit(
                chart._make_item_params(renderer, hit, "click", event, pos)
            )
            try:
                chart._handle_select_click(renderer, hit)
            except Exception:
                pass
            return
        if chart._emptyAreaEnabled("clickanywhere"):
            empty = chart._emptyAreaHit(pos)
            if empty is not None:
                empty["type"] = "click"
                empty["event"] = event
                chart.itemClicked.emit(empty)

    def mouse_move(self, event) -> None:
        chart = self._chart
        if chart._loading:
            return
        pos = event.position()
        consumed = chart._dispatch_hook("onMouseMove", pos)
        if not consumed:
            legend = chart.legendAt(pos)
            legend_hover = (
                legend.hitTest(pos)
                if legend is not None and chart.isInteractionEnabled("legend")
                else None
            )
            if legend_hover != chart._legend_hover:
                chart._legend_hover = legend_hover
                chart.update()
            if legend_hover is not None:
                if chart.tooltip.active:
                    chart.tooltip.hide()
                    chart._broadcastGroup("axisTipHide", {})
                if chart._hover is not None:
                    chart._clear_hover()
                    chart.update()
            elif chart.isInteractionEnabled("tooltip"):
                chart._update_tooltip(pos)
            elif chart.tooltip.active:
                chart.tooltip.hide()
                chart.update()
        self._sync_cursor(pos)
        QWidget.mouseMoveEvent(chart, event)

    def mouse_release(self, event) -> None:
        chart = self._chart
        if chart._loading:
            return
        pos = event.position()
        chart._dispatch_hook("onMouseRelease", pos)
        ctx = getattr(chart, "_press_ctx", None)
        chart._press_ctx = None
        if ctx is not None:
            start, consumed = ctx
            dragged = math.hypot(pos.x() - start.x(), pos.y() - start.y()) > 4.0
            if consumed and not dragged:
                over_legend = False
                legend = chart.legendAt(start)
                if legend is not None:
                    over_legend = legend.hitTest(start) is not None
                if not over_legend:
                    self.emit_click_at(pos, event)
        self._sync_cursor(pos)

    def mouse_double_click(self, event) -> None:
        chart = self._chart
        if chart._loading:
            return
        # 标注标签优先：双击标签进入编辑，不触发 resetView
        try:
            if chart._begin_annotation_edit(event.position()):
                event.accept()
                return
        except Exception:
            pass
        if chart._dispatch_hook("onMouseDoubleClick", event.position()):
            QWidget.mouseDoubleClickEvent(chart, event)
            return
        if chart._double_click_reset:
            chart.resetView()
            event.accept()
            return
        QWidget.mouseDoubleClickEvent(chart, event)

    def wheel(self, event) -> None:
        chart = self._chart
        if chart._loading:
            return
        if chart._dispatch_hook("onWheel", event):
            event.accept()
            return
        QWidget.wheelEvent(chart, event)

    def leave(self, event) -> None:
        chart = self._chart
        chart.tooltip.hide()
        chart._tooltip_axis_clear()
        chart._broadcastGroup("axisTipHide", {})
        chart._clear_hover(global_out=True)
        chart.setCursor(Qt.CursorShape.ArrowCursor)
        if chart._legend_hover is not None:
            chart._legend_hover = None
        chart.update()
        QWidget.leaveEvent(chart, event)
