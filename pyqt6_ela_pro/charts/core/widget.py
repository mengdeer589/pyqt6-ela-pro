"""ElaChartWidget 主控件（生命周期 / option / 查询 / 绘制编排）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import (
    QPointF,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtWidgets import QWidget

from ..._internal import connect_theme_signal, disconnect_theme
from .._utils import warn_key, warn_once
from ..exporter import ChartExporter
from ..interaction import ChartInteraction
from ..axes import (
    GridCoord,
)
from ._shared import (
    COMPONENT_REGISTRY,
    _opt_float,
    parseDataPoint,
)
from .animation import ChartAnimation
from .chart_annotation import _ChartAnnotationMixin
from .chart_events import _ChartEventsMixin
from .chart_option import _ChartOptionMixin
from .chart_paint import _ChartPaintMixin
from .chart_query import _ChartQueryMixin
from .legend import Legend
from .title import Title
from .tooltip import Tooltip


class ElaChartWidget(
    _ChartOptionMixin,
    _ChartPaintMixin,
    _ChartEventsMixin,
    _ChartAnnotationMixin,
    _ChartQueryMixin,
    QWidget,
):
    """类 ECharts 图表控件（Ela 主题感知，纯 QPainter 自绘）。

    ``setOption`` 默认按 ECharts 语义合并；``resize`` / ``dispatchAction`` /
    ``on``&``off`` 等实例 API 与 ECharts 对齐。布局带缓存，动画期每帧重排。
    """

    #: 图例切换系列显隐：(系列名, 是否可见)
    legendToggled = pyqtSignal(str, bool)
    #: dataZoom 窗口变化：(start, end)，0-100 百分比
    dataZoomChanged = pyqtSignal(float, float)
    #: timeline 帧切换：帧下标
    timelineChanged = pyqtSignal(int)
    #: 数据项点击（ECharts click params）：见 ``_make_item_params``
    itemClicked = pyqtSignal(dict)
    #: toolbox 动作触发：动作名（saveAsImage / restore / dataZoom）
    toolboxTriggered = pyqtSignal(str)
    #: brush 选区变化：选中数据点列表（空列表 = 清除选区）
    brushChanged = pyqtSignal(list)
    #: 双击标注标签：宿主可自行弹出编辑框（内置编辑器开启时也会发）
    annotationEditRequested = pyqtSignal(dict)
    #: 标注标签提交：{seriesName, componentType, dataIndex, text}
    annotationEdited = pyqtSignal(dict)
    #: 动画播放完毕（ECharts ``finished`` 事件）
    finished = pyqtSignal()

    #: ECharts 事件名 → 内部转发（``on``/``off`` 用）
    _ECHARTS_EVENTS = (
        "click",
        "mouseover",
        "mouseout",
        "mousemove",
        "globalout",
        "selectchanged",
        "legendselectchanged",
        "datazoom",
        "timelinechanged",
        "brushselected",
        "restore",
        "highlight",
        "downplay",
        "finished",
    )

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 150)
        self._option = {}
        #: 全图字体族（``setFontFamily``；**单个族名**，空 = 系统默认）
        self._font_family = ""
        self._series = []  # [SeriesRenderer]
        self._coords = []  # [Coord]
        self._components = []  # [组件实例]
        self._series_state = {}  # name -> bool（legend selected 状态）
        #: 调色板缓存 (key, list[QColor])，key = (主题模式, 自定义色板 id, 长度)
        self._palette_cache = None
        #: itemStyle 均匀性缓存 (key, {} | None)，见 ``uniformItemStyle``
        self._uniform_style_cache = None
        #: 系列层位图缓存 (key, QImage)，见 ``_paint_series_cached``
        self._series_pixmap_cache = None
        self._series_pixmap_key = None
        #: 交互开关：总开关 + 逐功能开关（缺失 = 启用）
        self._interactive = True
        self._feature_flags: dict = {}
        #: 当前悬停命中 (renderer, hit)：emphasis 高亮用
        self._hover = None
        #: axis 触发时的多系列命中 [(renderer, hit), ...]（每条系列各一个点）
        self._axis_hover = []
        self._opt_version = 0  # option 版本号（setOption 递增）
        self._layout_key = None  # 布局缓存键（脏标记）
        #: 渲染器内部几何版本号（``invalidateLayout()`` 递增）；进系列层缓存键，
        #: 否则下钻 / roam 后位图会被原样贴回。
        self._geometry_epoch = 0
        #: 生命周期 / ECharts 事件
        self._disposed = False
        self._event_handlers: dict = {}
        #: 图表组（``connectCharts``）：组名 / 组事件槽 / 重入守卫
        self._group = None
        self._group_slot = None
        self._syncing = False
        #: 导出（导出逻辑与画布状态分离，见 ``exporter.py``）
        self._exporter = ChartExporter(self)
        #: 鼠标交互（事件行为与画布状态分离，见 ``interaction.py``）
        self._interaction = ChartInteraction(self)
        #: 双击复位视图（Plotly ``doubleClick: 'reset'`` 语义，默认开）
        self._double_click_reset = True
        #: 图例悬停高亮的系列名（None = 无）
        self._legend_hover = None
        #: 本次按下的 (位置, 是否被拖拽组件吞掉)——松开时判「点击 vs 拖拽」
        self._press_ctx = None
        #: 标注标签行内编辑器与当前编辑目标（双击 markPoint/markLine 标签）
        self._annotation_editor = None
        self._annotation_target = None
        self._annotation_editable = True
        #: 直角坐标图默认内置缩放平移（无 dataZoom 时自动挂 inside 组件）
        self._wheel_zoom_enabled = bool(self.WHEEL_ZOOM_DEFAULT)
        #: 默认左键拖拽模式（Plotly ``dragmode`` 语义）
        self._drag_mode = str(self.DRAG_MODE_DEFAULT)
        #: 宿主是否显式调用过 ``setDragMode``（显式配置 brush 时默认走 select）
        self._drag_mode_explicit = False
        #: lazyUpdate 延迟重建标记
        self._lazy_pending = False
        #: 宿主经 ``addComponent`` 注入的组件（跨 ``setOption`` 存活，见该方法）
        self._host_components: list = []
        #: 选中态：系列名 → 数据下标集合（ECharts ``selectedMode``）
        self._selection: dict = {}
        #: 图例隐藏的数据项（饼 / 漏斗按数据项开关）：name → visible
        self._item_state: dict = {}
        #: 选中态版本（进系列层缓存键）
        self._selection_epoch = 0
        #: 上次 dataZoom option 段的快照：用于判断用户是否显式改了窗口
        #: （没改就保留当前缩放，ECharts 语义；见 ``_rebuild``）
        self._zoom_opt_snapshot = None
        #: timeline 基线快照（``options`` 帧切换用；core 内部维护）
        self._timeline_base = None
        #: loading 遮罩（showLoading / hideLoading）
        self._loading = False
        self._loading_opts: dict = {}
        self._spinner_angle = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        # 多实例组件：数组逐项建实例；``title`` / ``legend`` 仍指向第一个
        self.titles = [Title(self)]
        self.title = self.titles[0]
        self.legends = [Legend(self)]
        self.legend = self.legends[0]
        self.tooltip = Tooltip(self)
        self.anim = ChartAnimation(self.update, self)
        self.anim.finished.connect(self._on_animation_finished)
        self._chartEvent.connect(self._dispatch_chart_event)
        # 信号 → ECharts 事件转发
        self.legendToggled.connect(self._forward_legend_toggled)
        self.dataZoomChanged.connect(self._forward_data_zoom)
        self.timelineChanged.connect(self._forward_timeline_changed)
        self.itemClicked.connect(self._forward_click)
        self.brushChanged.connect(self._forward_brush_selected)
        self.toolboxTriggered.connect(self._forward_toolbox)
        # 主题连接走 _internal 的统一机制（destroyed 兜底 + 槽内 is_deleted 自愈），
        # 别手写 eTheme.themeModeChanged.connect。
        connect_theme_signal(self, self._on_theme_changed)

    def _disconnect_theme(self, *_args) -> None:
        """销毁路径显式断开主题单例信号连接。"""
        disconnect_theme(self)

    def deleteLater(self) -> None:
        self._disconnect_theme()
        super().deleteLater()

    # ---------------------------------------------------------------- API
    #: ECharts 事件名 → Qt 信号（``on``/``off`` 的转发源）
    _chartEvent = pyqtSignal(str, dict)

    # -- dispatchAction 分派实现 ------------------------------------------
    def _dispatch_legend(self, action: str, payload: dict) -> bool:
        names = payload.get("name")
        if isinstance(names, (list, tuple, set)):
            names = [str(n) for n in names]
        elif names is not None:
            names = [str(names)]
        else:
            # 无 name = 全部图例条目（饼 / 漏斗按数据项，其余按系列名）
            names = []
            for r in self._series:
                getter = getattr(r, "legendItems", None)
                if callable(getter):
                    names.extend([name for name, _ in getter()])
                else:
                    names.append(r.name)
        if not names:
            return False
        for name in names:
            is_series = any(r.name == name for r in self._series)
            if action == "legendSelect":
                if is_series:
                    self._setSeriesVisible(name, True)
                else:
                    self._setDataItemVisible(name, True)
            elif action == "legendUnSelect":
                if is_series:
                    self._setSeriesVisible(name, False)
                else:
                    self._setDataItemVisible(name, False)
            elif action == "legendAllSelect":
                if is_series:
                    self._setSeriesVisible(name, True)
                else:
                    self._setDataItemVisible(name, True)
            elif action == "legendInverseSelect":
                if is_series:
                    self._setSeriesVisible(name, not self._seriesVisible(name))
                else:
                    self._setDataItemVisible(
                        name, not bool(self._item_state.get(name, True))
                    )
            else:  # legendToggleSelect
                self._legendSelectToggle(name)
        if action != "legendToggleSelect":
            # 每个名字都要发：批量动作下宿主才能逐项同步。
            # ``legendToggleSelect`` 走 ``_legendSelectToggle``，它自己发。
            for name in names:
                visible = (
                    self._seriesVisible(name)
                    if any(r.name == name for r in self._series)
                    else bool(self._item_state.get(name, True))
                )
                self.legendToggled.emit(name, visible)
        self.update()
        return True

    def _component(self, optionKey: str):
        """按 optionKey 取首个组件实例。"""
        for comp in self._components:
            if str(getattr(comp, "optionKey", "")) == optionKey:
                return comp
        return None

    def _dispatch_data_zoom(self, payload: dict) -> bool:
        comp = self._component("dataZoom")
        if comp is None:
            return False
        apply_action = getattr(comp, "applyAction", None)
        if not callable(apply_action):
            return False
        if not apply_action(payload):
            return False
        # 不再 emit ``dataZoomChanged``：``applyAction`` 末尾已发，补发会让
        # dispatchAction 路径重复发 ECharts ``datazoom`` 事件。
        return True

    def _dispatch_show_tip(self, payload: dict) -> bool:
        renderer = self._renderer_for(payload)
        if renderer is None:
            return False
        data_index = payload.get("dataIndex")
        hit = None
        if data_index is not None:
            try:
                idx = int(data_index)
            except (TypeError, ValueError, OverflowError):
                idx = None
            if idx is not None:
                value = renderer.valueAtIndex(idx)
                if value is not None:
                    hit = dict(value)
                    hit.setdefault("dataIndex", idx)
        x, y = _opt_float(payload.get("x"), None), _opt_float(payload.get("y"), None)
        if x is not None and y is not None:
            pos = QPointF(x, y)
        elif hit is not None and hit.get("pos") is not None:
            pos = QPointF(hit["pos"])
        else:
            pos = QPointF(self.width() / 2, self.height() / 2)
            coord = self.coordFor(renderer.opt)
            if coord is not None and hit is not None:
                try:
                    px, py = parseDataPoint((renderer.data() or [None])[0], 0)
                    pt = coord.mapPoint(px, py)
                    pos = QPointF(pt)
                except Exception:
                    pass
        if hit is None:
            hit = {"name": renderer.name, "value": None}
        self._hover = (renderer, hit)
        self.tooltip.showAt(
            pos, self.tooltip.buildLines(hit, renderer.color(), renderer.name)
        )
        self.update()
        return True

    def _dispatch_emphasis(self, action: str, payload: dict) -> bool:
        renderer = self._renderer_for(payload)
        if renderer is None:
            return False
        if action == "downplay":
            if self._hover is not None and self._hover[0] is renderer:
                self._hover = None
            params = {
                "type": "downplay",
                "seriesIndex": self._series.index(renderer),
                "seriesName": renderer.name,
                "dataIndex": payload.get("dataIndex"),
                "name": payload.get("name"),
            }
            self._emit_event("downplay", params)
            self.update()
            return True
        data_index = payload.get("dataIndex")
        name = payload.get("name")
        hit = {"name": str(name or ""), "dataIndex": data_index}
        if data_index is not None:
            try:
                idx = int(data_index)
                hit["dataIndex"] = idx
                value = renderer.valueAtIndex(idx)
                if value:
                    hit["value"] = value.get("value")
                    hit.setdefault("name", str(value.get("name") or ""))
            except (TypeError, ValueError, OverflowError):
                pass
        self._hover = (renderer, hit)
        params = {
            "type": "highlight",
            "seriesIndex": self._series.index(renderer),
            "seriesName": renderer.name,
            "dataIndex": hit.get("dataIndex"),
            "name": hit.get("name"),
        }
        self._emit_event("highlight", params)
        self.update()
        return True

    def _restore_state(self) -> None:
        """恢复初始状态（ECharts restore）：dataZoom / 图例选择 / 下钻 / roam。"""
        for comp in self._components:
            restore = getattr(comp, "restore", None)
            if callable(restore):
                try:
                    restore()
                except Exception:
                    pass
        for name in list(self._series_state.keys()):
            self._setSeriesVisible(name, True)
        for r in self._series:
            for method in ("resetDrill", "resetPositions", "resetRoam"):
                fn = getattr(r, method, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
        self.invalidateLayout()
        self.update()
        self._emit_restore_event()

    def _renderer_for(self, payload: dict):
        """按 seriesIndex / seriesName / seriesId 找可见渲染器（缺省首个）。"""
        series_id = payload.get("seriesId")
        if series_id is not None:
            for r in self._series:
                if r.id == str(series_id):
                    return r
        name = payload.get("seriesName")
        if (
            name is None
            and payload.get("name") is not None
            and payload.get("seriesIndex") is None
            and payload.get("dataIndex") is None
        ):
            name = payload.get("name")
        if name is not None:
            for r in self._series:
                if r.name == str(name):
                    return r
        index = payload.get("seriesIndex")
        if index is not None:
            try:
                idx = int(index)
            except (TypeError, ValueError, OverflowError):
                idx = -1
            if 0 <= idx < len(self._series):
                return self._series[idx]
            return None
        return self._series[0] if self._series else None

    def _series_index(self, name) -> int:
        for i, r in enumerate(self._series):
            if r.name == str(name):
                return i
        return -1

    # -- 导出 / 图片 -------------------------------------------------------
    def getDataURL(self, opts: dict = None) -> str:
        """导出为 data URL（ECharts ``getDataURL``）。

        opts：``type``（``"png"`` / ``"jpeg"``）/ ``pixelRatio`` /
        ``backgroundColor``；``excludeComponents`` 暂不支持（忽略）。
        """
        self._ensure_alive()
        opts = dict(opts or {})
        return self._exporter.data_url(opts)

    def saveImage(self, path: str = None, *, format: str = None) -> str:
        """保存当前图表（``path=None`` 弹保存对话框；``svg`` 走矢量导出）。

        :returns: 实际保存路径，未保存返回 ``""``。
        """
        self._ensure_alive()
        target = path
        return self._exporter.save_image(target, format=format)

    def dispose(self) -> None:
        """销毁实例（ECharts ``dispose``；停定时器 / 断主题 / deleteLater）。"""
        if self._disposed:
            return
        self._disposed = True
        try:
            self._spinner_timer.stop()
        except Exception:
            pass
        try:
            self.anim.stop()
        except Exception:
            pass
        self.tooltip.hide()
        self._hover = None
        self._event_handlers.clear()
        self._leaveGroupHandlers()
        self._group = None
        if self._annotation_editor is not None:
            self._hide_annotation_editor()
            self._annotation_editor.deleteLater()
            self._annotation_editor = None
        # 组件一并解挂：事件过滤器 / 定时器会随 parent 销毁，但组件可能持有
        # chart 之外的东西（宿主句柄、注册的全局回调）。
        self._dispose_components(include_host=True)
        self._host_components.clear()
        self._components = []
        self._disconnect_theme()
        self.deleteLater()

    def isDisposed(self) -> bool:
        """实例是否已 dispose。"""
        return bool(self._disposed)

    def _ensure_alive(self) -> None:
        """公开 API 的 dispose 守卫（对齐 ECharts：已销毁实例再调用直接报错）。"""
        if self._disposed:
            raise RuntimeError("ElaChartWidget 已 dispose，不能再调用图表 API")

    def _option_ref(self) -> dict:
        """当前 option 的内部引用（无拷贝；仅包内部热路径使用）。"""
        return self._option

    # -- 图例 / 系列显隐（内部；对外走 dispatchAction / legend.selected） --
    def _setSeriesVisible(self, name, visible: bool) -> None:
        name = str(name)
        self._series_state[name] = bool(visible)
        # 回写 option：_rebuild 会重放 legend.selected，不同步会在下次 setOption
        # 把显隐状态还原；dict / 数组两种写法都要写。
        legend_opt = self._option.get("legend")
        legend_entries = (
            legend_opt
            if isinstance(legend_opt, list)
            else ([legend_opt] if isinstance(legend_opt, dict) else [])
        )
        for entry in legend_entries:
            if isinstance(entry, dict) and isinstance(entry.get("selected"), dict):
                entry["selected"][name] = bool(visible)
        for r in self._series:
            if r.name == name:
                r.visible = bool(visible)
                hook = getattr(r, "_on_visible_changed", None)
                if callable(hook):
                    try:
                        hook()
                    except Exception:
                        pass
        self._layout_key = None
        self.update()

    def _seriesVisible(self, name) -> bool:
        return bool(self._series_state.get(str(name), True))

    def _legendSelectToggle(self, name: str) -> None:
        """图例点击：切换单个系列（selectedMode=single 时互斥）。

        饼 / 漏斗的图例条目是**数据项名**，不走系列显隐，而是切换数据项。
        """
        name = str(name)
        if not any(r.name == name for r in self._series):
            self._toggleDataItem(name)
            return
        new_visible = not self._seriesVisible(name)
        if new_visible and self.legend.selectedMode() == "single":
            for r in self._series:
                if r.name != name and self._seriesVisible(r.name):
                    self._setSeriesVisible(r.name, False)
        self._setSeriesVisible(name, new_visible)
        self.legendToggled.emit(name, new_visible)
        self.update()

    def _toggleDataItem(self, name: str) -> None:
        """切换饼 / 漏斗的数据项显隐（图例按数据项名开关）。"""
        name = str(name)
        self._setDataItemVisible(name, not bool(self._item_state.get(name, True)))

    def _setDataItemVisible(self, name: str, visible: bool) -> None:
        """设置饼 / 漏斗数据项显隐（不切换）。"""
        name = str(name)
        self._item_state[name] = bool(visible)
        self._write_legend_selected(name, visible)
        hidden = {str(item) for item, shown in self._item_state.items() if not shown}
        for renderer in self._series:
            setter = getattr(renderer, "setHiddenItems", None)
            if not callable(setter):
                continue
            try:
                setter(hidden)
            except Exception:
                pass
        self._layout_key = None
        self.update()
        self.legendToggled.emit(name, bool(visible))

    def _write_legend_selected(self, name: str, visible: bool) -> None:
        """把单项显隐写回 ``legend.selected``（dict / 数组两种写法）。"""
        legend_opt = self._option.get("legend")
        entries = (
            legend_opt
            if isinstance(legend_opt, list)
            else ([legend_opt] if isinstance(legend_opt, dict) else [])
        )
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("selected"), dict):
                entry["selected"][name] = bool(visible)

    # ------------------------------------------------------------ 交互开关
    #: 可开关的交互功能（与组件 optionKey 对齐；tooltip / legend 由核心实现）
    INTERACTION_FEATURES = (
        "tooltip",
        "legend",
        "dataZoom",
        "brush",
        "timeline",
        "toolbox",
    )

    def setInteractive(self, enabled: bool) -> None:
        """交互总开关：关闭后所有鼠标交互失效，绘制与数据不变。

        打开 = 全开：置 ``True`` 会清空逐功能开关（``setInteractionEnabled`` 的覆盖）。

        :param enabled: ``False`` 变为静态图（动画与程序化 API 不受影响）
        """
        self._interactive = bool(enabled)
        if not self._interactive:
            self.tooltip.hide()
            self._hover = None
        else:
            self._feature_flags.clear()
        # 总开关也影响工具条按钮的启用态（子控件不会跟 chart 重绘走）
        self._notify_interaction_changed()
        self.invalidateLayout()
        self.update()

    def interactiveEnabled(self) -> bool:
        """交互总开关是否开启。"""
        return self._interactive

    def setInteractionEnabled(self, feature: str, enabled: bool) -> None:
        """逐功能开关（与总开关取与）；``feature`` 取 ``"tooltip"`` / ``"legend"``
        / ``"dataZoom"`` / ``"brush"`` / ``"timeline"`` / ``"toolbox"``。
        """
        key = str(feature)
        if key not in self.INTERACTION_FEATURES:
            raise ValueError(
                f"未知交互功能：{feature!r}"
                f"（可选：{', '.join(self.INTERACTION_FEATURES)}）"
            )
        self._feature_flags[key] = bool(enabled)
        if not enabled and key == "tooltip":
            self.tooltip.hide()
            self._hover = None
        # 工具条按钮是真实子控件（启用态在 ``layout()`` 里同步）：
        # 这里既要让它当场变灰 / 恢复，也要让下一次布局重算位置与状态
        self._notify_interaction_changed()
        self.invalidateLayout()
        self.update()

    def _notify_interaction_changed(self) -> None:
        """交互开关变化 → 让组件立刻刷新「子控件级」的状态（工具条按钮启用态）。"""
        for comp in self._components:
            hook = getattr(comp, "onInteractionChanged", None)
            if not callable(hook):
                continue
            try:
                hook()
            except Exception:
                continue

    def hitRadius(self) -> float:
        """命中半径（px）：``tooltip.hitRadius`` / Plotly ``hoverdistance``，默认 10。"""
        tooltip_opt = self._option.get("tooltip")
        raw = None
        if isinstance(tooltip_opt, dict):
            raw = tooltip_opt.get("hitRadius", tooltip_opt.get("hoverdistance"))
        radius = 10.0
        if raw is not None:
            try:
                radius = float(raw)
            except (TypeError, ValueError, OverflowError):
                radius = 10.0
        if not math.isfinite(radius) or radius <= 0:
            return 10.0
        return min(200.0, radius)

    #: 拖拽模式（对齐 Plotly ``dragmode``）：平移 / 框选缩放 / 框选 / 套索
    DRAG_MODES = ("pan", "zoom", "select", "lasso")
    #: 默认拖拽模式：左键框选缩放（Plotly ``dragmode: 'zoom'``）。
    DRAG_MODE_DEFAULT = "zoom"

    #: 直角坐标图是否默认内置滚轮缩放（``setWheelZoomEnabled`` 可改）
    WHEEL_ZOOM_DEFAULT = True

    def setWheelZoomEnabled(self, enabled: bool) -> None:
        """内置滚轮缩放开关（默认开，直角坐标图开箱即用）。

        option 里配了 ``dataZoom`` 就完全听用户的（本开关不删用户组件）；没配时
        自动挂 ``inside`` 组件（滚轮缩放 + 拖动平移），拖拽模式可把它让给刷选。
        """
        enabled = bool(enabled)
        self._wheel_zoom_enabled = enabled
        if not enabled:
            auto = self._auto_wheel_zoom()
            if auto is not None:
                self._drop_component(auto)
            return
        self._ensure_wheel_zoom()
        self._apply_drag_mode()

    def wheelZoomEnabled(self) -> bool:
        """内置滚轮缩放开关状态。"""
        return bool(self._wheel_zoom_enabled)

    def _auto_wheel_zoom(self):
        """取出自动创建的滚轮缩放组件（宿主自己配的不算）。"""
        for comp in self._host_components:
            if getattr(comp, "_wheel_zoom_auto", False):
                return comp
        return None

    def _drop_component(self, comp) -> None:
        """把一个组件从 chart 上摘干净（解挂事件过滤器 + 移出两个列表）。"""
        dispose = getattr(comp, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass
        for bucket in (self._components, self._host_components):
            while comp in bucket:
                bucket.remove(comp)
        self.invalidateLayout()
        self.update()

    def _ensure_zoom_component(self):
        """确保存在一个 dataZoom 组件（框选缩放用；滚轮开关关掉时也能工作）。"""
        comp = self._component("dataZoom")
        if comp is not None:
            return comp
        if not any(isinstance(coord, GridCoord) for coord in self._coords):
            return None
        cls = COMPONENT_REGISTRY.get("dataZoom")
        if cls is None:  # pragma: no cover
            return None
        try:
            comp = cls(
                self,
                [
                    {
                        "type": "inside",
                        "zoomOnMouseWheel": False,
                        "moveOnMouseMove": False,
                    }
                ],
            )
        except Exception as exc:
            warn_once(
                warn_key("brush-zoom-ctor", type(exc).__name__),
                f"框选缩放组件构造失败: {exc!r}",
            )
            return None
        comp._brush_zoom_auto = True
        comp._y_zoom_enabled = True
        comp._y_axis_indices = None
        self._host_components.append(comp)
        self._components.append(comp)
        return comp

    def _ensure_wheel_zoom(self) -> None:
        """无 ``dataZoom`` 的直角坐标图自动挂 ``inside`` 组件（滚轮缩放 + 拖拽平移）。"""
        if not self._wheel_zoom_enabled or self._auto_wheel_zoom() is not None:
            return
        if self._component("dataZoom") is not None:
            return
        if not any(isinstance(coord, GridCoord) for coord in self._coords):
            return
        cls = COMPONENT_REGISTRY.get("dataZoom")
        if cls is None:  # pragma: no cover - 注册表恒有 dataZoom
            return
        try:
            comp = cls(
                self,
                [
                    {
                        "type": "inside",
                        "zoomOnMouseWheel": True,
                        "moveOnMouseMove": self.dragMode() == "pan",
                    }
                ],
            )
        except Exception as exc:
            warn_once(
                warn_key("wheel-zoom-ctor", type(exc).__name__),
                f"默认滚轮缩放组件构造失败: {exc!r}",
            )
            return
        comp._wheel_zoom_auto = True
        comp._y_zoom_enabled = True
        comp._y_axis_indices = None
        # 走 ``_host_components``：跨 setOption 存活，且不会被 _rebuild 重复创建
        self._host_components.append(comp)
        self._components.append(comp)

    def setDragMode(self, mode: str) -> None:
        """切换拖拽模式（Plotly ``dragmode`` 语义）。

        ``pan`` 平移 / ``zoom`` 框选即缩放（默认）/ ``select`` 矩形框选 /
        ``lasso`` 套索选择。dataZoom 平移与 brush 拖拽互斥，按模式开关。
        """
        key = str(mode or "").strip().lower()
        if key not in self.DRAG_MODES:
            raise ValueError(
                f"未知拖拽模式：{mode!r}（可选：{', '.join(self.DRAG_MODES)}）"
            )
        self._drag_mode = key
        self._drag_mode_explicit = True
        self._apply_drag_mode()
        self.update()

    def _apply_drag_mode(self) -> None:
        """把当前 ``_drag_mode`` 应用到 dataZoom / brush（重建后也要重放）。"""
        key = str(getattr(self, "_drag_mode", self.DRAG_MODE_DEFAULT) or "zoom")
        data_zoom = self._component("dataZoom")
        if data_zoom is not None:
            # 缩放 / 选择模式：拖拽交给 brush（否则两者抢同一个拖拽手势）
            data_zoom.moveOnMouseMove = key == "pan"
            if hasattr(data_zoom, "zoomOnMouseWheel"):
                data_zoom.zoomOnMouseWheel = bool(self._wheel_zoom_enabled)
        if not any(isinstance(coord, GridCoord) for coord in self._coords):
            return
        brush = self._ensure_brush_component()
        if brush is not None:
            brush.enabled = key in ("zoom", "select", "lasso")
            brush.opt["type"] = "lasso" if key == "lasso" else "rect"

    def _ensure_brush_component(self):
        """取 brush 组件；option 没配就按需建一个（挂进 ``_host_components``
        跨 setOption 存活）。"""
        brush = self._component("brush")
        if brush is not None:
            return brush
        cls = COMPONENT_REGISTRY.get("brush")
        if cls is None:
            return None
        try:
            brush = cls(self, {"type": "rect"})
        except Exception as exc:
            warn_once("brush-ctor", f"brush 组件构造失败: {exc!r}")
            return None
        self._host_components.append(brush)
        self._components.append(brush)
        return brush

    def dragMode(self) -> str:
        """当前拖拽模式（默认 ``"zoom"``：左键框选缩放）。"""
        return str(getattr(self, "_drag_mode", "") or self.DRAG_MODE_DEFAULT)

    def brushComponent(self):
        """brush 组件句柄（宿主可读 ``selected_items`` / 接 ``selected`` 信号）。"""
        return self._component("brush")

    # ------------------------------------------------------------ 标注编辑

    def setDoubleClickReset(self, enabled: bool) -> None:
        """双击是否复位视图（默认 **开**，对齐 Plotly ``doubleClick: 'reset'``）。"""
        self._double_click_reset = bool(enabled)

    def doubleClickReset(self) -> bool:
        """双击复位是否开启。"""
        return bool(self._double_click_reset)

    def resetView(self) -> None:
        """视图还原到初始状态（dataZoom 窗口 / 漫游缩放 / 悬停态）。

        只影响视图，不动数据与图例显隐（图例用 ``dispatchAction(legendAllSelect)``）。
        """
        comp = self._component("dataZoom")
        if comp is not None and hasattr(comp, "reset_window"):
            comp.reset_window()
        for coord in list(self.coords):
            hook = getattr(coord, "resetView", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    continue
        for renderer in self._series:
            hook = getattr(renderer, "resetView", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    continue
        self.tooltip.hide()
        self._hover = None
        self._legend_hover = None
        self.invalidateLayout()
        self.update()

    def isInteractionEnabled(self, feature: str) -> bool:
        """功能是否生效（总开关关闭时恒为 ``False``；未设置默认启用）。"""
        if not self._interactive:
            return False
        return bool(self._feature_flags.get(str(feature), True))

    def _interactive_components(self) -> list:
        """过滤后的组件列表（交互被关闭的组件不接收鼠标 / 滚轮事件）。"""
        result = []
        for comp in self._components:
            key = str(getattr(comp, "optionKey", ""))
            if key and not self.isInteractionEnabled(key):
                continue
            result.append(comp)
        return result

    def addComponent(self, comp) -> None:
        """挂接宿主自定义组件，跨 ``setOption`` 存活（``_rebuild`` 不会重建 / dispose 它）。

        要跟着 option 重建的组件请用 :func:`registerComponent`。组件按鸭子类型
        实现 ``optionKey`` / ``layout`` / ``paint`` / ``hitTest`` 等钩子。
        """
        if comp is None:
            return
        if any(comp is existing for existing in self._host_components):
            return
        self._host_components.append(comp)
        if not any(comp is c for c in self._components):
            self._components.append(comp)
        self.invalidateLayout()
        self.update()

    def removeComponent(self, comp) -> bool:
        """摘掉宿主注入的组件（并在它实现了 ``dispose`` 时调用它）。"""
        found = None
        for existing in self._host_components:
            if existing is comp:
                found = existing
                break
        if found is None:
            return False
        self._host_components.remove(found)
        self._components = [c for c in self._components if c is not found]
        dispose = getattr(found, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass
        self.invalidateLayout()
        self.update()
        return True

    def _dispose_components(self, include_host: bool = False) -> None:
        """丢弃旧组件前调用其 ``dispose()``（没实现就跳过）。

        ``include_host=False``（``_rebuild`` 路径）跳过宿主经 ``addComponent``
        注入的组件；``include_host=True``（``dispose`` 路径）全收。
        """
        hosts = set() if include_host else {id(c) for c in self._host_components}
        for comp in self._components:
            if id(comp) in hosts:
                continue
            dispose = getattr(comp, "dispose", None)
            if not callable(dispose):
                continue
            try:
                dispose()
            except Exception:
                pass

    # ------------------------------------------------------------- 内部构建

    def _onBrushSelected(self, items) -> None:
        """brush 组件选区变化 → ``brushChanged`` 信号。"""
        self.brushChanged.emit(list(items or []))

    # ------------------------------------------------------------- Qt 事件
    def mousePressEvent(self, event) -> None:
        self._interaction.mouse_press(event)

    def mouseMoveEvent(self, event) -> None:
        self._interaction.mouse_move(event)

    def mouseReleaseEvent(self, event) -> None:
        self._interaction.mouse_release(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self._interaction.mouse_double_click(event)

    def wheelEvent(self, event) -> None:
        self._interaction.wheel(event)

    def leaveEvent(self, event) -> None:
        self._interaction.leave(event)

    def _on_theme_changed(self, _mode) -> None:
        # 配色经 T() 实时取；主题可能影响字体度量，保守失效布局缓存。
        if self._annotation_editor is not None and self._annotation_editor.isVisible():
            self._hide_annotation_editor()
        self._layout_key = None
        self.update()

    # -- 鼠标：legend 点击 / tooltip 跟随 / 组件钩子 ------------------------
    def _interactive_renderers(self) -> list:
        """可见系列（渲染器可覆写 onMousePress/Move/Release/onWheel 获得交互）。"""
        return [r for r in self._series if r.visible]

    def _call_hook(self, owner, hook_name: str, *args) -> bool:
        """调组件 / 渲染器的鼠标钩子，异常隔离并去重上报。

        钩子跑在 Qt 事件回调链上，未捕获异常会穿过 C++ 边界导致进程
        0xC0000409 终止（零 traceback），所以所有钩子都必须走这里。
        """
        hook = getattr(owner, hook_name, None)
        if not callable(hook):
            return False
        label = getattr(owner, "name", "") or owner.__class__.__name__
        try:
            return bool(hook(*args))
        except Exception as exc:
            warn_once(
                warn_key(
                    f"{hook_name}",
                    owner.__class__.__name__,
                    label,
                    type(exc).__name__,
                ),
                f"{owner.__class__.__name__}.{hook_name} 异常（{label}）: {exc!r}",
            )
            return False

    def _dispatch_hook(self, hook_name: str, *args) -> bool:
        """按「组件优先、系列其次」的顺序分发钩子，任一消费则返回 True。"""
        for comp in self._interactive_components():
            if self._call_hook(comp, hook_name, *args):
                return True
        if not self._interactive:
            return False
        for renderer in self._interactive_renderers():
            if self._call_hook(renderer, hook_name, *args):
                return True
        return False
