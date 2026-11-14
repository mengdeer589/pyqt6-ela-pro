# 蓝图节点图（blueprint）

类 UE5 Blueprint / ComfyUI 的节点图编辑器。**纯 UI 与交互，不含业务执行逻辑**；
节点类型、引脚类型、菜单、节点体内容都可以注册 / 覆写。

## 快速上手

```python
from pyqt6_ela_pro.blueprint import (
    ElaBlueprintCanvas,
    ElaBlueprintGraph,
    pin,
    register_node_type,
)

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
encoder.connect(head, "hidden", "hidden")   # 非法连接抛 ValueError

ex = canvas.execution()
ex.start(encoder)          # 节点对象 / id 都接受
ex.finish(encoder, 42)
canvas.show()
```

## 组成

- `ElaBlueprintGraph` / `ElaBlueprintNode` / `ElaEdge` / `ElaPin`：纯数据模型，
  支持 `to_dict()` / `from_dict()` 序列化。
- `ElaNodeRegistry` / `register_node_type` / `register_pin_type`：节点与引脚类型注册表；
  `pin(...)` 是注册时的便捷构造器。
- `ElaBlueprintCanvas`：主控件，负责平移 / 缩放 / 选择 / 连线 / 编辑 / 序列化。
- `ElaNodeCreationMenu` / `ElaNodeContextMenu` / `ElaEdgeContextMenu`：创建与右键菜单。
- `ElaExecutionController`：节点运行态（idle / running / done / error）与耗时徽标，
  不执行业务逻辑。

## 交互

- 平移：中键拖拽 / 空格 + 左键 / 右键拖拽空白；
- 缩放：滚轮以光标为中心，0.25x–2.5x；
- 选择：Ctrl + 点选多选、空白左键橡皮筋框选；
- 编辑：网格吸附、框选、复制 / 粘贴、方向键微调；
- 连线：从输出引脚拖到输入引脚，非法连接抛 `ValueError`（原因可读）。

## 只读模式

```python
canvas.setReadOnly(True)
canvas.isReadOnly()          # True
canvas.node_activated.connect(lambda node_id: ...)   # 双击节点
```

只读下禁创建 / 删除 / 拖动 / 连线 / 右键菜单；平移、缩放、选中、hover 与
`execution()` 运行指示保留。节点体内的控件不再接收鼠标事件（点击冒泡给节点
做选中 / 双击），适合把节点图当只读视图嵌入其它面板（如运行轨迹流程图）。

## GL 视口与性能

`ElaBlueprintCanvas` 保持 `QWidget` 基类与全部公共 API 不变，自绘内容可由私有视口
承载。默认是软件视口（raster）；设置 `ELABLUEPRINT_GL=on` 或构造时传
`use_gl=True` 使用 `QOpenGLWidget`，与软件路径共用同一份绘制代码：

```python
canvas = ElaBlueprintCanvas(use_gl=True)    # 优先 GL，不可用自动回退软件
canvas = ElaBlueprintCanvas(use_gl=False)   # 强制软件视口
canvas.is_using_gl()                         # 查询实际使用的视口
```

`use_gl=None`（默认）按环境变量 / GL 探测结果选择。原生子窗口（GL 视口）必须在
`window.show()` 之前构建，否则会重建顶层 HWND；`example/blueprint_page.py` 已用
`PRE_SHOW_BUILD = True` 处理。

选中节点的外发光按节点尺寸 / 缩放档位缓存为位图，并按当前视口裁剪；大图全选后
平移 / 缩放不会逐节点重画多层圆角描边。节点绘制的字体 / 颜色解析也做了缓存，
主题切换由 `_reset_paint_caches()` 统一失效。50 节点 / 70 连线（1200×700）的
示例页在软件视口与 GL 视口下都能维持约 60fps；如果目标机器允许 GL，建议优先开启。

## 移植说明

移植自 InstructionX_UIKit.blueprint（原库为 PyQt6）；类名统一 `Ela*` 前缀，主题令牌
在 `blueprint._tokens` 中适配 `eTheme`。
