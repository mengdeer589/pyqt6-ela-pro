"""蓝图编辑能力：节点进度、网格吸附、键盘操作、连线右键菜单。

这些是「神经网络训练流水线」示例页所依赖的公开 API 契约：

- ``ElaBlueprintNode.set_progress`` 只重绘不重排（进度条不参与尺寸计算）；
- ``ElaBlueprintCanvas.set_grid_snap`` 吸附**拖动位移**（多选保持相对布局）；
- 方向键微调 / Ctrl+A / Ctrl+D / Esc / Delete；
- 右键连线弹 ``ElaEdgeContextMenu``，删除走 ``graph.remove_edge``。
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QPointF, QSizeF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.blueprint import (
    ElaBlueprintCanvas,
    ElaBlueprintNode,
    ElaEdgeContextMenu,
    register_node_type,
)
from pyqt6_ela_pro.blueprint.node_widget import ElaNodeWidget
from pyqt6_ela_pro.blueprint import canvas as canvas_module

_LEFT = Qt.MouseButton.LeftButton
_RIGHT = Qt.MouseButton.RightButton
_NONE = Qt.MouseButton.NoButton
_NO_MOD = Qt.KeyboardModifier.NoModifier


def _mouse(kind, pos, button=_LEFT, buttons=_NONE):
    return QMouseEvent(kind, QPointF(pos), QPointF(pos), button, buttons, _NO_MOD)


def _key(key, mods=_NO_MOD):
    return QKeyEvent(QEvent.Type.KeyPress, key, mods)


def _send(widget, event):
    QApplication.instance().sendEvent(widget, event)


def _make_canvas(make) -> ElaBlueprintCanvas:
    register_node_type(
        "edit_in",
        "输入",
        "测试",
        outputs=[{"id": "out", "name": "出", "data_type": "any"}],
    )
    register_node_type(
        "edit_out",
        "输出",
        "测试",
        inputs=[{"id": "in", "name": "入", "data_type": "any"}],
    )
    canvas = make(ElaBlueprintCanvas)
    canvas.resize(900, 600)
    canvas.show()
    return canvas


class TestNodeProgress:
    def test_progress_clamped_and_signal(self):
        node = ElaBlueprintNode("t", "T")
        seen = []
        node.progress_changed.connect(lambda value: seen.append(value))
        node.set_progress(0.4)
        node.set_progress(2.0)
        assert node.progress == 1.0
        node.set_progress(-1.0)
        assert node.progress == 0.0
        node.set_progress(None)
        assert node.progress is None
        assert seen == [0.4, 1.0, 0.0, None]

    def test_progress_does_not_relayout(self, make):
        canvas = _make_canvas(make)
        node = canvas.create_node("edit_in", QPointF(100, 100))
        before = (node.size.width(), node.size.height())
        node.set_progress(0.5)
        assert (node.size.width(), node.size.height()) == before

    def test_progress_bar_is_painted(self, make):
        node = ElaBlueprintNode("t", "T")
        widget = make(ElaNodeWidget, node)
        widget.apply_view(QPointF(0, 0), 1.0)
        empty = QPixmap(widget.size())
        widget.render(empty)
        node.set_progress(1.0)
        full = QPixmap(widget.size())
        widget.render(full)
        # 节点底部（进度条所在的 3px 带）必须真的变了；上半部分不变
        y = widget.height() - 5
        assert empty.toImage().pixelColor(60, y) != full.toImage().pixelColor(60, y)
        assert empty.toImage().pixelColor(60, 20) == full.toImage().pixelColor(60, 20)

    def test_execution_reset_clears_progress(self, make):
        canvas = _make_canvas(make)
        node = canvas.create_node("edit_in", QPointF(100, 100))
        canvas.execution().start(node.id)
        node.set_progress(0.7)
        canvas.execution().reset()
        assert node.progress is None


class TestNodeTitleElide:
    def test_long_title_is_elided_before_status_badge(self, make):
        node = ElaBlueprintNode("t", "超级长的节点标题" * 8)
        node.set_status("done")
        node.set_elapsed_ms(123)
        widget = make(ElaNodeWidget, node)
        widget.apply_view(QPointF(0, 0), 1.0)
        drawn = widget._title_draw_text()
        assert drawn != node.title
        assert len(drawn) < len(node.title)
        # idle（无耗时徽标）同样给右侧状态图标留位
        node.set_status("idle")
        node.size = QSizeF(160.0, 80.0)
        assert widget._title_draw_text() != node.title


class TestGridSnap:
    def test_drag_snaps_delta_to_grid(self, make):
        canvas = _make_canvas(make)
        node = canvas.create_node("edit_in", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        canvas.set_grid_snap(True)
        center = widget.rect().center()
        _send(widget, _mouse(QEvent.Type.MouseButtonPress, center, _LEFT, _LEFT))
        _send(
            widget,
            _mouse(
                QEvent.Type.MouseMove,
                center + QPoint(30, 30),
                _NONE,
                _LEFT,
            ),
        )
        _send(
            widget,
            _mouse(
                QEvent.Type.MouseButtonRelease,
                center + QPoint(30, 30),
                _LEFT,
                _NONE,
            ),
        )
        # 间距 24：30px 的位移吸附到 24px
        assert node.pos == QPointF(124, 124)

    def test_multi_selection_keeps_relative_layout(self, make):
        canvas = _make_canvas(make)
        a = canvas.create_node("edit_in", QPointF(100, 100))
        b = canvas.create_node("edit_out", QPointF(300, 100))
        canvas.select_nodes([a.id, b.id])
        canvas.set_grid_snap(True)
        widget = canvas.node_widget(a.id)
        center = widget.rect().center()
        _send(widget, _mouse(QEvent.Type.MouseButtonPress, center, _LEFT, _LEFT))
        _send(
            widget,
            _mouse(QEvent.Type.MouseMove, center + QPoint(30, 0), _NONE, _LEFT),
        )
        _send(
            widget,
            _mouse(
                QEvent.Type.MouseButtonRelease, center + QPoint(30, 0), _LEFT, _NONE
            ),
        )
        assert a.pos == QPointF(124, 100)
        assert b.pos == QPointF(324, 100)

    def test_grid_step_follows_zoom(self, make):
        canvas = _make_canvas(make)
        canvas.set_grid_step(24)
        assert canvas.grid_step() == 24
        canvas._zoom = 0.5
        assert canvas.grid_step() == 48


class TestKeyboardEditing:
    def test_arrow_nudge_and_shift_step(self, make):
        canvas = _make_canvas(make)
        node = canvas.create_node("edit_in", QPointF(100, 100))
        canvas.select_nodes([node.id])
        canvas.keyPressEvent(_key(Qt.Key.Key_Right))
        assert node.pos == QPointF(101, 100)
        canvas.keyPressEvent(_key(Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier))
        assert node.pos == QPointF(101, 110)

    def test_ctrl_a_selects_all(self, make):
        canvas = _make_canvas(make)
        canvas.create_node("edit_in", QPointF(100, 100))
        canvas.create_node("edit_out", QPointF(300, 100))
        canvas.keyPressEvent(_key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier))
        assert len(canvas.selected_nodes()) == 2

    def test_ctrl_d_duplicates_selection(self, make):
        canvas = _make_canvas(make)
        node = canvas.create_node("edit_in", QPointF(100, 100))
        canvas.select_nodes([node.id])
        canvas.keyPressEvent(_key(Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier))
        assert len(canvas.graph.nodes()) == 2
        copies = canvas.selected_nodes()
        assert len(copies) == 1 and copies[0].id != node.id
        assert copies[0].pos == QPointF(124, 124)

    def test_escape_clears_selection(self, make):
        canvas = _make_canvas(make)
        node = canvas.create_node("edit_in", QPointF(100, 100))
        canvas.select_nodes([node.id])
        canvas.keyPressEvent(_key(Qt.Key.Key_Escape))
        assert canvas.selected_nodes() == []


class TestEdgeContextMenu:
    def test_right_click_selects_edge_and_opens_menu(self, make, monkeypatch):
        canvas = _make_canvas(make)
        a = canvas.create_node("edit_in", QPointF(100, 100))
        b = canvas.create_node("edit_out", QPointF(400, 300))
        edge = canvas.graph.add_edge(a.id, "out", b.id, "in")
        assert edge is not None

        monkeypatch.setattr(
            canvas_module,
            "execElaMenu",
            lambda menu, pos: menu.actions()[0].trigger(),
        )
        midpoint = canvas.edge_widget(edge.id).path().pointAtPercent(0.5)
        _send(
            canvas,
            _mouse(
                QEvent.Type.MouseButtonPress,
                midpoint.toPoint(),
                _RIGHT,
                _RIGHT,
            ),
        )
        _send(
            canvas,
            _mouse(
                QEvent.Type.MouseButtonRelease,
                midpoint.toPoint(),
                _RIGHT,
                _NONE,
            ),
        )
        assert canvas.graph.edge(edge.id) is None
        assert canvas.selected_edges() == []

    def test_edge_menu_emits_edge_id(self):
        menu = ElaEdgeContextMenu("edge-1")
        seen = []
        menu.delete_requested.connect(lambda edge_id: seen.append(edge_id))
        menu.actions()[0].trigger()
        assert seen == ["edge-1"]
        menu.deleteLater()
