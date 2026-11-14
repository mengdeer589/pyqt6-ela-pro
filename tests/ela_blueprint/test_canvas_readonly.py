"""蓝图画布只读模式：禁编辑，保留平移 / 缩放 / 选中 / 双击激活。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.blueprint import ElaBlueprintCanvas, register_node_type


def _mouse(t, pos, button, buttons):
    return QMouseEvent(
        t,
        QPointF(pos),
        QPointF(pos),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _send(widget, t, pos, button=None, buttons=None):
    button = button or Qt.MouseButton.LeftButton
    buttons = buttons if buttons is not None else button
    QApplication.instance().sendEvent(widget, _mouse(t, pos, button, buttons))


class TestCanvasReadOnly:
    def test_readonly_blocks_editing_but_keeps_navigation(self, qapp, clean_registry):
        register_node_type(
            "ro_proc",
            "处理",
            "流程",
            inputs=[{"id": "in", "data_type": "any"}],
            outputs=[{"id": "out", "data_type": "any"}],
        )
        canvas = ElaBlueprintCanvas(use_gl=False)
        canvas.resize(800, 600)
        canvas.show()
        qapp.processEvents()
        first = canvas.create_node("ro_proc", QPointF(40, 40))
        second = canvas.create_node("ro_proc", QPointF(300, 40))
        first.connect(second, "out", "in")

        canvas.setReadOnly(True)
        assert canvas.isReadOnly() is True
        assert canvas.create_node("ro_proc", QPointF(0, 200)) is None
        assert canvas.add_node(first) is first

        canvas.select_nodes([first])
        before = QPointF(first.pos)
        assert canvas.nudge_selection(12, 12) is False
        assert first.pos == before
        canvas.delete_selection()
        assert canvas.graph.node(first.id) is not None
        assert canvas.duplicate_selection() == []

        widget = canvas.node_widget(first)
        _send(widget, QEvent.Type.MouseButtonPress, QPointF(20, 20))
        _send(
            widget,
            QEvent.Type.MouseMove,
            QPointF(90, 90),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        _send(widget, QEvent.Type.MouseButtonRelease, QPointF(90, 90))
        qapp.processEvents()
        assert first.pos == before

        handle = widget.pin_widget("out")
        if handle is not None:
            _send(handle, QEvent.Type.MouseButtonPress, QPointF(4, 4))
            assert canvas._wire is None
            _send(handle, QEvent.Type.MouseButtonRelease, QPointF(4, 4))

        zoom = canvas.zoom()
        canvas.set_zoom(zoom * 1.2)
        assert canvas.zoom() > zoom

        offset = QPointF(canvas._offset)
        _send(
            canvas,
            QEvent.Type.MouseButtonPress,
            QPointF(400, 300),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
        )
        _send(
            canvas,
            QEvent.Type.MouseMove,
            QPointF(430, 330),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
        )
        _send(
            canvas,
            QEvent.Type.MouseButtonRelease,
            QPointF(430, 330),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.NoButton,
        )
        qapp.processEvents()
        assert canvas._offset != offset

        hits = []
        canvas.node_activated.connect(hits.append)
        _send(widget, QEvent.Type.MouseButtonDblClick, QPointF(20, 20))
        qapp.processEvents()
        assert hits == [first.id]

        canvas.execution().start(second)
        assert second.status == "running"
        canvas.execution().finish(second, 120.0)
        assert second.status == "done"
        canvas.close()
