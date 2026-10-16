"""
[pyqt6_ela_pro] ElaBlueprintCanvas 节点图编辑器页面

类 UE5 Blueprint / ComfyUI 的节点图编辑器：右键空白创建节点、拖引脚
连线、拖节点 / 框选 / Ctrl 多选、Delete 删除、滚轮缩放、右键节点菜单。
附带「执行模拟」演示 running/done/error 状态与路径流动动画，以及
JSON 保存 / 加载。
"""

import json
import os

from PyQt6.QtCore import QPointF, QTimer
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6ElaWidgetTools import (
    ElaContentDialog,
    ElaLineEdit,
    ElaPushButton,
    ElaSpinBox,
    ElaMessageBar,
    ElaMessageBarType,
)

from pyqt6_ela_pro import (
    ElaBlueprintCanvas,
    ElaBlueprintGraph,
    register_node_type,
)
from pyqt6_ela_pro.blueprint import register_pin_type
from .base_page import ExamplePage

DEMO_OWNER = "blueprint-demo"
_DEMO_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "blueprint_demo.json"
)


def _ensure_demo_types():
    """注册演示节点类型（幂等：同定义重复注册被静默忽略）。"""
    register_pin_type("image", "#C080D0")

    def build_resize_body(node, container):
        spin = ElaSpinBox()
        spin.setRange(16, 8192)
        spin.setValue(int(node.properties.get("width", 512)))
        spin.valueChanged.connect(
            lambda v: node.properties.__setitem__("width", int(v))
        )
        container.layout().addWidget(spin)

    def build_blur_body(node, container):
        spin = ElaSpinBox()
        spin.setRange(0, 64)
        spin.setValue(int(node.properties.get("radius", 4)))
        spin.valueChanged.connect(
            lambda v: node.properties.__setitem__("radius", int(v))
        )
        container.layout().addWidget(spin)

    register_node_type(
        "load_image",
        "载入图像",
        "输入",
        outputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        accent="primary",
        description="从磁盘载入一张图像",
        owner=DEMO_OWNER,
    )
    register_node_type(
        "noise",
        "添加噪点",
        "处理",
        inputs=[{"id": "img", "name": "图像", "data_type": "image", "multi": True}],
        outputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        accent="warning",
        description="为图像叠加高斯噪声",
        owner=DEMO_OWNER,
    )
    register_node_type(
        "resize",
        "调整尺寸",
        "处理",
        inputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        accent="warning",
        body_builder=build_resize_body,
        description="按指定宽度缩放图像",
        owner=DEMO_OWNER,
    )
    register_node_type(
        "blur",
        "高斯模糊",
        "处理",
        # multi：演示图有两路汇入（噪点 / 缩放），单连接会被后到的边静默替换
        inputs=[{"id": "img", "name": "图像", "data_type": "image", "multi": True}],
        outputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        accent="warning",
        body_builder=build_blur_body,
        description="按半径对图像做高斯模糊",
        owner=DEMO_OWNER,
    )
    register_node_type(
        "save_image",
        "保存图像",
        "输出",
        inputs=[{"id": "img", "name": "图像", "data_type": "image", "multi": True}],
        accent="danger",
        description="把结果写入磁盘",
        owner=DEMO_OWNER,
    )


class BlueprintPage(ExamplePage):
    """ElaBlueprintCanvas：UE5 风格节点图编辑器"""

    #: 画布的视口是原生子窗口（``_GLViewport = QOpenGLWidget``）：必须在窗口 show
    #: **之前**构建好，否则给已显示的顶层窗口挂原生子窗口会让 Windows/Qt 重建顶层
    #: HWND（类名 ``QWindowIcon`` → ``QWindowOwnDCIcon``），用户看到主窗口「闪一次」。
    PRE_SHOW_BUILD = True

    PAGE_TITLE = "ElaBlueprintCanvas 节点图编辑器"

    def __init__(self, parent=None):
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        _ensure_demo_types()
        self._canvas = ElaBlueprintCanvas(ElaBlueprintGraph(), owner=DEMO_OWNER)
        self._canvas.setMinimumHeight(440)
        self._sim_timer = None
        self._rename_dialog = None
        # 画布把右键菜单里「重命名 / 属性」转成信号（行为归宿主）；示例
        # 给出最小实现，说明这两个入口该怎么接
        self._canvas.node_rename_requested.connect(self._rename_node)
        self._canvas.node_properties_requested.connect(self._show_node_properties)
        self._demo_scene()
        self._canvas.fit_view()

        self._addInfoText(
            "操作：右键空白创建节点 · 拖引脚连线（磁吸高亮）· 拖节点 / 框选 / Ctrl 多选 · "
            "Delete 删除 · 滚轮缩放 · 右键节点打开菜单（重命名 / 属性由宿主实现）",
            main_layout,
        )
        main_layout.addWidget(self._canvas, 1)
        self._buildControls(main_layout)

    # ── 控制栏 ─────────────────────────────────────────────────────────

    def _buildControls(self, main_layout):
        row = QHBoxLayout()
        row.setSpacing(8)
        run_btn = ElaPushButton("执行模拟", self)
        run_btn.clicked.connect(self._run_simulation)
        reset_btn = ElaPushButton("重置状态", self)
        reset_btn.clicked.connect(self._reset_states)
        fit_btn = ElaPushButton("适应视图", self)
        fit_btn.clicked.connect(self._canvas.fit_view)
        save_btn = ElaPushButton("保存 JSON", self)
        save_btn.clicked.connect(self._save_json)
        load_btn = ElaPushButton("加载 JSON", self)
        load_btn.clicked.connect(self._load_json)
        clear_btn = ElaPushButton("清空画布", self)
        clear_btn.clicked.connect(self._clear_canvas)
        for btn in (run_btn, reset_btn, fit_btn, save_btn, load_btn, clear_btn):
            row.addWidget(btn)
        row.addStretch()
        main_layout.addLayout(row)

    # ── 演示场景 ────────────────────────────────────────────────────────

    def _demo_scene(self):
        n1 = self._canvas.add_node_at("load_image", QPointF(40, 60))
        n2 = self._canvas.add_node_at("noise", QPointF(280, 20))
        n3 = self._canvas.add_node_at("resize", QPointF(280, 170))
        n4 = self._canvas.add_node_at("blur", QPointF(520, 90))
        n5 = self._canvas.add_node_at("save_image", QPointF(780, 120))
        g = self._canvas.graph
        g.add_edge(n1.id, "img", n2.id, "img")
        g.add_edge(n1.id, "img", n3.id, "img")
        g.add_edge(n2.id, "img", n4.id, "img")
        g.add_edge(n3.id, "img", n4.id, "img")
        g.add_edge(n4.id, "img", n5.id, "img")

    # ── 执行模拟（QTimer 顺序推进，纯 UI 状态）──────────────────────────

    def _run_simulation(self):
        """启动演示执行链：每个节点先 running 一个节拍，再 done / error。

        先 ``start``、隔一拍才 ``finish`` —— 同一回调里连着调两者的话
        running 状态在事件循环回到重绘之前就被覆盖，旋转圈 / 脉冲描边
        永远不可见（这个演示的一半意义就是看到它）。
        """
        self._stop_simulation()
        self._canvas.execution().reset()
        graph = self._canvas.graph
        nodes = graph.nodes()
        if not nodes:
            return
        # 有连边的节点按创建序排前，孤立节点排最后
        chain = [n.id for n in nodes if graph.edges_of(n.id)]
        chain += [n.id for n in nodes if not graph.edges_of(n.id)]
        chain = list(dict.fromkeys(chain))  # 去重保序
        self._canvas.execution().set_path(chain)
        self._sim_chain = chain
        self._sim_index = 0
        self._sim_phase = "start"
        self._sim_timer = QTimer(self)
        self._sim_timer.setSingleShot(True)
        self._sim_timer.timeout.connect(lambda: self._sim_step(self._sim_timer))
        # 首节点同步起步：点完按钮立即能看到 running
        self._sim_step(self._sim_timer)

    def _stop_simulation(self):
        """停止在途的演示执行链（重置 / 清空 / 重跑时调用）。"""
        timer = getattr(self, "_sim_timer", None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._sim_timer = None

    def _sim_step(self, timer):
        """单步推进（槽内异常兜底：Qt 回调抛异常 = 进程静默终止）。"""
        try:
            self._sim_step_impl(timer)
        except Exception as exc:  # noqa: BLE001
            self._stop_simulation()
            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.TopRight,
                "",
                f"模拟中断：{exc}",
                2000,
                self.window(),
            )

    def _sim_step_impl(self, timer):
        chain = self._sim_chain
        if self._sim_index >= len(chain):
            return
        ex = self._canvas.execution()
        nid = chain[self._sim_index]
        if self._sim_phase == "start":
            ex.start(nid)
            self._sim_phase = "end"
        else:
            node = self._canvas.graph.node(nid)
            if node is None:
                # 模拟途中节点被删：跳过而不是拿 None.title 抛异常
                self._sim_index += 1
                self._sim_phase = "start"
            else:
                if (self._sim_index + 1) % 4 == 0:
                    # 每 4 个节点失败一次演示 error 状态
                    ex.fail(nid, f"模拟失败：{node.title}")
                else:
                    ex.finish(nid, 20 + self._sim_index * 17)
                self._sim_index += 1
                self._sim_phase = "start"
        if self._sim_index < len(chain):
            timer.start(160)

    def _reset_states(self):
        """停止执行链并复位全部节点状态（控制栏按钮）。"""
        self._stop_simulation()
        self._canvas.execution().reset()

    def _clear_canvas(self):
        """停止执行链并清空画布。"""
        self._stop_simulation()
        self._canvas.graph.clear()

    # ── 节点菜单：重命名 / 属性（画布只发信号，行为由宿主实现）──────────

    def _rename_node(self, node_id):
        """右键「重命名」：非模态小对话框改标题（示例接法）。

        用 ``show()`` 而不是 ``exec()``：模态会把测试与其它宿主回调阻塞住
        （AGENTS 对模态对话框的通用约定）。
        """
        node = self._canvas.graph.node(node_id)
        if node is None:
            return
        old = getattr(self, "_rename_dialog", None)
        if old is not None:
            old.close()
        dialog = ElaContentDialog(self)
        dialog.setWindowTitle("重命名节点")
        edit = ElaLineEdit(dialog)
        edit.setText(node.title)
        edit.setBorderRadius(6)
        dialog.setCentralWidget(edit)
        dialog.setLeftButtonText("取消")
        dialog.setRightButtonText("确定")

        def _apply() -> None:
            text = edit.text().strip()
            if text:
                node.set_title(text)
            dialog.close()

        dialog.rightButtonClicked.connect(_apply)
        dialog.leftButtonClicked.connect(dialog.close)
        self._rename_dialog = dialog
        dialog.show()
        edit.setFocus()

    def _show_node_properties(self, node_id):
        """右键「属性…」：示例用信息条展示（真实属性面板由宿主实现）。"""
        node = self._canvas.graph.node(node_id)
        if node is None:
            return
        parts = [f"类型 {node.type_name}", f"状态 {node.status}"]
        for key, value in node.properties.items():
            parts.append(f"{key} = {value}")
        ElaMessageBar.information(
            ElaMessageBarType.PositionPolicy.TopRight,
            "节点属性",
            " · ".join(parts),
            2600,
            self.window(),
        )

    # ── JSON 保存 / 加载 ────────────────────────────────────────────────

    def _save_json(self):
        try:
            with open(_DEMO_JSON, "w", encoding="utf-8") as f:
                json.dump(self._canvas.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError as exc:
            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.TopRight,
                "",
                f"保存失败：{exc}",
                2000,
                self.window(),
            )
            return
        ElaMessageBar.success(
            ElaMessageBarType.PositionPolicy.TopRight,
            "",
            f"已保存到 {_DEMO_JSON}",
            2000,
            self.window(),
        )

    def _load_json(self):
        self._stop_simulation()
        try:
            with open(_DEMO_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.TopRight,
                "",
                f"加载失败：{exc}",
                2000,
                self.window(),
            )
            return
        # from_dict 自身已整体容错（坏节点 / 坏边逐条跳过）；这里再兜一道
        # 是槽内异常 = 进程终止的通用防线
        try:
            self._canvas.from_dict(data)
        except Exception as exc:  # noqa: BLE001
            ElaMessageBar.error(
                ElaMessageBarType.PositionPolicy.TopRight,
                "",
                f"加载失败：{exc}",
                2000,
                self.window(),
            )
            return
        self._canvas.fit_view()
        ElaMessageBar.success(
            ElaMessageBarType.PositionPolicy.TopRight,
            "",
            "已恢复画布",
            2000,
            self.window(),
        )
