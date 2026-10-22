"""图表鼠标交互协调器（点击 / 悬停 / 图例 / 双击复位 / 滚轮）。"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QWidget


class ChartInteraction:
    """把画布的鼠标事件行为从 ``ElaChartWidget`` 中拆出来。"""

    def __init__(self, chart) -> None:
        self._chart = chart

    def mouse_press(self, event) -> None:
        chart = self._chart
        if chart._loading:
            return
        pos = event.position()
        consumed = chart._dispatch_hook("onMousePress", pos)
        # 拖拽类组件会吞掉按下事件；按下→原地松开仍是点击，记下上下文在松开时补发。
        chart._press_ctx = (QPointF(pos), bool(consumed))
        if consumed:
            QWidget.mousePressEvent(chart, event)
            return
        if chart.legend.shown and chart.isInteractionEnabled("legend"):
            name = chart.legend.hitTest(pos)
            if name is not None:
                chart.legend.toggle(name)
                QWidget.mousePressEvent(chart, event)
                return
        self.emit_click_at(pos, event)
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
            legend_hover = (
                chart.legend.hitTest(pos)
                if chart.legend.shown and chart.isInteractionEnabled("legend")
                else None
            )
            if legend_hover != chart._legend_hover:
                chart._legend_hover = legend_hover
                chart.update()
            if legend_hover is not None:
                if chart.tooltip.active:
                    chart.tooltip.hide()
                if chart._hover is not None:
                    chart._hover = None
                    chart.update()
            elif chart.isInteractionEnabled("tooltip"):
                chart._update_tooltip(pos)
            elif chart.tooltip.active:
                chart.tooltip.hide()
                chart.update()
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
                if chart.legend.shown:
                    over_legend = chart.legend.hitTest(start) is not None
                if not over_legend:
                    self.emit_click_at(pos, event)

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
        if chart._hover is not None:
            chart._hover = None
        if chart._legend_hover is not None:
            chart._legend_hover = None
        chart.update()
        QWidget.leaveEvent(chart, event)
