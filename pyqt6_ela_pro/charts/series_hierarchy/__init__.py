"""``charts.series_hierarchy`` 包门面：再导出 + 注册（拆分自同名模块）。"""

from __future__ import annotations

from ._shared import (
    _HNode,
    _assign_branch_colors,
    _build_hierarchy,
    _dist,
    _dist_to_polygon_edge,
    _label_font,
    _parse_named_values,
    _parse_pct,
    _series_palette_color,
    _squarify,
    _text_color,
)
from .pie import (
    PieSeriesRenderer,
)
from .radar import (
    RadarSeriesRenderer,
)
from .gauge import (
    GaugeSeriesRenderer,
)
from .funnel import (
    FunnelSeriesRenderer,
)
from .sunburst import (
    SunburstSeriesRenderer,
)
from .treemap import (
    TreemapSeriesRenderer,
)
from .tree import (
    TreeSeriesRenderer,
)
from .sankey import (
    SankeySeriesRenderer,
)
from .graph import (
    GraphSeriesRenderer,
)
from .lines import (
    LinesSeriesRenderer,
)

from ..core import registerSeries

registerSeries("pie", PieSeriesRenderer)
registerSeries("radar", RadarSeriesRenderer)
registerSeries("gauge", GaugeSeriesRenderer)
registerSeries("funnel", FunnelSeriesRenderer)
registerSeries("sunburst", SunburstSeriesRenderer)
registerSeries("treemap", TreemapSeriesRenderer)
registerSeries("tree", TreeSeriesRenderer)
registerSeries("sankey", SankeySeriesRenderer)
registerSeries("graph", GraphSeriesRenderer)
registerSeries("lines", LinesSeriesRenderer)

__all__ = [
    "FunnelSeriesRenderer",
    "GaugeSeriesRenderer",
    "GraphSeriesRenderer",
    "LinesSeriesRenderer",
    "PieSeriesRenderer",
    "RadarSeriesRenderer",
    "SankeySeriesRenderer",
    "SunburstSeriesRenderer",
    "TreeSeriesRenderer",
    "TreemapSeriesRenderer",
    "_HNode",
    "_assign_branch_colors",
    "_build_hierarchy",
    "_dist",
    "_dist_to_polygon_edge",
    "_label_font",
    "_parse_named_values",
    "_parse_pct",
    "_series_palette_color",
    "_squarify",
    "_text_color",
]
