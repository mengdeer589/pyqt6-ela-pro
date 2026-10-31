"""ElaChartWidget 的 option 生命周期 / 合并 / 增量数据方法组。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional


import copy
import math

from ..._internal import is_deleted
from PyQt6.QtCore import (
    QTimer,
)

from .. import data as _cdata
from ..data import ElaNumericBuffer
from ..option import (
    _animation_enabled,
    _copy_any,
    _copy_option_shallow_arrays,
    _deep_merge,
    _hold_value,
    _merge_option,
    _snapshot_series_data,
    _unwrap_option,
)
from .._tokens import (
    ANIM_DURATION,
)
from .._utils import component_opt as _component_opt
from .._utils import component_options as _component_options
from .._utils import grid_options as _grid_options
from .._utils import single_option
from .._utils import warn_key, warn_once
from ..axes import (
    CalendarCoord,
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
    single_font_family,
)
from .legend import Legend
from .title import Title
from ._shared import (
    COMPONENT_REGISTRY,
    SERIES_REGISTRY,
    _easing_from_name,
    _needs_grid_coord,
)


if TYPE_CHECKING:
    from .widget import ElaChartWidget


#: ``updateAxis`` 的轴名 -> option 键（radar 的维度定义在 ``series.indicator``，
#: 本库不读顶层 ``radar`` 组件）
_AXIS_OPTION_KEYS = {
    "x": "xAxis",
    "y": "yAxis",
    "single": "singleAxis",
}


class _ChartOptionMixin:
    """方法组 mixin：状态由 ``ElaChartWidget.__init__`` 建立。"""

    def setOption(
        self, option: dict, notMerge: bool = False, lazyUpdate: bool = False
    ) -> "ElaChartWidget":
        """设置 option（ECharts ``setOption(option, notMerge, lazyUpdate)``）。

        默认合并：dict 深合并；``series`` / ``dataZoom`` / ``graphic`` 数组按
        ``id`` → ``name`` → 下标逐项合并，其余 list 整体替换。``notMerge=True``
        全量替换并重置交互状态；``lazyUpdate=True`` 把重建 / 重绘推迟到下一事件循环。

        ``series[].data`` 的大数值数组按引用摄入（``ElaNumericBuffer``），调用方
        在本次调用后不得原地修改，改数据请重新 ``setOption``。

        :returns: self（支持链式调用）
        """
        self._ensure_alive()
        if not isinstance(option, dict):
            option = {}
        prev_list, prev_by_name = self._capture_prev_data(option)
        if notMerge:
            # 先包成紧凑存储再存入，否则深拷贝会逐元素复制百万级 list。
            self._option = _copy_option_shallow_arrays(option)
            self._series_state = {}
            self._item_state = {}
            self._timeline_base = None
            self._zoom_opt_snapshot = None  # 全量替换 = 缩放复位
            self._selection = {}
            self._selection_epoch += 1
            self.tooltip.hide()
            self._hover = None
            # 全量替换 = 缩放复位：默认滚轮组件跨 setOption 存活，不重置会让
            # adoptWindow 把旧窗口套到新数据上。
            self._reset_host_zoom = True
        else:
            _merge_option(self._option, option)
        # 版本号必须由 ``_rebuild`` 递增：``lazyUpdate`` 会在重建前返回，
        # 提前递增会让旧渲染器把位图存进新键，重建后同键命中旧数据。
        self._update_timeline_base(option)
        if lazyUpdate:
            self._lazy_pending = True
            self._schedule_lazy_option()
        else:
            self._apply_option(prev_list, prev_by_name)
        return self

    # -- 全图字体族（单族约束） -------------------------------------------

    def setFontFamily(self, family) -> None:
        """设置全图字体族（单个族名；``None`` / 空串恢复系统默认）。

        只接受单族：逗号列表会被折叠成第一个并留告警（多族在 Win7 上走慢
        shaping 路径且进程级毒化后续文本）。单组件可用 ``textStyle.fontFamily``
        等覆盖；本方法只失效布局缓存并重绘，不重建组件。
        """
        self._font_family = single_font_family(family)
        self.invalidateLayout()
        self.update()

    def fontFamily(self) -> str:
        """当前全图字体族（空串 = 系统默认）。"""
        return str(getattr(self, "_font_family", "") or "")

    # -- 单组件增量更新（比让宿主手写整个数组更安全） ---------------------

    def updateAxis(self, axis: str, patch: dict, axisIndex: int = 0) -> bool:
        """只更新一条坐标轴（深合并到该轴，其余轴原样保留）。

        :param axis: ``"x"`` / ``"y"`` / ``"single"``
        :param patch: 轴 option 片段，如 ``{"axisLabel": {"formatter": "{value} 月"}}``
        :param axisIndex: 轴下标（单轴传 0）
        :returns: 是否找到目标轴并完成合并
        """
        key = _AXIS_OPTION_KEYS.get(str(axis or "").strip().lower())
        if key is None or not isinstance(patch, dict):
            return False
        try:
            index = int(axisIndex)
        except (TypeError, ValueError, OverflowError):
            return False
        current = self._option.get(key)
        if isinstance(current, list):
            if not 0 <= index < len(current):
                return False
            payload = [{} for _ in range(index)] + [patch]
        elif isinstance(current, dict):
            if index != 0:
                return False
            payload = patch
        else:
            return False
        self.setOption({key: payload})
        return True

    def updateSeries(
        self,
        patch: dict,
        *,
        seriesIndex: Optional[int] = None,
        seriesName: Optional[str] = None,
        seriesId: Optional[str] = None,
    ) -> bool:
        """只更新一个系列（按 id → name → 下标定位，深合并）。

        重建前会把 dataZoom / 图例 / 选中态写回 option，缩放窗口不会被打回初始值。
        """
        if not isinstance(patch, dict):
            return False
        index = self._series_option_index(seriesIndex, seriesName, seriesId)
        if index is None:
            return False
        series = self._option.get("series")
        target = series[index] if isinstance(series, list) else None
        if not isinstance(target, dict):
            return False
        _deep_merge(target, patch)
        # ``_rebuild`` 内部会用 snapshotWindow/adoptWindow 保留用户缩放窗口
        self._opt_version += 1
        self._rebuild()
        self.update()
        return True

    def _series_option_index(
        self,
        seriesIndex: Optional[int],
        seriesName: Optional[str],
        seriesId: Optional[str],
    ) -> Optional[int]:
        series = self._option.get("series")
        if not isinstance(series, list) or not series:
            return None
        if seriesId is not None:
            key = str(seriesId).strip()
            if not key:
                return None
            for index, item in enumerate(series):
                if isinstance(item, dict) and str(item.get("id") or "") == key:
                    return index
            return None
        if seriesName is not None:
            key = str(seriesName)
            for index, item in enumerate(series):
                if isinstance(item, dict) and str(item.get("name") or "") == key:
                    return index
            return None
        try:
            index = int(seriesIndex if seriesIndex is not None else 0)
        except (TypeError, ValueError, OverflowError):
            return None
        return index if 0 <= index < len(series) else None

    def setAxisLabelFormatter(self, axis: str, formatter, axisIndex: int = 0) -> bool:
        """设置一条轴标签的 formatter（字符串模板或 ``callable(value, index)``）。"""
        return self.updateAxis(axis, {"axisLabel": {"formatter": formatter}}, axisIndex)

    def setCategoryLabels(self, labels, axisIndex: int = 0) -> bool:
        """替换类目轴（x 轴）的标签列表，保留该轴其它 option 与缩放窗口。"""
        return self.updateAxis("x", {"data": list(labels or ())}, axisIndex)

    def _capture_prev_data(self, new_option: dict):
        """捕获旧系列数据供过渡动画插值；动画关闭时完全跳过。

        百万级数据的 ``list(r.data())`` 是一次完整物化，而插值关闭时根本不读。

        :returns: ``(prev_list, prev_by_name)``；跳过时两者均为 ``None``
        """
        if not _animation_enabled(self._option, new_option):
            return None, None
        prev_list = [_snapshot_series_data(r) for r in self._series]
        prev_by_name = {
            r.name: prev_list[i] for i, r in enumerate(self._series) if r.name
        }
        return prev_list, prev_by_name

    def _schedule_lazy_option(self) -> None:
        """排一次延迟重建（常驻子定时器）。

        无主 ``QTimer.singleShot`` 不随本对象销毁，而 ``lazyUpdate`` 可以连调多次，
        所以复用同一个子定时器而不是每次新建。
        """
        timer = self.__dict__.get("_lazy_timer")
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_lazy_option)
            self._lazy_timer = timer
        timer.start(0)

    def _apply_lazy_option(self) -> None:
        """延迟重建（lazyUpdate）；对象已销毁时安全跳过。"""
        if self._disposed or is_deleted(self) or not self._lazy_pending:
            return
        self._lazy_pending = False
        prev_list, prev_by_name = self._capture_prev_data({})
        self._apply_option(prev_list, prev_by_name)

    def _capture_timeline_base(self) -> None:
        """捕获 timeline 基线：``baseOption``（优先）或除 ``options`` 外的顶层键。

        一律走 ``_copy_any``：``deepcopy`` 会逐元素复制百万点数组，绕过按引用摄入。
        只在基线为空时捕获，且调用点只能是 ``setOption`` —— 帧切换期间 ``_option``
        已是「基线 + 当前帧」，再捕获会把帧值写回基线。
        """
        frames = self._option.get("options")
        if not isinstance(frames, list) or not frames:
            self._timeline_base = None
            return
        if self._timeline_base is not None:
            return
        base = self._option.get("baseOption")
        if isinstance(base, dict):
            merged = _copy_any(base)
            extra = {
                k: v
                for k, v in self._option.items()
                if k not in ("baseOption", "options")
            }
            _deep_merge(merged, extra)
        else:
            merged = {
                k: _copy_any(v) for k, v in self._option.items() if k != "options"
            }
        self._timeline_base = merged

    def _update_timeline_base(self, option: dict) -> None:
        """把宿主本次传入的非帧键合并进 timeline 基线。

        帧切换时 ``_option`` 是生效结果，不能当基线来源；只用本次 ``setOption``
        的入参，保证「更新静态配置」与「切帧回落」都成立。
        """
        frames = self._option.get("options")
        if not isinstance(frames, list) or not frames:
            self._timeline_base = None
            return
        self._capture_timeline_base()
        if self._timeline_base is None:
            return
        source = option if isinstance(option, dict) else {}
        base_opt = source.get("baseOption")
        if isinstance(base_opt, dict):
            _deep_merge(self._timeline_base, _copy_any(base_opt))
        for key, value in source.items():
            if key in ("options", "baseOption"):
                continue
            if key in ("series", "dataZoom", "graphic") and isinstance(value, list):
                self._timeline_base[key] = _copy_any(value)
                continue
            if isinstance(value, dict) and isinstance(
                self._timeline_base.get(key), dict
            ):
                _deep_merge(self._timeline_base[key], _copy_any(value))
            else:
                self._timeline_base[key] = _copy_any(value)

    def _apply_timeline_frame(self) -> None:
        """把当前帧（``_timeline_index``）合并到 timeline 基线上。

        无 ``options`` 帧时为空操作；结果写回 ``_option``（保留结构键）。
        """
        frames = self._option.get("options")
        if not isinstance(frames, list) or not frames or self._timeline_base is None:
            return
        timeline_opt = self._option.get("timeline")
        idx = getattr(self, "_timeline_index", 0)
        if isinstance(timeline_opt, dict):
            if "currentIndex" in timeline_opt:
                idx = timeline_opt.get("currentIndex")
            else:
                timeline_opt["currentIndex"] = idx
        try:
            idx = int(idx or 0)
        except (TypeError, ValueError, OverflowError):
            idx = 0
        idx = max(0, min(idx, len(frames) - 1))
        self._timeline_index = idx
        frame = frames[idx]
        if not isinstance(frame, dict):
            return
        effective = _copy_any(self._timeline_base)
        _deep_merge(effective, frame)
        effective["options"] = _copy_any(frames)
        if isinstance(self._option.get("baseOption"), dict):
            effective["baseOption"] = _copy_any(self._option["baseOption"])
        # ``timeline.currentIndex`` 是**当前帧状态**，不属于基线：基线里可能
        # 没有这个键（宿主只写了 data），不补回去的话 goto 之后
        # ``_option["timeline"]["currentIndex"]`` 会消失。
        timeline_eff = effective.get("timeline")
        if not isinstance(timeline_eff, dict):
            timeline_eff = (
                _copy_any(timeline_opt) if isinstance(timeline_opt, dict) else {}
            )
            effective["timeline"] = timeline_eff
        timeline_eff["currentIndex"] = idx
        self._option = effective

    def _refresh(self) -> None:
        """按当前 option 重建并播放过渡动画（timeline 帧切换用）。"""
        prev_list = [list(r.data()) for r in self._series]
        prev_by_name = {
            r.name: prev_list[i] for i, r in enumerate(self._series) if r.name
        }
        # 帧切换不重捕基线：基线只由宿主 setOption 更新（见 ``_update_timeline_base``）。
        self._apply_timeline_frame()
        self._apply_option(prev_list, prev_by_name)

    def _apply_option(self, prev_list: list, prev_by_name: dict) -> None:
        """重建渲染器并注入旧数据（动画插值），随后播放入场 / 过渡动画。

        ``prev_list`` / ``prev_by_name`` 允许为 ``None``（动画关闭时跳过快照）。
        """
        self._apply_timeline_frame()
        self._rebuild()
        if prev_list is not None or prev_by_name:
            for i, r in enumerate(self._series):
                prev = (prev_by_name or {}).get(r.name) if r.name else None
                if prev is None and prev_list is not None and i < len(prev_list):
                    prev = prev_list[i]
                r.prev_data = prev
        self._start_animation()
        self.update()

    def _start_animation(self) -> None:
        """按 option 动画键启动入场 / 过渡动画；关闭时直接呈现终态。

        读取 ``animation`` / ``animationDuration`` / ``animationEasing`` 及其
        ``...Update`` 变体。
        """
        opt = self._option
        enabled = opt.get("animation", True) is not False
        has_prev = any(r.prev_data is not None for r in self._series)
        if has_prev:
            duration = opt.get(
                "animationDurationUpdate", opt.get("animationDuration", ANIM_DURATION)
            )
            easing_name = opt.get("animationEasingUpdate", opt.get("animationEasing"))
        else:
            duration = opt.get("animationDuration", ANIM_DURATION)
            easing_name = opt.get("animationEasing")
        if enabled:
            # 走策略解析：Reduced 压时长、Disabled 同步落终值（都仍会发 finished）。
            self.anim.startResolved(duration, _easing_from_name(easing_name))
        else:
            self.anim.setDuration(duration)
            self.anim.setEasing(_easing_from_name(easing_name))
            self.anim.complete()

    def getOption(self) -> dict:
        """当前 option 深拷贝（ECharts ``getOption``）。

        大数值数组还原为普通 ``list``（缓冲区是内部存储，调用方观察不到）。
        """
        self._ensure_alive()
        option = _unwrap_option(_copy_any(self._option))
        return self._overlay_live_state(option)

    def _overlay_live_state(self, option: dict) -> dict:
        """把交互状态写回 ``getOption`` 的返回值（不改内部 ``_option``）。

        ECharts 的 ``getOption`` 返回当前 option：图例选择 / dataZoom 窗口 / 选中态
        都要反映用户操作，宿主才能保存与恢复视图。
        """
        if not isinstance(option, dict):
            return option
        legend = option.get("legend")
        if self._series:
            series_names = {r.name for r in self._series}
            live = {}
            for r in self._series:
                getter = getattr(r, "legendItems", None)
                names = [name for name, _ in getter()] if callable(getter) else [r.name]
                for name in names:
                    live[name] = (
                        self._seriesVisible(name)
                        if name in series_names
                        else bool(self._item_state.get(name, True))
                    )
            if isinstance(legend, dict):
                legend["selected"] = dict(live)
            elif isinstance(legend, list):
                for entry in legend:
                    if isinstance(entry, dict):
                        entry["selected"] = dict(live)
        zoom = self._component("dataZoom")
        if zoom is not None and option.get("dataZoom") is not None:
            entries = option.get("dataZoom")
            if isinstance(entries, dict):
                entries = [entries]
                option["dataZoom"] = entries
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    entry["start"] = float(zoom.start)
                    entry["end"] = float(zoom.end)
                    if zoom._y_zoom_enabled:
                        entry["yStart"] = float(zoom.y_start)
                        entry["yEnd"] = float(zoom.y_end)
        series_entries = option.get("series")
        if isinstance(series_entries, list):
            for index, entry in enumerate(series_entries):
                if not isinstance(entry, dict) or index >= len(self._series):
                    continue
                selected = self._selection.get(self._series[index].name)
                if selected:
                    entry["selectedMap"] = {str(i): True for i in sorted(selected)}
                elif "selectedMap" in entry:
                    entry["selectedMap"] = {}
        return option

    def resize(self, width=None, height=None) -> None:
        """ECharts ``resize``：无参强制重排；兼容 QWidget ``resize(w, h)``。

        ``width`` 传 dict 时按 ECharts opts 解析（``{"width":..., "height":...}``）。
        """
        self._ensure_alive()
        opts = width if isinstance(width, dict) else None
        if opts is not None:
            width = opts.get("width")
            height = opts.get("height")
        if width is not None or height is not None:
            w = int(width) if width is not None else self.width()
            h = int(height) if height is not None else self.height()
            super().resize(w, h)
        self.invalidateLayout()
        self._layout_all(force=True)
        self.update()

    def appendData(self, params: dict) -> bool:
        """向指定系列追加数据（ECharts ``appendData({seriesIndex|seriesName, data})``）。

        ``params`` 需含 ``seriesIndex`` / ``seriesName`` / ``seriesId`` 之一与
        ``data``；返回是否找到目标系列并追加。
        """
        self._ensure_alive()
        if not isinstance(params, dict):
            return False
        data = params.get("data")
        if data is None:
            return False
        series_opts = [
            s for s in (self._option.get("series") or []) if isinstance(s, dict)
        ]
        if not series_opts:
            return False
        index = None
        if params.get("seriesIndex") is not None:
            try:
                idx = int(params["seriesIndex"])
            except (TypeError, ValueError, OverflowError):
                return False
            if 0 <= idx < len(series_opts):
                index = idx
        elif params.get("seriesName"):
            name = str(params["seriesName"])
            for i, s in enumerate(series_opts):
                if str(s.get("name") or "") == name:
                    index = i
                    break
        elif params.get("seriesId"):
            sid = str(params["seriesId"])
            for i, s in enumerate(series_opts):
                if str(s.get("id") or "") == sid:
                    index = i
                    break
        if index is None:
            return False
        target = series_opts[index]
        # 缓冲区只读，先物化成 list；避开 setOption 的全量重建，轴窗口与交互状态保留。
        data_list = target.get("data")
        if isinstance(data_list, ElaNumericBuffer):
            data_list = data_list.toList()
        elif not isinstance(data_list, list):
            data_list = []
        if isinstance(data, list):
            data_list.extend(
                _hold_value(data) if _cdata.isBufferLike(data) else copy.deepcopy(data)
            )
        else:
            data_list.append(copy.deepcopy(data))
        target["data"] = data_list
        name = str(target.get("name") or "")
        renderer = None
        if name:
            renderer = next((r for r in self._series if r.name == name), None)
        if renderer is None and 0 <= index < len(self._series):
            renderer = self._series[index]
        if renderer is None:
            # 未注册 / 已丢失的系列：退回全量合并，至少保证 option 一致
            patch = [{} for _ in range(index)] + [target]
            self.setOption({"series": patch})
            return True
        renderer.opt["data"] = data_list
        load = getattr(renderer, "_load_data", None)
        if callable(load):
            load()
        for coord in self._coords:
            try:
                coord.setSeries(self._option.get("series") or [])
            except Exception:
                pass
        for comp in self._components:
            capture = getattr(comp, "captureExtent", None)
            if callable(capture):
                try:
                    capture()
                except Exception:
                    pass
        self._opt_version += 1
        self.invalidateLayout()
        self._layout_all(force=True)
        self.update()
        return True

    def clear(self) -> None:
        """清空图表（ECharts ``clear``；等价 ``setOption({}, notMerge=True)``）。"""
        self.setOption({}, notMerge=True)

    def dispatchAction(self, payload: dict) -> bool:
        """触发 ECharts 动作（``dispatchAction``）。

        支持：``legendToggleSelect`` / ``legendSelect`` / ``legendUnSelect`` /
        ``legendAllSelect`` / ``legendInverseSelect`` / ``dataZoom`` /
        ``restore`` / ``showTip`` / ``hideTip`` / ``highlight`` /
        ``downplay`` / ``select`` / ``unselect`` / ``toggleSelect`` /
        ``timelineChange`` / ``timelinePlayChange``。

        :returns: 动作是否被识别并执行
        """
        self._ensure_alive()
        if not isinstance(payload, dict):
            return False
        action = str(payload.get("type") or "")
        if action in (
            "legendToggleSelect",
            "legendSelect",
            "legendUnSelect",
            "legendAllSelect",
            "legendInverseSelect",
        ):
            return self._dispatch_legend(action, payload)
        if action == "dataZoom":
            return self._dispatch_data_zoom(payload)
        if action == "restore":
            self._restore_state()
            return True
        if action == "showTip":
            return self._dispatch_show_tip(payload)
        if action == "hideTip":
            self.tooltip.hide()
            self.update()
            return True
        if action in ("highlight", "downplay"):
            return self._dispatch_emphasis(action, payload)
        if action in ("select", "unselect", "toggleSelect"):
            return self._dispatch_select(action, payload)
        if action == "timelineChange":
            comp = self._component("timeline")
            if comp is None:
                return False
            try:
                comp.goto(int(payload.get("currentIndex", 0)))
            except (TypeError, ValueError, OverflowError):
                return False
            return True
        if action == "timelinePlayChange":
            comp = self._component("timeline")
            if comp is None:
                return False
            want = bool(payload.get("playState", not comp.playing))
            if want != bool(comp.playing):
                comp.togglePlay()
            return True
        return False

    def toggleMagicType(self) -> bool:
        """工具条 ``magicType``：折线 → 柱状 → 堆叠柱状 → 折线循环切换。

        只改 cartesian 的 ``line`` / ``bar`` 系列（保留数据 / 名称 / 颜色）。
        """
        series = self._option.get("series")
        if not isinstance(series, list):
            return False
        targets = [
            s
            for s in series
            if isinstance(s, dict)
            and str(s.get("type") or "line") in ("line", "bar")
            and s.get("coordinateSystem") in (None, "cartesian2d", "grid")
        ]
        if not targets:
            return False
        if any(str(s.get("type") or "line") == "line" for s in targets):
            target = "bar"
        elif any(s.get("stack") for s in targets):
            target = "line"
        else:
            target = "stack"
        if target != "stack":
            # 合并语义不会删除旧键：切回 line / bar 时先从实际 option 里摘掉 stack
            for existing in series:
                if isinstance(existing, dict):
                    existing.pop("stack", None)
        patch = []
        for s in series:
            convertible = (
                isinstance(s, dict)
                and str(s.get("type") or "line") in ("line", "bar")
                and s.get("coordinateSystem") in (None, "cartesian2d", "grid")
            )
            if not convertible:
                patch.append({})
                continue
            new = dict(s)
            if target == "line":
                new["type"] = "line"
                new.pop("stack", None)
            elif target == "bar":
                new["type"] = "bar"
                new.pop("stack", None)
            else:
                new["type"] = "bar"
                new["stack"] = "magic"
            patch.append(new)
        self.setOption({"series": patch})
        return True

    def zoomStep(self, factor: float) -> bool:
        """按倍数步进缩放（``<1`` 放大 / ``>1`` 缩小），围绕当前窗口中心。

        无 dataZoom 组件时返回 ``False``；窗口最小 0.5%、最大 100%。
        """
        comp = self._component("dataZoom")
        if comp is None:
            return False
        try:
            start = float(getattr(comp, "start", 0.0))
            end = float(getattr(comp, "end", 100.0))
            factor = float(factor)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(factor) or factor <= 0:
            return False
        span = max(0.5, end - start)
        new_span = min(100.0, max(0.5, span * factor))
        center = (start + end) / 2.0
        new_start = center - new_span / 2.0
        new_end = center + new_span / 2.0
        if new_start < 0.0:
            new_end -= new_start
            new_start = 0.0
        if new_end > 100.0:
            new_start -= new_end - 100.0
            new_end = 100.0
        payload = {
            "type": "dataZoom",
            "start": max(0.0, new_start),
            "end": new_end,
        }
        enable_y = getattr(comp, "enableYAxisZoom", None)
        if callable(enable_y):
            enable_y()
        if getattr(comp, "_y_zoom_enabled", False):
            y_start = float(getattr(comp, "y_start", 0.0))
            y_end = float(getattr(comp, "y_end", 100.0))
            y_span = max(0.5, y_end - y_start)
            new_y_span = min(100.0, max(0.5, y_span * factor))
            y_center = (y_start + y_end) / 2.0
            new_y_start = y_center - new_y_span / 2.0
            new_y_end = y_center + new_y_span / 2.0
            if new_y_start < 0.0:
                new_y_end -= new_y_start
                new_y_start = 0.0
            if new_y_end > 100.0:
                new_y_start -= new_y_end - 100.0
                new_y_end = 100.0
            payload["yStart"] = max(0.0, new_y_start)
            payload["yEnd"] = new_y_end
        return bool(self.dispatchAction(payload))

    def _rebuild(self) -> None:
        """按当前 option 重建组件 / 坐标系 / 系列渲染器（并使布局缓存失效）。"""
        if self._disposed:
            # 迟到的定时器（timeline / lazy）可能在 dispose 之后触发重建
            return
        # 重建 = 渲染器换了：版本号必须在这里递增，否则位图缓存会把旧图当新状态。
        self._opt_version += 1
        self._hide_annotation_editor()
        opt = self._option
        self._layout_key = None
        title_opts = _component_options(opt.get("title"), "show")
        if len(title_opts) != len(self.titles):
            self.titles = [Title(self) for _ in title_opts]
        for title, title_opt in zip(self.titles, title_opts):
            title.setOption(title_opt)
        self.title = self.titles[0]

        # 未写 ``legend`` = 不显示图例（ECharts 语义）。
        if "legend" in opt:
            legend_opts = _component_options(opt.get("legend"), "show")
        else:
            legend_opts = [{"show": False}]
        if len(legend_opts) != len(self.legends):
            self.legends = [Legend(self) for _ in legend_opts]
        for legend, legend_opt in zip(self.legends, legend_opts):
            legend.setOption(legend_opt)
        self.legend = self.legends[0]

        self.tooltip.setOption(_component_opt(opt.get("tooltip"), "show", "tooltip"))
        series_opts = [s for s in (opt.get("series") or []) if isinstance(s, dict)]

        # 图例 selected：初始显隐状态（ECharts ``legend.selected``，多图例逐个应用）
        for legend_opt in legend_opts:
            selected = legend_opt.get("selected")
            if isinstance(selected, dict):
                for name, visible in selected.items():
                    self._series_state[str(name)] = bool(visible)
                    self._item_state[str(name)] = bool(visible)

        # 坐标系：calendar > polar > singleAxis > grid。grid 仅在 option 显式给出
        # xAxis/yAxis/grid，或存在落在 grid 的系列时创建。
        self._coords = []
        if "calendar" in opt:
            c = self._make_coord(CalendarCoord, "calendar")
            if c is not None:
                self._coords.append(c)
        if "polar" in opt or "radiusAxis" in opt or "angleAxis" in opt:
            c = self._make_coord(PolarCoord, "polar")
            if c is not None:
                self._coords.append(c)
        if "singleAxis" in opt:
            c = self._make_coord(SingleAxisCoord, "singleAxis")
            if c is not None:
                self._coords.append(c)
        need_grid = (
            "xAxis" in opt
            or "yAxis" in opt
            or "grid" in opt
            or _needs_grid_coord(series_opts)
        )
        if need_grid:
            grid_opts = _grid_options(opt.get("grid"))
            shared_axes = None
            for index in range(len(grid_opts)):
                grid = self._make_coord(GridCoord, f"grid:{index}", index, shared_axes)
                if grid is not None:
                    if shared_axes is None:
                        shared_axes = (grid.x_axes, grid.y_axes)
                    self._coords.insert(index, grid)
        for c in self._coords:
            c.setSeries(series_opts)
        # 轴范围刚由 setSeries 重算：跨 setOption 存活的 dataZoom（默认滚轮组件）
        # 必须在这里重捕全量范围，否则会一直拿旧数据的范围当全量。
        for comp in self._components:
            capture = getattr(comp, "captureExtent", None)
            if not callable(capture):
                continue
            try:
                capture()
            except Exception as exc:
                warn_once(
                    warn_key(
                        "capture-extent",
                        comp.__class__.__name__,
                        type(exc).__name__,
                    ),
                    f"重捕轴范围失败（{comp.__class__.__name__}）: {exc!r}",
                )

        # 系列渲染器
        self._series = []
        for i, s in enumerate(series_opts):
            type_name = str(s.get("type") or "line")
            cls = SERIES_REGISTRY.get(type_name)
            if cls is None:
                continue  # 未注册类型安全跳过
            try:
                r = cls(self, s)
            except Exception as exc:
                warn_once(
                    warn_key("series-ctor", type_name, type(exc).__name__),
                    f"系列构造失败（type={type_name}）: {exc!r}",
                )
                continue
            # 注入 option 内序号：bar 槽位等按序号定位自身
            r._series_index = i
            if not r.name:
                r.name = f"series{i}"
                r.opt.setdefault("name", r.name)
            r.visible = self._seriesVisible(r.name)
            self._series.append(r)

        # 选中态：保留交互产生的选择，按数据长度剪枝；option 里的
        # ``series.selected`` / ``data[i].selected`` 作为显式初值。
        names = {r.name for r in self._series}
        pruned = {}
        for name, indices in self._selection.items():
            if name not in names:
                continue
            renderer = next((r for r in self._series if r.name == name), None)
            if renderer is None:
                continue
            data_len = len(renderer.data())
            keep = {i for i in indices if 0 <= i < data_len}
            if keep:
                pruned[name] = keep
        self._selection = pruned
        for r in self._series:
            selected = r.opt.get("selected")
            seeds = set()
            if isinstance(selected, (list, tuple, set)):
                for value in selected:
                    try:
                        seeds.add(int(value))
                    except (TypeError, ValueError, OverflowError):
                        continue
            # ``ElaNumericBuffer`` 只承载数值，不可能有 ``data[i].selected``，
            # 跳过整趟遍历。
            data_items = r.data()
            if not _cdata.isBufferLike(data_items):
                for index, item in enumerate(data_items):
                    if isinstance(item, dict) and item.get("selected") is True:
                        seeds.add(index)
            if seeds:
                data_len = len(r.data())
                self._selection[r.name] = {i for i in seeds if 0 <= i < data_len}

        # 丢弃旧组件前先 dispose（解挂事件过滤器 / 定时器），否则旧实例会继续
        # 拦截输入并用陈旧状态改坐标轴。
        old_zoom = self._component("dataZoom")
        old_zoom_state = old_zoom.snapshotWindow() if old_zoom is not None else None
        zoom_opt_changed = opt.get("dataZoom") != self._zoom_opt_snapshot
        self._dispose_components()
        # option 组件全部重建；宿主注入的（``addComponent``）原样挂回去。
        self._components = list(self._host_components)
        for key, cls in list(COMPONENT_REGISTRY.items()):
            optionKey = getattr(cls, "optionKey", key)
            for value, series_opt in self._component_inputs(
                cls, opt, optionKey, series_opts
            ):
                self._spawn_component(cls, value, series_opt)
        # 用户缩放跨 setOption 保留：dataZoom 段没变就沿用旧窗口。
        reset_zoom = bool(getattr(self, "_reset_host_zoom", False))
        self._reset_host_zoom = False
        new_zoom = self._component("dataZoom")
        if (
            new_zoom is not None
            and old_zoom_state
            and not zoom_opt_changed
            and not reset_zoom
        ):
            new_zoom.adoptWindow(old_zoom_state)
        self._zoom_opt_snapshot = _copy_any(opt.get("dataZoom"))
        # 直角坐标图默认滚轮缩放（用户配了 dataZoom 就完全听用户的）
        self._ensure_wheel_zoom()
        if reset_zoom:
            # 全量替换 / clear：所有 dataZoom（含跨 setOption 存活的 host 组件）
            # 回到各自 option 的初始窗口。
            for comp in self._components:
                if getattr(comp, "optionKey", "") != "dataZoom":
                    continue
                comp.start = comp.init_start
                comp.end = comp.init_end
                comp.y_start = comp.y_init_start
                comp.y_end = comp.y_init_end
                try:
                    comp.apply()
                except Exception:
                    pass
        # 显式配置 brush = 用户要框选数据；未显式 setDragMode 时默认走 select
        if not self._drag_mode_explicit and self._drag_mode == self.DRAG_MODE_DEFAULT:
            if isinstance(opt.get("brush"), (dict, list)):
                self._drag_mode = "select"
        elif (
            not self._drag_mode_explicit
            and self._drag_mode == "select"
            and not isinstance(opt.get("brush"), (dict, list))
        ):
            self._drag_mode = self.DRAG_MODE_DEFAULT
        # 默认左键框选：dataZoom / brush 的拖拽接管按当前模式重放
        self._apply_drag_mode()

        # 图例条目：饼 / 漏斗按数据项，其余按系列名。图例隐藏时不构建条目
        # （饼图 legendItems 会遍历全部数据项，百万级纯浪费）。
        show_legend = any(bool(opt.get("show", True)) for opt in legend_opts)
        hidden = {
            str(name) for name, visible in self._item_state.items() if not visible
        }
        items = []
        for r in self._series:
            setter = getattr(r, "setHiddenItems", None)
            if callable(setter):
                try:
                    setter(hidden)
                except Exception:
                    pass
            if not show_legend:
                continue
            getter = getattr(r, "legendItems", None)
            if callable(getter):
                items.extend(getter())
            else:
                items.append((r.name, self.colorForSeries(r)))
        for legend in self.legends:
            legend.setItems(items)
        self._layout_all(force=True)

    def _make_coord(self, cls, kind: str, *args):
        """构造单个坐标系：失败降级为 None 并记录一次（不拖垮整图）。"""
        try:
            return cls(self, self._option, *args)
        except Exception as exc:
            warn_once(f"coord-ctor:{kind}", f"坐标构造失败（{kind}）: {exc!r}")
            return None

    def _component_inputs(self, cls, opt: dict, optionKey: str, series_opts: list):
        """列出该组件键下所有该建的实例：``(构造参数, 所属 series 或 None)``。

        数组形式的顶层键在组件声明 ``spawnPerItem = True`` 时逐元素建实例
        （``visualMap`` 的多实例语义）；否则整包传入（``dataZoom`` 自己处理 list）。
        """
        per_item = bool(getattr(cls, "spawnPerItem", False))

        def expand(value):
            """→ 构造参数列表（空 = 不建实例）。

            只有 ``spawnPerItem`` 为真时才逐元素拆；否则整包传入，避免把
            ``dataZoom: [...]`` 拆成多个组件而破坏联动。
            """
            if not isinstance(value, (dict, list)):
                return []
            if isinstance(value, list):
                if per_item:
                    return [v for v in value if isinstance(v, dict)]
                if getattr(cls, "singleOption", False):
                    first = single_option(value, optionKey)
                    return [first] if first is not None else []
                return [value]
            return [value]

        for value in expand(opt.get(optionKey)):
            yield value, None
        for s in series_opts:
            for value in expand(s.get(optionKey)):
                yield value, s

    def _spawn_component(self, cls, comp_opt, series_opt) -> None:
        try:
            comp = cls(self, comp_opt)
        except Exception as exc:
            warn_once(
                f"component-ctor:{getattr(cls, '__name__', cls)!r}",
                f"组件构造失败（{getattr(cls, 'optionKey', '')}）: {exc!r}",
            )
            return
        if series_opt is not None:
            comp.series_opt = series_opt
        # 组件事件 → 图表级信号（brush 选区 / toolbox 动作）
        selected = getattr(comp, "selected", None)
        if selected is not None and hasattr(selected, "connect"):
            try:
                selected.connect(self._onBrushSelected)
            except Exception:
                pass
        if getattr(comp, "optionKey", "") == "toolbox":
            comp.on_action = self.toolboxTriggered.emit
        self._components.append(comp)
