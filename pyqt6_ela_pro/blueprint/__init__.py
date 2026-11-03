"""蓝图（节点图）组件包：纯 UI 与交互，不含业务执行逻辑。

节点类型 / 引脚 / 菜单均可注册扩展；用法见 ``docs/blueprint.md``。"""

from .canvas import ElaBlueprintCanvas
from .execution import ElaExecutionController
from .menu import ElaEdgeContextMenu, ElaNodeContextMenu, ElaNodeCreationMenu
from .model import (
    ElaBlueprintGraph,
    ElaBlueprintNode,
    ElaEdge,
    ElaPin,
    ElaPinDirectionType,
    types_compatible,
)
from .registry import (
    PIN_COLORS,
    ElaNodeRegistry,
    ElaNodeSpec,
    pin,
    pin_color,
    register_node_type,
    register_pin_type,
)
from .viewport import gl_available

__all__ = [
    # model
    "ElaPinDirectionType",
    "ElaPin",
    "ElaEdge",
    "ElaBlueprintNode",
    "ElaBlueprintGraph",
    "types_compatible",
    # registry
    "ElaNodeSpec",
    "ElaNodeRegistry",
    "register_node_type",
    "register_pin_type",
    "pin",
    "PIN_COLORS",
    "pin_color",
    # canvas
    "ElaBlueprintCanvas",
    # menus
    "ElaNodeCreationMenu",
    "ElaNodeContextMenu",
    "ElaEdgeContextMenu",
    # execution
    "ElaExecutionController",
    # viewport
    "gl_available",
]
