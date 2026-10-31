"""系列渲染器基类。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations

from typing import TYPE_CHECKING


import math

from PyQt6.QtCore import (
    QPointF,
    QRectF,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
)

from .. import data as _cdata
from .._tokens import (
    T,
)
from .._utils import merged_text_style, parse_color, text_italic, text_weight
from .._utils import to_float as _to_float
from ..axes import (
    chartFont,
    formatValue,
)
from ._shared import formatLabelTemplate, parseDataPoint

if TYPE_CHECKING:
    from .widget import ElaChartWidget


class SeriesRenderer:
    """系列渲染器协议基类。

    子类实现 ``layout(rect)`` / ``paint(p, anim_t)`` / ``hitTest(pos)``。
    坐标映射经 ``self.chart.coordFor(self.opt)`` 取得 Coord 后
    ``coord.mapPoint(x, y)``。

    可选扩展：
    - ``valueAtIndex(index)`` → dict（{"name","value","series","color"}），
      供 tooltip axis 触发取数；
    - ``self.prev_data``：上次 option 前的旧 data 列表（core 自动注入），
      用于旧→新插值动画。
    """

    def __init__(self, chart: "ElaChartWidget", opt: dict):
        self.chart = chart
        #: 原始 series option（**不是副本**；标签编辑等需要写回宿主 option）
        self._source_opt = opt if isinstance(opt, dict) else {}
        self.opt = dict(opt or {})
        self.name = str(self.opt.get("name") or "")
        #: ECharts ``series.id``（setOption 合并时的身份匹配键）
        self.id = str(self.opt.get("id") or "")
        #: 系列显隐（legend 点击切换；初始状态由 widget 按 legend.selected 注入）
        self.visible = True
        #: **最近一次绘制所用的动画进度**（core 在 paint / 命中分发前写入）。
        #: ``hitTest`` 靠它判断「现在是否处于动画中」，见该方法 docstring。
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

    # -- 协议 ------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        """计算几何（坐标映射经 coord）。"""

    def paint(self, p: QPainter, anim_t: float) -> None:
        """绘制。anim_t ∈ [0,1]，入场 / 更新动画进度。"""
        raise NotImplementedError

    def hitTest(self, pos: QPointF):
        """命中检测 → ``{"name","value","series",...}`` 或 None。

        **默认实现在动画期一律返回 None**：``anim_t`` 是绘制期变量，而子类的
        几何来自 ``layout()``（终态），用终态几何命中会指到「动画结束后才会到
        的位置」—— 用户看到的是高亮 / tooltip 落在错误的图元上。想支持动画期
        命中的子类在自己的 ``hitTest`` 里用 ``self._anim_t`` 复算几何即可。
        完整规则与已实现清单见 AGENTS.md「charts」。
        """
        if self._anim_t < 1.0:
            return None
        return None

    # -- 辅助 ------------------------------------------------------------
    @property
    def silent(self) -> bool:
        """ECharts ``series.silent``：True 时不响应鼠标命中（tooltip / click）。"""
        return bool(self.opt.get("silent", False))

    def animProgress(self, t: float) -> float:
        """系列动画进度：``series.animation=false`` 时直接呈现终态。"""
        if self.opt.get("animation", True) is False:
            return 1.0
        return t

    def requestSeriesRepaint(self) -> None:
        """请求下一帧重绘**系列层**（持续动效每帧推进外观时用）。

        只 ``chart.update()`` 不够：系列层位图缓存键里没有任何逐帧变化量，
        相位推进后仍然贴回同一张位图 —— 表现为「只有鼠标移动（hover 进键）
        时动效才动」。几何没变，所以也**不能**用 ``invalidateLayout()``
        （会连带全量重排，百万点图表上每 40ms 一次）。
        """
        chart = self.chart
        chart.invalidateSeriesLayer()
        chart.update()

    def data(self) -> list:
        """系列原始 data 列表（None 容灾）。

        接受两种承载：``list``（默认）与 ``ElaNumericBuffer``（大数组零拷贝
        摄入的产物，见 ``charts.data``）。**不能只认 list** ——``setOption``
        会把大数值数组包成缓冲区，只认 list 会让整条曲线静默消失。

        返回值对外语义与 list 一致（``Sequence``：可 ``len`` / 下标 / 迭代 /
        与 list 比较），既有的 40 余处只读调用点无需改动。内部热路径
        （``layout`` / 采样 / 范围统计）请用 :meth:`dataView`，它不做任何
        list 化。

        **裸 ndarray 会就地包成 ``ElaNumericBuffer`` 再返回**，因为 ndarray 的
        ``__eq__`` 不返回 bool：``if renderer.data() == other:`` 会在它上面抛
        ``ValueError: The truth value of an array ... is ambiguous``，而这行
        常出现在 Qt 回调里 = 0xC0000409。``ElaNumericBuffer`` 的 ``__eq__``
        走 list 比较，契约与返回值宣称的一致。短数组（< ``_BUFFER_MIN_LEN``）
        不包装，所以裸 ndarray 确实会到这里。
        """
        d = self.opt.get("data")
        if isinstance(d, list):
            return d
        if isinstance(d, _cdata.ElaNumericBuffer):
            return d
        if _cdata.isBufferLike(d):
            # 包一次并**写回 opt**：`_data_ref` 等调用方要求同一 data 对象
            # 反复拿到的是同一实例（采样缓存键含 id(data)，每次新建包装件会让
            # 键每帧变化 → 降采样缓存永不命中，布局耗时 22 倍）。
            wrapped = _cdata.ElaNumericBuffer(d)
            self.opt["data"] = wrapped
            return wrapped
        return []

    def dataView(self):
        """系列数据的**只读视图**（内部热路径专用，不做任何拷贝）。

        与 :meth:`data` 判据相同但语义更明确：返回的就是 ``opt["data]``
        本身，不做任何 list 化。内部热路径（``layout`` / 采样 / 范围统计）
        统一走这里。
        """
        d = self.opt.get("data")
        if isinstance(d, list) or _cdata.isBufferLike(d):
            return d
        return []

    def valueStats(self) -> dict:
        """有限 y 值的统计（min / max / 下标 / sum / count），按数据身份缓存。

        markLine / markPoint 的 average / max / min 走这里 —— 原先它们用
        ``_SeriesMarkBase._points()`` 逐点物化整份数据，30 万点每次布局
        175ms（纯折线 0.87ms），而布局缓存键含 dataZoom 窗口，缩放每步都重付。
        """
        data = self.dataView()
        key = (id(data), len(data))
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
            color = parse_color(raw)
            if color.isValid():
                return color
        return self.chart.colorForSeries(self)

    def legendItems(self) -> list:
        """图例条目 ``[(name, QColor)]``（默认 = 系列名；饼 / 漏斗按数据项）。"""
        return [(self.name, self.color())]

    # -- itemStyle / label / emphasis（ECharts 通用键） --------------------
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

        **O(1) 判据是「容器类型」而非抽样** —— 紧凑数值容器必是纯数值序列，
        ``list`` 必须全量扫（带 dict 项的列表本就不是百万级场景）。原先的
        32 项探窗会静默漏掉 ``[1]*500 + [{"itemStyle": …}]``，见 AGENTS.md
        「charts」。
        """
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

    def uniformItemStyleResolved(self) -> dict:
        """一次性解析「全系列统一」的外观，供绘制循环**循环外**取用。

        返回 ``{"color": QColor|None, "opacity": float, "borderColor": ...,
        "borderWidth": float, "borderRadius": float|None}``。仅当
        ``uniformItemStyle()`` 判定为均匀时可用（否则返回 ``None``）。

        用途：bar / scatter 逐图元绘制时，若每根柱子都调
        ``itemColor`` / ``itemOpacity`` / ``itemBorder`` / ``_bar_radius``，
        素材多时就是每图元 4 次方法调用。绘制循环外解析一次，
        循环内只做数组取值即可。
        """
        if self.uniformItemStyle() is None:
            return None
        style = self.itemStyle()
        raw_color = style.get("color")
        color = None
        if isinstance(raw_color, str) and raw_color:
            c = parse_color(raw_color)
            if c.isValid():
                color = c
        raw_border = style.get("borderColor")
        border = None
        if isinstance(raw_border, str) and raw_border:
            c = parse_color(raw_border)
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

    def itemColor(self, index=None, default=None) -> QColor:
        """数据项颜色：项 ``itemStyle.color`` → 系列 ``itemStyle.color``
        → ``default`` → 全局调色板。"""
        raw = self._itemStyleFor(index).get("color") or self.itemStyle().get("color")
        if isinstance(raw, str) and raw:
            color = parse_color(raw)
            if color.isValid():
                return color
        if default is not None:
            return parse_color(default)
        return self.color()

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
            candidate = parse_color(raw)
            if candidate.isValid():
                color = candidate
        try:
            width = max(0.0, float(width))
        except (TypeError, ValueError, OverflowError):
            width = 0.0
        return color, width

    # -- visualMap 着色（map / heatmap / scatter 共用组件查找） -------------

    def visualMapComponent(self):
        """绑定到本系列的 ``visualMap`` 组件（显式绑定优先 → 通用件）；没有返回 None。

        必须按「系列身份」取，不能拿第一个 ``mapColor``：多个系列共用同一个
        visualMap 时，别的系列的分段色才不会被第一个抢走。
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

    # -- emphasis / blur 状态（ECharts 通用键） ---------------------------
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
            color = parse_color(raw)
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

        ``none``（默认）与 ``series`` 都不淡化：默认就淡化会让每次鼠标移动
        重画全部图元（密集散点纯属浪费），也不是 ECharts 语义。
        """
        return self.emphasisFocus() == "self"

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
            color = parse_color(raw)
            if color.isValid():
                return color
        return None

    def labelOption(self) -> dict:
        """系列级 ``label``（非 dict 时返回空 dict）。"""
        label = self.opt.get("label")
        return label if isinstance(label, dict) else {}

    def labelShown(self) -> bool:
        """是否显示数据标签（``label.show``）。"""
        return bool(self.labelOption().get("show", False))

    def labelTextStyle(self) -> dict:
        """数据点标签的字号 / 颜色 / 粗细（组件级优先，回退顶层 ``textStyle``）。"""
        return merged_text_style(self.chart, self.labelOption())

    def labelColor(self, default=None) -> QColor:
        """标签颜色（``label.color`` → 顶层 ``textStyle.color`` → ``default``）。

        ``default`` 缺省为次级文本色；层级系列（树图 / 桑基等）传自己的兜底色。
        """
        raw = self.labelTextStyle().get("color")
        if isinstance(raw, str) and raw:
            color = parse_color(raw)
            if color.isValid():
                return color
        if default is not None:
            return parse_color(default) if not isinstance(default, QColor) else default
        return QColor(T("color.text.secondary"))

    def labelColorFor(self, index=None) -> QColor:
        """单个数据点的标签颜色（item ``label.color`` 优先）。"""
        if isinstance(index, int):
            try:
                data = self.data()
                if 0 <= index < len(data):
                    item = data[index]
                    label = item.get("label") if isinstance(item, dict) else None
                    if isinstance(label, dict):
                        raw = label.get("color")
                        if isinstance(raw, str) and raw:
                            color = parse_color(raw)
                            if color.isValid():
                                return color
            except Exception:
                pass
        return self.labelColor()

    def labelFontSize(self) -> float:
        """标签字号（``label.fontSize`` → 顶层 ``textStyle.fontSize`` → font.xs）。"""
        try:
            return max(
                6.0, float(self.labelTextStyle().get("fontSize", T("font.xs")))
            )
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

        文本优先级：系列 ``labelTexts`` 覆盖（双击编辑写入）→ 数据项
        ``label.text``（字面量）/ ``label.formatter`` → 系列 ``label.formatter``。
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

    def setLabelText(self, index, text) -> bool:
        """覆盖某个数据点的标签文本（写入 ``series.labelTexts[str(index)]``）。

        空字符串 = 删除覆盖、恢复默认数值文案。不改 data 形状，因此不会破坏
        大数组的 numpy / LOD 快路径。
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

        命中框由各渲染器在 ``paint`` 时写入 ``_label_rects``（与画出来的
        标签完全一致）；``label.editable: false`` 可关闭单个系列的编辑。
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
        """tooltip axis 触发：返回 {"name","value","series","color"} 或 None。"""
        return None

    def nearestIndexAt(self, x):
        """按 x 值找最近的数据下标（value / time 轴的 axis tooltip 用）。

        默认 ``None``（该系列不支持按 x 反查，调用方跳过）。category 轴不走
        这里 —— 它的 ``invertX`` 本来就是类目下标。
        """
        return None

    def _sampling_params(self):
        """``sampling`` option 解析（折线 / 散点等大系列共用）。

        ECharts 语义：``sampling`` 可为 False / 字符串（``minmax`` / ``m4`` /
        ``lttb`` / ``minmaxLTTB``）/ dict
        {``algorithm``, ``threshold``, ``pointsPerPixel``}；返回
        ``(enabled, threshold, pointsPerPixel, algorithm)``。

        **这里只表达用户意图**（是否抽稀）——能不能抽由调用方的三层兜底决定
        （tsdownsample → numpy 按桶 min/max → 纯 Python 等距）。
        """
        sopt = self.opt.get("sampling", True)
        enabled = bool(sopt)
        threshold = 2000.0
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

    def _full_index(self, index):
        """tooltip 局部下标 → 全量数据下标（dataZoom category 窗口偏移换算）。"""
        if not isinstance(index, int):
            return index
        coord = self.chart.coordFor(self.opt)
        axis = getattr(coord, "x_axis", None)
        if axis is not None and getattr(axis, "type", "") == "category":
            return index + axis.windowOffset()
        return index
