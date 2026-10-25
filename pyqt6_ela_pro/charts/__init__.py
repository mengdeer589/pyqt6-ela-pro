"""
pyqt6_ela_pro.charts：类 ECharts 原生图表引擎（纯 QPainter + Ela 主题）。

包级导出：``ElaChartWidget`` / ``registerSeries`` / ``registerComponent`` /
注册表 / 协议基类 / 坐标系 / 内置组件 / ``chartToken``（自定义扩展取主题色）。

实例 API 与 ECharts 对齐（``camelCase``）：

- 配置：``setOption(option, notMerge=False, lazyUpdate=False)``（默认合并，
  ``series``/``dataZoom``/``graphic`` 按 id → name → 下标逐项合并）/
  ``getOption``（拷贝查询）/ ``appendData({seriesIndex|seriesName, data})`` /
  ``clear``
- 控制：``resize`` / ``dispatchAction``（legend* / dataZoom / select /
  unselect / toggleSelect / restore / showTip / hideTip / highlight / downplay /
  timeline*）/ ``setInteractive`` / ``setInteractionEnabled`` / ``showLoading`` /
  ``hideLoading`` / ``toggleMagicType`` / ``setGroup`` + ``connectCharts`` /
  ``dispose`` / ``isDisposed``
- 查询与命中：``seriesRenderers`` / ``coords`` / ``components`` / ``palette`` /
  ``colorForSeries`` / ``primaryCoord`` / ``coordFor`` / ``hitItem`` /
  ``hoverInfo`` / ``convertToPixel`` / ``convertFromPixel`` / ``containPixel`` /
  ``getDataURL`` / ``getWidth`` / ``getHeight`` / ``getDevicePixelRatio``
- 事件：ECharts 事件名经 ``on(eventName, handler)`` / ``off(...)``
  （``click`` / ``mouseover`` / ``mouseout`` / ``mousemove`` / ``globalout`` /
  ``selectchanged`` / ``legendselectchanged`` / ``datazoom`` /
  ``timelinechanged`` / ``brushselected`` / ``restore`` / ``highlight`` /
  ``downplay`` / ``finished``），handler 收 ECharts params dict；同时保留 Qt 信号
  （``itemClicked`` / ``legendToggled`` / ``dataZoomChanged`` /
  ``timelineChanged`` / ``toolboxTriggered`` / ``brushChanged`` / ``finished``）
- 扩展：``registerSeries`` / ``registerComponent``（同名覆盖会告警）、
  ``SeriesRenderer`` / ``Coord`` 协议、``chartToken``

主题：全部颜色经 ``charts._tokens.chartToken`` 映射到 ``eTheme`` /
``ElaThemeType`` 语义令牌，深浅色切换实时换肤，观感与 Ela 组件库一致。

说明：本引擎移植自 InstructionX_UIKit.charts（ECharts 风格 setOption API，
原库为 PyQt6；无 LICENSE，保留出处）。当前内置 21 个系列
（cartesian / hierarchy / 关系 / 地图等）与 9 个组件
（mark* / graphic / dataZoom / brush / visualMap / timeline / toolbox）。

**大数组（百万级）折线**：``setOption`` 会把 ``series[].data`` 的大数值数组
按引用摄入（``ElaNumericBuffer``，见 ``charts.data``），不再逐元素深拷贝。
两点契约：① 可直接传 numpy 数组（按引用持有，零拷贝）；② 传入后**不得原地
修改**该数组（缓冲区只读，改数据请重新 ``setOption``）。``getOption()`` 仍
返回普通 list，调用方观察不到缓冲区。
"""

from .core import (
    COMPONENT_REGISTRY,
    SERIES_REGISTRY,
    ChartAnimation,
    ElaChartWidget,
    Legend,
    SeriesRenderer,
    SimpleLineSeriesRenderer,
    Title,
    Tooltip,
    connectCharts,
    defaultPalette,
    disconnectCharts,
    formatValue,
    niceTicks,
    parseDataPoint,
    registerComponent,
    registerSeries,
)
from .axes import (
    AxisModel,
    CalendarCoord,
    Coord,
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
    chartFont,
)
from ._tokens import chartToken, ECHARTS_PALETTE
from .data import (
    ElaNumericBuffer,
    isBufferLike,
    numpyAvailable,
    toBuffer,
    unwrapData,
)

__all__ = [
    "ElaChartWidget",
    "ChartAnimation",
    "SeriesRenderer",
    "Coord",
    "Title",
    "Legend",
    "Tooltip",
    "AxisModel",
    "GridCoord",
    "PolarCoord",
    "SingleAxisCoord",
    "CalendarCoord",
    "SERIES_REGISTRY",
    "COMPONENT_REGISTRY",
    "registerSeries",
    "registerComponent",
    "connectCharts",
    "disconnectCharts",
    "defaultPalette",
    "niceTicks",
    "formatValue",
    "parseDataPoint",
    "chartFont",
    "chartToken",
    "ECHARTS_PALETTE",
    "SimpleLineSeriesRenderer",
    "ElaNumericBuffer",
    "toBuffer",
    "isBufferLike",
    "unwrapData",
    "numpyAvailable",
]

#: 系列 / 组件模块导入即完成注册（全部系列 + mark*/graphic/map +
#: dataZoom/brush/visualMap/timeline/toolbox）
from . import series_cartesian as _series_cartesian  # noqa: E402,F401
from . import series_hierarchy as _series_hierarchy  # noqa: E402,F401
from . import series_map as _series_map  # noqa: E402,F401
from . import components as _components  # noqa: E402,F401
from . import interact as _interact  # noqa: E402,F401

del _series_cartesian, _series_hierarchy, _series_map, _components, _interact
