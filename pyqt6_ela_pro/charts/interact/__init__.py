"""``charts.interact`` 包门面：再导出 + 注册（拆分自同名模块）。"""

from __future__ import annotations

from ._shared import (
    _axis_index_list,
)
from .datazoom import (
    DataZoomComponent,
)
from .brush import (
    BrushComponent,
)
from .visualmap import (
    VisualMapComponent,
)
from .timeline import (
    ChartTimeline,
)
from .toolbox import (
    ToolboxComponent,
)

from ..core import registerComponent

registerComponent("dataZoom", DataZoomComponent)
registerComponent("brush", BrushComponent)
registerComponent("visualMap", VisualMapComponent)
registerComponent("timeline", ChartTimeline)
registerComponent("toolbox", ToolboxComponent)

__all__ = [
    "BrushComponent",
    "ChartTimeline",
    "DataZoomComponent",
    "ToolboxComponent",
    "VisualMapComponent",
    "_axis_index_list",
]
