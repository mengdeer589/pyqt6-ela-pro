"""
蓝图（节点图）组件包。

类 UE5 Blueprint / ComfyUI 的节点图编辑器，**纯 UI 与交互**，不含业务
执行逻辑。扩展性第一：节点类型、引脚类型、菜单、节点体内容全部可
注册 / 覆写。

快速上手::

    from pyqt6_ela_pro.blueprint import (
        ElaBlueprintCanvas, ElaBlueprintGraph, pin, register_node_type)

    register_node_type(
        "encoder", "编码器", "模型",
        inputs=pin("batch", "批次", "tensor"),
        outputs=pin("hidden", "Hidden", "tensor"),
        accent="warning",
    )
    register_node_type(
        "head", "输出头", "模型",
        inputs=pin("hidden", "Hidden", "tensor"),
        outputs=pin("logits", "Logits", "tensor"),
    )

    canvas = ElaBlueprintCanvas(ElaBlueprintGraph())
    encoder = canvas.create_node("encoder", (40, 80))
    head = canvas.create_node("head", (240, 80))
    encoder.connect(head, "hidden", "hidden")   # 非法连接抛 ValueError（原因可读）

    ex = canvas.execution()
    ex.start(encoder)                            # 节点对象 / id 都接受
    ex.finish(encoder, 42)
    canvas.show()

移植自 InstructionX_UIKit.blueprint（原库为 PyQt6，类名 Ela* 前缀；
主题令牌经 blueprint._tokens 适配 eTheme；原库无 LICENSE，保留出处）。
"""

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
