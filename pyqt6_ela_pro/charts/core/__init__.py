"""``charts.core`` 包门面：再导出 + 注册（拆分自同名模块）。"""

from __future__ import annotations

from ._shared import (
    COMPONENT_REGISTRY,
    GRID_SERIES_TYPES,
    SERIES_REGISTRY,
    _ANIM_EASINGS,
    _CHART_GROUPS,
    _HOVERABLE_COMPONENTS,
    _anchor_px,
    _easing_from_name,
    _elapsed_ms,
    _group_members,
    _needs_grid_coord,
    _now,
    _opt_float,
    _sort_value,
    connectCharts,
    defaultPalette,
    disconnectCharts,
    formatLabelTemplate,
    parseDataPoint,
    registerComponent,
    registerSeries,
)
from .renderer import (
    SeriesRenderer,
)
from .animation import (
    ChartAnimation,
)
from .title import (
    Title,
)
from .legend import (
    Legend,
)
from .tooltip import (
    Tooltip,
    _default_tooltip_title,
)
from .annotation import (
    _AnnotationEditor,
)
from .simple_line import (
    SimpleLineSeriesRenderer,
)
from .widget import (
    ElaChartWidget,
)

from ..axes import Coord, formatValue, niceTicks

__all__ = [
    "COMPONENT_REGISTRY",
    "ChartAnimation",
    "Coord",
    "ElaChartWidget",
    "GRID_SERIES_TYPES",
    "Legend",
    "SERIES_REGISTRY",
    "SeriesRenderer",
    "SimpleLineSeriesRenderer",
    "Title",
    "Tooltip",
    "_ANIM_EASINGS",
    "_AnnotationEditor",
    "_CHART_GROUPS",
    "_HOVERABLE_COMPONENTS",
    "_anchor_px",
    "_default_tooltip_title",
    "_easing_from_name",
    "_elapsed_ms",
    "_group_members",
    "_needs_grid_coord",
    "_now",
    "_opt_float",
    "_sort_value",
    "connectCharts",
    "defaultPalette",
    "disconnectCharts",
    "formatLabelTemplate",
    "formatValue",
    "niceTicks",
    "parseDataPoint",
    "registerComponent",
    "registerSeries",
]
