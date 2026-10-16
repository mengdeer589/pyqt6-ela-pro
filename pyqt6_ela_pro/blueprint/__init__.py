"""
蓝图（节点图）组件包。

类 UE5 Blueprint / ComfyUI 的节点图编辑器，**纯 UI 与交互**，不含业务
执行逻辑。扩展性第一：节点类型、引脚类型、菜单、节点体内容全部可
注册 / 覆写。

快速上手::

    from PyQt6.QtCore import QPointF
    from pyqt6_ela_pro.blueprint import (
        ElaBlueprintGraph, ElaBlueprintCanvas, register_node_type)

    register_node_type(
        "resize", "Resize", "处理",
        inputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        description="调整图像尺寸",
    )
    graph = ElaBlueprintGraph()
    canvas = ElaBlueprintCanvas(graph)
    canvas.add_node_at("start", QPointF(40, 120))
    canvas.show()

移植自 InstructionX_UIKit.blueprint（原库为 PyQt6，类名 Ela* 前缀；
主题令牌经 blueprint._tokens 适配 eTheme；原库无 LICENSE，保留出处）。
"""

from .canvas import ElaBlueprintCanvas
from .edge_widget import ElaEdgeWidget, ElaTempWire, bezier_path
from .execution import ElaExecutionController
from .menu import ElaNodeContextMenu, ElaNodeCreationMenu
from .model import (
    ElaBlueprintGraph,
    ElaBlueprintNode,
    ElaEdge,
    ElaPin,
    ElaPinDirectionType,
    types_compatible,
)
from .node_widget import ElaNodeWidget, ElaPinHandle, format_elapsed
from .registry import (
    PIN_COLORS,
    ElaNodeRegistry,
    ElaNodeSpec,
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
    "PIN_COLORS",
    "register_pin_type",
    "pin_color",
    # widgets
    "ElaNodeWidget",
    "ElaPinHandle",
    "format_elapsed",
    "ElaEdgeWidget",
    "ElaTempWire",
    "bezier_path",
    "ElaBlueprintCanvas",
    # menus
    "ElaNodeCreationMenu",
    "ElaNodeContextMenu",
    # execution
    "ElaExecutionController",
    # viewport
    "gl_available",
]
