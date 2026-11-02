"""BlueprintPage（多模态 LLM 平台示例页）回归。

页面按五节组织，每节标题行都带「</> 代码」与「播放」按钮：

- 平台全景：50 节点 / 70 连线，训练链覆盖 16 条边；
- 训练模拟：``set_path`` 点亮路径、首节点 running、进度 / 指标推进、重置清空；
- 分布式编排：13 节点 / 14 连线，扇出 → 归约 → 优化；
- 节点体与编辑交互：body_builder 控件、网格吸附开关、复制 / 全选；
- 保存与恢复：``to_dict`` / ``from_dict`` 往返。
"""

from __future__ import annotations

import inspect

from PyQt6.QtCore import QRectF
from PyQt6ElaWidgetTools import ElaLineEdit, ElaToggleSwitch

from pyqt6_ela_pro import ElaButton
from pyqt6_ela_pro.example.blueprint_page import BlueprintPage

_SECTION_METHODS = (
    "_demoPipeline",
    "_demoTraining",
    "_demoDistributed",
    "_demoNodeBody",
    "_demoPersistence",
)
_PLAY_METHODS = (
    "_playPipeline",
    "_run_training",
    "_playDistributed",
    "_playEditing",
    "_playPersistence",
)


class TestSections:
    def test_every_section_has_code_button(self, qapp, make):
        page = make(BlueprintPage)
        buttons = [b for b in page.findChildren(ElaButton) if b.text() == "</> 代码"]
        assert len(buttons) == len(_SECTION_METHODS), (
            "每节都必须有「</> 代码」按钮（用户报过没有代码展示）"
        )

    def test_every_section_has_play_button(self, qapp, make):
        page = make(BlueprintPage)
        buttons = [b for b in page.findChildren(ElaButton) if b.text() == "播放"]
        assert len(buttons) == len(_PLAY_METHODS), "每节都必须有「播放」按钮"

    def test_demo_methods_show_their_own_api(self, qapp, make):
        page = make(BlueprintPage)
        sources = {
            name: inspect.getsource(getattr(page, name)) for name in _SECTION_METHODS
        }
        assert "create_node" in sources["_demoPipeline"]
        assert "register_node_type" in sources["_demoPipeline"]
        assert "set_progress" in sources["_demoTraining"]
        assert "execution().start" in sources["_demoTraining"]
        assert "create_node" in sources["_demoDistributed"]
        assert ".connect(" in sources["_demoDistributed"]
        assert "set_grid_snap" in sources["_demoNodeBody"]
        assert "duplicate_selection" in sources["_demoNodeBody"]
        assert "to_dict" in sources["_demoPersistence"]
        assert "from_dict" in sources["_demoPersistence"]

    def test_play_methods_are_callable(self, qapp, make):
        page = make(BlueprintPage)
        for name in _PLAY_METHODS:
            assert callable(getattr(page, name)), f"{name} 必须可被「播放」按钮调用"


class TestPipeline:
    def test_pipeline_nodes_and_edges(self, qapp, make):
        page = make(BlueprintPage)
        assert len(page._canvas.graph.nodes()) == 50
        assert len(page._canvas.graph.edges()) == 70
        assert len(page._nodes) == 50
        # 关键节点都在（标题可在 create_node 时覆盖）
        assert set(page._nodes) >= {
            "text",
            "tokenizer",
            "text_emb",
            "block1",
            "lm_head",
            "lm_loss",
            "total_loss",
            "optim",
        }

    def test_fusion_receives_three_modalities(self, qapp, make):
        page = make(BlueprintPage)
        graph = page._canvas.graph
        fusion = page._nodes["fusion"]
        sources = {
            edge.from_node for edge in graph.edges() if edge.to_node == fusion.id
        }
        assert sources == {
            page._nodes["text_emb"].id,
            page._nodes["vision_enc"].id,
            page._nodes["audio_enc"].id,
        }

    def test_router_fans_out_to_experts(self, qapp, make):
        page = make(BlueprintPage)
        graph = page._canvas.graph
        router = page._nodes["router"]
        targets = {
            edge.to_node for edge in graph.edges() if edge.from_node == router.id
        }
        assert targets == {page._nodes["expert_a"].id, page._nodes["expert_b"].id}

    def test_node_bodies_are_interactive(self, qapp, make):
        page = make(BlueprintPage)
        text = page._nodes["text"]
        optim = page._nodes["optim"]
        assert text.properties["size"] == "118M"
        assert optim.properties["optimizer"] == 0
        assert optim.properties["lr"] == "3e-4"

    def test_edge_labels_present_and_layout(self, qapp, make):
        page = make(BlueprintPage)
        labels = [edge.label for edge in page._canvas.graph.edges()]
        assert "hidden [B, 512]" in labels and "corpus" in labels
        assert "accum 4" in labels and "每 2 epoch" in labels
        edge = next(edge for edge in page._canvas.graph.edges() if edge.label)
        assert not page._canvas.edge_widget(edge).label_rect().isNull()

    def test_tree_layout_spreads_branches_without_overlap(self, qapp, make):
        page = make(BlueprintPage)
        nodes = page._canvas.graph.nodes()
        # 树形布局：分支自由展开，不是几行等距网格
        assert len({round(node.pos.y()) for node in nodes}) > 15
        rects = [QRectF(node.pos, node.size) for node in nodes]
        for index, first in enumerate(rects):
            for second in rects[index + 1 :]:
                overlap = first.intersected(second)
                assert overlap.width() <= 1 or overlap.height() <= 1

    def test_edges_stay_between_adjacent_columns(self, qapp, make):
        page = make(BlueprintPage)
        graph = page._canvas.graph

        def column(node):
            return round((node.pos.x() - 20) / 205)

        for edge in graph.edges():
            source = graph.node(edge.from_node)
            target = graph.node(edge.to_node)
            assert abs(column(source) - column(target)) <= 1


class TestDistributed:
    def test_topology_fan_out_and_fan_in(self, qapp, make):
        page = make(BlueprintPage)
        graph = page._dist_canvas.graph
        assert len(graph.nodes()) == 13
        assert len(graph.edges()) == 14
        shard = next(node for node in graph.nodes() if node.type_name == "dt_shard")
        reduce_node = next(
            node for node in graph.nodes() if node.type_name == "dt_reduce"
        )
        assert len([e for e in graph.edges() if e.from_node == shard.id]) == 3
        assert len([e for e in graph.edges() if e.to_node == reduce_node.id]) == 3

    def test_labels(self, qapp, make):
        page = make(BlueprintPage)
        labels = [edge.label for edge in page._dist_canvas.graph.edges()]
        assert "global batch 96" in labels
        assert "all-reduce" in labels
        assert "accum 4" in labels


class TestTrainingSimulation:
    def test_run_lights_all_edges_and_first_node_running(self, qapp, make):
        page = make(BlueprintPage)
        page._run_training()
        try:
            # 分支 DAG：16 条边全部在路径上（不是只认相邻节点对）
            assert len(page._canvas.execution().path_edge_ids()) == 16
            qapp.processEvents()
            first = page._train_chain[0]
            assert first.title == "文本语料"
            assert first.status == "running"
        finally:
            page._reset_training()
        assert all(n.status == "idle" for n in page._canvas.graph.nodes())
        assert all(n.progress is None for n in page._canvas.graph.nodes())

    def test_reset_clears_metrics_and_timer(self, qapp, make):
        page = make(BlueprintPage)
        page._run_training()
        assert page._train_player.running
        page._reset_training()
        assert not page._train_player.running
        assert "—" in page._metric_labels["loss"].text()

    def test_failure_marks_error_node(self, qapp, make):
        page = make(BlueprintPage)
        page._simulate_failure()
        node = page._nodes["lm_loss"]
        assert node.status == "error"
        assert "NaN" in node.error_message
        page._reset_training()


class TestEditingDemo:
    def test_body_canvas_has_graph(self, qapp, make):
        page = make(BlueprintPage)
        assert len(page._body_canvas.graph.nodes()) == 3
        assert len(page._body_canvas.graph.edges()) == 2
        assert [edge.label for edge in page._body_edges] == [
            "batch 128",
            "hidden [B, 512]",
        ]

    def test_snap_switch_drives_canvas(self, qapp, make):
        page = make(BlueprintPage)
        switches = page.findChildren(ElaToggleSwitch)
        assert switches, "编辑交互节应有网格吸附开关"
        switches[0].setIsToggled(True)
        qapp.processEvents()
        assert page._body_canvas.grid_snap()

    def test_duplicate_and_select_all(self, qapp, make):
        page = make(BlueprintPage)
        canvas = page._body_canvas
        canvas.select_all()
        assert len(canvas.selected_nodes()) == 3
        canvas.duplicate_selection()
        assert len(canvas.graph.nodes()) == 6
        assert len(canvas.selected_nodes()) == 3


class TestPlayback:
    def test_pipeline_play_rebuilds_full_graph(self, qapp, make):
        page = make(BlueprintPage)
        page._playPipeline()
        page._section_player.play_now(page._pipeline_play_steps())
        assert len(page._canvas.graph.nodes()) == 50
        assert len(page._canvas.graph.edges()) == 70
        assert len(page._train_chain) == 16
        assert "重建完成" in page._train_note.text()

    def test_distributed_play_settles_all_nodes(self, qapp, make):
        page = make(BlueprintPage)
        page._playDistributed()
        page._section_player.play_now(page._distributed_play_steps())
        assert all(node.status == "done" for node in page._dist_chain)
        assert "回放完成" in page._dist_note.text()

    def test_editing_play_sets_snap_and_labels(self, qapp, make):
        page = make(BlueprintPage)
        page._playEditing()
        page._section_player.play_now(page._editing_play_steps())
        assert page._body_canvas.grid_snap()
        assert [edge.label for edge in page._body_edges] == [
            "batch 128",
            "hidden [B, 512]",
        ]

    def test_persistence_play_roundtrips_graph(self, qapp, make):
        page = make(BlueprintPage)
        page._playPersistence()
        page._section_player.play_now(page._persistence_play_steps())
        assert len(page._nodes) == 50
        assert len(page._canvas.graph.edges()) == 70
        assert len(page._train_chain) == 16
        assert "已恢复" in page._persist_note.text()

    def test_stop_playbacks_stops_running_scripts(self, qapp, make):
        page = make(BlueprintPage)
        page._playDistributed()
        assert page._section_player.running
        page._stop_playbacks()
        assert not page._section_player.running

    def test_play_step_counts(self, qapp, make):
        page = make(BlueprintPage)
        assert len(page._pipeline_play_steps()) == 50 + 70 + 1
        assert len(page._distributed_play_steps()) == 13 * 4 + 1
        assert len(page._editing_play_steps()) == 8
        assert len(page._persistence_play_steps()) == 3

    def test_training_completes_interrupted_rebuild(self, qapp, make):
        page = make(BlueprintPage)
        page._playPipeline()
        page._run_training()  # 打断逐节点重建：必须先把整张图补完
        try:
            assert len(page._canvas.graph.nodes()) == 50
            assert len(page._canvas.graph.edges()) == 70
            assert len(page._train_chain) == 16
            assert page._train_player.running
        finally:
            page._reset_training()


class TestContextMenuHandlers:
    def test_rename_updates_title(self, qapp, make):
        page = make(BlueprintPage)
        node = page._nodes["block1"]
        page._rename_node(node.id)
        dialog = page._rename_dialog
        assert dialog is not None
        edit = dialog.findChild(ElaLineEdit)
        assert edit is not None
        edit.setText("新标题")
        dialog.rightButtonClicked.emit()
        qapp.processEvents()
        assert node.title == "新标题"
        dialog.close()

    def test_rename_ignores_blank_text(self, qapp, make):
        page = make(BlueprintPage)
        node = page._nodes["block1"]
        old = node.title
        page._rename_node(node.id)
        edit = page._rename_dialog.findChild(ElaLineEdit)
        edit.setText("   ")
        page._rename_dialog.rightButtonClicked.emit()
        qapp.processEvents()
        assert node.title == old
        page._rename_dialog.close()

    def test_properties_handler_runs(self, qapp, make):
        page = make(BlueprintPage)
        page._show_node_properties(page._nodes["block1"].id)  # 不得抛（信息条反馈）


class TestSerialization:
    def test_roundtrip_keeps_graph(self, qapp, make):
        page = make(BlueprintPage)
        data = page._canvas.to_dict()
        assert len(data["graph"]["nodes"]) == 50
        assert len(data["graph"]["edges"]) == 70
        page._canvas.from_dict(data)
        assert len(page._canvas.graph.nodes()) == 50
        assert len(page._canvas.graph.edges()) == 70

    def test_rebind_after_from_dict(self, qapp, make):
        page = make(BlueprintPage)
        old = page._nodes["lm_loss"]
        page._canvas.from_dict(page._canvas.to_dict())
        page._rebind_nodes()
        assert page._nodes["lm_loss"] is page._canvas.graph.node(old.id)
        assert page._train_chain[0] is page._nodes["text"]
