"""BlueprintPage（节点图编辑器示例页）回归。

覆盖 2026-10 审计修复后的示例行为：

- 执行模拟两阶段（先 running 再 done / error）—— 原先 start+finish 在
  同一回调里，running / 旋转圈永远不可见；
- ``set_path`` 覆盖分支 DAG 的边（演示图 5 条边全部流动）；
- 「重置状态 / 清空画布」停止在途执行链（原先只复位状态，链条继续跑）；
- 右键菜单「重命名 / 属性」有宿主实现（原先点了没反应）。
"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaLineEdit

from pyqt6_ela_pro.example.blueprint_page import BlueprintPage


class TestSimulation:
    def test_demo_scene_and_running_visible(self, qapp, make):
        page = make(BlueprintPage)
        canvas = page._canvas
        assert len(canvas.graph.nodes()) == 5
        page._run_simulation()
        try:
            first = page._sim_chain[0]
            node = canvas.graph.node(first)
            assert node.status == "running", (
                "首节点应立即进入 running（否则运行态在重绘前就被 finish 覆盖）"
            )
            # 分支 DAG：5 条边全部高亮（旧实现只认相邻节点对，只亮 3 条）
            assert len(canvas.execution().path_edge_ids()) == 5
        finally:
            page._reset_states()
        assert all(n.status == "idle" for n in canvas.graph.nodes())

    def test_reset_stops_pending_chain(self, qapp, make):
        page = make(BlueprintPage)
        page._run_simulation()
        assert page._sim_timer is not None
        page._reset_states()
        assert page._sim_timer is None

    def test_clear_canvas_stops_chain(self, qapp, make):
        page = make(BlueprintPage)
        page._run_simulation()
        page._clear_canvas()
        assert page._sim_timer is None
        assert page._canvas.graph.nodes() == []

    def test_relaunch_does_not_stack_chains(self, qapp, make):
        page = make(BlueprintPage)
        page._run_simulation()
        first_timer = page._sim_timer
        page._run_simulation()
        assert page._sim_timer is not first_timer
        page._reset_states()


class TestContextMenuHandlers:
    def test_rename_updates_title(self, qapp, make):
        page = make(BlueprintPage)
        node = page._canvas.graph.nodes()[0]
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
        node = page._canvas.graph.nodes()[0]
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
        node = page._canvas.graph.nodes()[0]
        page._show_node_properties(node.id)  # 不得抛（信息条反馈）
