"""
[pyqt6_ela_pro] ElaBlueprintCanvas 节点图编辑器页面

以**多模态 LLM 平台全景**为例（纯 UI，不执行任何训练）：50 节点 / 70 连线，
10 列树形布局（节点按上下游分支自由展开，不是等距网格）—— 数据源 → 预处理 → 编码器 → 多模态主干 → 输出头 → 损失 →
All-Reduce / 累积 / 优化 → 运维 → 交付。每节都能点 ``</> 代码`` 看该节用到的
公开 API，标题行的「播放」按钮按脚本演示本节能力：

1. 多模态平台全景：``register_node_type`` / ``register_pin_type`` /
   ``create_node`` / ``node.connect`` / ``fit_view``（播放会逐个重建整张图）；
2. 训练过程模拟：``execution().set_path / start / finish / fail`` +
   ``ElaBlueprintNode.set_progress``（节点底部进度条）+ 流动边 + 指标面板；
3. 分布式训练编排：第二张「扇出 → 扇入」DAG（分片 / rank / All-Reduce /
   梯度累积 / 余弦调度 / EMA / 导出），连线标签 ``connect(..., label=...)``；
4. 自定义节点体与编辑交互：``body_builder`` 里的 ``ElaComboBox`` /
   ``ElaSpinBox``、网格吸附 ``set_grid_snap``、复制 / 全选 / 方向键微调、
   右键连线删除、``set_edge_label``；
5. 保存与恢复：``canvas.to_dict`` / ``canvas.from_dict``（播放走内存快照）。

节点体里的控件是可交互的（信号写回 ``node.properties``）；拖动节点走标题栏、
引脚行或体空白处。
"""

import json
import os
import tempfile
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6ElaWidgetTools import (
    ElaComboBox,
    ElaContentDialog,
    ElaLineEdit,
    ElaMessageBar,
    ElaMessageBarType,
    ElaPushButton,
    ElaSpinBox,
    ElaText,
    ElaToggleSwitch,
)

from pyqt6_ela_pro import (
    ElaBlueprintCanvas,
    ElaBlueprintGraph,
    ElaButton,
    register_node_type,
)
from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro.blueprint import pin, register_pin_type

from ._step_player import _ScriptPlayer
from .base_page import ExamplePage

DEMO_OWNER = "blueprint-demo"
#: 演示 JSON 落到临时目录（不写包目录，避免示例运行污染仓库）
_DEMO_JSON = os.path.join(tempfile.gettempdir(), "pyqt6_ela_pro_blueprint_demo.json")
#: 训练链顺序（set_path 用：序列里从前到后的每条边都会被点亮）
_TRAIN_ORDER = (
    "text",
    "tokenizer",
    "text_emb",
    "pos",
    "block1",
    "cross_attn",
    "lm_head",
    "labels",
    "lm_loss",
    "total_loss",
    "backward",
    "allreduce",
    "accum",
    "optim",
    "ckpt",
    "eval",
)
#: 演示 epoch 数 / 每个 epoch 展示的指标
_EPOCHS = 2
_LOSS = ("1.680", "1.430")
_ACC = ("42.0%", "58.0%")
_LR = ("1.5e-4", "7.5e-5")


class BlueprintPage(ExamplePage):
    """ElaBlueprintCanvas：以神经网络训练流水线为例的节点图编辑器。"""

    #: 画布的视口可能是原生子窗口（``ELABLUEPRINT_GL=on`` 时是 ``QOpenGLWidget``）：
    #: 必须在窗口 show **之前**构建，否则给已显示的顶层窗口挂原生子窗口会让
    #: Windows/Qt 重建顶层 HWND（主窗口「闪一次」）。
    PRE_SHOW_BUILD = True

    PAGE_TITLE = "ElaBlueprintCanvas 节点图编辑器"

    #: 指标面板的标题
    METRIC_TITLES = {
        "epoch": "Epoch",
        "loss": "Loss",
        "acc": "Accuracy",
        "lr": "LR",
    }

    def __init__(self, parent=None):
        self._canvas = None
        self._body_canvas = None
        self._dist_canvas = None
        self._nodes = {}
        self._train_chain = []
        self._train_player = None
        self._section_player = None
        self._pipeline_scene = {}
        self._pipeline_edges = []
        self._pipeline_building = False
        self._dist_chain = []
        self._dist_note = None
        self._body_edges = []
        self._snap_switch = None
        self._persist_data = None
        self._persist_note = None
        self._build_training_steps = None
        self._metric_labels = {}
        self._train_note = None
        self._rename_dialog = None
        self._fitted = False
        super().__init__(parent)
        self._section_player = _ScriptPlayer(self)
        # 0ms 单发定时器是**本页的子对象**：首帧布局完成后再适应视图。
        # 不用 QTimer.singleShot（无主定时器，页面销毁后回调摸已释放控件）。
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_canvases)

    def showEvent(self, event):  # noqa: N802 (Qt 命名)
        """首次显示后按真实画布尺寸适应视图（构造期画布还没被布局定宽）。"""
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self._fit_timer.start(0)

    def _fit_canvases(self):
        if self._canvas is not None:
            self._canvas.fit_view()
        if self._dist_canvas is not None:
            self._dist_canvas.fit_view()
        if self._body_canvas is not None:
            self._body_canvas.fit_view()

    def _section_header(self, title, method, on_play=None):
        """节标题行：``</> 代码`` + 标题 + 「播放」。"""
        row = self._createHeaderRow(title, method)
        if on_play is not None:
            play = ElaButton("播放", variant="text", color="primary", parent=self)
            play.setFixedWidth(60)
            play.clicked.connect(lambda: self._safe_call(on_play))
            # 标题占满剩余宽度（不给 stretch 时 ElaText 只拿 sizeHint，
            # 长标题会被折成两行 —— 右侧明明还有大片空白）
            row.setStretch(1, 1)
            row.addWidget(play)
        return row

    def _safe_call(self, callback):
        """跑点击回调并吞掉异常（Qt 回调链上未捕获异常 = 进程静默终止）。"""
        try:
            callback()
        except Exception:  # noqa: BLE001 —— 见 docstring
            traceback.print_exc()

    # ================================================================ 01 流水线
    def _demoPipeline(self, main_layout):
        """01. 50 节点多模态 LLM 平台图（数据 → 模型 → 损失 → 训练 → 交付）。"""
        main_layout.addLayout(
            self._section_header(
                "01. 多模态 LLM 平台全景（50 节点 / 70 连线）",
                self._demoPipeline,
                self._playPipeline,
            )
        )
        self._addInfoText(
            "一张 50 节点 / 70 连线的大图：数据源 → 预处理 → 编码器 → 多模态主干 → "
            "5 个任务头 → 5 个损失 → All-Reduce / 累积 / 优化 → 运维 → 交付。"
            "滚轮放大看节点体与连线标签，空白拖动平移；「播放」会清空画布后"
            "逐个 create_node / connect 重建。",
            main_layout,
        )

        register_pin_type("loss", "danger")
        register_pin_type("grads", "warning")
        register_pin_type("metrics", "success")
        register_pin_type("weights", "primary")

        def optim_body(node, container):
            combo = ElaComboBox()
            combo.addItems(["AdamW", "SGD", "Lion"])
            combo.setFixedWidth(150)
            combo.setCurrentIndex(int(node.properties.get("optimizer", 0)))
            combo.currentIndexChanged.connect(
                lambda index: node.properties.__setitem__("optimizer", index)
            )
            container.layout().addWidget(combo)
            edit = ElaLineEdit()
            edit.setFixedWidth(150)
            edit.setPlaceholderText("学习率")
            edit.setText(str(node.properties.get("lr", "3e-4")))
            edit.textChanged.connect(
                lambda text: node.properties.__setitem__("lr", text)
            )
            container.layout().addWidget(edit)

        register_node_type(
            "gp_src",
            "数据源",
            "数据",
            outputs=pin("data", "数据", "tensor"),
            accent="primary",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_prep",
            "预处理",
            "数据",
            inputs=pin("in", "输入", "tensor", multi=True),
            outputs=pin("out", "输出", "tensor"),
            accent="primary",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_enc",
            "编码器",
            "模型",
            inputs=pin("in", "输入", "tensor", multi=True),
            outputs=pin("out", "输出", "tensor"),
            accent="warning",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_model",
            "模型层",
            "模型",
            inputs=pin("in", "输入", "tensor", multi=True),
            outputs=pin("out", "输出", "tensor"),
            accent="warning",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_router",
            "MoE Router",
            "模型",
            inputs=pin("in", "输入", "tensor"),
            outputs=[
                pin("a", "Expert A", "tensor"),
                pin("b", "Expert B", "tensor"),
            ],
            accent="warning",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_head",
            "输出头",
            "模型",
            inputs=pin("in", "输入", "tensor", multi=True),
            outputs=pin("logits", "Logits", "tensor"),
            accent="warning",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_loss",
            "损失",
            "训练",
            inputs=[
                pin("logits", "Logits", "tensor"),
                pin("labels", "标签", "tensor"),
            ],
            outputs=pin("loss", "Loss", "loss"),
            accent="danger",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_total",
            "总损失",
            "训练",
            inputs=pin("losses", "分项损失", "loss", multi=True),
            outputs=pin("loss", "Loss", "loss"),
            accent="danger",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_backward",
            "反向传播",
            "训练",
            inputs=pin("loss", "Loss", "loss"),
            outputs=pin("grads", "Grads", "grads"),
            accent="danger",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_grads",
            "梯度处理",
            "训练",
            inputs=pin("in", "Grads", "grads"),
            outputs=pin("out", "Grads", "grads"),
            accent="danger",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_opt",
            "优化器",
            "训练",
            inputs=pin("grads", "Grads", "grads"),
            outputs=pin("update", "Update", "grads"),
            accent="success",
            body_builder=optim_body,
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_sched",
            "调度器",
            "训练",
            inputs=pin("in", "Step", "grads"),
            outputs=pin("out", "Step", "grads"),
            accent="success",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_ema",
            "EMA",
            "运维",
            inputs=pin("in", "Update", "grads"),
            outputs=pin("weights", "权重", "weights"),
            accent="primary",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_ckpt",
            "检查点",
            "运维",
            inputs=pin("update", "Update", "grads"),
            outputs=pin("out", "State", "weights"),
            accent="success",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_eval",
            "验证指标",
            "运维",
            inputs=pin("in", "输入", "any"),
            outputs=pin("metrics", "Metrics", "metrics"),
            accent="primary",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_log",
            "训练日志",
            "运维",
            inputs=pin("in", "输入", "any"),
            accent="primary",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_deliver",
            "交付",
            "交付",
            inputs=pin("in", "输入", "any", multi=True),
            accent="success",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "gp_monitor",
            "监控",
            "交付",
            inputs=pin("in", "输入", "any", multi=True),
            accent="primary",
            owner=DEMO_OWNER,
        )

        self._canvas = ElaBlueprintCanvas(ElaBlueprintGraph(), owner=DEMO_OWNER)
        self._canvas.setMinimumHeight(700)
        self._canvas.node_rename_requested.connect(self._rename_node)
        self._canvas.node_properties_requested.connect(self._show_node_properties)

        # 10 列 × 5 行（C5 多一行放「标签数据」源）：列 = 阶段，行 = 并行子任务。
        scene = {
            # C0 数据源
            "text": ("gp_src", "文本语料", (20, 300), {"size": "118M"}),
            "code": ("gp_src", "代码语料", (20, 170), {"size": "42M"}),
            "image": ("gp_src", "图文对", (20, 40), {"size": "5.2M"}),
            "audio": ("gp_src", "语音语料", (20, 560), {"size": "1.8M"}),
            "pref": ("gp_src", "偏好数据", (20, 700), {"size": "240K"}),
            # C1 预处理
            "dedup": ("gp_prep", "去重", (225, 300), None),
            "clean": ("gp_prep", "清洗", (225, 430), None),
            "tokenizer": ("gp_prep", "分词器", (225, 170), {"vocab": "32k"}),
            "image_dec": ("gp_prep", "图像解码", (225, 40), None),
            "audio_dec": ("gp_prep", "音频解码", (225, 560), None),
            # C2 编码器
            "text_emb": ("gp_enc", "文本嵌入", (430, 300), None),
            "pos": ("gp_enc", "位置编码", (430, 170), None),
            "vision_enc": ("gp_enc", "视觉编码", (430, 40), None),
            "audio_enc": ("gp_enc", "音频编码", (430, 560), None),
            # C3 模型 1
            "fusion": ("gp_model", "模态融合", (635, 300), None),
            "self_attn": ("gp_model", "自注意力", (635, 150), {"heads": 8}),
            "block1": ("gp_model", "Transformer", (635, 430), {"layers": 12}),
            "router": ("gp_router", "MoE Router", (635, 570), {"experts": 2}),
            "norm": ("gp_model", "LayerNorm", (635, 700), None),
            # C4 模型 2
            "cross_attn": ("gp_model", "交叉注意力", (840, 300), None),
            "ffn": ("gp_model", "前馈网络", (840, 430), None),
            "expert_a": ("gp_model", "Expert A", (840, 570), None),
            "expert_b": ("gp_model", "Expert B", (840, 700), None),
            "moe_out": ("gp_model", "MoE 合并", (840, 800), None),
            # C5 输出头 + 标签源
            "lm_head": ("gp_head", "LM Head", (1045, 300), {"vocab": "32k"}),
            "cls_head": ("gp_head", "分类头", (1045, 170), {"classes": 32}),
            "det_head": ("gp_head", "检测头", (1045, 430), None),
            "contrast_head": ("gp_head", "对比头", (1045, 680), None),
            "pref_head": ("gp_head", "偏好头", (1045, 800), None),
            "labels": ("gp_src", "标签数据", (1045, 920), {"classes": 32}),
            # C6 损失
            "lm_loss": ("gp_loss", "LM Loss", (1250, 300), None),
            "cls_loss": ("gp_loss", "分类损失", (1250, 170), None),
            "det_loss": ("gp_loss", "检测损失", (1250, 430), None),
            "contrast_loss": ("gp_loss", "对比损失", (1250, 680), None),
            "pref_loss": ("gp_loss", "偏好损失", (1250, 800), None),
            # C7 训练
            "total_loss": ("gp_total", "总损失", (1455, 520), {"weighted": True}),
            "backward": ("gp_backward", "反向传播", (1455, 640), {"amp": "bf16"}),
            "allreduce": ("gp_grads", "All-Reduce", (1455, 760), None),
            "accum": ("gp_grads", "梯度累积", (1455, 880), {"steps": 4}),
            "optim": (
                "gp_opt",
                "AdamW 优化器",
                (1455, 1000),
                {"optimizer": 0, "lr": "3e-4"},
            ),
            # C8 运维
            "log": ("gp_log", "训练日志", (1660, 520), {"backend": "TB"}),
            "sched": ("gp_sched", "余弦调度", (1660, 640), {"warmup": 500}),
            "ema": ("gp_ema", "EMA 权重", (1660, 760), {"decay": 0.999}),
            "ckpt": ("gp_ckpt", "检查点", (1660, 880), {"every": "2 epoch"}),
            "eval": ("gp_eval", "验证指标", (1660, 1000), {"metrics": "F1"}),
            # C9 交付
            "export": ("gp_deliver", "导出 ONNX", (1865, 520), {"opset": 17}),
            "quantize": ("gp_deliver", "量化", (1865, 640), {"bits": 8}),
            "registry": ("gp_deliver", "模型注册", (1865, 760), {"version": "v1"}),
            "serving": ("gp_deliver", "在线服务", (1865, 880), {"qps": 1200}),
            "monitor": ("gp_monitor", "监控告警", (1865, 1000), {"alerts": "on"}),
        }
        self._pipeline_scene = scene
        self._nodes = {
            name: self._canvas.create_node(type_name, pos, properties, title=title)
            for name, (type_name, title, pos, properties) in scene.items()
        }

        # 70 条边：每列只连到相邻列（同列只做短距离连接），避免长对角线穿过节点。
        self._pipeline_edges = [
            # C0 数据源 → C1 预处理
            ("text", "data", "dedup", "in", ""),
            ("text", "data", "clean", "in", ""),
            ("text", "data", "tokenizer", "in", "corpus"),
            ("code", "data", "dedup", "in", ""),
            ("code", "data", "clean", "in", ""),
            ("code", "data", "tokenizer", "in", ""),
            ("image", "data", "image_dec", "in", ""),
            ("audio", "data", "audio_dec", "in", ""),
            ("pref", "data", "clean", "in", ""),
            # C1 预处理 → C2 编码器
            ("dedup", "out", "text_emb", "in", ""),
            ("clean", "out", "text_emb", "in", ""),
            ("tokenizer", "out", "text_emb", "in", "tokens"),
            ("tokenizer", "out", "pos", "in", ""),
            ("image_dec", "out", "vision_enc", "in", ""),
            ("audio_dec", "out", "audio_enc", "in", ""),
            # C2 编码器 → C3 模型 1
            ("text_emb", "out", "fusion", "in", ""),
            ("vision_enc", "out", "fusion", "in", ""),
            ("audio_enc", "out", "fusion", "in", ""),
            ("text_emb", "out", "self_attn", "in", ""),
            ("pos", "out", "self_attn", "in", ""),
            ("text_emb", "out", "block1", "in", "hidden [B, 512]"),
            ("pos", "out", "block1", "in", ""),
            ("block1", "out", "router", "in", ""),
            ("block1", "out", "norm", "in", ""),
            # C3 模型 1 → C4 模型 2
            ("fusion", "out", "cross_attn", "in", ""),
            ("self_attn", "out", "cross_attn", "in", ""),
            ("block1", "out", "cross_attn", "in", ""),
            ("fusion", "out", "ffn", "in", ""),
            ("self_attn", "out", "ffn", "in", ""),
            ("block1", "out", "ffn", "in", ""),
            ("norm", "out", "ffn", "in", ""),
            ("router", "a", "expert_a", "in", ""),
            ("router", "b", "expert_b", "in", ""),
            ("expert_a", "out", "moe_out", "in", ""),
            ("expert_b", "out", "moe_out", "in", ""),
            # C4 模型 2 → C5 输出头（每个头一个来源，避免多头扇入交叉）
            ("cross_attn", "out", "lm_head", "in", ""),
            ("ffn", "out", "cls_head", "in", ""),
            ("ffn", "out", "det_head", "in", ""),
            ("moe_out", "out", "contrast_head", "in", ""),
            ("moe_out", "out", "pref_head", "in", ""),
            # C5 输出头 → C6 损失
            ("lm_head", "logits", "lm_loss", "logits", "logits"),
            ("cls_head", "logits", "cls_loss", "logits", ""),
            ("det_head", "logits", "det_loss", "logits", ""),
            ("contrast_head", "logits", "contrast_loss", "logits", ""),
            ("pref_head", "logits", "pref_loss", "logits", ""),
            # 标签源统一扇出到 5 个损失（与总损失扇入对称）
            ("labels", "data", "lm_loss", "labels", "labels"),
            ("labels", "data", "cls_loss", "labels", ""),
            ("labels", "data", "det_loss", "labels", ""),
            ("labels", "data", "contrast_loss", "labels", ""),
            ("labels", "data", "pref_loss", "labels", ""),
            # C6 损失 → C7 训练
            ("lm_loss", "loss", "total_loss", "losses", ""),
            ("cls_loss", "loss", "total_loss", "losses", ""),
            ("det_loss", "loss", "total_loss", "losses", ""),
            ("contrast_loss", "loss", "total_loss", "losses", ""),
            ("pref_loss", "loss", "total_loss", "losses", ""),
            ("total_loss", "loss", "backward", "loss", "loss"),
            ("backward", "grads", "allreduce", "in", "grads"),
            ("allreduce", "out", "accum", "in", ""),
            ("accum", "out", "optim", "grads", "accum 4"),
            # C7 训练 → C8 运维
            ("optim", "update", "sched", "in", ""),
            ("optim", "update", "ema", "in", ""),
            ("optim", "update", "ckpt", "update", "每 2 epoch"),
            ("optim", "update", "eval", "in", ""),
            ("backward", "grads", "log", "in", ""),
            # C8 运维 → C9 交付
            ("sched", "out", "registry", "in", ""),
            ("ckpt", "out", "registry", "in", ""),
            ("ema", "weights", "export", "in", "weights"),
            ("ema", "weights", "quantize", "in", ""),
            ("eval", "metrics", "serving", "in", "metrics"),
            ("eval", "metrics", "monitor", "in", ""),
        ]
        for src, from_pin, dst, to_pin, label in self._pipeline_edges:
            self._nodes[src].connect(self._nodes[dst], from_pin, to_pin, label=label)
        self._canvas.fit_view()
        main_layout.addWidget(self._canvas)

    # ================================================================ 02 训练
    def _demoTraining(self, main_layout):
        """02. 训练过程模拟：运行态 / 节点进度 / 流动边 / 指标。"""
        main_layout.addLayout(
            self._section_header(
                "02. 训练过程模拟（start / finish / fail + 进度条 + 流动边）",
                self._demoTraining,
                self._run_training,
            )
        )
        self._addInfoText(
            "纯 UI 模拟：控制器只把节点标记成 running / done / error，"
            "不执行任何训练。路径上的边会变成流动虚线，节点底部是进度条。",
            main_layout,
        )
        self._train_chain = [
            self._nodes[name] for name in _TRAIN_ORDER if name in self._nodes
        ]

        controls = QHBoxLayout()
        controls.setSpacing(8)
        run_btn = ElaPushButton("开始训练", self)
        run_btn.clicked.connect(self._run_training)
        reset_btn = ElaPushButton("重置状态", self)
        reset_btn.clicked.connect(self._reset_training)
        fail_btn = ElaPushButton("演示错误", self)
        fail_btn.clicked.connect(self._simulate_failure)
        fit_btn = ElaPushButton("适应视图", self)
        fit_btn.clicked.connect(self._canvas.fit_view)
        for button in (run_btn, reset_btn, fail_btn, fit_btn):
            controls.addWidget(button)
        controls.addStretch()
        main_layout.addLayout(controls)

        metrics = QHBoxLayout()
        metrics.setSpacing(18)
        for key, title in self.METRIC_TITLES.items():
            label = ColorText(f"{title}  —", self)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextWeight(QFont.Weight.DemiBold)
            label.setTextPixelSize(14)
            metrics.addWidget(label)
            self._metric_labels[key] = label
        metrics.addStretch()
        main_layout.addLayout(metrics)

        self._train_note = ColorText("就绪：点击「开始训练」按 epoch 重播。", self)
        self._train_note.setTextFormat(Qt.TextFormat.PlainText)
        self._train_note.setTextPixelSize(12)
        main_layout.addWidget(self._train_note)

        # 预填一轮完成态：打开页面就能看到状态描边 / 耗时徽标 / 进度条
        self._prefill_training_state()

        self._train_player = _ScriptPlayer(self)

        def build_steps():
            def start(node_name):
                node = self._nodes.get(node_name)
                if node is not None:
                    self._canvas.execution().start(node)

            def progress(node_name, value):
                node = self._nodes.get(node_name)
                if node is not None:
                    node.set_progress(value)

            def finish(node_name, elapsed):
                node = self._nodes.get(node_name)
                if node is not None:
                    self._canvas.execution().finish(node, elapsed)

            steps = []
            for epoch in range(1, _EPOCHS + 1):
                steps.append(
                    (0, lambda e=epoch: self._set_metric("epoch", f"{e} / {_EPOCHS}"))
                )
                for name in _TRAIN_ORDER:
                    elapsed = 12 + _TRAIN_ORDER.index(name) * 6 + epoch * 4
                    steps.append((0, lambda n=name: start(n)))
                    steps.append((0, lambda n=name: progress(n, 0.45)))
                    steps.append((0, lambda n=name: progress(n, 1.0)))
                    steps.append((0, lambda n=name, ms=elapsed: finish(n, ms)))
                    if name == "lm_loss":
                        steps.append(
                            (
                                0,
                                lambda e=epoch: self._set_metric("loss", _LOSS[e - 1]),
                            )
                        )
                    if name == "eval":
                        steps.append(
                            (
                                0,
                                lambda e=epoch: self._set_metric("acc", _ACC[e - 1]),
                            )
                        )
                steps.append((0, lambda e=epoch: self._set_metric("lr", _LR[e - 1])))
            steps.append((0, self._training_finished))
            return steps

        self._build_training_steps = build_steps

    # ================================================================ 03 分布式
    def _demoDistributed(self, main_layout):
        """03. 分布式训练编排：分片 → 多 rank → All-Reduce → 累积 / 优化 / EMA。"""
        main_layout.addLayout(
            self._section_header(
                "03. 分布式训练编排（分片 / All-Reduce / 累积 / EMA）",
                self._demoDistributed,
                self._playDistributed,
            )
        )
        self._addInfoText(
            "第二张图演示「扇出 → 扇入」的 DAG：数据分片扇出到 3 个 rank，"
            "本地梯度经 All-Reduce 汇总，再进入梯度累积 / 优化器 / 余弦调度 / EMA。"
            "标签用 connect(..., label=...) 写入。",
            main_layout,
        )

        register_pin_type("weights", "primary")

        def rank_body(node, container):
            spin = ElaSpinBox()
            spin.setRange(1, 256)
            spin.setFixedWidth(110)
            spin.setValue(int(node.properties.get("local_batch", 32)))
            spin.valueChanged.connect(
                lambda value: node.properties.__setitem__("local_batch", int(value))
            )
            container.layout().addWidget(spin)

        def accum_body(node, container):
            spin = ElaSpinBox()
            spin.setRange(1, 64)
            spin.setFixedWidth(110)
            spin.setValue(int(node.properties.get("steps", 4)))
            spin.valueChanged.connect(
                lambda value: node.properties.__setitem__("steps", int(value))
            )
            container.layout().addWidget(spin)

        register_node_type(
            "dt_batch",
            "全局 Batch",
            "分布式",
            outputs=pin("out", "样本", "tensor"),
            accent="primary",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "dt_shard",
            "数据分片",
            "分布式",
            inputs=pin("in", "样本", "tensor"),
            outputs=pin("out", "分片", "tensor"),
            accent="primary",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "dt_rank",
            "Rank · 前向",
            "分布式",
            inputs=pin("in", "分片", "tensor"),
            outputs=pin("out", "Grads", "grads"),
            accent="warning",
            body_builder=rank_body,
            owner=DEMO_OWNER,
        )
        register_node_type(
            "dt_reduce",
            "All-Reduce",
            "训练",
            inputs=[
                pin("in0", "Rank 0", "grads", multi=True),
                pin("in1", "Rank 1", "grads", multi=True),
                pin("in2", "Rank 2", "grads", multi=True),
            ],
            outputs=pin("out", "Grads", "grads"),
            accent="danger",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "dt_accum",
            "梯度累积",
            "训练",
            inputs=pin("in", "Grads", "grads"),
            outputs=pin("out", "Grads", "grads"),
            accent="danger",
            body_builder=accum_body,
            owner=DEMO_OWNER,
        )
        register_node_type(
            "dt_sched",
            "余弦调度",
            "训练",
            inputs=pin("in", "Update", "grads"),
            outputs=pin("out", "Update", "grads"),
            accent="success",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "dt_ema",
            "EMA 权重",
            "评估",
            inputs=pin("in", "Update", "grads"),
            outputs=pin("out", "Weights", "weights"),
            accent="primary",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "dt_export",
            "导出 ONNX",
            "评估",
            inputs=pin("in", "Weights", "weights"),
            accent="success",
            owner=DEMO_OWNER,
        )
        register_node_type(
            "dt_eval",
            "离线评估",
            "评估",
            inputs=pin("in", "Weights", "weights"),
            outputs=pin("out", "Metrics", "metrics"),
            accent="primary",
            owner=DEMO_OWNER,
        )

        canvas = ElaBlueprintCanvas(ElaBlueprintGraph(), owner=DEMO_OWNER)
        self._dist_canvas = canvas
        canvas.setMinimumHeight(460)
        batch = canvas.create_node("dt_batch", (20, 180))
        shard = canvas.create_node("dt_shard", (200, 180))
        ranks = [
            canvas.create_node("dt_rank", (380, y), {"local_batch": 32})
            for y in (40, 180, 320)
        ]
        for index, rank in enumerate(ranks):
            rank.set_title(f"Rank {index} · 前向")
        reduce = canvas.create_node("dt_reduce", (560, 180))
        accum = canvas.create_node("dt_accum", (740, 180), {"steps": 4})
        optim = canvas.create_node("gp_opt", (920, 180), {"optimizer": 0, "lr": "3e-4"})
        optim.set_title("AdamW 优化器")
        sched = canvas.create_node(
            "dt_sched", (1100, 60), {"type": "cosine", "warmup": 500}
        )
        ema = canvas.create_node("dt_ema", (1280, 60), {"decay": 0.999})
        ckpt = canvas.create_node("gp_ckpt", (1100, 300), {"every": "每 2 step"})
        ckpt.set_title("检查点")
        export = canvas.create_node("dt_export", (1460, 60), {"opset": 17})
        eval_node = canvas.create_node("dt_eval", (1460, 240), {"split": "validation"})

        batch.connect(shard, "out", "in", label="global batch 96")
        for index, rank in enumerate(ranks):
            shard.connect(rank, "out", "in", label=f"shard {index}")
            rank.connect(reduce, "out", f"in{index}", label="local grads")
        reduce.connect(accum, "out", "in", label="all-reduce")
        accum.connect(optim, "out", "grads", label="accum 4")
        optim.connect(ckpt, "update", "update", label="每 2 step")
        optim.connect(sched, "update", "in", label="step")
        sched.connect(ema, "out", "in", label="cosine")
        ema.connect(export, "out", "in", label="onnx")
        ema.connect(eval_node, "out", "in", label="EMA weights")

        self._dist_chain = [
            batch,
            shard,
            *ranks,
            reduce,
            accum,
            optim,
            ckpt,
            sched,
            ema,
            export,
            eval_node,
        ]

        canvas.fit_view()
        main_layout.addWidget(canvas)

        self._dist_note = ColorText(
            "就绪：点击「播放」按 rank 回放一遍扇出 → 归约 → 优化。", self
        )
        self._dist_note.setTextFormat(Qt.TextFormat.PlainText)
        self._dist_note.setTextPixelSize(12)
        main_layout.addWidget(self._dist_note)

    # ================================================================ 04 编辑
    def _demoNodeBody(self, main_layout):
        """04. 自定义节点体 + 编辑交互（吸附 / 复制 / 微调 / 连线菜单）。"""
        main_layout.addLayout(
            self._section_header(
                "04. 自定义节点体与编辑交互（吸附 / 快捷键 / 右键连线）",
                self._demoNodeBody,
                self._playEditing,
            )
        )
        self._addInfoText(
            "节点体是 body_builder 注入的普通控件（下拉框 / 数字框都能交互）；"
            "方向键微调选中节点（Shift 10px），Ctrl+A 全选、Ctrl+D 复制、"
            "Delete 删除、右键连线可删除。",
            main_layout,
        )

        def sampler_body(node, container):
            combo = ElaComboBox()
            combo.addItems(["随机采样", "顺序采样", "分层采样"])
            combo.setFixedWidth(150)
            combo.setCurrentIndex(int(node.properties.get("sampler", 0)))
            combo.currentIndexChanged.connect(
                lambda index: node.properties.__setitem__("sampler", index)
            )
            container.layout().addWidget(combo)
            spin = ElaSpinBox()
            spin.setRange(1, 512)
            spin.setFixedWidth(120)
            spin.setValue(int(node.properties.get("workers", 8)))
            spin.valueChanged.connect(
                lambda value: node.properties.__setitem__("workers", int(value))
            )
            container.layout().addWidget(spin)

        register_node_type(
            "demo_sampler",
            "采样器（自定义节点体）",
            "演示",
            inputs=pin("in", "数据集", "tensor"),
            outputs=pin("out", "批次", "tensor"),
            accent="primary",
            body_builder=sampler_body,
            description="body_builder 里放 ElaComboBox + ElaSpinBox",
            owner=DEMO_OWNER,
        )

        self._body_canvas = ElaBlueprintCanvas(ElaBlueprintGraph(), owner=DEMO_OWNER)
        self._body_canvas.setMinimumHeight(300)
        sampler = self._body_canvas.create_node(
            "demo_sampler", (40, 40), {"sampler": 0, "workers": 8}
        )
        model = self._body_canvas.create_node(
            "gp_enc", (340, 40), {"d_model": 512, "heads": 8, "layers": 12}
        )
        eval_node = self._body_canvas.create_node(
            "gp_eval", (640, 40), {"metrics": "Accuracy · F1"}
        )
        self._body_edges = [
            sampler.connect(model, "out", "in", label="batch 128"),
            model.connect(eval_node, "out", "in", label="hidden [B, 512]"),
        ]
        self._body_canvas.fit_view()
        main_layout.addWidget(self._body_canvas)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)
        snap_switch = ElaToggleSwitch(self)
        snap_switch.toggled.connect(self._body_canvas.set_grid_snap)
        self._snap_switch = snap_switch
        snap_label = ElaText("拖动吸附网格", self)
        snap_label.setTextPixelSize(14)
        edit_row.addWidget(snap_switch)
        edit_row.addWidget(snap_label)
        duplicate_btn = ElaPushButton("复制选中", self)
        duplicate_btn.clicked.connect(self._body_canvas.duplicate_selection)
        select_btn = ElaPushButton("全选", self)
        select_btn.clicked.connect(self._body_canvas.select_all)
        fit_btn = ElaPushButton("适应视图", self)
        fit_btn.clicked.connect(self._body_canvas.fit_view)
        for button in (duplicate_btn, select_btn, fit_btn):
            edit_row.addWidget(button)
        edit_row.addStretch()
        main_layout.addLayout(edit_row)

        label_row = QHBoxLayout()
        label_row.setSpacing(8)
        label_edit = ElaLineEdit(self)
        label_edit.setPlaceholderText("先点选一条连线，再输入标签…")
        label_edit.setFixedWidth(260)
        apply_btn = ElaPushButton("设置连线标签", self)
        clear_btn = ElaPushButton("清除连线标签", self)

        def apply_edge_label(text):
            for edge_id in self._body_canvas.selected_edge_ids():
                self._body_canvas.set_edge_label(edge_id, text)

        apply_btn.clicked.connect(lambda: apply_edge_label(label_edit.text()))
        clear_btn.clicked.connect(lambda: apply_edge_label(""))
        label_row.addWidget(label_edit)
        label_row.addWidget(apply_btn)
        label_row.addWidget(clear_btn)
        label_row.addStretch()
        main_layout.addLayout(label_row)

    # ================================================================ 05 持久化
    def _demoPersistence(self, main_layout):
        """05. 保存与恢复：canvas.to_dict / canvas.from_dict。"""
        main_layout.addLayout(
            self._section_header(
                "05. 保存与恢复（to_dict / from_dict）",
                self._demoPersistence,
                self._playPersistence,
            )
        )
        self._addInfoText(
            f"把整张图（节点 / 连线 / 视图缩放与偏移）写成 JSON：{_DEMO_JSON}；"
            "from_dict 对坏节点与坏连线逐条跳过，不会让整张图载入失败。",
            main_layout,
        )

        row = QHBoxLayout()
        row.setSpacing(8)
        save_btn = ElaPushButton("保存 JSON", self)
        load_btn = ElaPushButton("加载 JSON", self)
        row.addWidget(save_btn)
        row.addWidget(load_btn)
        row.addStretch()
        main_layout.addLayout(row)

        self._persist_note = ColorText(
            "就绪：点击「播放」演示「序列化 → 清空 → 恢复」全过程。", self
        )
        self._persist_note.setTextFormat(Qt.TextFormat.PlainText)
        self._persist_note.setTextPixelSize(12)
        main_layout.addWidget(self._persist_note)

        def save():
            try:
                data = self._canvas.to_dict()
                with open(_DEMO_JSON, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
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

        def load():
            try:
                with open(_DEMO_JSON, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                ElaMessageBar.error(
                    ElaMessageBarType.PositionPolicy.TopRight,
                    "",
                    f"加载失败：{exc}",
                    2000,
                    self.window(),
                )
                return
            self._canvas.from_dict(data)
            self._rebind_nodes()
            self._prefill_training_state()
            self._canvas.fit_view()
            ElaMessageBar.success(
                ElaMessageBarType.PositionPolicy.TopRight,
                "",
                "已恢复画布",
                2000,
                self.window(),
            )

        save_btn.clicked.connect(save)
        load_btn.clicked.connect(load)

    def _rebind_nodes(self):
        """``from_dict`` 重建节点对象后，把示例页按名字保存的引用重新绑上。"""
        graph = self._canvas.graph
        self._nodes = {
            name: new
            for name, old in self._nodes.items()
            if (new := graph.node(old.id)) is not None
        }
        self._train_chain = [
            self._nodes[name] for name in _TRAIN_ORDER if name in self._nodes
        ]

    # ================================================================ 播放入口
    def _stop_playbacks(self):
        """停掉所有节播放（只停脚本，不复位节点状态）。"""
        for player in (self._section_player, self._train_player):
            if player is not None:
                player.stop()

    def _ensure_pipeline_complete(self):
        """01 的逐节点重建被打断时，同步补完（否则画布停在半张图）。"""
        if not self._pipeline_building:
            return
        self._section_player.stop()
        self._canvas.graph.clear()
        self._nodes = {}
        self._train_chain = []
        self._section_player.play_now(self._pipeline_play_steps())

    # -- 01 重建大图 ------------------------------------------------------
    def _playPipeline(self):
        """01 播放：清空画布，逐个节点 / 连线重建 50 节点图。"""
        self._stop_playbacks()
        if self._canvas is None or not self._pipeline_scene:
            return
        self._canvas.execution().reset()
        self._canvas.graph.clear()
        self._nodes = {}
        self._train_chain = []
        self._pipeline_building = True
        self._set_train_note("正在重建：逐个 create_node / connect …")
        self._section_player.play(self._pipeline_play_steps(), interval=16)

    def _pipeline_play_steps(self):
        steps = [
            (0, lambda name=name: self._add_pipeline_node(name))
            for name in self._pipeline_scene
        ]
        steps += [
            (0, lambda edge=edge: self._connect_pipeline_edge(edge))
            for edge in self._pipeline_edges
        ]
        steps.append((0, self._finish_pipeline_rebuild))
        return steps

    def _add_pipeline_node(self, name):
        type_name, title, pos, properties = self._pipeline_scene[name]
        self._nodes[name] = self._canvas.create_node(
            type_name, pos, properties, title=title
        )

    def _connect_pipeline_edge(self, spec):
        src, from_pin, dst, to_pin, label = spec
        from_node = self._nodes.get(src)
        to_node = self._nodes.get(dst)
        if from_node is None or to_node is None:
            return
        from_node.connect(to_node, from_pin, to_pin, label=label)

    def _finish_pipeline_rebuild(self):
        self._pipeline_building = False
        self._train_chain = [
            self._nodes[name] for name in _TRAIN_ORDER if name in self._nodes
        ]
        self._prefill_training_state()
        self._canvas.fit_view()
        self._set_train_note(
            f"重建完成：{len(self._nodes)} 节点 / "
            f"{len(self._canvas.graph.edges())} 连线。"
        )

    # -- 03 分布式回放 ----------------------------------------------------
    def _playDistributed(self):
        """03 播放：按 rank 顺序回放执行状态。"""
        self._stop_playbacks()
        self._ensure_pipeline_complete()
        if self._dist_canvas is None or not self._dist_chain:
            return
        execution = self._dist_canvas.execution()
        execution.reset()
        execution.set_path(self._dist_chain)
        self._set_dist_note("回放中：分片扇出 → 3 个 rank → All-Reduce → 累积 → 优化。")
        execution.start(self._dist_chain[0])
        self._section_player.play(self._distributed_play_steps(), interval=45)

    def _distributed_play_steps(self):
        execution = self._dist_canvas.execution()
        steps = []
        for index, node in enumerate(self._dist_chain):
            elapsed = 10 + index * 5
            steps.append((0, lambda n=node: execution.start(n)))
            steps.append((0, lambda n=node: n.set_progress(0.45)))
            steps.append((0, lambda n=node: n.set_progress(1.0)))
            steps.append((0, lambda n=node, ms=elapsed: execution.finish(n, ms)))
        steps.append((0, self._finish_distributed_play))
        return steps

    def _finish_distributed_play(self):
        self._set_dist_note("回放完成：14 条边全部在路径上（纯 UI 演示）。")

    def _set_dist_note(self, text):
        if self._dist_note is not None:
            self._dist_note.setText(text)

    # -- 04 编辑交互 ------------------------------------------------------
    def _playEditing(self):
        """04 播放：开吸附 → 全选 → 微调 → 写连线标签 → 适应视图。"""
        self._stop_playbacks()
        self._ensure_pipeline_complete()
        if self._body_canvas is None:
            return
        self._section_player.play(self._editing_play_steps(), interval=70)

    def _editing_play_steps(self):
        canvas = self._body_canvas
        steps = []
        if self._snap_switch is not None:
            steps.append((0, lambda: self._snap_switch.setIsToggled(True)))
        steps.append((0, canvas.clear_selection))
        steps.append((0, canvas.select_all))
        steps.append((0, lambda: canvas.nudge_selection(6, 0)))
        steps.append((0, lambda: canvas.nudge_selection(-6, 0)))
        for edge, label in zip(self._body_edges, ("batch 128", "hidden [B, 512]")):
            steps.append((0, lambda e=edge, text=label: canvas.set_edge_label(e, text)))
        steps.append((0, canvas.fit_view))
        return steps

    # -- 05 保存与恢复 ----------------------------------------------------
    def _playPersistence(self):
        """05 播放：内存快照 → 清空画布 → from_dict 恢复。"""
        self._stop_playbacks()
        self._ensure_pipeline_complete()
        if self._canvas is None:
            return
        self._section_player.play(self._persistence_play_steps(), interval=650)

    def _persistence_play_steps(self):
        return [
            (0, self._snapshot_graph),
            (0, self._clear_graph_for_restore),
            (0, self._restore_graph),
        ]

    def _snapshot_graph(self):
        if not self._canvas.graph.nodes():
            self._set_persist_note("画布为空：再点一次「播放」会恢复上一次快照。")
            return
        self._persist_data = self._canvas.to_dict()
        graph = self._persist_data.get("graph") or {}
        self._set_persist_note(
            f"已写入内存快照：{len(graph.get('nodes') or [])} 节点 / "
            f"{len(graph.get('edges') or [])} 连线。"
        )

    def _clear_graph_for_restore(self):
        self._train_chain = []
        self._canvas.graph.clear()
        self._canvas.fit_view()
        self._set_persist_note("画布已清空：节点与连线全部消失。")

    def _restore_graph(self):
        if self._persist_data is None:
            return
        self._canvas.from_dict(self._persist_data)
        self._rebind_nodes()
        self._prefill_training_state()
        self._canvas.fit_view()
        self._set_persist_note(
            f"已恢复：{len(self._nodes)} 节点 / "
            f"{len(self._canvas.graph.edges())} 连线（含属性与视图）。"
        )

    def _set_persist_note(self, text):
        if self._persist_note is not None:
            self._persist_note.setText(text)

    # ================================================================ 训练控制
    def _run_training(self):
        """重播训练模拟（先复位，再按脚本推进）。"""
        self._stop_playbacks()
        self._ensure_pipeline_complete()
        if (
            self._build_training_steps is None
            or self._train_player is None
            or not self._train_chain
        ):
            return
        self._canvas.execution().reset()
        self._reset_metrics()
        self._canvas.execution().set_path(self._train_chain)
        self._set_train_note("训练中：每个节点 45% → 100% 进度后标记完成。")
        # 首节点同步起步：点完按钮立刻能看到 running（不等第一个定时器）
        self._canvas.execution().start(self._train_chain[0])
        self._train_player.play(self._build_training_steps(), interval=45)

    def _reset_training(self):
        """停止模拟并把节点 / 指标复位到空闲态。"""
        self._stop_playbacks()
        self._ensure_pipeline_complete()
        self._canvas.execution().reset()
        self._reset_metrics()
        self._set_train_note("已重置：节点回到 idle，进度与耗时清空。")

    def _simulate_failure(self):
        """演示 error 状态：danger 描边 + 错误图标 + tooltip。"""
        self._stop_playbacks()
        self._ensure_pipeline_complete()
        loss = self._nodes.get("lm_loss")
        if loss is None:
            return
        self._canvas.execution().reset()
        self._canvas.execution().fail(loss, "模拟错误：loss = NaN（仅 UI 演示）")
        self._set_metric("loss", "NaN")
        self._set_train_note("已把「LM Loss」标记为 error，悬停节点可看错误信息。")

    def _prefill_training_state(self):
        """预填一轮完成态：状态描边 / 耗时徽标 / 进度条立即可见。"""
        for index, node in enumerate(self._train_chain):
            node.set_elapsed_ms(12 + index * 6)
            node.set_progress(1.0)
            node.set_status("done")
        self._set_metric("epoch", f"1 / {_EPOCHS}")
        self._set_metric("loss", _LOSS[0])
        self._set_metric("acc", _ACC[0])
        self._set_metric("lr", _LR[0])

    def _training_finished(self):
        self._set_train_note(f"训练完成：{_EPOCHS} / {_EPOCHS} epoch（纯 UI 模拟）。")

    def _set_metric(self, key, value):
        label = self._metric_labels.get(key)
        if label is not None:
            label.setText(f"{self.METRIC_TITLES[key]}  {value}")

    def _reset_metrics(self):
        for key in self.METRIC_TITLES:
            self._set_metric(key, "—")

    def _set_train_note(self, text):
        if self._train_note is not None:
            self._train_note.setText(text)

    # ================================================================ 节点菜单
    def _rename_node(self, node_id):
        """右键「重命名」：非模态小对话框改标题（示例接法）。"""
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

        def apply_title() -> None:
            text = edit.text().strip()
            if text:
                node.set_title(text)
            dialog.close()

        dialog.rightButtonClicked.connect(apply_title)
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

    # ================================================================ 页面装配
    def _addDemoContent(self, main_layout):
        self._addInfoText(
            "以多模态 LLM 平台为例（仅 UI）：右键空白创建节点、拖引脚连线、"
            "拖节点 / 框选 / Ctrl 多选、Delete 删除、滚轮缩放、右键节点或连线"
            "打开菜单。每节都能点「</> 代码」查看公开 API，点「播放」看脚本演示。",
            main_layout,
        )
        self._demoPipeline(main_layout)
        self._demoTraining(main_layout)
        self._demoDistributed(main_layout)
        self._demoNodeBody(main_layout)
        self._demoPersistence(main_layout)
