"""``charts.components`` 包门面：再导出 + 注册（拆分自同名模块）。"""

from __future__ import annotations

from .mark import (
    MarkAreaComponent,
    MarkLineComponent,
    MarkPointComponent,
    _SeriesMarkBase,
    _TYPE_LABELS,
)
from .graphic import (
    GraphicComponent,
    lerp_color,
)

from ..core import registerComponent

registerComponent("markPoint", MarkPointComponent)
registerComponent("markLine", MarkLineComponent)
registerComponent("markArea", MarkAreaComponent)
registerComponent("graphic", GraphicComponent)

__all__ = [
    "DEMO_MAP",
    "GraphicComponent",
    "MapSeriesRenderer",
    "MarkAreaComponent",
    "MarkLineComponent",
    "MarkPointComponent",
    "_SeriesMarkBase",
    "_TYPE_LABELS",
    "lerp_color",
]
