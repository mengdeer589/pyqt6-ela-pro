"""蓝图画布测试（ElaBlueprintCanvas：交互 / 坐标 / 序列化 / 执行指示）。

交互模拟采用直接 ``QApplication.sendEvent`` 投递到目标控件的方式：
offscreen 平台下 QTest 的命中路由不可靠（move 事件不落到子控件），
sendEvent 目标明确且与 eventFilter 分发链等价。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.blueprint import (
    ElaBlueprintCanvas,
    ElaBlueprintNode,
    ElaNodeCreationMenu,
    register_node_type,
)


@pytest.fixture
def canvas(qapp, clean_registry):
    register_node_type(
        "start", "开始", "流程", outputs=[{"id": "out", "data_type": "exec"}]
    )
    register_node_type(
        "proc",
        "处理",
        "处理",
        inputs=[{"id": "in", "data_type": "exec", "multi": True}],
        outputs=[{"id": "out", "data_type": "exec"}],
    )
    register_node_type(
        "end", "结束", "输出", inputs=[{"id": "in", "data_type": "exec", "multi": True}]
    )
    c = ElaBlueprintCanvas()
    c.resize(900, 600)
    c.show()
    qapp.processEvents()
    yield c
    if c.isVisible():
        c.close()
    c.deleteLater()
    qapp.processEvents()


def mouse_event(t, pos, button, buttons):
    return QMouseEvent(
        t, QPointF(pos), QPointF(pos), button, buttons, Qt.KeyboardModifier.NoModifier
    )


def send_to(widget, t, pos, button, buttons):
    QApplication.instance().sendEvent(widget, mouse_event(t, pos, button, buttons))


class TestCreation:
    def test_add_node_at_creates_widget(self, canvas):
        node = canvas.add_node_at("start", QPointF(60, 120))
        assert canvas.node_widget(node.id) is not None
        assert node.pos == QPointF(60, 120)

    def test_add_node_uses_existing(self, canvas):
        node = ElaBlueprintNode("start", "自定义")
        node.add_output("out", "输出", "exec")
        canvas.add_node(node, QPointF(10, 10))
        assert canvas.graph.node(node.id) is node

    def test_owner_scope(self, qapp, clean_registry):
        register_node_type("only_plug", "仅插件", "插件", owner="plug")
        c = ElaBlueprintCanvas(owner="plug")
        node = c.add_node_at("only_plug", QPointF(0, 0))
        assert node is not None
        c.deleteLater()


class TestCoordinates:
    def test_scene_view_roundtrip(self, canvas):
        canvas._zoom = 1.5
        canvas._offset = QPointF(30, -20)
        pt = QPointF(123.0, 456.0)
        assert canvas.view_to_scene(canvas.scene_to_view(pt)) == pt

    def test_pin_scene_pos(self, canvas):
        node = canvas.add_node_at("start", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        pin = node.outputs[0]
        expected = node.pos + widget.pin_logical_center(pin)
        assert canvas.pin_scene_pos(node.id, pin.id, pin.direction) == expected


class TestInteraction:
    def test_drag_node_moves_and_emits(self, canvas):
        node = canvas.add_node_at("start", QPointF(100, 150))
        widget = canvas.node_widget(node.id)
        moved = []
        canvas.node_moved.connect(lambda nid, pos: moved.append((nid, pos)))
        center = widget.rect().center()
        send_to(
            widget,
            QEvent.Type.MouseButtonPress,
            center,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        send_to(
            widget,
            QEvent.Type.MouseMove,
            center + QPoint(60, 40),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
        send_to(
            widget,
            QEvent.Type.MouseButtonRelease,
            center + QPoint(60, 40),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
        assert node.pos == QPointF(160, 190)
        assert moved and moved[0][0] == node.id

    def test_wire_drag_creates_edge(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 150))
        n2 = canvas.add_node_at("proc", QPointF(400, 150))
        h1 = canvas.node_widget(n1.id).pin_widget("out", None)
        h2 = canvas.node_widget(n2.id).pin_widget("in", None)
        p1, p2 = h1.rect().center(), h2.rect().center()
        send_to(
            h1,
            QEvent.Type.MouseButtonPress,
            p1,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        send_to(
            h2, QEvent.Type.MouseMove, p2, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton
        )
        send_to(
            h2,
            QEvent.Type.MouseButtonRelease,
            p2,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
        assert len(canvas.graph.edges()) == 1
        edge = canvas.graph.edges()[0]
        assert edge.from_node == n1.id and edge.to_node == n2.id

    def test_wire_drag_incompatible_type_no_edge(self, canvas):
        register_node_type(
            "img_src", "图像源", "输入", outputs=[{"id": "img", "data_type": "image"}]
        )
        register_node_type(
            "tensor_sink",
            "张量接收",
            "输出",
            inputs=[{"id": "t", "data_type": "tensor"}],
        )
        a = canvas.add_node_at("img_src", QPointF(100, 150))
        b = canvas.add_node_at("tensor_sink", QPointF(400, 150))
        h1 = canvas.node_widget(a.id).pin_widget("img", None)
        h2 = canvas.node_widget(b.id).pin_widget("t", None)
        p1, p2 = h1.rect().center(), h2.rect().center()
        send_to(
            h1,
            QEvent.Type.MouseButtonPress,
            p1,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        send_to(
            h2, QEvent.Type.MouseMove, p2, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton
        )
        send_to(
            h2,
            QEvent.Type.MouseButtonRelease,
            p2,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
        assert len(canvas.graph.edges()) == 0
        # 拖到无兼容引脚会弹出创建菜单（Popup 自动 grab 鼠标），关闭并
        # 让其销毁，避免后续测试的事件被弹出窗口拦截
        for menu in canvas.findChildren(ElaNodeCreationMenu):
            menu.close()
        QApplication.instance().processEvents()

    def test_box_select(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        canvas.add_node_at("proc", QPointF(500, 400))
        vp = canvas._viewport
        # 框住 n1 的区域（视口坐标 = 场景坐标，zoom=1, offset=0）
        start, end = QPoint(80, 80), QPoint(320, 260)
        send_to(
            vp,
            QEvent.Type.MouseButtonPress,
            start,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        send_to(
            vp,
            QEvent.Type.MouseMove,
            end,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
        send_to(
            vp,
            QEvent.Type.MouseButtonRelease,
            end,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
        assert canvas.selected_nodes() == [n1.id]

    def test_delete_selection_removes_nodes_and_edges(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        n2 = canvas.add_node_at("proc", QPointF(400, 100))
        canvas.graph.add_edge(n1.id, "out", n2.id, "in")
        canvas.select_nodes([n1.id])
        canvas.delete_selection()
        assert canvas.graph.node(n1.id) is None
        assert len(canvas.graph.edges()) == 0

    def test_wheel_zoom_around_cursor(self, canvas):
        canvas._viewport.setFocus()
        canvas._zoom_settle.stop()

        def wheel(pos, delta):
            ev = QWheelEvent(
                QPointF(pos),
                QPointF(pos),
                QPoint(0, 0),
                QPoint(0, delta),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            )
            QApplication.instance().sendEvent(canvas._viewport, ev)

        wheel(QPoint(450, 300), -120)
        assert canvas.zoom() < 1.0
        wheel(QPoint(450, 300), 240)
        assert canvas.zoom() > 1.0

    def test_set_zoom_clamped(self, canvas):
        canvas.set_zoom(99.0)
        assert canvas.zoom() == 2.5
        canvas.set_zoom(0.01)
        assert canvas.zoom() == 0.25

    def test_duplicate_node(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        canvas._duplicate_node(n1.id)
        copies = [n for n in canvas.graph.nodes() if n.id != n1.id]
        assert len(copies) == 1
        assert copies[0].pos == n1.pos + QPointF(24.0, 24.0)


class TestSerialization:
    def test_roundtrip_preserves_graph_and_view(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        n2 = canvas.add_node_at("proc", QPointF(400, 100))
        canvas.graph.add_edge(n1.id, "out", n2.id, "in")
        canvas.set_zoom(1.7)
        canvas._offset = QPointF(25.0, -40.0)
        data = canvas.to_dict()

        c2 = ElaBlueprintCanvas()
        c2.from_dict(data)
        assert len(c2.graph.nodes()) == 2
        assert len(c2.graph.edges()) == 1
        assert c2.zoom() == pytest.approx(1.7)
        assert c2._offset == QPointF(25.0, -40.0)
        assert c2.graph.nodes()[0].pos == QPointF(100, 100)
        c2.deleteLater()

    def test_fit_view_empty(self, canvas):
        canvas.fit_view()
        assert canvas.zoom() == 1.0
        assert canvas._offset == QPointF(0.0, 0.0)

    def test_fit_view_with_nodes(self, canvas):
        canvas.add_node_at("start", QPointF(100, 100))
        canvas.add_node_at("end", QPointF(600, 400))
        canvas.fit_view()
        assert 0.25 <= canvas.zoom() <= 2.5


class TestExecutionIntegration:
    def test_run_sequence_updates_status(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        n2 = canvas.add_node_at("proc", QPointF(400, 100))
        canvas.graph.add_edge(n1.id, "out", n2.id, "in")
        ex = canvas.execution()
        ex.set_path([n1.id, n2.id])
        assert ex.path_edge_ids() == [canvas.graph.edges()[0].id]
        ex.start(n1.id)
        assert n1.status == "running"
        ex.finish(n1.id, 12.5)
        assert n1.status == "done" and n1.elapsed_ms == 12.5
        ex.fail(n2.id, "出错")
        assert n2.status == "error" and n2.error_message == "出错"
        ex.reset()
        assert all(n.status == "idle" for n in canvas.graph.nodes())
        assert ex.path_edge_ids() == []

    def test_finished_signal(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        n2 = canvas.add_node_at("proc", QPointF(400, 100))
        ex = canvas.execution()
        done = []
        ex.finished.connect(lambda: done.append(True))
        ex.start(n1.id)
        ex.start(n2.id)
        assert not done
        ex.finish(n1.id, 1.0)
        assert not done
        ex.finish(n2.id, 2.0)
        assert done


class TestRendering:
    def test_canvas_renders_with_nodes(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        n2 = canvas.add_node_at("proc", QPointF(400, 100))
        canvas.graph.add_edge(n1.id, "out", n2.id, "in")
        canvas.select_nodes([n1.id])
        pm = canvas.grab()
        assert not pm.isNull()
        assert pm.width() == 900 and pm.height() == 600

    def test_node_widget_paints_content(self, canvas):
        node = canvas.add_node_at("start", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        pm = widget.grab()
        assert not pm.isNull()

    def test_theme_switch_no_crash(self, canvas):
        canvas.add_node_at("start", QPointF(100, 100))
        canvas._retheme()
        pm = canvas.grab()
        assert not pm.isNull()
