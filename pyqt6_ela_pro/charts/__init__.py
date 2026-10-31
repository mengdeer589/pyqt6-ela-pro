"""pyqt6_ela_pro.charts：类 ECharts 原生图表引擎（纯 QPainter + Ela 主题）。

包级导出 ``ElaChartWidget`` / ``registerSeries`` / ``registerComponent`` /
``chartToken`` 等；实例 API 与 ECharts 对齐（``camelCase``），详见 README 与
``docs/charts.md``。

``series[].data`` 的大数值数组按引用摄入（``ElaNumericBuffer``）：可直接传
numpy（零拷贝），但传入后不得原地修改；``getOption()`` 仍返回普通 list。
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

#: 系列 / 组件模块导入即完成注册
from . import series_cartesian as _series_cartesian  # noqa: E402,F401
from . import series_hierarchy as _series_hierarchy  # noqa: E402,F401
from . import series_map as _series_map  # noqa: E402,F401
from . import components as _components  # noqa: E402,F401
from . import interact as _interact  # noqa: E402,F401

del _series_cartesian, _series_hierarchy, _series_map, _components, _interact
