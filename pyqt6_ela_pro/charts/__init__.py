"""pyqt6_ela_pro.charts：类 ECharts 原生图表引擎（纯 QPainter + Ela 主题）。"""

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
from ._tokens import chartToken
from ._theme import ECHARTS_PALETTE as _ECHARTS_PALETTE
from ._theme import (
    chartThemeSpec,
    chartThemes,
    defaultChartTheme,
    registerChartTheme,
    setDefaultChartTheme,
    unregisterChartTheme,
)
from .colormaps import colormapColors, colormapNames, registerColormap
from .geo import mapNames, projectPoint, registerMap, unregisterMap
from .geo_coord import GeoCoord
from .gantt_view import ElaGanttView
from .models import *  # noqa: F403
from .models import __all__ as _models_all
from .stream import DataRing
from .data import (
    ElaNumericBuffer,
    isBufferLike,
    numpyAvailable,
    toBuffer,
    unwrapData,
)

#: 公开色板是副本：宿主 append 不会改全局 fallback。
ECHARTS_PALETTE = list(_ECHARTS_PALETTE)

__all__ = [
    "ElaChartWidget",
    "ElaGanttView",
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
    "chartThemes",
    "defaultChartTheme",
    "setDefaultChartTheme",
    "registerChartTheme",
    "unregisterChartTheme",
    "chartThemeSpec",
    "registerColormap",
    "colormapNames",
    "colormapColors",
    "registerMap",
    "unregisterMap",
    "mapNames",
    "projectPoint",
    "GeoCoord",
    "SimpleLineSeriesRenderer",
    "ElaNumericBuffer",
    "DataRing",
    "toBuffer",
    "isBufferLike",
    "unwrapData",
    "numpyAvailable",
] + list(_models_all)

#: 系列 / 组件模块导入即完成注册
from . import series_cartesian as _series_cartesian  # noqa: E402,F401
from . import series_hierarchy as _series_hierarchy  # noqa: E402,F401
from . import series_map as _series_map  # noqa: E402,F401
from . import components as _components  # noqa: E402,F401
from . import interact as _interact  # noqa: E402,F401

del _series_cartesian, _series_hierarchy, _series_map, _components, _interact
