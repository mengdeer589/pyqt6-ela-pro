"""ElaChartWidget 的 option 生命周期 / 合并 / 增量数据方法组。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional


import copy
import math
import time

from ..._internal import is_deleted
from PyQt6.QtCore import (
    QRectF,
    QTimer,
)

from .. import data as _cdata
from ..data import ElaNumericBuffer
from ..dataset import expandDataset
from ..geo_coord import GeoCoord
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
from .._utils import resolve_color_option
from .._utils import single_option
from .._utils import text_weight
from .._utils import warn_key, warn_once
from ..models import ActionPayload, ChartOption, OptionIssue
from ..stream import DataRing, ring_points
from ..axes import (
    AxisModel,
    CalendarCoord,
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
    _axis_options,
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

    @staticmethod
    def _realtime_value(item):
        raw = item.get("value") if isinstance(item, dict) else item
        if isinstance(raw, (list, tuple)):
            raw = raw[-1] if raw else None
        try:
            return float(raw)
        except (TypeError, ValueError, OverflowError):
            return float("-inf")

    def _apply_realtime_sort(self, option) -> None:
        """``realtimeSort``：按值重排类目轴与 bar 数据（单图内静态排序）。"""
        series = [s for s in (option.get("series") or []) if isinstance(s, dict)]
        bar = next(
            (
                s
                for s in series
                if str(s.get("type") or "") == "bar" and bool(s.get("realtimeSort"))
            ),
            None,
        )
        if bar is None:
            return
        data = bar.get("data")
        if not isinstance(data, list) or not data:
            return
        x_axis = option.get("xAxis")
        y_axis = option.get("yAxis")
        horizontal = (
            isinstance(x_axis, dict)
            and str(x_axis.get("type") or "") == "value"
            and isinstance(y_axis, dict)
            and str(y_axis.get("type") or "category") == "category"
        )
        axis = y_axis if horizontal else x_axis
        if not isinstance(axis, dict):
            return
        categories = axis.get("data")
        if not isinstance(categories, list) or len(categories) != len(data):
            return
        order = sorted(
            range(len(data)),
            key=lambda index: self._realtime_value(data[index]),
            reverse=True,
        )
        axis["data"] = [categories[index] for index in order]
        for item in series:
            content = item.get("data")
            if (
                str(item.get("type") or "") == "bar"
                and isinstance(content, list)
                and len(content) == len(order)
            ):
                item["data"] = [content[index] for index in order]

    @staticmethod
    def _universal_config(option) -> dict:
        """``universalTransition`` 配置；未启用返回 None。"""
        raw = option.get("universalTransition")
        if raw is None:
            for series in option.get("series") or []:
                if isinstance(series, dict):
                    raw = series.get("universalTransition")
                    if raw is not None:
                        break
        if raw is None or raw is False:
            return None
        duration = 300.0
        if isinstance(raw, dict):
            if raw.get("enabled") is False:
                return None
            value = raw.get("duration")
            if value is None:
                value = option.get("animationDurationUpdate")
            try:
                duration = max(0.0, float(value))
            except (TypeError, ValueError, OverflowError):
                duration = 300.0
        return {"duration": duration}

    def _begin_universal_transition(
        self, image, duration: float = 300.0, morph=None
    ) -> None:
        """开始旧系列层 → 新系列层的交叉淡出 / 几何形变。"""
        if self._disposed or image is None or image.isNull():
            return
        self._universal_prev = image
        self._universal_morph = morph
        self._universal_t = 0.0
        self._universal_started = time.perf_counter()
        self._universal_duration = max(0.0, float(duration or 0.0))
        if self._universal_duration <= 0.0:
            self._universal_prev = None
            self._universal_t = 1.0
            return
        self._universal_timer.start()

    def _tick_universal(self) -> None:
        if self._disposed:
            return
        try:
            now = time.perf_counter()
            if self._universal_prev is not None or self._universal_morph is not None:
                elapsed = (now - self._universal_started) * 1000.0
                if self._universal_duration <= 0.0:
                    self._universal_t = 1.0
                else:
                    self._universal_t = min(
                        1.0, max(0.0, elapsed / self._universal_duration)
                    )
                if self._universal_t >= 1.0:
                    self._universal_prev = None
                    self._universal_morph = None
            if self._incoming_morph is not None:
                elapsed = (now - self._incoming_started) * 1000.0
                if self._incoming_duration <= 0.0:
                    self._incoming_t = 1.0
                else:
                    self._incoming_t = min(
                        1.0, max(0.0, elapsed / self._incoming_duration)
                    )
                if self._incoming_t >= 1.0:
                    self._incoming_morph = None
            if (
                self._universal_prev is None
                and self._universal_morph is None
                and self._incoming_morph is None
            ):
                self._universal_timer.stop()
            self.update()
        except Exception:
            self._universal_timer.stop()

    def _capture_morph_snapshot(self):
        snapshots = []
        for renderer in self._series:
            snapshot = getattr(renderer, "morphSnapshot", None)
            if not callable(snapshot):
                continue
            try:
                value = snapshot()
            except Exception:
                value = None
            if value:
                snapshots.append((renderer.name, value))
        return snapshots or None

    def setOption(
        self, option: dict, notMerge: bool = False, lazyUpdate: bool = False
    ) -> "ElaChartWidget":
        """设置 option（ECharts ``setOption(option, notMerge, lazyUpdate)``）。

        默认深合并；``series`` / ``dataZoom`` / ``graphic`` / ``visualMap`` 等数组按
        ``id`` → ``name`` → 下标逐项合并，其余 list 整体替换。``series[].data`` 的
        大数值数组按引用摄入，调用方此后不得原地修改。

        :param notMerge: 全量替换并重置交互状态
        :param lazyUpdate: 把重建 / 重绘推迟到下一事件循环
        :returns: self（支持链式调用）
        """
        self._ensure_alive()
        if isinstance(option, ChartOption):
            model = option
        elif isinstance(option, dict):
            model = ChartOption.from_dict(option)
        else:
            model = ChartOption()
        model = expandDataset(
            model,
            base=None if notMerge else self._option,
        )
        option = model
        self._apply_realtime_sort(option)
        universal = None
        cross = None
        if not lazyUpdate:
            config = self._universal_config(option)
            if config is None and not notMerge:
                config = self._universal_config(self._option)
            if config is not None and self._series:
                image = self._capture_series_image()
                morph = self._capture_morph_snapshot()
                if image is not None:
                    universal = (image, config["duration"], morph)
                coord = self.primaryCoord()
                plot = getattr(coord, "plot", None)
                cross = {
                    "image": image,
                    "size": (self.width(), self.height()),
                    "plot": QRectF(plot) if isinstance(plot, QRectF) else QRectF(),
                    "morph": morph,
                    "duration": config["duration"],
                }
        prev_list, prev_by_name = (
            (None, None) if lazyUpdate else self._capture_prev_data(option)
        )
        if notMerge:
            # 先包成紧凑存储再存入，否则深拷贝会逐元素复制百万级 list。
            self._option = ChartOption.from_dict(_copy_option_shallow_arrays(option))
            self._series_state = {}
            self._item_state = {}
            self._timeline_base = None
            self._timeline_index = 0
            self._timeline_playing = False
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
            self._option = ChartOption.from_dict(self._option)
        # 版本号必须由 ``_rebuild`` 递增：``lazyUpdate`` 会在重建前返回，
        # 提前递增会让旧渲染器把位图存进新键，重建后同键命中旧数据。
        self._update_timeline_base(option)
        if lazyUpdate:
            self._lazy_pending = True
            self._schedule_lazy_option()
        else:
            self._apply_option(prev_list, prev_by_name)
        if universal is not None:
            self._begin_universal_transition(*universal)
        if cross is not None:
            self._publish_universal(cross)
        return self

    def _publish_universal(self, payload: dict) -> None:
        """把旧几何 / 截图广播给同组图表（跨图 ``universalTransition``）。"""
        if self._group:
            self._broadcastGroup("universalTransition", payload)

    def setFontFamily(self, family) -> None:
        """设置全图字体族（单个族名；``None`` / 空串恢复系统默认）。
        只接受单族：多族在 Win7 上走慢 shaping 路径且进程级毒化。只失效布局
        缓存并重绘，不重建组件。
        """
        self._ensure_alive()
        self._font_family = single_font_family(family)
        self.invalidateLayout()
        self.update()

    def fontFamily(self) -> str:
        """当前全图字体族（空串 = 系统默认）。"""
        return str(getattr(self, "_font_family", "") or "")

    def updateAxis(self, axis: str, patch: dict, axisIndex: int = 0) -> bool:
        """只更新一条坐标轴（深合并到该轴，其余轴原样保留）。

        :param axis: ``"x"`` / ``"y"`` / ``"single"``
        :param patch: 轴 option 片段，如 ``{"axisLabel": {"formatter": "{value} 月"}}``
        :param axisIndex: 轴下标（单轴传 0）
        :returns: 是否找到目标轴并完成合并
        """
        name = str(axis or "").strip().lower()
        key = _AXIS_OPTION_KEYS.get(name)
        payload = self._axis_patch_payload(key, patch, axisIndex)
        if payload is None:
            return False
        self.setOption({key: payload})
        return True

    def _axis_patch_payload(self, key, patch, axis_index):
        """校验轴目标并生成 ``setOption`` 片段；目标不存在返回 ``None``（不写入）。"""
        if key is None or not isinstance(patch, dict):
            return None
        try:
            index = int(axis_index)
        except (TypeError, ValueError, OverflowError):
            return None
        current = self._option.get(key)
        if isinstance(current, list):
            if not 0 <= index < len(current):
                return None
            return [{} for _ in range(index)] + [patch]
        if isinstance(current, dict):
            return patch if index == 0 else None
        return None

    def setAxisLabelStyle(
        self,
        axis: str,
        *,
        fontSize: float = None,
        fontWeight=None,
        bold: bool = None,
        color: str = None,
        fontFamily: str = None,
        fontStyle: str = None,
        align: str = None,
        verticalAlign: str = None,
        rotate: float = None,
        margin: float = None,
        axisIndex: int = 0,
    ) -> bool:
        """设置一条（或 x/y 两条）坐标轴刻度标签的样式，只改传入的键。

        默认对齐：x 轴文字水平居中于刻度；y 轴文字垂直居中于刻度线、水平贴轴
        （左轴右对齐 / 右轴左对齐）。``align="auto"`` / ``"center"`` 可覆盖。

        :param axis: ``"x"`` / ``"y"`` / ``"single"`` / ``"both"``（x + y）
        :param bold: ``True`` 加粗 / ``False`` 常规，优先于 ``fontWeight``
        :param margin: 标签与轴线的间距（px）
        :returns: 是否写入（轴不存在 / 参数非法 / 没有任何键时 False）
        """
        name = str(axis or "").strip().lower()
        if name in ("both", "all"):
            targets = ("x", "y")
        elif name in _AXIS_OPTION_KEYS:
            targets = (name,)
        else:
            return False
        patch = {}
        if fontSize is not None:
            try:
                size = float(fontSize)
            except (TypeError, ValueError, OverflowError):
                return False
            if not math.isfinite(size) or size <= 0.0:
                return False
            if size > 4096.0:
                return False
            patch["fontSize"] = int(size) if size.is_integer() else size
        if bold is not None:
            if not isinstance(bold, bool):
                return False
            patch["fontWeight"] = 700 if bold else 400
        elif fontWeight is not None:
            weight = text_weight(fontWeight)
            if weight is None:
                return False
            patch["fontWeight"] = weight
        if color is not None:
            if (
                not isinstance(color, str)
                or not resolve_color_option(color, self).isValid()
            ):
                return False
            patch["color"] = color.strip()
        if fontFamily is not None:
            if not isinstance(fontFamily, str):
                return False
            patch["fontFamily"] = single_font_family(fontFamily)
        if fontStyle is not None:
            style_name = str(fontStyle).strip().lower()
            if style_name not in ("normal", "italic", "oblique"):
                return False
            patch["fontStyle"] = style_name
        if align is not None:
            value = str(align).strip().lower()
            if value == "auto":
                patch["align"] = None
            elif value in ("left", "center", "right"):
                patch["align"] = value
            else:
                return False
        if verticalAlign is not None:
            value = str(verticalAlign).strip().lower()
            if value == "auto":
                patch["verticalAlign"] = None
            elif value in ("top", "middle", "bottom"):
                patch["verticalAlign"] = value
            else:
                return False
        if rotate is not None:
            try:
                angle = float(rotate)
            except (TypeError, ValueError, OverflowError):
                return False
            if not math.isfinite(angle):
                return False
            patch["rotate"] = int(angle) if angle.is_integer() else angle
        if margin is not None:
            try:
                gap = float(margin)
            except (TypeError, ValueError, OverflowError):
                return False
            if not math.isfinite(gap) or gap < 0.0:
                return False
            patch["margin"] = int(gap) if gap.is_integer() else gap
        if not patch:
            return False
        try:
            index = int(axisIndex)
        except (TypeError, ValueError, OverflowError):
            return False
        payload = {}
        for target in targets:
            axis_payload = self._axis_patch_payload(
                _AXIS_OPTION_KEYS[target], {"axisLabel": patch}, index
            )
            if axis_payload is None:
                return False
            payload[_AXIS_OPTION_KEYS[target]] = axis_payload
        self.setOption(payload)
        return True

    def axisLabelStyle(self, axis: str = "x", axisIndex: int = 0) -> dict:
        """一条轴标签的实际样式（含默认对齐 / 间距；无此轴返回 ``{}``）。
        返回 ``fontSize`` / ``fontWeight`` / ``fontFamily`` / ``fontStyle`` /
        ``color`` / ``align`` / ``verticalAlign`` / ``margin`` / ``rotate``。
        """
        name = str(axis or "").strip().lower()
        key = _AXIS_OPTION_KEYS.get(name)
        if key is None:
            return {}
        try:
            index = int(axisIndex)
        except (TypeError, ValueError, OverflowError):
            return {}
        options = _axis_options(self._option.get(key))
        if not 0 <= index < len(options):
            return {}
        opt = options[index]
        model = AxisModel(opt, "category" if opt.get("data") else "value", self)
        horizontal = name == "y"
        position = model.position or (
            ("left" if index == 0 else "right")
            if horizontal
            else ("bottom" if index == 0 else "top")
        )
        if horizontal:
            align_default = "left" if position == "right" else "right"
            valign_default = "middle"
            margin_default = 6.0
        else:
            align_default = "center"
            valign_default = "bottom" if position == "top" else "top"
            margin_default = 6.0 if name == "single" else 5.0
        font = model.labelFont()
        return {
            "fontSize": font.pixelSize(),
            "fontWeight": font.weight(),
            "fontFamily": font.family(),
            "fontStyle": "italic" if font.italic() else "normal",
            "color": model.labelColor().name(),
            "align": model.labelAlign(align_default),
            "verticalAlign": model.labelVerticalAlign(valign_default),
            "margin": model.labelMargin(margin_default),
            "rotate": model.labelRotate(),
        }

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
        self._ensure_alive()
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
        """捕获旧系列数据供过渡动画插值；动画关闭时完全跳过（避免百万级物化）。

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
        """排一次延迟重建（常驻子定时器）：``lazyUpdate`` 可连调多次，复用同一个。"""
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
        try:
            prev_list, prev_by_name = self._capture_prev_data({})
            self._apply_option(prev_list, prev_by_name)
        except Exception as exc:
            warn_once(
                warn_key("lazy-update", type(exc).__name__),
                f"lazyUpdate 重建失败: {exc!r}",
            )

    def _capture_timeline_base(self) -> None:
        """捕获 timeline 基线：``baseOption``（优先）或除 ``options`` 外的顶层键。
        一律走 ``_copy_any``（``deepcopy`` 会逐元素复制百万点数组）；只在基线为空
        时捕获——帧切换期间 ``_option`` 已是「基线 + 当前帧」。
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

        帧切换时 ``_option`` 是生效结果，不能当基线来源，只用本次入参。
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
                _merge_option(self._timeline_base, {key: value})
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
        # 帧必须走 setOption 合并语义：``series`` / ``dataZoom`` / ``graphic``
        # 逐项合并，不能整表替换（部分帧是 ECharts 的常见写法）。
        _merge_option(effective, frame)
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
        self._option = ChartOption.from_dict(effective)

    def _refresh(self) -> None:
        """按当前 option 重建并播放过渡动画（timeline 帧切换用）。"""
        prev_list = [_snapshot_series_data(r) for r in self._series]
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
        """按 option 动画键启动入场 / 过渡动画；关闭时直接呈现终态。"""
        opt = self._option
        enabled = opt.get("animation", True) is not False
        has_prev = any(r.prev_data is not None for r in self._series)
        if has_prev:
            duration = opt.get(
                "animationDurationUpdate", opt.get("animationDuration", ANIM_DURATION)
            )
            easing_name = opt.get("animationEasingUpdate", opt.get("animationEasing"))
            delay = opt.get("animationDelayUpdate", opt.get("animationDelay", 0))
        else:
            duration = opt.get("animationDuration", ANIM_DURATION)
            easing_name = opt.get("animationEasing")
            delay = opt.get("animationDelay", 0)
        try:
            duration = float(duration)
        except (TypeError, ValueError, OverflowError):
            duration = float(ANIM_DURATION)
        try:
            delay = max(0.0, float(delay))
        except (TypeError, ValueError, OverflowError):
            delay = 0.0
        self._anim_base_duration = duration
        total = max(
            duration + delay,
            self._max_series_animation_duration(has_prev, duration, delay),
        )
        if enabled:
            # 系列可各自声明更长的时长 / 延迟；全局时钟取最大值，线性推进，系列自行映射。
            # 走策略解析：Reduced 压时长、Disabled 同步落终值（都仍会发 finished）。
            self.anim.startResolved(total, _easing_from_name(easing_name))
        else:
            self.anim.setDuration(total)
            self.anim.setEasing(_easing_from_name(easing_name))
            self.anim.complete()

    def _max_series_animation_duration(
        self, has_prev: bool, base_duration: float = 0.0, base_delay: float = 0.0
    ) -> float:
        """所有可见系列声明的（延迟 + 时长）最大值（ms）。"""
        longest = float(base_duration) + float(base_delay)
        for renderer in self._series:
            if not renderer.visible:
                continue
            value = renderer.animationDuration(has_prev)
            duration = float(base_duration if value is None else value)
            delay = renderer.animationDelay(has_prev)
            if delay <= 0.0 and base_delay > 0.0:
                delay = float(base_delay)
            longest = max(longest, duration + delay)
        return longest

    def getOption(self) -> ChartOption:
        """当前 option 深拷贝（dataclass 模型，dict 兼容）。"""
        self._ensure_alive()
        option = _unwrap_option(_copy_any(self._option))
        return ChartOption.from_dict(self._overlay_live_state(option))

    def getOptionDict(self) -> dict:
        """当前 option 的普通 dict 形式（ECharts 互操作 / 序列化）。"""
        return self.getOption().to_dict()

    def validateOption(self, option) -> list[OptionIssue]:
        """轻量校验 option；返回 ``OptionIssue`` 列表（不抛异常）。"""
        issues: list[OptionIssue] = []
        try:
            if isinstance(option, ChartOption):
                model = option
            elif isinstance(option, dict):
                model = ChartOption.from_dict(option)
            else:
                return [OptionIssue("", "option 必须是 ChartOption 或 dict")]
        except Exception as exc:
            return [OptionIssue("", f"option 解析失败：{exc}")]
        series = model.get("series")
        if series is not None and not isinstance(series, list):
            issues.append(OptionIssue("series", "series 必须是列表"))
            series = []
        for index, item in enumerate(series or []):
            path = f"series[{index}]"
            if not isinstance(item, dict):
                issues.append(OptionIssue(path, "系列必须是 dict 或 SeriesOption"))
                continue
            type_name = str(item.get("type") or "")
            if not type_name:
                issues.append(OptionIssue(f"{path}.type", "系列缺少 type"))
            elif type_name not in SERIES_REGISTRY:
                issues.append(
                    OptionIssue(
                        f"{path}.type",
                        f"未注册的系列类型 {type_name!r}",
                        "warning",
                    )
                )
        return issues

    def _overlay_live_state(self, option: dict) -> dict:
        """把交互状态（图例选择 / dataZoom 窗口 / 选中态）写回 ``getOption`` 的返回值。

        不改内部 ``_option``；宿主才能保存与恢复视图。
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

    def pushData(self, series, points, maxPoints: int = None) -> bool:
        """向系列追加流式数据；``maxPoints`` 只保留窗口内最后 N 点。

        ``series`` 可为系列名 / ``id`` / 下标；点可为单点或点列表。内部用
        ``DataRing`` 环形缓冲，不清空 / 复制整窗。
        """
        self._ensure_alive()
        index = self._stream_series_index(series)
        if index is None:
            return False
        series_opts = [
            s for s in (self._option.get("series") or []) if isinstance(s, dict)
        ]
        target = series_opts[index]
        state = getattr(self, "_stream_data", None)
        if state is None:
            state = {}
            self._stream_data = state
        ring = state.get(index)
        if ring is not None and target.get("data") is not ring:
            ring = None
        if ring is None:
            current = target.get("data")
            if isinstance(current, DataRing):
                ring = current
            else:
                values = _cdata.unwrapData(current) if current is not None else []
                if not isinstance(values, list):
                    values = []
                ring = DataRing(values, maxPoints)
        elif maxPoints is not None and maxPoints != ring.maxPoints:
            ring = DataRing(ring, maxPoints)
        ring.push(ring_points(points))
        state[index] = ring
        target["data"] = ring
        renderer = self._renderer_for_series_index(index)
        if renderer is not None:
            renderer.opt["data"] = ring
            renderer.prev_data = None
        self.anim.stop()
        self.anim.setProgress(1.0)
        self._refresh_stream(target)
        self.update()
        return True

    def _refresh_stream(self, target) -> None:
        """流式推送后只刷新坐标系范围 / 轴窗口，不重建组件与渲染器。"""
        series_opts = [
            s for s in (self._option.get("series") or []) if isinstance(s, dict)
        ]
        try:
            coords = list(self._coords)
        except Exception:
            coords = []
        if not coords:
            try:
                coord = self.coordFor(target)
            except Exception:
                coord = None
            coords = [coord] if coord is not None else []
        for coord in coords:
            try:
                coord.setSeries(series_opts)
            except Exception:
                continue
        for comp in self._components:
            capture = getattr(comp, "captureExtent", None)
            if callable(capture):
                try:
                    capture()
                except Exception:
                    continue
        for comp in self._components:
            apply = getattr(comp, "apply", None)
            if callable(apply):
                try:
                    apply()
                except Exception:
                    continue
        self._opt_version += 1
        self.invalidateLayout()
        self.invalidateSeriesLayer()
        try:
            self._layout_all(force=True)
        except Exception:
            pass

    def setDataWindow(self, series, data, maxPoints: int = None) -> bool:
        """整窗替换流式数据（``data`` 只保留最后 ``maxPoints`` 点）。"""
        self._ensure_alive()
        index = self._stream_series_index(series)
        if index is None:
            return False
        series_opts = [
            s for s in (self._option.get("series") or []) if isinstance(s, dict)
        ]
        ring = DataRing(ring_points(data), maxPoints)
        target = series_opts[index]
        target["data"] = ring
        state = getattr(self, "_stream_data", None)
        if state is None:
            state = {}
            self._stream_data = state
        state[index] = ring
        renderer = self._renderer_for_series_index(index)
        if renderer is not None:
            renderer.opt["data"] = ring
            renderer.prev_data = None
        self.anim.stop()
        self.anim.setProgress(1.0)
        self._refresh_stream(target)
        self.update()
        return True

    def streamLength(self, series) -> int:
        """流式窗口当前点数（非流式系列返回其数据长度）。"""
        index = self._stream_series_index(series)
        if index is None:
            return 0
        state = getattr(self, "_stream_data", None) or {}
        ring = state.get(index)
        if ring is not None:
            return len(ring)
        series_opts = self._option.get("series") or []
        if 0 <= index < len(series_opts):
            data = series_opts[index].get("data")
            try:
                return len(data) if data is not None else 0
            except TypeError:
                return 0
        return 0

    def _renderer_for_series_index(self, index: int):
        """option 内 series 下标 → 渲染器（``_series`` 可能跳过未注册类型）。"""
        for renderer in self._series:
            if getattr(renderer, "_series_index", -1) == index:
                return renderer
        return None

    def _stream_series_index(self, series):
        series_opts = self._option.get("series") or []
        if isinstance(series, int) and not isinstance(series, bool):
            return series if 0 <= series < len(series_opts) else None
        text = str(series or "")
        for index, item in enumerate(series_opts):
            if not isinstance(item, dict):
                continue
            if text and text in (
                str(item.get("name") or ""),
                str(item.get("id") or ""),
            ):
                return index
        return None

    def appendData(self, params: dict) -> bool:
        """向指定系列追加数据（ECharts ``appendData({seriesIndex|seriesName, data})``）。

        ``params`` 需含 ``seriesIndex`` / ``seriesName`` / ``seriesId`` 之一与 ``data``。
        :returns: 是否找到目标系列并追加
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
        if isinstance(data_list, (ElaNumericBuffer, DataRing)):
            data_list = data_list.toList()
        elif not isinstance(data_list, list):
            # 短于 toBuffer 阈值时 option 里保留的是裸 ndarray / array.array：
            # 必须先物化，不能当空数组丢掉已有数据。
            data_list = _cdata.unwrapData(data_list) if data_list is not None else []
            if not isinstance(data_list, list):
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
        if renderer is None:
            renderer = self._renderer_for_series_index(index)
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
        """触发 ECharts 动作（``dispatchAction``；未识别的 ``type`` 返回 ``False``）。

        :returns: 动作是否被识别并执行
        """
        self._ensure_alive()
        if isinstance(payload, ActionPayload):
            payload = payload.to_dict()
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
        self._ensure_alive()
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
        # 只有已经启用 Y 窗口的组件才缩放 Y；显式 dataZoom 未给 yAxisIndex
        # 时不能因为点一次 zoomStep 就偷偷开始压 Y 轴。
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
        self._progressive_step = 1
        self._progressive_scheduled = False
        self._hide_annotation_editor()
        opt = self._option
        self._layout_key = None
        legend_opts = self._rebuild_header(opt)
        series_opts = [s for s in (opt.get("series") or []) if isinstance(s, dict)]
        self._rebuild_coords(opt, series_opts)
        self._rebuild_series(series_opts)
        self._rebuild_components(opt, series_opts)

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

        self._rebuild_legend_items(opt, legend_opts)
        self._layout_all(force=True)
        self._refresh_accessible_description()

    def _rebuild_header(self, opt: dict) -> list:
        """重建标题 / 图例 / tooltip，并应用图例初始显隐。"""
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

        # 图例 selected：初始显隐状态（ECharts ``legend.selected``，多图例逐个应用）
        for legend_opt in legend_opts:
            selected = legend_opt.get("selected")
            if isinstance(selected, dict):
                for name, visible in selected.items():
                    self._series_state[str(name)] = bool(visible)
                    self._item_state[str(name)] = bool(visible)
        return legend_opts

    def _rebuild_coords(self, opt: dict, series_opts: list) -> None:
        """重建坐标系并同步轴域；随后让常驻组件重捕 dataZoom 全量范围。"""
        # 坐标系：calendar > polar > singleAxis > grid。grid 仅在 option 显式给出
        # xAxis/yAxis/grid，或存在落在 grid 的系列时创建。
        self._coords = []
        if "calendar" in opt:
            c = self._make_coord(CalendarCoord, "calendar")
            if c is not None:
                self._coords.append(c)
        if "geo" in opt:
            geo_opts = _component_options(opt.get("geo"), "geo")
            for index in range(max(1, len(geo_opts))):
                try:
                    self._coords.append(GeoCoord(self, opt, index))
                except Exception as exc:
                    warn_once(
                        f"coord-ctor:geo:{index}",
                        f"坐标系构造失败（geo:{index}）: {exc!r}",
                    )
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

    def _rebuild_series(self, series_opts: list) -> None:
        """重建系列渲染器，并迁移选中态。"""
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
            data_len = renderer.itemCount()
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
            selected_map = r.opt.get("selectedMap")
            if isinstance(selected_map, dict):
                for key, value in selected_map.items():
                    if not value:
                        continue
                    try:
                        seeds.add(int(key))
                    except (TypeError, ValueError, OverflowError):
                        continue
            # 基类按顶层 data 扫 ``data[i].selected``；层级系列覆写成扁平节点。
            seeds.update(r.selectedSeedIndices())
            if seeds:
                data_len = r.itemCount()
                self._selection[r.name] = {i for i in seeds if 0 <= i < data_len}

    def _rebuild_components(self, opt: dict, series_opts: list) -> None:
        """重建交互 / 表达组件，并恢复 dataZoom 窗口与默认滚轮缩放。"""
        # 用户一旦配了 dataZoom，自动创建的滚轮 inside 必须退场；否则它留在
        # _host_components 里、永远排在最前，_component("dataZoom") / 滚轮 /
        # dispatchAction 都会命中隐藏的 auto，而可见 slider 不动。
        if opt.get("dataZoom"):
            auto = self._auto_wheel_zoom()
            if auto is not None:
                self._drop_component(auto)
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

    def _rebuild_legend_items(self, opt: dict, legend_opts: list) -> None:
        """把当前系列的图例条目推给所有图例。"""
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

    def _make_coord(self, cls, kind: str, *args):
        """构造单个坐标系：失败降级为 None 并记录一次（不拖垮整图）。"""
        try:
            return cls(self, self._option, *args)
        except Exception as exc:
            warn_once(f"coord-ctor:{kind}", f"坐标构造失败（{kind}）: {exc!r}")
            return None

    def _component_inputs(self, cls, opt: dict, optionKey: str, series_opts: list):
        """列出该组件键下所有该建的实例：``(构造参数, 所属 series 或 None)``。
        数组形式的顶层键在 ``spawnPerItem = True`` 时逐元素建实例（``visualMap``
        多实例语义）；否则整包传入（``dataZoom`` 自己处理 list）。
        """
        per_item = bool(getattr(cls, "spawnPerItem", False))

        def expand(value):
            """→ 构造参数列表（空 = 不建实例）。
            只有 ``spawnPerItem`` 为真才逐元素拆；否则整包传入，避免拆散
            ``dataZoom: [...]`` 的联动。
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
