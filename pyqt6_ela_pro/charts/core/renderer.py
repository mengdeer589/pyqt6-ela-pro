"""系列渲染器基类。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations

from typing import TYPE_CHECKING


import math
from collections.abc import Sequence

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
)

from .. import data as _cdata
from .._tokens import (
    ANIM_EASING,
    T,
)
from .._utils import (
    merged_text_style,
    parse_color,
    resolve_color_option,
    text_italic,
    text_on_fill,
    text_weight,
)
from .._utils import to_float as _to_float
from ..labels import label_text_size, paint_label
from ..axes import (
    chartFont,
    formatValue,
)
from ..models import OptionModel, SeriesOption
from ._shared import _easing_from_name, formatLabelTemplate, parseDataPoint

if TYPE_CHECKING:
    from .widget import ElaChartWidget


class SeriesRenderer:
    """系列渲染器协议基类。
    子类实现 ``layout(rect)`` / ``paint(p, anim_t)`` / ``hitTest(pos)``；
    坐标映射经 ``self.chart.coordFor(self.opt)`` 取得 Coord。
    """

    #: ``labelShown`` 的缺省值（层级系列的 ``label.show`` 默认开）
    labelVisibleByDefault = False

    def __init__(self, chart: "ElaChartWidget", opt: dict):
        self.chart = chart
        #: 原始 series option（**不是副本**；标签编辑等需要写回宿主 option）
        if isinstance(opt, OptionModel):
            self._source_opt = opt
            self.opt = type(opt).from_dict({k: v for k, v in opt.items()})
        elif isinstance(opt, dict):
            self._source_opt = SeriesOption.from_dict(opt)
            self.opt = SeriesOption.from_dict(self._source_opt)
        else:
            self._source_opt = SeriesOption()
            self.opt = SeriesOption()
        self.name = str(self.opt.get("name") or "")
        #: ECharts ``series.id``（setOption 合并时的身份匹配键）
        self.id = str(self.opt.get("id") or "")
        #: 系列显隐（legend 点击切换；初始状态由 widget 按 legend.selected 注入）
        self.visible = True
        #: **最近一次绘制所用的动画进度**（core 在 paint / 命中分发前写入）；
        #: ``hitTest`` 靠它判断当前是否处于动画中。
        self._anim_t = 1.0
        #: 上次 option 的旧数据（core 注入，用于动画插值）
        self.prev_data = None
        #: itemStyle 均匀性缓存 (key, {} | None)，见 ``uniformItemStyle``
        self._uniform_style_cache = None
        #: 最近一次绘制出的数据标签命中框 ``[(dataIndex, QRectF, text)]``
        self._label_rects = []
        #: ``valueStats`` 缓存（数据身份 + 长度；持强引用防 id 复用）
        self._stats_key = None
        self._stats_ref = None
        self._stats_cache = None
        #: 本帧是否因 ``progressive`` 只画了前缀
        self._progressive_partial = False

    def layout(self, rect: QRectF) -> None:
        """计算几何（坐标映射经 coord）。"""

    def paint(self, p: QPainter, anim_t: float) -> None:
        """绘制。anim_t ∈ [0,1]，入场 / 更新动画进度。"""
        raise NotImplementedError

    def hitTest(self, pos: QPointF):
        """命中检测 → ``{"name","value","series",...}`` 或 None。

        默认实现不参与命中；需要动画期命中的子类覆写本方法。
        """
        return None

    @property
    def silent(self) -> bool:
        """ECharts ``series.silent``：True 时不响应鼠标命中（tooltip / click）。"""
        return bool(self.opt.get("silent", False))

    def animProgress(self, t: float, raw: float = None) -> float:
        """系列动画进度：``series.animation=false`` 时直接呈现终态。

        ``raw`` 是线性时间进度；系列按自己的 ``animationDuration`` /
        ``animationEasing`` / ``animationDelay`` 映射，缺省沿用顶层配置。
        """
        if self.opt.get("animation", True) is False:
            return 1.0
        if raw is None or t >= 1.0:
            return t
        if self.itemCount() > self.animationThreshold():
            return 1.0
        anim = getattr(self.chart, "anim", None)
        total = float(getattr(anim, "requested", 0) or 0.0)
        delay = self.animationDelay(self.prev_data is not None)
        duration = self.animationDuration(self.prev_data is not None)
        if duration is None:
            duration = float(getattr(self.chart, "_anim_base_duration", 0.0) or 0.0)
        if duration <= 0:
            return 1.0
        elapsed = raw * total
        if elapsed < delay:
            return 0.0
        progress = (elapsed - delay) / duration
        progress = max(0.0, min(1.0, progress))
        curve = QEasingCurve(self.animationEasing(self.prev_data is not None))
        return curve.valueForProgress(progress)

    def animationDelay(self, transition: bool = False) -> float:
        """系列 ``animationDelay``（过渡时优先 ``animationDelayUpdate``）。"""
        keys = (
            ("animationDelayUpdate", "animationDelay")
            if transition
            else ("animationDelay",)
        )
        for key in keys:
            raw = self.opt.get(key)
            if raw is None:
                chart_opt = getattr(self.chart, "_option", None)
                raw = chart_opt.get(key) if isinstance(chart_opt, dict) else None
            if raw is None:
                continue
            value = _to_float(raw, None)
            if value is not None:
                return max(0.0, value)
        return 0.0

    def animationThreshold(self) -> float:
        """``animationThreshold``：数据量超过阈值时关闭入场 / 过渡动画。"""
        raw = self.opt.get("animationThreshold")
        if raw is None:
            chart_opt = getattr(self.chart, "_option", None)
            raw = (
                chart_opt.get("animationThreshold")
                if isinstance(chart_opt, dict)
                else None
            )
        value = _to_float(raw, None)
        return 2000.0 if value is None else max(0.0, value)

    def progressiveChunkMode(self) -> str:
        """``progressiveChunkMode``：``sequential`` 或 ``mod``。"""
        raw = self.opt.get("progressiveChunkMode")
        if raw is None:
            chart_opt = getattr(self.chart, "_option", None)
            raw = (
                chart_opt.get("progressiveChunkMode")
                if isinstance(chart_opt, dict)
                else None
            )
        return "mod" if str(raw or "").strip().lower() == "mod" else "sequential"

    def progressiveIndices(self, total: int):
        """本帧要绘制的下标；``mod`` 模式跨数据均匀取样。"""
        limit = self.progressiveLimit(total)
        if limit >= total:
            return range(total)
        if self.progressiveChunkMode() == "mod":
            stride = max(1, int(math.ceil(total / max(1, limit))))
            return list(range(0, total, stride))[:limit]
        return range(limit)

    def progressiveSelect(self, values):
        """按 ``progressiveIndices`` 选中本帧数据；未启用时原样返回。"""
        indices = self.progressiveIndices(len(values))
        if len(indices) >= len(values):
            return values
        return [values[index] for index in indices]

    def progressiveLimit(self, total: int) -> int:
        """本帧可绘制的点数（``progressive`` / ``progressiveThreshold``）。

        未启用 / 数据量未过阈值时返回 ``total``；启用后按
        ``chart._progressive_step × budget`` 逐帧补齐。
        """
        self._progressive_partial = False
        try:
            total = int(total)
        except (TypeError, ValueError, OverflowError):
            return 0
        if total <= 0 or getattr(self.chart, "_progressive_disabled", False):
            return total
        raw = self.opt.get("progressive")
        chart_opt = getattr(self.chart, "_option", None)
        if raw is None and isinstance(chart_opt, dict):
            raw = chart_opt.get("progressive")
        if raw is None or raw is False:
            return total
        raw_threshold = self.opt.get("progressiveThreshold")
        if raw_threshold is None and isinstance(chart_opt, dict):
            raw_threshold = chart_opt.get("progressiveThreshold")
        threshold = _to_float(raw_threshold, 3000.0)
        if total <= max(0.0, threshold):
            return total
        if isinstance(raw, bool):
            budget = 2000
        else:
            try:
                budget = max(1, int(raw))
            except (TypeError, ValueError, OverflowError):
                budget = 2000
        step = max(1, int(getattr(self.chart, "_progressive_step", 1) or 1))
        limit = min(total, budget * step)
        self._progressive_partial = limit < total
        return limit

    def animationDuration(self, transition: bool = False):
        """系列 ``animationDuration``（过渡时优先 ``animationDurationUpdate``）。"""
        keys = (
            ("animationDurationUpdate", "animationDuration")
            if transition
            else ("animationDuration",)
        )
        for key in keys:
            raw = self.opt.get(key)
            if raw is None:
                continue
            value = _to_float(raw, None)
            if value is not None:
                return max(0.0, value)
        return None

    def animationEasing(self, transition: bool = False):
        """系列缓动曲线；未配置时回退顶层曲线。"""
        anim = getattr(self.chart, "anim", None)
        default = getattr(anim, "easing", None)
        if default is None:
            default = ANIM_EASING
        keys = (
            ("animationEasingUpdate", "animationEasing")
            if transition
            else ("animationEasing",)
        )
        for key in keys:
            raw = self.opt.get(key)
            if raw is not None:
                return _easing_from_name(raw, default)
        return default

    def requestSeriesRepaint(self) -> None:
        """请求下一帧重绘系列层（持续动效每帧推进外观时用）。
        只 ``chart.update()`` 不够：系列层位图缓存键不含相位，会贴回同一张位图。
        几何没变，所以不能用 ``invalidateLayout()``（会连带全量重排）。
        """
        chart = self.chart
        chart.invalidateSeriesLayer()
        chart.update()

    def morphSnapshot(self):
        """``universalTransition`` 的几何快照；默认不参与形变。"""
        return None

    def morphKey(self, index) -> str:
        """形变匹配键：数据项 ``id`` → ``name`` → 下标字符串。"""
        data = self.data()
        if isinstance(index, int) and 0 <= index < len(data):
            item = data[index]
            if isinstance(item, dict):
                key = item.get("id", item.get("name"))
                if key is not None and key != "":
                    return str(key)
        return str(index)

    def data(self) -> list:
        """系列原始 data（``list`` / ``ElaNumericBuffer``；缺省返回空 list）。

        对外语义与 list 一致（可 len / 下标 / 迭代 / 比较）；内部热路径优先
        用 :meth:`dataView`，避免把缓冲物化成 list。
        """
        d = self.opt.get("data")
        if isinstance(d, list):
            return d
        if isinstance(d, _cdata.ElaNumericBuffer):
            return d
        if isinstance(d, Sequence) and not isinstance(d, (str, bytes, bytearray)):
            return d
        if _cdata.isBufferLike(d):
            # 写回 opt：调用方要求同一 data 对象反复拿到同一实例
            # （采样缓存键含 id(data)，每次新建包装件会让缓存永不命中）。
            wrapped = _cdata.ElaNumericBuffer(d)
            self.opt["data"] = wrapped
            return wrapped
        return []

    def dataView(self):
        """系列数据的只读视图（内部热路径专用，不做拷贝 / list 化）。"""
        d = self.opt.get("data")
        if isinstance(d, list) or _cdata.isBufferLike(d):
            return d
        if isinstance(d, Sequence) and not isinstance(d, (str, bytes, bytearray)):
            return d
        return []

    def valueStats(self) -> dict:
        """有限 y 值的统计（min / max / 下标 / sum / count），按数据身份缓存。
        markLine / markPoint 的 average / max / min 走这里；逐点物化整份数据
        在缩放时每步都要重付，所以缓存。
        """
        data = self.dataView()
        key = (id(data), len(data), _cdata.dataVersion(data))
        if self._stats_ref is data and self._stats_key == key:
            return self._stats_cache
        lo = hi = None
        lo_i = hi_i = None
        total = 0.0
        count = 0
        for index, item in enumerate(data):
            _x, y = parseDataPoint(item, index)
            if y is None or not math.isfinite(y):
                continue
            count += 1
            total += y
            if lo is None or y < lo:
                lo, lo_i = y, index
            if hi is None or y > hi:
                hi, hi_i = y, index
        stats = {
            "min": lo,
            "max": hi,
            "minIndex": lo_i,
            "maxIndex": hi_i,
            "sum": total,
            "count": count,
        }
        self._stats_key = key
        self._stats_ref = data
        self._stats_cache = stats
        return stats

    def color(self) -> QColor:
        """系列主色（``itemStyle.color`` 覆盖 → option color → 全局调色板）。"""
        raw = self.itemStyle().get("color")
        if isinstance(raw, str) and raw:
            color = resolve_color_option(raw, self.chart)
            if color.isValid():
                return color
        return self.chart.colorForSeries(self)

    def legendItems(self) -> list:
        """图例条目 ``[(name, QColor)]``（默认 = 系列名；饼 / 漏斗按数据项）。"""
        return [(self.name, self.color())]

    def itemStyle(self) -> dict:
        """系列级 ``itemStyle``（非 dict 时返回空 dict）。"""
        style = self.opt.get("itemStyle")
        return style if isinstance(style, dict) else {}

    @staticmethod
    def itemStyleOf(item) -> dict:
        """数据项级 ``itemStyle``（``{"value": ..., "itemStyle": {...}}``）。"""
        if isinstance(item, dict):
            style = item.get("itemStyle")
            if isinstance(style, dict):
                return style
        return {}

    def uniformItemStyle(self):
        """系列级统一 ``itemStyle``；``None`` = 存在逐项 itemStyle。
        紧凑数值容器直接判为均匀（元素类型在包装时已校验）；``list`` 必须全量扫，
        抽样会漏掉少量带 ``itemStyle`` 的 dict 项。
        """
        if self.visualMapComponent() is not None:
            return None
        data = self.opt.get("data")
        try:
            n = len(data)
        except TypeError:
            n = 0
        key = (id(self.opt), id(data), n)
        hit = self._uniform_style_cache
        if hit is not None and hit[0] == key and hit[1] is self.opt and hit[2] is data:
            return hit[3]
        # 紧凑数值容器：元素类型在包装时已校验，必定没有逐项 itemStyle
        if n and _cdata.isBufferLike(data):
            self._uniform_style_cache = (key, self.opt, data, {})
            return {}
        result = {}
        if n:
            for i in range(n):
                item = data[i]
                if isinstance(item, dict) and isinstance(item.get("itemStyle"), dict):
                    result = None
                    break
        self._uniform_style_cache = (key, self.opt, data, result)
        return result

    def _itemStyleFor(self, index):
        """取某下标的项级 ``itemStyle``（走 ``uniformItemStyle`` 快路径）。"""
        uniform = self.uniformItemStyle()
        if uniform is not None:
            return uniform
        item = None
        data = self.data()
        if isinstance(index, int) and 0 <= index < len(data):
            item = data[index]
        return self.itemStyleOf(item)

    def itemCount(self) -> int:
        """数据项总数（选中集裁剪 / 外部索引换算的统一口径）。"""
        return len(self.data())

    def selectedSeedIndices(self) -> set:
        """option 里的初始选中下标（``data[i].selected``）。"""
        seeds = set()
        data = self.data()
        if _cdata.isBufferLike(data):
            return seeds
        for index, item in enumerate(data):
            if isinstance(item, dict) and item.get("selected") is True:
                seeds.add(index)
        return seeds

    def nameAtIndex(self, index: int) -> str:
        """数据下标 → 可读名称（选中事件 / 外部查询用）。"""
        try:
            data = self.data()
            if not (0 <= index < len(data)):
                return ""
            x, _y = parseDataPoint(data[index], index)
            coord = self.chart.coordFor(self.opt)
            axis = getattr(coord, "x_axis", None)
            if axis is not None and axis.type == "category":
                cats = axis.categories
                local = axis.localIndex(x)
                if isinstance(local, int) and 0 <= local < len(cats):
                    return str(cats[local])
            return str(x)
        except Exception:
            return ""

    def resolveColor(self, raw, default=None) -> QColor:
        """option 颜色解析：支持 ``color.*`` 主题令牌。"""
        return resolve_color_option(raw, self.chart, default)

    def itemRadius(self, index=None, default: float = 0.0) -> float:
        """数据项圆角（``itemStyle.borderRadius``，列表取最大）。"""
        raw = self._itemStyleFor(index).get("borderRadius")
        if raw is None:
            raw = self.itemStyle().get("borderRadius")
        if isinstance(raw, (list, tuple)):
            raw = max((_to_float(v, 0.0) for v in raw), default=0.0)
        return max(0.0, _to_float(raw, default))

    def uniformItemStyleResolved(self) -> dict:
        """一次性解析「全系列统一」的外观，供绘制循环循环外取用。
        返回 ``{"color", "opacity", "borderColor", "borderWidth", "borderRadius"}``；
        仅当 ``uniformItemStyle()`` 判定为均匀时可用（否则 ``None``）。
        """
        if self.uniformItemStyle() is None:
            return None
        style = self.itemStyle()
        raw_color = style.get("color")
        color = None
        if isinstance(raw_color, str) and raw_color:
            c = resolve_color_option(raw_color, self.chart)
            if c.isValid():
                color = c
        raw_border = style.get("borderColor")
        border = None
        if isinstance(raw_border, str) and raw_border:
            c = resolve_color_option(raw_border, self.chart)
            if c.isValid():
                border = c
        try:
            opacity = max(0.0, min(1.0, float(style.get("opacity", 1.0))))
        except (TypeError, ValueError, OverflowError):
            opacity = 1.0
        try:
            border_width = max(0.0, float(style.get("borderWidth", 0)))
        except (TypeError, ValueError, OverflowError):
            border_width = 0.0
        raw_radius = style.get("borderRadius")
        radius = None
        if raw_radius is not None:
            if isinstance(raw_radius, (list, tuple)):
                raw_radius = max((_to_float(v, 0.0) for v in raw_radius), default=0.0)
            radius = max(0.0, _to_float(raw_radius, 0.0))
        return {
            "color": color,
            "opacity": opacity,
            "borderColor": border,
            "borderWidth": border_width,
            "borderRadius": radius,
        }

    def colorByData(self) -> bool:
        raw = self.opt.get("colorBy")
        if raw is None:
            chart_opt = getattr(self.chart, "_option", None)
            raw = chart_opt.get("colorBy") if isinstance(chart_opt, dict) else None
        return str(raw or "").strip().lower() == "data"

    def itemColor(self, index=None, default=None) -> QColor:
        """数据项颜色：项 ``itemStyle.color`` → 系列 ``itemStyle.color``
        → ``default`` → 全局调色板。"""
        raw = self._itemStyleFor(index).get("color") or self.itemStyle().get("color")
        if isinstance(raw, str) and raw:
            color = resolve_color_option(raw, self.chart)
            if color.isValid():
                return color
        if default is not None:
            resolved = resolve_color_option(default, self.chart)
            if resolved.isValid():
                return resolved
        if self.colorByData() and isinstance(index, int):
            palette = self.chart.palette()
            if palette:
                color = parse_color(palette[index % len(palette)])
                if color.isValid():
                    return color
        return self.color()

    def _visual_value(self, item):
        """visualMap 取值维度：``dimension`` 优先，缺省最后一维。"""
        value = item.get("value") if isinstance(item, dict) else item
        if isinstance(value, (list, tuple)) and value:
            vm = self.visualMapComponent()
            dim = (getattr(vm, "opt", None) or {}).get("dimension") if vm else None
            if isinstance(dim, int) and not isinstance(dim, bool):
                index = dim if 0 <= dim < len(value) else len(value) - 1
            else:
                index = len(value) - 1
            return _to_float(value[index], None)
        return _to_float(value, None)

    def visualColor(self, index=None):
        """``visualMap`` 映射出的颜色；未绑定 / 取不到值返回 ``None``。"""
        vm = self.visualMapComponent()
        if vm is None or not isinstance(index, int):
            return None
        data = self.data()
        if not 0 <= index < len(data):
            return None
        value = self._visual_value(data[index])
        if value is None:
            return None
        return self.visualColorForValue(value)

    def visualColorForValue(self, value):
        """按裸数值取 ``visualMap`` 颜色（层级节点 / 流带 / 仪表用）。"""
        vm = self.visualMapComponent()
        if vm is None:
            return None
        number = _to_float(value, None)
        if number is None:
            return None
        try:
            color = parse_color(vm.mapColor(number))
        except Exception:
            return None
        return color if color.isValid() else None

    def hasItemColor(self, index) -> bool:
        """数据项是否显式配置了 ``itemStyle.color``。"""
        data = self.data()
        if not isinstance(index, int) or not 0 <= index < len(data):
            return False
        item = data[index]
        if not isinstance(item, dict):
            return False
        style = item.get("itemStyle")
        return isinstance(style, dict) and isinstance(style.get("color"), str)

    def dataColor(self, index=None, default=None) -> QColor:
        """绘制颜色：数据项颜色 > visualMap > 系列颜色 / default。"""
        if not self.hasItemColor(index):
            visual = self.visualColor(index)
            if visual is not None:
                return visual
        return self.itemColor(index, default)

    def itemOpacity(self, index=None) -> float:
        """数据项透明度：项 ``itemStyle.opacity`` → 系列 ``itemStyle.opacity``（默认 1）。"""
        raw = self._itemStyleFor(index).get("opacity")
        if raw is None:
            raw = self.itemStyle().get("opacity")
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError, OverflowError):
            return 1.0

    def itemBorder(self, index=None):
        """数据项描边 → ``(QColor | None, width)``（未配置颜色返回 None）。"""
        style = self._itemStyleFor(index)
        series_style = self.itemStyle()
        raw = style.get("borderColor") or series_style.get("borderColor")
        width = style.get("borderWidth", series_style.get("borderWidth", 0))
        color = None
        if isinstance(raw, str) and raw:
            candidate = resolve_color_option(raw, self.chart)
            if candidate.isValid():
                color = candidate
        try:
            width = max(0.0, float(width))
        except (TypeError, ValueError, OverflowError):
            width = 0.0
        return color, width

    def visualMapComponent(self):
        """绑定到本系列的 ``visualMap`` 组件（显式绑定优先 → 通用件）；没有返回 None。

        必须按系列身份取：多个系列共用 visualMap 时不能把别的系列的分段色抢走。
        """
        idx = getattr(self, "_series_index", 0)
        sid = str(self.opt.get("id") or "")
        generic = None
        for comp in self.chart.components:
            if not callable(getattr(comp, "mapColor", None)):
                continue
            binds = getattr(comp, "bindsTo", None)
            if not callable(binds):
                return comp
            if not binds(idx, sid):
                continue
            if getattr(comp, "isGeneric", False):
                if generic is None:
                    generic = comp
                continue
            return comp
        return generic

    def emphasisOption(self) -> dict:
        """系列级 ``emphasis``（非 dict 时返回空 dict）。"""
        opt = self.opt.get("emphasis")
        return opt if isinstance(opt, dict) else {}

    def emphasisItemStyle(self, index=None) -> dict:
        """hover 高亮样式：系列 ``emphasis.itemStyle`` → 项 ``emphasis.itemStyle``。"""
        style = dict(self.emphasisOption().get("itemStyle") or {})
        item = None
        data = self.data()
        if isinstance(index, int) and 0 <= index < len(data):
            item = data[index]
        if isinstance(item, dict):
            item_emphasis = item.get("emphasis")
            if isinstance(item_emphasis, dict) and isinstance(
                item_emphasis.get("itemStyle"), dict
            ):
                style.update(item_emphasis["itemStyle"])
        return style

    def blurOption(self) -> dict:
        """系列级 ``blur``（非 dict 时返回空 dict）。"""
        opt = self.opt.get("blur")
        return opt if isinstance(opt, dict) else {}

    def blurItemStyle(self) -> dict:
        """非高亮项的淡化样式（``blur.itemStyle``）。"""
        style = self.blurOption().get("itemStyle")
        return style if isinstance(style, dict) else {}

    def emphasisColor(self, index=None):
        """hover 高亮色（``emphasis.itemStyle.color``）；未配置返回 None。"""
        raw = self.emphasisItemStyle(index).get("color")
        if isinstance(raw, str) and raw:
            color = resolve_color_option(raw, self.chart)
            if color.isValid():
                return color
        return None

    def emphasisOpacity(self, index=None):
        """hover 高亮透明度（``emphasis.itemStyle.opacity``）；未配置 None。"""
        raw = self.emphasisItemStyle(index).get("opacity")
        if raw is None:
            return None
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError, OverflowError):
            return None

    def blurOpacity(self):
        """非高亮项透明度（``blur.itemStyle.opacity``）；未配置 None。"""
        raw = self.blurItemStyle().get("opacity")
        if raw is None:
            return None
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError, OverflowError):
            return None

    def emphasisFocus(self) -> str:
        """``emphasis.focus``：``none`` / ``self`` / ``series``（其它值按 none）。"""
        mode = str(self.emphasisOption().get("focus") or "none").strip().lower()
        return mode if mode in ("none", "self", "series") else "none"

    def blurScope(self) -> str:
        """``blurScope``：``coordinateSystem`` / ``series`` / ``global``。"""
        raw = (
            self.emphasisOption().get("blurScope")
            or self.opt.get("blurScope")
            or "coordinateSystem"
        )
        scope = str(raw).strip()
        return (
            scope
            if scope in ("coordinateSystem", "series", "global")
            else "coordinateSystem"
        )

    def blursOtherItems(self) -> bool:
        """hover 是否淡化同系列其它项（ECharts 只在 ``focus='self'`` 时 blur）。
        ``none``（默认）与 ``series`` 都不淡化：默认淡化会让每次鼠标移动重画
        全部图元，也不是 ECharts 语义。
        """
        return self.emphasisFocus() == "self"

    def hoverState(
        self,
        hovered,
        index,
        color,
        alpha: float,
        border_color=None,
        border_width: float = 0.0,
    ):
        """统一下发 hover / emphasis / blur 后的 ``(color, alpha, border)``。"""
        color = self.resolveColor(color)
        if hovered is None or not isinstance(index, int):
            return color, alpha, border_color, border_width
        if index == hovered:
            emphasis = self.emphasisColor(index)
            if emphasis is not None:
                color = emphasis
            elif color.isValid():
                color = color.lighter(112)
            emp_opacity = self.emphasisOpacity(index)
            if emp_opacity is not None:
                alpha = emp_opacity
            style = self.emphasisItemStyle(index)
            raw_border = style.get("borderColor")
            if isinstance(raw_border, str) and raw_border:
                candidate = self.resolveColor(raw_border)
                if candidate.isValid():
                    border_color = candidate
            raw_width = style.get("borderWidth")
            if raw_width is not None:
                border_width = max(0.0, _to_float(raw_width, border_width))
        elif self.blursOtherItems():
            blur = self.blurOpacity()
            alpha *= blur if blur is not None else 0.4
        return color, alpha, border_color, border_width

    def selectedStyle(
        self,
        index,
        color,
        alpha: float,
        border_color=None,
        border_width: float = 0.0,
    ):
        """统一下发选中态；显式 ``select.itemStyle`` 优先。"""
        color = self.resolveColor(color)
        if not isinstance(index, int) or not self.chart.isSelected(self, index):
            return color, alpha, border_color, border_width
        style = self.selectItemStyle(index)
        select_color = self.selectColor(index)
        if select_color is not None:
            color = select_color
        raw_opacity = style.get("opacity")
        if raw_opacity is not None:
            try:
                alpha = max(0.0, min(1.0, float(raw_opacity)))
            except (TypeError, ValueError, OverflowError):
                pass
        raw_border = style.get("borderColor")
        if isinstance(raw_border, str) and raw_border:
            candidate = self.resolveColor(raw_border)
            if candidate.isValid():
                border_color = candidate
        raw_width = style.get("borderWidth")
        if raw_width is not None:
            border_width = max(0.0, _to_float(raw_width, border_width))
        return color, alpha, border_color, border_width

    def stateStyle(
        self,
        index,
        hovered,
        color,
        alpha: float,
        border_color=None,
        border_width: float = 0.0,
    ):
        """hover → selected 的完整状态链（选中色最后覆盖）。"""
        color, alpha, border_color, border_width = self.hoverState(
            hovered, index, color, alpha, border_color, border_width
        )
        return self.selectedStyle(index, color, alpha, border_color, border_width)

    def selectOption(self) -> dict:
        """系列级 ``select``（选中态样式）。"""
        opt = self.opt.get("select")
        return opt if isinstance(opt, dict) else {}

    def selectItemStyle(self, index=None) -> dict:
        """选中项样式：系列 ``select.itemStyle`` → 数据项 ``select.itemStyle``。"""
        style = dict(self.selectOption().get("itemStyle") or {})
        if isinstance(index, int):
            try:
                data = self.data()
                if 0 <= index < len(data) and isinstance(data[index], dict):
                    item_select = data[index].get("select")
                    if isinstance(item_select, dict) and isinstance(
                        item_select.get("itemStyle"), dict
                    ):
                        style.update(item_select["itemStyle"])
            except Exception:
                pass
        return style

    def selectColor(self, index=None):
        """选中项颜色（``select.itemStyle.color``）；未配置 None。"""
        raw = self.selectItemStyle(index).get("color")
        if isinstance(raw, str) and raw:
            color = resolve_color_option(raw, self.chart)
            if color.isValid():
                return color
        return None

    def labelOption(self) -> dict:
        """系列级 ``label``（非 dict 时返回空 dict）。"""
        label = self.opt.get("label")
        return label if isinstance(label, dict) else {}

    def labelShown(self) -> bool:
        """是否显示数据标签（``label.show``）。"""
        return bool(self.labelOption().get("show", self.labelVisibleByDefault))

    def labelTextStyle(self) -> dict:
        """数据点标签的字号 / 颜色 / 粗细（组件级优先，回退顶层 ``textStyle``）。"""
        return merged_text_style(self.chart, self.labelOption())

    def labelColor(self, default=None) -> QColor:
        """标签颜色（``label.color`` → 顶层 ``textStyle.color`` → ``default``）。

        ``default`` 缺省为次级文本色；层级系列（树图 / 桑基等）传自己的兜底色。
        """
        raw = self.labelTextStyle().get("color")
        if isinstance(raw, str) and raw:
            color = resolve_color_option(raw, self.chart)
            if color.isValid():
                return color
        if default is not None:
            resolved = resolve_color_option(default, self.chart)
            if resolved.isValid():
                return resolved
        return QColor(T("color.text.secondary", self.chart))

    def explicitLabelColor(self, index=None):
        """显式 ``label.color``（item → 系列 → 顶层 ``textStyle``）；未设置 None。"""
        if isinstance(index, int):
            try:
                data = self.data()
                if 0 <= index < len(data):
                    item = data[index]
                    label = item.get("label") if isinstance(item, dict) else None
                    if isinstance(label, dict):
                        raw = label.get("color")
                        if isinstance(raw, str) and raw:
                            color = resolve_color_option(raw, self.chart)
                            if color.isValid():
                                return color
            except Exception:
                pass
        raw = self.labelTextStyle().get("color")
        if isinstance(raw, str) and raw:
            color = resolve_color_option(raw, self.chart)
            if color.isValid():
                return color
        return None

    def contrastLabelColor(self, fill, index=None) -> QColor:
        """填充色上的标签：显式颜色优先；半透明填充跟随主题文字，
        实色填充按填充色选黑 / 白。"""
        explicit = self.explicitLabelColor(index)
        if explicit is not None:
            return explicit
        color = parse_color(fill)
        if color.isValid() and color.alpha() < 255:
            return self.labelColorFor(index)
        return text_on_fill(color, self.chart)

    def labelColorFor(self, index=None) -> QColor:
        """单个数据点的标签颜色（item ``label.color`` 优先）。"""
        explicit = self.explicitLabelColor(index)
        if explicit is not None:
            return explicit
        return self.labelColor()

    def labelFontSize(self) -> float:
        """标签字号（``label.fontSize`` → 顶层 ``textStyle.fontSize`` → font.xs）。"""
        try:
            return max(6.0, float(self.labelTextStyle().get("fontSize", T("font.xs"))))
        except (TypeError, ValueError, OverflowError):
            return float(T("font.xs"))

    def labelFontWeight(self):
        """标签字重（``label.fontWeight`` → 顶层 ``textStyle.fontWeight``）。"""
        return text_weight(self.labelTextStyle().get("fontWeight"))

    def labelFont(self) -> QFont:
        """标签字体（字号 / 字重 / 字族 / 斜体统一解析，绘制点一律用它）。"""
        style = self.labelTextStyle()
        try:
            size = max(6.0, float(style.get("fontSize", T("font.xs"))))
        except (TypeError, ValueError, OverflowError):
            size = float(T("font.xs"))
        return chartFont(
            size,
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    def labelLayoutOption(self) -> dict:
        """``labelLayout``（系列优先，回退顶层）。"""
        option = self.opt.get("labelLayout")
        if not isinstance(option, dict):
            chart_option = getattr(self.chart, "_option", None)
            option = (
                chart_option.get("labelLayout")
                if isinstance(chart_option, dict)
                else None
            )
        return dict(option) if isinstance(option, dict) else {}

    def labelHideOverlap(self) -> bool:
        return bool(self.labelLayoutOption().get("hideOverlap", False))

    def labelMoveOverlap(self):
        """``labelLayout.moveOverlap``：``True`` / ``"shiftY"`` / ``"shiftX"``。"""
        raw = self.labelLayoutOption().get("moveOverlap")
        if raw is True:
            return "shiftY"
        text = str(raw or "").strip().lower()
        return text if text in ("shifty", "shiftx") else None

    def labelVisualOption(self, index=None, extra=None) -> dict:
        """数据标签视觉 option：系列 → 数据项 → 调用方覆盖，并解析主题色。"""
        option = dict(self.labelOption())
        if isinstance(extra, dict):
            option.update(extra)
        if isinstance(index, int):
            try:
                data = self.data()
                if 0 <= index < len(data):
                    item = data[index]
                    label = item.get("label") if isinstance(item, dict) else None
                    if isinstance(label, dict):
                        option.update(label)
            except Exception:
                pass
        return self._resolve_label_colors(option)

    def _resolve_label_colors(self, option: dict) -> dict:
        out = dict(option)
        for key in ("color", "backgroundColor", "borderColor"):
            value = out.get(key)
            if isinstance(value, str) and value.strip():
                color = resolve_color_option(value, self.chart)
                if color.isValid():
                    out[key] = color
        rich = out.get("rich")
        if isinstance(rich, dict):
            resolved = {}
            for name, style in rich.items():
                if not isinstance(style, dict):
                    resolved[name] = style
                    continue
                local = dict(style)
                for key in ("color", "backgroundColor", "borderColor"):
                    value = local.get(key)
                    if isinstance(value, str) and value.strip():
                        color = resolve_color_option(value, self.chart)
                        if color.isValid():
                            local[key] = color
                resolved[name] = local
            out["rich"] = resolved
        return out

    def _label_font_for(self, option: dict) -> QFont:
        base = self.labelTextStyle()
        try:
            size = max(
                6.0, float(option.get("fontSize", base.get("fontSize", T("font.xs"))))
            )
        except (TypeError, ValueError, OverflowError):
            size = self.labelFontSize()
        weight = text_weight(option.get("fontWeight"))
        if weight is None:
            weight = self.labelFontWeight()
        return chartFont(
            size,
            weight,
            option.get("fontFamily") or base.get("fontFamily"),
            text_italic(option.get("fontStyle") or base.get("fontStyle")),
        )

    def labelOverlaps(self, rect: QRectF) -> bool:
        if not self.labelHideOverlap():
            return False
        return self.labelRectOverlaps(rect)

    def labelRectOverlaps(self, rect: QRectF) -> bool:
        return any(
            QRectF(old).intersects(rect)
            for _index, old, _text in self._label_rects
            if isinstance(old, QRectF)
        )

    def _shift_label_rect(self, rect: QRectF, probe: QRectF, mode: str):
        if mode not in ("shifty", "shiftx"):
            return None
        step = max(4.0, (probe.height() if mode == "shifty" else probe.width()) + 2.0)
        for index in range(1, 13):
            delta = index * step
            candidates = (
                (rect.translated(0, delta), rect.translated(0, -delta))
                if mode == "shifty"
                else (rect.translated(delta, 0), rect.translated(-delta, 0))
            )
            for candidate in candidates:
                moved = QRectF(
                    candidate.center().x() - probe.width() / 2.0,
                    candidate.center().y() - probe.height() / 2.0,
                    probe.width(),
                    probe.height(),
                )
                if not self.labelRectOverlaps(moved):
                    return candidate
        return None

    def paintLabelIn(
        self,
        p: QPainter,
        rect: QRectF,
        text,
        *,
        index=None,
        align=None,
        angle: float = 0.0,
        color=None,
        label_option: dict = None,
        draw: bool = True,
    ) -> QRectF:
        """在 ``rect`` 内画数据标签（富文本 / 背景 / 边框 / 内边距）。"""
        option = self.labelVisualOption(index, label_option)
        font = self._label_font_for(option)
        if not draw or not (self.labelHideOverlap() or self.labelMoveOverlap()):
            return paint_label(
                p,
                rect,
                text,
                font=font,
                color=color,
                option=option,
                align=align,
                angle=angle,
                draw=draw,
            )
        probe = paint_label(
            p,
            rect,
            text,
            font=font,
            color=color,
            option=option,
            align=align,
            angle=angle,
            draw=False,
        )
        if self.labelRectOverlaps(probe):
            moved = self._shift_label_rect(rect, probe, self.labelMoveOverlap())
            if moved is not None:
                rect = moved
                probe = paint_label(
                    p,
                    rect,
                    text,
                    font=font,
                    color=color,
                    option=option,
                    align=align,
                    angle=angle,
                    draw=False,
                )
            elif self.labelHideOverlap():
                return QRectF()
        return paint_label(
            p,
            rect,
            text,
            font=font,
            color=color,
            option=option,
            align=align,
            angle=angle,
            draw=draw,
        )

    def paintLabelAt(
        self,
        p: QPainter,
        anchor: QPointF,
        text,
        fm=None,
        angle: float = 0.0,
        *,
        index=None,
        color=None,
        label_option: dict = None,
        draw: bool = True,
    ) -> QRectF:
        """在基线锚点 ``anchor`` 画数据标签（旋转 / 富文本 / 背景）。"""
        option = self.labelVisualOption(index, label_option)
        font = self._label_font_for(option)
        metrics = QFontMetricsF(font)
        size = label_text_size(text, font, option)
        rect = QRectF(
            anchor.x(),
            anchor.y() - metrics.ascent(),
            max(size.width(), 1.0),
            max(size.height(), metrics.height()),
        )
        return self.paintLabelIn(
            p,
            rect,
            text,
            index=index,
            align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            angle=angle,
            color=color,
            label_option=option,
            draw=draw,
        )

    def _apply_label_formatter(self, formatter, params: dict, fallback: str) -> str:
        """统一执行 ``label.formatter``（callable / 模板字符串）。"""
        if callable(formatter):
            try:
                text = formatter(params)
                return str(text) if text is not None else fallback
            except Exception:
                return fallback
        if isinstance(formatter, str):
            text = formatLabelTemplate(formatter, params)
            if text is not None:
                return text
        return fallback

    def labelText(self, index, value, name=None) -> str:
        """按 ``label.formatter`` 生成标签文本（缺省显示数值）。
        优先级：系列 ``labelTexts`` 覆盖（双击编辑写入）→ 数据项 ``label.text``
        / ``label.formatter`` → 系列 ``label.formatter``。
        """
        # 1) 双击编辑写入的按点覆盖
        overrides = self._source_opt.get("labelTexts")
        if isinstance(overrides, dict):
            key = str(index)
            if key in overrides:
                return str(overrides[key])
        params = {
            "a": self.name,
            "b": name if name is not None else self.name,
            "c": value,
            "value": value,
            "name": name if name is not None else self.name,
            "series": self.name,
            "dataIndex": index,
        }
        # 2) 数据项级 label（ECharts 兼容）
        item = None
        try:
            data = self.data()
            idx = int(index)
            if 0 <= idx < len(data):
                item = data[idx]
        except (TypeError, ValueError, OverflowError):
            item = None
        item_label = item.get("label") if isinstance(item, dict) else None
        params["data"] = item
        if isinstance(item_label, dict):
            if "text" in item_label:
                return str(item_label.get("text") or "")
            if item_label.get("formatter") is not None:
                return self._apply_label_formatter(
                    item_label.get("formatter"), params, formatValue(value)
                )
        # 3) 系列级 formatter
        return self._apply_label_formatter(
            self.labelOption().get("formatter"), params, formatValue(value)
        )

    def hierarchyLabelText(
        self,
        index,
        name,
        value=None,
        item=None,
        dimension_index=None,
        fallback=None,
    ) -> str:
        """层级 / 关系节点标签文本：``labelTexts`` 覆盖 → 节点 ``label`` → 系列 formatter。"""
        overrides = self._source_opt.get("labelTexts")
        if isinstance(overrides, dict):
            if dimension_index is not None:
                composite = f"{index}:{dimension_index}"
                if composite in overrides:
                    return str(overrides[composite])
            key = str(index)
            if key in overrides:
                return str(overrides[key])
        params = {
            "a": self.name,
            "b": name,
            "c": value,
            "name": name,
            "value": value,
            "series": self.name,
            "dataIndex": index,
            "data": item,
        }
        if dimension_index is not None:
            params["dimensionIndex"] = dimension_index
        node_label = item.get("label") if isinstance(item, dict) else None
        if isinstance(node_label, dict):
            if "text" in node_label:
                return str(node_label.get("text") or "")
            if node_label.get("formatter") is not None:
                return self._apply_label_formatter(
                    node_label.get("formatter"), params, name
                )
        return self._apply_label_formatter(
            self.labelOption().get("formatter"),
            params,
            name if fallback is None else fallback,
        )

    def setLabelText(self, index, text) -> bool:
        """覆盖某个数据点的标签文本（写入 ``series.labelTexts[str(index)]``）。

        空字符串 = 删除覆盖；不改 data 形状，因此不破坏大数组的 LOD 快路径。
        """
        try:
            idx = int(index)
        except (TypeError, ValueError, OverflowError):
            return False
        data = self.data()
        if not (0 <= idx < len(data)):
            return False
        text = str(text)
        overrides = self._source_opt.get("labelTexts")
        if not isinstance(overrides, dict):
            overrides = {}
            self._source_opt["labelTexts"] = overrides
            self.opt["labelTexts"] = overrides
        if text == "":
            overrides.pop(str(idx), None)
        else:
            overrides[str(idx)] = text
        return True

    def labelHitTest(self, pos: QPointF):
        """数据点标签命中：返回 ``(dataIndex, rect, text)``，未命中 None。
        命中框由各渲染器在 ``paint`` 时写入 ``_label_rects``；
        ``label.editable: false`` 可关闭单个系列的编辑。
        """
        if not self.labelShown():
            return None
        if self.labelOption().get("editable", True) is False:
            return None
        for index, rect, text in reversed(self._label_rects):
            if rect.adjusted(-2, -2, 2, 2).contains(pos):
                return index, QRectF(rect), text
        return None

    def valueAtIndex(self, index: int):
        """按**全量**数据下标返回 {"name","value","series","color"} 或 None。

        与 ``hitTest`` 的 ``dataIndex`` 同一域；axis tooltip 的窗口内局部下标
        在调用前由 core 加 ``windowOffset()``。无专用几何的系列用数据项兜底。
        """
        data = self.data()
        if not isinstance(index, int) or not 0 <= index < len(data):
            return None
        item = data[index]
        if isinstance(item, dict):
            value = item.get("value")
            name = str(item.get("name") or index)
        else:
            value = item
            name = str(index)
        return {
            "name": name,
            "value": value,
            "color": self.dataColor(index),
            "series": self.name,
            "dataIndex": index,
        }

    def nearestIndexAt(self, x):
        """按 x 值找最近的数据下标（value / time 轴的 axis tooltip 用）。

        默认 ``None``（该系列不支持按 x 反查）；category 轴不走这里。
        """
        return None

    def _sampling_params(self):
        """``sampling`` option 解析（折线 / 散点等大系列共用）。
        ``sampling`` 可为 False / 算法名（``minmax`` / ``m4`` / ``lttb`` /
        ``minmaxLTTB``）/ dict（``algorithm`` / ``threshold`` / ``pointsPerPixel``）；
        """
        sopt = self.opt.get("sampling", True)
        enabled = bool(sopt)
        threshold = _to_float(self.opt.get("samplingThreshold"), 2000.0)
        if _to_float(self.opt.get("largeThreshold"), None) is not None and bool(
            self.opt.get("large")
        ):
            threshold = _to_float(self.opt.get("largeThreshold"), threshold)
        ppb = 2.0
        algo = "minmax"
        if isinstance(sopt, str):
            name = sopt.strip().lower()
            if name in ("false", "none", "off"):
                enabled = False
            elif name:
                algo = name
        elif isinstance(sopt, dict):
            threshold = _to_float(sopt.get("threshold"), threshold)
            ppb = _to_float(sopt.get("pointsPerPixel"), ppb)
            algo = str(sopt.get("algorithm") or algo)
        return enabled, max(2.0, threshold), max(0.5, ppb), algo
