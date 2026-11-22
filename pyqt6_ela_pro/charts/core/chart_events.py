"""ElaChartWidget 的事件注册 / 分发与图表组联动方法组。"""

from __future__ import annotations

from typing import TYPE_CHECKING


import time
import weakref

from PyQt6.QtCore import (
    QPointF,
    QRectF,
)

from .._utils import warn_once
from ..models import ChartEvent, event_from_dict
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
        self._ensure_alive()
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
        if str(name).startswith("axisTip") and not self._axisLinkEnabled():
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
        try:
            self._applyGroupEvent(name, params)
        except Exception as exc:
            warn_once(
                f"group-event:{name}",
                f"图表组事件处理异常（{name}）: {exc!r}",
            )

    def _axisLinkEnabled(self) -> bool:
        """``axisPointer.link`` / ``tooltip.axisPointer.link`` = False 时断开跨图联动。"""
        return self.tooltip._axisPointer().get("link") is not False

    def _applyGroupEvent(self, name: str, params: dict) -> None:
        if name == "universalTransition":
            self._receive_universal(params)
        elif name == "datazoom":
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
            series_names = {r.name for r in self._series}
            for item_name, visible in selected.items():
                key = str(item_name)
                if key in series_names:
                    self._setSeriesVisible(key, bool(visible))
                else:
                    self._setDataItemVisible(key, bool(visible), emit=False)
            self.update()
        elif name == "axisTip":
            if not self._axisLinkEnabled() or self.tooltip.trigger != "axis":
                return
            try:
                percent = float(params.get("percent", 0.0))
            except (TypeError, ValueError, OverflowError):
                return
            coord = self.primaryCoord()
            if not isinstance(coord, GridCoord):
                return
            plot = coord.plot
            value = params.get("value")
            kind = str(params.get("axisKind") or "x").lower()
            try:
                axis_index = max(0, int(params.get("axisIndex", 0) or 0))
            except (TypeError, ValueError, OverflowError):
                axis_index = 0
            frac = max(0.0, min(1.0, percent))
            if kind == "y":
                axes = coord.y_axes
                axis = axes[min(axis_index, len(axes) - 1)] if axes else None
                if value is not None and axis is not None:
                    try:
                        y = axis.map(value, plot.bottom(), plot.top())
                    except Exception:
                        y = plot.top() + frac * plot.height()
                else:
                    y = plot.top() + frac * plot.height()
                self._tooltip_axis(QPointF(plot.center().x(), y))
            else:
                axes = coord.x_axes
                axis = axes[min(axis_index, len(axes) - 1)] if axes else None
                if value is not None and axis is not None:
                    try:
                        x = axis.map(value, plot.left(), plot.right())
                    except Exception:
                        x = plot.left() + frac * plot.width()
                else:
                    x = plot.left() + frac * plot.width()
                self._tooltip_axis(QPointF(x, plot.center().y()))
            self.update()
        elif name == "axisTipHide":
            self.tooltip.hide()
            self._tooltip_axis_clear()
            self._clear_hover()
            self.update()

    def _receive_universal(self, params: dict) -> None:
        """接收同组图表的 ``universalTransition`` 旧几何 / 截图。"""
        if self._disposed or self._universal_config(self._option) is None:
            return  # 目标图未启用 universalTransition：不接收跨图形变
        image = params.get("image")
        morph = params.get("morph") or []
        if not morph and (image is None or image.isNull()):
            return
        try:
            duration = max(0.0, float(params.get("duration", 300.0)))
        except (TypeError, ValueError, OverflowError):
            duration = 300.0
        plot = params.get("plot")
        self._incoming_morph = {
            "image": image,
            "morph": morph,
            "plot": QRectF(plot) if isinstance(plot, QRectF) else QRectF(),
        }
        self._incoming_t = 0.0
        self._incoming_started = time.perf_counter()
        self._incoming_duration = duration
        if duration <= 0.0:
            self._incoming_morph = None
            self._incoming_t = 1.0
            return
        self._incoming_timer_start()

    def _incoming_timer_start(self) -> None:
        if not self._universal_timer.isActive():
            self._universal_timer.start()

    def on(self, eventName: str, handler) -> "ElaChartWidget":
        """注册 ECharts 事件处理器（``chart.on('click', fn)``）。

        handler 接收 ECharts params dict；异常被捕获并仅告警一次，不穿透 Qt 事件循环。
        """
        self._ensure_alive()
        if not callable(handler):
            raise TypeError("on(eventName, handler): handler 必须可调用")
        self._event_handlers.setdefault(str(eventName), []).append(handler)
        return self

    def off(self, eventName: str = None, handler=None) -> "ElaChartWidget":
        """移除事件处理器（``off()`` 清空 / ``off(name)`` 按事件 / ``off(name, fn)`` 按函数）。"""
        self._ensure_alive()
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
            event = event_from_dict(str(name), params)
            self._chartEvent.emit(str(name), event)
        except Exception as exc:
            warn_once(f"event-emit:{name}", f"事件参数异常（{name}）：{exc!r}")

    def _dispatch_chart_event(self, name: str, params: ChartEvent) -> None:
        event = event_from_dict(str(name), params)
        for handler in list(self._event_handlers.get(name, ())):
            try:
                handler(event)
            except Exception as exc:
                warn_once(
                    f"event-handler:{name}",
                    f"事件处理器异常（{name}）：{exc!r}",
                )

    def _forward_click(self, params: dict) -> None:
        self._emit_event("click", params)

    def _forward_legend_toggled(self, name: str, visible: bool) -> None:
        selected = dict(self._series_state)
        selected.update(self._item_state)
        self._emit_event(
            "legendselectchanged",
            {
                "type": "legendselectchanged",
                "name": str(name),
                "selected": selected,
            },
        )
        self._broadcastGroup("legendselectchanged", {"selected": selected})

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
