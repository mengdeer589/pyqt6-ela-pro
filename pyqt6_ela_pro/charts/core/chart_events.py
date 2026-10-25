"""ElaChartWidget 的事件注册 / 分发与图表组联动方法组。"""

from __future__ import annotations

from typing import TYPE_CHECKING


import weakref

from PyQt6.QtCore import (
    QPointF,
)

from .._utils import warn_once
from ..axes import (
    GridCoord,
)
from ._shared import (
    _CHART_GROUPS,
    _group_members,
)


if TYPE_CHECKING:
    from .widget import ElaChartWidget


class _ChartEventsMixin:
    """方法组 mixin：状态由 ``ElaChartWidget.__init__`` 建立。"""

    def setGroup(self, name: str) -> "ElaChartWidget":
        """设置图表组名（配合 ``connectCharts(group)`` 跨图联动）。"""
        key = str(name).strip() if name else None
        if key == self._group:
            return self
        self._leaveGroupHandlers()
        self._group = key or None
        if self._group:
            alive = [c for c in _group_members(self._group) if c is not self]
            alive.append(self)
            _CHART_GROUPS[self._group] = [weakref.ref(c) for c in alive]
            self._joinGroupHandlers(self._group)
        return self

    def _joinGroupHandlers(self, group: str) -> None:
        if self._group_slot is None:
            self._group_slot = self._onGroupEvent
            self._chartEvent.connect(self._group_slot)
        self._group = str(group)

    def _leaveGroupHandlers(self) -> None:
        if self._group_slot is not None:
            try:
                self._chartEvent.disconnect(self._group_slot)
            except (TypeError, RuntimeError):
                pass
            self._group_slot = None

    def _broadcastGroup(self, name: str, params: dict) -> None:
        """向同组其它图广播（自身或正在应用联动时不再转发）。"""
        if self._syncing or not self._group:
            return
        for chart in _group_members(self._group):
            if chart is self:
                continue
            chart._syncing = True
            try:
                chart._applyGroupEvent(name, dict(params or {}))
            except Exception:
                pass
            finally:
                chart._syncing = False

    def _onGroupEvent(self, name: str, params: dict) -> None:
        if self._syncing:
            return
        self._applyGroupEvent(name, params)

    def _applyGroupEvent(self, name: str, params: dict) -> None:
        if name == "datazoom":
            zoom = self._component("dataZoom")
            if zoom is None:
                return
            zoom.adoptWindow(
                {
                    "start": params.get("start", zoom.start),
                    "end": params.get("end", zoom.end),
                }
            )
            zoom.apply()
            self.invalidateLayout()
            self.update()
        elif name == "legendselectchanged":
            selected = params.get("selected")
            if not isinstance(selected, dict):
                return
            for series_name, visible in selected.items():
                self._setSeriesVisible(str(series_name), bool(visible))
            self.update()
        elif name == "axisTip":
            if self.tooltip.trigger != "axis":
                return
            try:
                percent = float(params.get("percent", 0.0))
            except (TypeError, ValueError, OverflowError):
                return
            coord = self.primaryCoord()
            if not isinstance(coord, GridCoord):
                return
            plot = coord.plot
            x = plot.left() + max(0.0, min(1.0, percent)) * plot.width()
            self._tooltip_axis(QPointF(x, plot.center().y()))
            self.update()
        elif name == "axisTipHide":
            self.tooltip.hide()
            self._tooltip_axis_clear()
            self._clear_hover()
            self.update()

    def on(self, eventName: str, handler) -> "ElaChartWidget":
        """注册 ECharts 事件处理器（``chart.on('click', fn)``）。

        handler 接收一个 dict（ECharts params，含 ``type``）。异常被捕获并
        仅告警一次，不会穿透 Qt 事件循环导致进程 abort。
        """
        if not callable(handler):
            raise TypeError("on(eventName, handler): handler 必须可调用")
        self._event_handlers.setdefault(str(eventName), []).append(handler)
        return self

    def off(self, eventName: str = None, handler=None) -> "ElaChartWidget":
        """移除事件处理器（``off()`` 清空 / ``off(name)`` 按事件 / ``off(name, fn)`` 按函数）。"""
        if eventName is None:
            self._event_handlers.clear()
            return self
        key = str(eventName)
        if handler is None:
            self._event_handlers.pop(key, None)
            return self
        handlers = self._event_handlers.get(key)
        if handlers:
            try:
                handlers.remove(handler)
            except ValueError:
                pass
            if not handlers:
                self._event_handlers.pop(key, None)
        return self

    def _emit_event(self, name: str, params: dict) -> None:
        """发射 ECharts 事件（唯一出口；载荷异常不扩散）。"""
        try:
            self._chartEvent.emit(str(name), dict(params or {}))
        except Exception as exc:
            warn_once(f"event-emit:{name}", f"事件参数异常（{name}）：{exc!r}")

    def _dispatch_chart_event(self, name: str, params: dict) -> None:
        for handler in list(self._event_handlers.get(name, ())):
            try:
                handler(dict(params))
            except Exception as exc:
                warn_once(
                    f"event-handler:{name}",
                    f"事件处理器异常（{name}）：{exc!r}",
                )

    def _forward_click(self, params: dict) -> None:
        self._emit_event("click", params)

    def _forward_legend_toggled(self, name: str, visible: bool) -> None:
        self._emit_event(
            "legendselectchanged",
            {
                "type": "legendselectchanged",
                "name": str(name),
                "selected": dict(self._series_state),
            },
        )
        self._broadcastGroup(
            "legendselectchanged", {"selected": dict(self._series_state)}
        )

    def _forward_data_zoom(self, start: float, end: float) -> None:
        self._emit_event(
            "datazoom",
            {
                "type": "datazoom",
                "start": float(start),
                "end": float(end),
                "batch": [{"start": float(start), "end": float(end)}],
            },
        )
        self._broadcastGroup("datazoom", {"start": float(start), "end": float(end)})

    def _forward_timeline_changed(self, index: int) -> None:
        self._emit_event(
            "timelinechanged",
            {"type": "timelinechanged", "currentIndex": int(index)},
        )

    def _forward_brush_selected(self, items: list) -> None:
        selected = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            selected.append(
                {
                    "seriesIndex": self._series_index(item.get("series")),
                    "seriesName": str(item.get("series") or ""),
                    "dataIndex": item.get("dataIndex"),
                    "value": item.get("value"),
                    "name": item.get("name", ""),
                }
            )
        self._emit_event(
            "brushselected",
            {
                "type": "brushselected",
                "batch": [{"brushId": 0, "areas": [], "selected": selected}],
                "selected": selected,
            },
        )

    def _forward_toolbox(self, action: str) -> None:
        if str(action) == "restore":
            self._emit_restore_event()

    def _emit_restore_event(self) -> None:
        self._emit_event("restore", {"type": "restore"})

    def _on_animation_finished(self) -> None:
        if self._disposed:
            return
        try:
            self.finished.emit()
        except Exception:
            pass
        self._emit_event("finished", {"type": "finished"})
