"""ElaChartWidget 的命中 / 像素换算 / 选中态 / tooltip 查询方法组。"""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import (
    QPointF,
)
from PyQt6.QtGui import (
    QColor,
)
from PyQt6ElaWidgetTools import eTheme

from .._theme import chart_theme_key
from .._tokens import (
    T,
    palette_for_mode,
)
from .._utils import warn_key, warn_once
from .._utils import parse_color
from .._utils import resolve_color_option
from ..models import HitResult, LabelHit, SeriesItem
from ..axes import (
    GridCoord,
    formatValue,
)
from ._shared import (
    _HOVERABLE_COMPONENTS,
    _sort_value,
)
from .renderer import SeriesRenderer


class _ChartQueryMixin:
    """方法组 mixin：状态由 ``ElaChartWidget.__init__`` 建立。"""

    def _resolve_finder(self, finder):
        """解析 finder（字符串或 dict）→ Coord；无法解析返回 None。"""
        alias = {
            "cartesian2d": "grid",
            "grid": "grid",
            "polar": "polar",
            "singleaxis": "singleAxis",
            "singleAxis": "singleAxis",
            "calendar": "calendar",
            "geo": "geo",
        }
        if isinstance(finder, str):
            kind = alias.get(finder, alias.get(finder.lower(), finder))
            for c in self._coords:
                if c.kind == kind:
                    return c
            return None
        if isinstance(finder, dict):
            for key in ("seriesIndex", "seriesName", "seriesId"):
                if finder.get(key) is not None:
                    renderer = self._renderer_for(finder)
                    return self.coordFor(renderer.opt) if renderer else None
            grid = next((c for c in self._coords if c.kind == "grid"), None)
            if grid is not None and (
                finder.get("xAxisIndex") is not None
                or finder.get("yAxisIndex") is not None
            ):
                return grid.axis_view_for_indices(
                    finder.get("xAxisIndex", 0), finder.get("yAxisIndex", 0)
                )
            if finder.get("geoIndex") is not None:
                try:
                    return self.geoCoord(int(finder["geoIndex"]))
                except (TypeError, ValueError, OverflowError):
                    return None
            for key, kind in (
                ("gridIndex", "grid"),
                ("polarIndex", "polar"),
                ("angleAxisIndex", "polar"),
                ("radiusAxisIndex", "polar"),
                ("singleAxisIndex", "singleAxis"),
                ("calendarIndex", "calendar"),
            ):
                if finder.get(key) is not None:
                    try:
                        if int(finder[key]) != 0:
                            return None  # 多坐标系未实现
                    except (TypeError, ValueError, OverflowError):
                        return None
                    for c in self._coords:
                        if c.kind == kind:
                            return c
            return None
        return None

    def convertToPixel(self, finder, value):
        """数据值 → 像素（ECharts ``convertToPixel``）。
        grid / polar / calendar 返回 ``[x, y]``；singleAxis 返回标量；
        无法解析时返回 ``None``。
        """
        coord = self._resolve_finder(finder)
        if coord is None:
            return None
        if isinstance(value, dict):
            if "coord" in value:
                value = value["coord"]
            else:
                value = [value.get("x"), value.get("y")]
        if not isinstance(value, (list, tuple)):
            value = [value]
        try:
            if coord.kind == "singleAxis":
                pt = coord.mapPoint(value[0])
                return float(pt.y())
            if coord.kind == "calendar":
                pt = coord.mapPoint(value[0])
            else:
                pt = coord.mapPoint(value[0], value[1] if len(value) > 1 else None)
            if pt is None:
                return None
            return [float(pt.x()), float(pt.y())]
        except Exception:
            return None

    def convertFromPixel(self, finder, value):
        """像素 → 数据值（ECharts ``convertFromPixel``）。
        grid 返回 ``[x, y]``；polar 返回 ``[angle, radius]``；singleAxis
        返回标量；calendar 返回 ``[ISO 日期]``。
        """
        coord = self._resolve_finder(finder)
        if coord is None:
            return None
        if isinstance(value, QPointF):
            pos = QPointF(value)
        elif isinstance(value, dict):
            try:
                pos = QPointF(float(value.get("x", 0)), float(value.get("y", 0)))
            except (TypeError, ValueError, OverflowError):
                return None
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                pos = QPointF(float(value[0]), float(value[1]))
            except (TypeError, ValueError, OverflowError):
                return None
        else:
            return None
        invert = getattr(coord, "invertPoint", None)
        if not callable(invert):
            return None
        try:
            result = invert(pos)
        except Exception:
            return None
        if result is None:
            return None
        if isinstance(result, (list, tuple)):
            return list(result)
        return result

    def containPixel(self, finder, value) -> bool:
        """像素是否落在坐标系内（ECharts ``containPixel``）。"""
        coord = self._resolve_finder(finder)
        if coord is None:
            return False
        if isinstance(value, QPointF):
            pos = QPointF(value)
        elif isinstance(value, dict):
            try:
                pos = QPointF(float(value.get("x", 0)), float(value.get("y", 0)))
            except (TypeError, ValueError, OverflowError):
                return False
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                pos = QPointF(float(value[0]), float(value[1]))
            except (TypeError, ValueError, OverflowError):
                return False
        else:
            return False
        contain = getattr(coord, "containPoint", None)
        if not callable(contain):
            return False
        try:
            return bool(contain(pos))
        except Exception:
            return False

    def getWidth(self) -> int:
        """图表宽度（ECharts ``getWidth``）。"""
        return int(self.width())

    def getHeight(self) -> int:
        """图表高度（ECharts ``getHeight``）。"""
        return int(self.height())

    def getDevicePixelRatio(self) -> float:
        """设备像素比（ECharts ``getDevicePixelRatio``）。"""
        try:
            return float(self.devicePixelRatioF())
        except Exception:
            return 1.0

    @property
    def seriesRenderers(self) -> list:
        """系列渲染器列表（含隐藏系列，``r.visible`` 标记）。"""
        return list(self._series)

    @property
    def coords(self) -> list:
        """坐标系列表。"""
        return list(self._coords)

    @property
    def components(self) -> list:
        """组件实例列表。"""
        return list(self._components)

    def palette(self) -> list:
        """当前生效调色板：option["color"] 覆盖，否则默认调色板（主题实时取）。
        按（主题, 自定义色板身份）缓存；返回深拷贝的 QColor —— 绘制路径会逐图元
        ``setAlphaF``，共享实例会把整个调色板改成半透明。
        """
        custom = self._option.get("color")
        has_custom = isinstance(custom, list) and bool(custom)
        key = (
            eTheme.getThemeMode(),
            chart_theme_key(self),
            id(custom) if has_custom else 0,
            len(custom) if has_custom else 0,
        )
        hit = self._palette_cache
        # ``hit[1] is custom`` 复核不能省：换色板后新 list 可能复用同一 id 与长度。
        if hit is not None and hit[0] == key and hit[1] is custom:
            return [parse_color(c) for c in hit[2]]
        if has_custom:
            pal = [
                c
                for c in (resolve_color_option(v, self) for v in custom)
                if c.isValid()
            ]
            if not pal:
                pal = palette_for_mode(eTheme.getThemeMode(), self)
        else:
            pal = palette_for_mode(eTheme.getThemeMode(), self)
        self._palette_cache = (key, custom, pal)
        return [parse_color(c) for c in pal]

    def colorForSeries(self, series) -> QColor:
        """系列主色：series opt 的 "color" → 全局调色板按序号取色。
        序号取 ``_rebuild`` 写好的 ``_series_index``（本函数在逐图元绘制路径上，
        不能用 O(系列数) 的 ``list.index()``）。
        """
        if isinstance(series, SeriesRenderer):
            idx = getattr(series, "_series_index", 0)
            if not isinstance(idx, int):
                idx = 0
            own = series.opt.get("color")
        else:
            idx = int(series)
            own = None
        if isinstance(own, str) and own:
            color = resolve_color_option(own, self)
            if color.isValid():
                return color
        pal = self.palette()
        if not pal:
            return resolve_color_option(T("color.primary", self), self)
        return parse_color(pal[idx % len(pal)])

    def seriesItems(
        self,
        seriesName: str = "",
        *,
        seriesIndex: int = None,
        seriesId: str = None,
    ) -> list:
        """某个系列的全部数据项（``SeriesItem`` dataclass）。"""
        renderer = self._renderer_for(
            {
                "seriesName": seriesName or None,
                "seriesIndex": seriesIndex,
                "seriesId": seriesId,
            }
        )
        if renderer is None:
            return []
        index = self._series.index(renderer) if renderer in self._series else -1
        items = []
        for data_index in range(renderer.itemCount()):
            try:
                info = renderer.valueAtIndex(data_index)
            except Exception:
                info = None
            if info is None:
                continue
            items.append(
                SeriesItem(
                    series_name=renderer.name,
                    series_index=index,
                    data_index=data_index,
                    name=str(info.get("name") or ""),
                    value=info.get("value"),
                    color=info.get("color"),
                    pos=info.get("pos"),
                    rect=info.get("rect"),
                )
            )
        return items

    def itemAt(
        self,
        seriesName: str = "",
        index: int = 0,
        *,
        seriesIndex: int = None,
        seriesId: str = None,
    ) -> Optional[SeriesItem]:
        """某个系列指定下标的数据项；不存在返回 ``None``。"""
        try:
            wanted = int(index)
        except (TypeError, ValueError, OverflowError):
            return None
        renderer = self._renderer_for(
            {
                "seriesName": seriesName or None,
                "seriesIndex": seriesIndex,
                "seriesId": seriesId,
            }
        )
        if renderer is None:
            return None
        try:
            info = renderer.valueAtIndex(wanted)
        except Exception:
            return None
        if info is None:
            return None
        index_in_series = (
            self._series.index(renderer) if renderer in self._series else -1
        )
        return SeriesItem(
            series_name=renderer.name,
            series_index=index_in_series,
            data_index=wanted,
            name=str(info.get("name") or ""),
            value=info.get("value"),
            color=info.get("color"),
            pos=info.get("pos"),
            rect=info.get("rect"),
        )

    def labelRects(
        self,
        seriesName: str = "",
        *,
        seriesIndex: int = None,
        seriesId: str = None,
    ) -> list:
        """某个系列当前的数据标签命中框（``LabelHit`` dataclass）。"""
        renderer = self._renderer_for(
            {
                "seriesName": seriesName or None,
                "seriesIndex": seriesIndex,
                "seriesId": seriesId,
            }
        )
        if renderer is None:
            return []
        return [
            LabelHit(data_index=int(index), rect=rect, text=str(text))
            for index, rect, text in getattr(renderer, "_label_rects", ())
            if isinstance(index, int)
        ]

    def hitTestAll(self, pos: QPointF) -> list:
        """光标下的全部命中项（组件优先，其次系列）。"""
        out = []
        for comp in reversed(self._components):
            if str(getattr(comp, "optionKey", "")) not in _HOVERABLE_COMPONENTS:
                continue
            try:
                hit = comp.hitTest(pos)
            except Exception:
                hit = None
            if hit:
                renderer = comp._renderer() if hasattr(comp, "_renderer") else None
                if renderer is not None:
                    index = (
                        self._series.index(renderer) if renderer in self._series else -1
                    )
                    out.append(
                        HitResult(
                            series_name=renderer.name,
                            series_index=index,
                            data_index=hit.get("dataIndex"),
                            item=hit,
                        )
                    )
        for renderer in reversed(self._series):
            if not renderer.visible or renderer.silent:
                continue
            try:
                hit = renderer.hitTest(pos)
            except Exception:
                hit = None
            if hit:
                index = self._series.index(renderer) if renderer in self._series else -1
                out.append(
                    HitResult(
                        series_name=renderer.name,
                        series_index=index,
                        data_index=hit.get("dataIndex"),
                        item=hit,
                    )
                )
        return out

    def coordAt(self, pos: QPointF):
        """像素所在坐标系：优先包含该点的网格，其次 ``containPoint``，否则主坐标系。"""
        grids = [c for c in self._coords if isinstance(c, GridCoord)]
        for coord in grids:
            if coord.plot.adjusted(-1, -1, 1, 1).contains(pos):
                return coord
        for coord in self._coords:
            contain = getattr(coord, "containPoint", None)
            if callable(contain):
                try:
                    if contain(pos):
                        return coord
                except Exception:
                    pass
        return self.primaryCoord()

    def legendAt(self, pos):
        """坐标命中的图例实例（多图例；无命中返回 None）。"""
        for legend in getattr(self, "legends", ()):
            if legend.shown and legend.rect.contains(pos):
                return legend
        return None

    def primaryCoord(self):
        """主坐标系（coords[0]，无则 None）。"""
        return self._coords[0] if self._coords else None

    def geoCoords(self) -> list:
        """全部顶层 ``geo`` 坐标系。"""
        return [c for c in self._coords if getattr(c, "kind", "") == "geo"]

    def geoCoord(self, index: int = 0):
        """按 ``geoIndex`` 取顶层 geo；越界回退第一个。"""
        geos = self.geoCoords()
        if not geos:
            return None
        try:
            index = max(0, int(index))
        except (TypeError, ValueError, OverflowError):
            index = 0
        return geos[index] if index < len(geos) else geos[0]

    def coordFor(self, series_opt: dict = None):
        """按 series 的 ``coordinateSystem`` / ``xAxisIndex`` / ``yAxisIndex`` 取坐标系。"""
        want = None
        if isinstance(series_opt, dict):
            want = series_opt.get("coordinateSystem")
        alias = {
            "cartesian2d": "grid",
            "grid": "grid",
            "polar": "polar",
            "singleAxis": "singleAxis",
            "calendar": "calendar",
            "geo": "geo",
            None: None,
        }
        want = alias.get(want, want)
        if want == "geo":
            geos = [c for c in self._coords if getattr(c, "kind", "") == "geo"]
            index = 0
            if isinstance(series_opt, dict):
                try:
                    index = max(0, int(series_opt.get("geoIndex", 0) or 0))
                except (TypeError, ValueError, OverflowError):
                    index = 0
            if geos:
                return geos[index] if index < len(geos) else geos[0]
            return None
        if want in (None, "grid"):
            grids = [c for c in self._coords if isinstance(c, GridCoord)]
            if grids:
                # 网格归属由**轴**决定（ECharts：``xAxis[i].gridIndex``），
                # 系列用 ``xAxisIndex`` / ``yAxisIndex`` 选轴，再顺着轴找网格。
                grid_index = 0
                if isinstance(series_opt, dict):
                    try:
                        axis_index = max(0, int(series_opt.get("xAxisIndex", 0) or 0))
                    except (TypeError, ValueError, OverflowError):
                        axis_index = 0
                    axes = grids[0].x_axes
                    if 0 <= axis_index < len(axes):
                        grid_index = axes[axis_index].grid_index
                    else:
                        try:
                            grid_index = max(
                                0, int(series_opt.get("gridIndex", 0) or 0)
                            )
                        except (TypeError, ValueError, OverflowError):
                            grid_index = 0
                coord = grids[grid_index] if grid_index < len(grids) else grids[0]
                return coord.axis_view(series_opt)
        if want:
            for c in self._coords:
                if c.kind == want:
                    return c
        primary = self.primaryCoord()
        if isinstance(primary, GridCoord):
            return primary.axis_view(series_opt)
        return primary

    def _make_item_params(
        self, renderer, hit: dict, event_type: str, event=None, pos=None
    ) -> dict:
        """命中 → ECharts 事件 params（click / highlight 等共用）。"""
        data_index = hit.get("dataIndex")
        data = hit.get("data")
        if data is None:
            raw_data = renderer.data()
            if isinstance(data_index, int) and 0 <= data_index < len(raw_data):
                data = raw_data[data_index]
        # params.color 是数据项颜色（雷达 colorBy='data'、饼图逐扇区），命中方给了就用它。
        raw_color = hit.get("color")
        item_color = (
            resolve_color_option(raw_color, self)
            if raw_color is not None
            else renderer.color()
        )
        if not item_color.isValid():
            item_color = renderer.color()
        params = {
            "type": event_type,
            "componentType": "series",
            "seriesType": str(renderer.opt.get("type") or ""),
            "seriesIndex": self._series.index(renderer)
            if renderer in self._series
            else -1,
            "seriesId": renderer.id,
            "seriesName": renderer.name,
            "name": str(hit.get("name") or ""),
            "dataIndex": data_index,
            "data": data,
            "value": hit.get("value"),
            "color": item_color.name(),
        }
        for extra in ("title", "text"):
            if hit.get(extra) is not None:
                params[extra] = hit[extra]
        if hit.get("pos") is not None:
            params["pos"] = hit["pos"]
        if pos is not None:
            params["offsetX"] = float(pos.x())
            params["offsetY"] = float(pos.y())
        if event is not None:
            params["event"] = event
        return params

    def textStyle(self) -> dict:
        """全局 ``textStyle``（组件级未设置时的文字外观兜底）。

        组件自己的 ``textStyle`` / ``axisLabel`` / ``label`` 同名键优先。
        """
        style = self._option.get("textStyle")
        return style if isinstance(style, dict) else {}

    def preferredHeight(
        self,
        seriesIndex: int = None,
        *,
        rowHeight: float = 26.0,
        padding: float = 88.0,
    ) -> int:
        """系列建议高度（甘特按展示行数 × 行高）；无实现时返回当前高度。"""
        for index, renderer in enumerate(self._series):
            if seriesIndex is not None and index != seriesIndex:
                continue
            hook = getattr(renderer, "preferredHeight", None)
            if not callable(hook):
                continue
            try:
                return int(hook(rowHeight=rowHeight, padding=padding))
            except Exception:
                break
        return int(self.height())

    def hitItem(self, pos: QPointF):
        """坐标命中数据项 → ECharts click params（无命中 None）。"""
        found = self._hitItemWithSeries(pos)
        if not found:
            return None
        renderer, hit = found
        return self._make_item_params(renderer, hit, "click", None, pos)

    def hoverInfo(self):
        """当前悬停命中 ``(渲染器, hit)``；无悬停返回 ``None``（emphasis 高亮用）。"""
        return self._hover

    def _hoverKey(self, found):
        if found is None:
            return None
        return (found[0], found[1].get("dataIndex"))

    def _emitHoverEvent(self, name: str, found) -> None:
        try:
            self._emit_event(name, self._make_item_params(found[0], found[1], name))
        except Exception:
            pass

    def _set_hover(self, found) -> None:
        """更新悬停命中并发出 ECharts ``mouseover`` / ``mouseout`` / ``mousemove``。"""
        old = self._hover
        old_key = self._hoverKey(old)
        new_key = self._hoverKey(found)
        if old is not None and old_key != new_key:
            self._emitHoverEvent("mouseout", old)
        self._hover = found
        if found is not None:
            if old_key != new_key:
                self._emitHoverEvent("mouseover", found)
            self._emitHoverEvent("mousemove", found)

    def _clear_hover(self, *, global_out: bool = False) -> None:
        if self._hover is not None:
            self._emitHoverEvent("mouseout", self._hover)
            self._hover = None
        if global_out:
            self._emit_event("globalout", {"type": "globalout"})

    def emphasizedIndices(self, renderer) -> set:
        """指定系列当前需要强调的数据下标集合（item / axis 两种悬停共用）。"""
        out = set()
        if self._hover is not None and self._hover[0] is renderer:
            index = self._hover[1].get("dataIndex")
            if isinstance(index, int) and not isinstance(index, bool):
                out.add(index)
        for owner, hit in self._axis_hover:
            if owner is not renderer:
                continue
            index = hit.get("dataIndex")
            if isinstance(index, int) and not isinstance(index, bool):
                out.add(index)
        return out

    def selectedModeOf(self, renderer) -> str:
        """系列的选中模式：``false`` / ``single`` / ``multiple`` / ``series``。"""
        mode = str(renderer.opt.get("selectedMode") or "false").strip().lower()
        return mode if mode in ("single", "multiple", "series") else "false"

    def selectedIndices(self, renderer) -> set:
        """指定系列当前选中的数据下标（副本）。"""
        return set(self._selection.get(renderer.name, ()))

    def isSelected(self, renderer, index) -> bool:
        if not isinstance(index, int) or isinstance(index, bool):
            return False
        return index in self._selection.get(renderer.name, ())

    def _selectionChanged(self) -> None:
        self._selection_epoch += 1
        self.invalidateSeriesLayer()
        self.update()

    def _setSelection(self, renderer, indices, *, action: str) -> bool:
        """设置 / 清除 / 切换选中集，返回是否真的变化。"""
        try:
            wanted = {int(i) for i in indices}
        except (TypeError, ValueError, OverflowError):
            return False
        data_len = renderer.itemCount()
        wanted = {i for i in wanted if 0 <= i < data_len}
        current = self._selection.setdefault(renderer.name, set())
        before = set(current)
        if action == "select":
            current.update(wanted)
        elif action == "unselect":
            current.difference_update(wanted)
        else:  # toggleSelect
            for index in wanted:
                current.symmetric_difference_update({index})
        if current == before:
            return False
        if not current:
            self._selection.pop(renderer.name, None)
        self._selectionChanged()
        return True

    def _handle_select_click(self, renderer, hit: dict) -> None:
        """点击命中时按 ``selectedMode`` 切换（默认 false = 不选中）。"""
        mode = self.selectedModeOf(renderer)
        if mode == "false":
            return
        index = hit.get("dataIndex")
        if not isinstance(index, int) or isinstance(index, bool):
            return
        if mode == "single":
            current = self._selection.get(renderer.name, set())
            if current == {index}:
                if self._setSelection(renderer, [index], action="unselect"):
                    self._emitSelectChanged("unselect", renderer)
            else:
                self._selection[renderer.name] = {index}
                self._selectionChanged()
                self._emitSelectChanged("select", renderer)
            return
        if mode == "series":
            total = renderer.itemCount()
            if total <= 0:
                return
            all_indices = set(range(total))
            current = set(self._selection.get(renderer.name, ()))
            if current == all_indices:
                if self._setSelection(renderer, all_indices, action="unselect"):
                    self._emitSelectChanged("unselect", renderer)
            else:
                self._selection[renderer.name] = all_indices
                self._selectionChanged()
                self._emitSelectChanged("select", renderer)
            return
        if self._setSelection(renderer, [index], action="toggleSelect"):
            self._emitSelectChanged("toggleSelect", renderer)

    def _emitSelectChanged(self, action: str, renderer) -> None:
        indices = sorted(self._selection.get(renderer.name, ()))
        selected = [
            {
                "seriesIndex": self._series.index(renderer)
                if renderer in self._series
                else -1,
                "seriesName": renderer.name,
                "dataIndex": int(index),
                "name": self._dataNameAt(renderer, int(index)),
            }
            for index in indices
        ]
        self._emit_event(
            "selectchanged",
            {
                "type": "selectchanged",
                "fromAction": action,
                "selected": selected,
                "fromOutside": False,
            },
        )

    def _dataNameAt(self, renderer, index) -> str:
        try:
            return renderer.nameAtIndex(index)
        except Exception:
            return ""

    def _dispatch_select(self, action: str, payload: dict) -> bool:
        renderer = self._renderer_for(payload)
        if renderer is None:
            return False
        raw = payload.get("dataIndex")
        if raw is None:
            return False
        indices = raw if isinstance(raw, (list, tuple, set)) else [raw]
        changed = self._setSelection(renderer, indices, action=action)
        if changed:
            self._emitSelectChanged(action, renderer)
        return True

    def _hitItemWithSeries(self, pos: QPointF):
        """命中查询：返回 ``(渲染器, 命中 info)``；无命中 None（silent 系列跳过）。
        markPoint / markLine 优先（画在系列之上）；markArea 是背景区域、graphic
        是装饰，都不参与命中。
        """
        # 动画进度可能在最后一次 paint 之后又推进了（鼠标事件先到），这里
        # 按当前进度刷新一遍，保证 hitTest 看到的动画阶段是「现在」。
        t = self.anim.t
        raw = self.anim.raw if self.anim.isRunning() else None
        for comp in reversed(self._components):
            if str(getattr(comp, "optionKey", "")) not in _HOVERABLE_COMPONENTS:
                continue
            hit = None
            try:
                hit = comp.hitTest(pos)
            except Exception as exc:
                warn_once(
                    warn_key(
                        "component-hit",
                        comp.__class__.__name__,
                        type(exc).__name__,
                    ),
                    f"{comp.__class__.__name__}.hitTest 异常: {exc!r}",
                )
                hit = None
            if hit:
                renderer = comp._renderer() if hasattr(comp, "_renderer") else None
                return renderer, hit
        for r in reversed(self._series):
            if not r.visible or r.silent:
                continue
            hit = None
            try:
                r._anim_t = r.animProgress(t, raw)
                hit = r.hitTest(pos)
            except Exception:
                hit = None
            if hit:
                return r, hit
        return None

    def _update_tooltip(self, pos: QPointF) -> None:
        if not self.tooltip.shown or not self._series or self.tooltip.trigger == "none":
            if self.tooltip.active:
                self.tooltip.hide()
                self._broadcastGroup("axisTipHide", {})
            self._tooltip_axis_clear()
            if self._hover is not None:
                self._clear_hover()
                self.update()
            return
        if self.tooltip.trigger == "axis":
            self._tooltip_axis(pos)
        else:
            self._tooltip_item(pos)
        self.update()

    def _grid_axis_indices(self, coord) -> tuple:
        """网格自己的主轴在**全局轴数组**里的下标（``invertX`` / ``invertPoint`` 要）。"""
        xi = 0
        yi = 0
        if isinstance(coord, GridCoord):
            try:
                xi = coord.x_axes.index(coord.x_axis)
            except ValueError:
                xi = 0
            try:
                yi = coord.y_axes.index(coord.y_axis)
            except ValueError:
                yi = 0
        return xi, yi

    def _emptyAreaHit(self, pos: QPointF) -> Optional[dict]:
        """空区命中：把像素反查成数据坐标（``hoveranywhere`` / ``clickanywhere``）。
        Plotly 语义：光标不在任何 trace 上时，事件 / 提示仍带**光标的数据坐标**。
        坐标系不支持反查（polar / calendar 等）时返回 ``None``。
        """
        coord = self.coordAt(pos)
        if coord is None:
            return None
        try:
            xi, yi = self._grid_axis_indices(coord)
            x, y = coord.invertPoint(pos, xi, yi)
        except Exception:
            return None
        if x is None or y is None:
            return None
        if isinstance(x, (int, float)) and not math.isfinite(x):
            return None
        if isinstance(y, (int, float)) and not math.isfinite(y):
            return None
        return {
            "componentType": "grid",
            "series": "",
            "name": "",
            "value": [x, y],
            "x": x,
            "y": y,
        }

    def _emptyAreaEnabled(self, key: str) -> bool:
        """读取 ``hoveranywhere`` / ``clickanywhere``（默认关，对齐 Plotly）。"""
        opt = self._option.get(key)
        if isinstance(opt, bool):
            return opt
        tooltip_opt = self._option.get("tooltip")
        if key == "hoveranywhere" and isinstance(tooltip_opt, dict):
            return bool(tooltip_opt.get("hoverAnywhere", False))
        if key == "clickanywhere" and isinstance(tooltip_opt, dict):
            return bool(tooltip_opt.get("clickAnywhere", False))
        return False

    def _tooltip_item(self, pos: QPointF) -> None:
        self._tooltip_axis_clear()
        found = self._hitItemWithSeries(pos)
        if found is not None:
            renderer, hit = found
            self._set_hover(found)
            raw_color = hit.get("color")
            color = (
                resolve_color_option(raw_color, self)
                if raw_color is not None
                else renderer.color()
            )
            if not color.isValid():
                color = renderer.color()
            self.tooltip.showAt(pos, self.tooltip.buildLines(hit, color, renderer.name))
            return
        if self._hover is not None:
            self._clear_hover()
        if self._emptyAreaEnabled("hoveranywhere"):
            empty = self._emptyAreaHit(pos)
            if empty is not None:
                color = QColor(T("color.text.secondary", self))
                self.tooltip.showAt(pos, self.tooltip.buildLines(empty, color, ""))
                self.update()
                return
        if self.tooltip.active:
            self._broadcastGroup("axisTipHide", {})
        self.tooltip.hide()

    def _axis_pointer_link(self):
        return self.tooltip._axisPointer().get("link")

    def _linked_axes(self, coord, own_index: int, kind: str = "x") -> list:
        """``axisPointer.link`` 中与当前轴同组、除自身外的轴下标。"""
        link = self._axis_pointer_link()
        if link is None or link is False:
            return []
        axes = coord.x_axes if kind == "x" else coord.y_axes
        keys = ("xAxisIndex", "xAxis") if kind == "x" else ("yAxisIndex", "yAxis")
        indices = []
        if str(link).strip().lower() == "all":
            indices = list(range(len(axes)))
        elif isinstance(link, (list, tuple)):
            for item in link:
                if not isinstance(item, dict):
                    continue
                group = item.get(keys[0], item.get(keys[1]))
                if isinstance(group, (list, tuple)):
                    group = [
                        int(value)
                        for value in group
                        if isinstance(value, int) and not isinstance(value, bool)
                    ]
                elif isinstance(group, int) and not isinstance(group, bool):
                    group = [group]
                else:
                    continue
                if own_index in group:
                    indices = group
                    break
        return [index for index in indices if index != own_index]

    def _tooltip_axis(self, pos: QPointF) -> None:
        coord = self.coordAt(pos)
        if not isinstance(coord, GridCoord):
            # 坐标系不支持反查：退化为 item 模式
            self._tooltip_axis_clear()
            self._tooltip_item(pos)
            return
        if not coord.plot.adjusted(-1.0, -1.0, 1.0, 1.0).contains(pos):
            # 光标离开绘图区（标题 / 图例 / 边距）→ 隐藏，不能继续按最近的 x 显示。
            if self.tooltip.active:
                self._broadcastGroup("axisTipHide", {})
            self.tooltip.hide()
            self._tooltip_axis_clear()
            return
        x_axis_index, _y_axis_index = self._grid_axis_indices(coord)
        anchor = None
        try:
            anchor = coord.invertX(pos, x_axis_index)
        except Exception:
            anchor = None
        if anchor is not None:
            # 必须先判有限：轴跨度溢出会得到 inf，随后 int(inf) 抛 OverflowError；
            # 这行在 mouseMoveEvent 里，抛出就是 0xC0000409 静默终止。
            if isinstance(anchor, (int, float)) and not math.isfinite(anchor):
                anchor = None
        if anchor is None:
            self._tooltip_axis_clear()
            self._tooltip_item(pos)
            return

        x_category = coord.x_axis.type == "category"
        y_category = not x_category and coord.y_axis.type == "category"
        category_axis = x_category or y_category
        rows = []
        markers = []
        axis_hover = []
        primary_index = None
        axis_title = None
        for r in self._series:
            if not r.visible or r.silent:
                continue
            info = None
            try:
                series_coord = self.coordFor(r.opt) or coord
                if (
                    isinstance(series_coord, GridCoord)
                    and series_coord.grid_index != coord.grid_index
                ):
                    continue
                if x_category:
                    # 每个系列按自己的 x 轴反查窗口内类目下标（多 x 轴类目列表可能不同）。
                    local = series_coord.x_axis.invert(
                        pos.x(), series_coord.plot.left(), series_coord.plot.right()
                    )
                    if isinstance(local, (int, float)) and math.isfinite(local):
                        index = int(local)
                        info = r.valueAtIndex(
                            index + series_coord.x_axis.windowOffset()
                        )
                        if primary_index is None:
                            primary_index = index
                elif y_category:
                    # 横向柱：类目在 y 轴，按光标所在行取数据项，不能按 x 值找最近柱。
                    hook = getattr(r, "valueAtPosition", None)
                    if callable(hook):
                        # 行序由系列自己决定（甘特支持 yAxis.inverse）：直接按像素命中。
                        info = hook(pos)
                        if info is not None and primary_index is None:
                            row = info.get("rowIndex")
                            if isinstance(row, int):
                                primary_index = row
                    else:
                        # 类目 0 在顶部：invert 的 start/end 要按 top→bottom 传。
                        local = series_coord.y_axis.invert(
                            pos.y(), series_coord.plot.top(), series_coord.plot.bottom()
                        )
                        if isinstance(local, (int, float)) and math.isfinite(local):
                            index = int(local)
                            info = r.valueAtIndex(
                                index + series_coord.y_axis.windowOffset()
                            )
                            if primary_index is None:
                                primary_index = index
                else:
                    # value / log / time：按 x 值找最近的数据点（不能把 invertX 结果当下标）。
                    index = r.nearestIndexAt(anchor)
                    if index is not None:
                        info = r.valueAtIndex(index)
                        if primary_index is None:
                            primary_index = index
            except Exception:
                info = None
            if not info:
                continue
            try:
                if axis_title is None:
                    axis_title = info.get("axisTitle")
                axis_hover.append((r, info))
                raw_color = info.get("color")
                color = (
                    resolve_color_option(raw_color, self)
                    if raw_color is not None
                    else r.color()
                )
                if not color.isValid():
                    color = r.color()
                axis_text = info.get("axisText")
                rows.append(
                    (
                        color,
                        str(info.get("series") or r.name),
                        str(axis_text)
                        if axis_text is not None
                        else formatValue(info.get("value")),
                        info.get("value"),
                    )
                )
                if info.get("pos") is not None:
                    markers.append((QPointF(info["pos"]), parse_color(color)))
            except Exception:
                if axis_hover and axis_hover[-1][0] is r:
                    axis_hover.pop()
                continue

        self._axis_hover = axis_hover
        self._set_hover(axis_hover[0] if axis_hover else None)
        if not rows:
            # 退化：尝试 item 命中
            self._tooltip_item(pos)
            return
        # unified 排序：ECharts ``tooltip.order``（``valueAsc`` / ``valueDesc``）
        # 或 Plotly 风格的 ``hoversort``（``value ascending`` / ``value descending``）
        order = ""
        tooltip_opt = self._option.get("tooltip")
        if isinstance(tooltip_opt, dict):
            order = (
                str(tooltip_opt.get("order") or tooltip_opt.get("hoversort") or "")
                .strip()
                .lower()
            )
        if order in ("valueasc", "value ascending", "ascending"):
            rows.sort(key=lambda row: _sort_value(row[3]))
        elif order in ("valuedesc", "value descending", "descending"):
            rows.sort(key=lambda row: _sort_value(row[3]), reverse=True)
        title = axis_title
        if title is None:
            if x_category:
                cats = coord.x_axis.categories
                if isinstance(primary_index, int) and 0 <= primary_index < len(cats):
                    title = cats[primary_index]
            elif y_category:
                cats = coord.y_axis.categories
                if isinstance(primary_index, int) and 0 <= primary_index < len(cats):
                    title = cats[primary_index]
            else:
                title = coord.x_axis.formatTooltipValue(anchor)
        # 交给 tooltip 的行统一为 (color, name, value_str)（第 4 项仅供排序）
        lines = [(color, name, value) for color, name, value, *_rest in rows]
        if title:
            lines.insert(0, (None, "", title))
        marker = markers[0][0] if markers else pos
        pointer = marker if self.tooltip.axisPointerSnap(category_axis) else pos
        axis_kind = "y" if y_category else "x"
        axis_anchor = anchor
        if y_category:
            try:
                axis_anchor = coord.invertPoint(pos, x_axis_index, _y_axis_index)[1]
            except Exception:
                axis_anchor = None
        own_axis_index = _y_axis_index if y_category else x_axis_index
        linked_axes = []
        if axis_anchor is not None:
            linked_axes = [
                (axis_kind, index, axis_anchor)
                for index in self._linked_axes(coord, own_axis_index, axis_kind)
            ]
        self.tooltip.showAt(
            pos,
            lines,
            marker_pos=pointer,
            markers=markers,
            axis_pointer=True,
            axis_label=title,
            pointer_axis="y" if y_category else "x",
            coord=coord,
            x_axis_index=x_axis_index,
            y_axis_index=_y_axis_index,
            linked_axes=linked_axes,
        )
        plot = coord.plot
        if plot.width() > 0 and plot.height() > 0:
            percent = (
                (pos.y() - plot.top()) / plot.height()
                if y_category
                else (pos.x() - plot.left()) / plot.width()
            )
            self._broadcastGroup(
                "axisTip",
                {
                    "percent": percent,
                    "value": axis_anchor,
                    "axisKind": axis_kind,
                    "axisIndex": own_axis_index,
                },
            )

    def _tooltip_axis_clear(self) -> None:
        """清掉 axis 触发的多系列命中（item / 离开路径共用）。"""
        if self._axis_hover:
            self._axis_hover = []
