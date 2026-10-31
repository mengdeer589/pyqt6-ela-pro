"""直角坐标系列：导入本包即经 ``registerSeries`` 注册全部系列。"""

from __future__ import annotations

from ._shared import (
    _GAP_MIN_PIXELS,
    _GRID_EXTENT_CACHE,
    _GRID_EXTENT_CACHE_LIMIT,
    _SAMPLE_CACHE_MAX,
    _axis_label,
    _datum_list,
    _draw_symbol,
    _finite,
    _fix_value_axis,
    _grid_series_opts,
    _grid_value_extent,
    _grid_value_extent_uncached,
    _has_explicit_x,
    _label_placement,
    _lerp,
    _monotone_path,
    _numeric_xy,
    _ramp_color,
    _seq_len,
    _smooth_path,
    _win_span,
)
from .bar import (
    BarSeriesRenderer,
)
from .line import (
    LineSeriesRenderer,
)
from .scatter import (
    ScatterSeriesRenderer,
)
from .heatmap import (
    HeatmapSeriesRenderer,
)
from .pictorial import (
    PictorialBarSeriesRenderer,
)
from .effect_scatter import (
    EffectScatterSeriesRenderer,
)
from .candlestick import (
    CandlestickSeriesRenderer,
)
from .boxplot import (
    BoxplotSeriesRenderer,
)
from .parallel import (
    ParallelSeriesRenderer,
)
from .themeriver import (
    ThemeRiverSeriesRenderer,
)

from ..core import registerSeries

registerSeries("bar", BarSeriesRenderer)
registerSeries("pictorialBar", PictorialBarSeriesRenderer)
registerSeries("line", LineSeriesRenderer)
registerSeries("scatter", ScatterSeriesRenderer)
registerSeries("effectScatter", EffectScatterSeriesRenderer)
registerSeries("candlestick", CandlestickSeriesRenderer)
registerSeries("boxplot", BoxplotSeriesRenderer)
registerSeries("heatmap", HeatmapSeriesRenderer)
registerSeries("parallel", ParallelSeriesRenderer)
registerSeries("themeRiver", ThemeRiverSeriesRenderer)

__all__ = [
    "BarSeriesRenderer",
    "BoxplotSeriesRenderer",
    "CandlestickSeriesRenderer",
    "EffectScatterSeriesRenderer",
    "HeatmapSeriesRenderer",
    "LineSeriesRenderer",
    "ParallelSeriesRenderer",
    "PictorialBarSeriesRenderer",
    "ScatterSeriesRenderer",
    "ThemeRiverSeriesRenderer",
    "_GAP_MIN_PIXELS",
    "_GRID_EXTENT_CACHE",
    "_GRID_EXTENT_CACHE_LIMIT",
    "_SAMPLE_CACHE_MAX",
    "_axis_label",
    "_datum_list",
    "_draw_symbol",
    "_finite",
    "_fix_value_axis",
    "_grid_series_opts",
    "_grid_value_extent",
    "_grid_value_extent_uncached",
    "_has_explicit_x",
    "_label_placement",
    "_lerp",
    "_monotone_path",
    "_numeric_xy",
    "_ramp_color",
    "_seq_len",
    "_smooth_path",
    "_win_span",
]
