"""节点移动 / 尺寸变化的局部重绘区域契约。

选中外发光由画布层自绘，**超出节点控件矩形**（blur 外扩 + 半笔宽 + 阴影
偏移）。只依赖 Qt 对子控件移动 / 改尺寸的自动失效（控件自身旧 / 新矩形）
时，光晕外圈不会进入脏区，旧位置会残留一圈灰晕 —— 也就是拖动时的拖影。
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.blueprint import ElaBlueprintCanvas, register_node_type

_LEFT = Qt.MouseButton.LeftButton
_NONE = Qt.MouseButton.NoButton
_NO_MOD = Qt.KeyboardModifier.NoModifier
#: 光晕带内的取样偏移（节点矩形外 6px，小于发光外扩）
_PROBE_OFFSET = 6


def _send(widget, etype, pos, button, buttons) -> None:
    event = QMouseEvent(etype, QPointF(pos), QPointF(pos), button, buttons, _NO_MOD)
    QApplication.instance().sendEvent(widget, event)


class _RegionSpy:
    """收集画布向绘制视口提交的重绘矩形（canvas.update 的实参）。"""

    def __init__(self, canvas) -> None:
        self.rects = []
        self._real = canvas.update
        canvas.update = self._spy

    def _spy(self, *args):
        if args:
            self.rects.append(args[0])
        return self._real(*args)

    def covers(self, point: QPoint) -> bool:
        return any(r is not None and r.contains(point) for r in self.rects)


def _make_canvas(qapp, make) -> ElaBlueprintCanvas:
    register_node_type("box", "盒子", "测试")
    canvas = make(ElaBlueprintCanvas)
    canvas.resize(900, 600)
    canvas.show()
    qapp.processEvents()
    return canvas


def _selected_node(canvas, qapp):
    node = canvas.create_node("box", QPointF(300, 250))
    widget = canvas.node_widget(node.id)
    canvas.select_nodes([node.id])
    qapp.processEvents()
    return node, widget


class TestDragRepaintRegions:
    def test_old_and_new_glow_band_are_repainted(self, qapp, make):
        canvas = _make_canvas(qapp, make)
        _node, widget = _selected_node(canvas, qapp)
        old_rect = widget.geometry()

        spy = _RegionSpy(canvas)
        center = widget.rect().center()
        _send(widget, QEvent.Type.MouseButtonPress, center, _LEFT, _LEFT)
        assert canvas._drag is not None, "press 未开始拖动"
        _send(widget, QEvent.Type.MouseMove, center + QPoint(80, 40), _NONE, _LEFT)
        _send(
            widget,
            QEvent.Type.MouseButtonRelease,
            center + QPoint(80, 40),
            _LEFT,
            _NONE,
        )

        old_probe = QPoint(old_rect.left() - _PROBE_OFFSET, old_rect.center().y())
        assert spy.covers(old_probe), (
            "旧位置的光晕带未进入重绘区域（拖动会留下残影）"
            f" rects={spy.rects!r} pos={_node.pos} geo={widget.geometry()}"
            f" zoom={canvas._zoom} offset={canvas._offset}"
        )
        new_rect = widget.geometry()
        assert new_rect != old_rect
        new_probe = QPoint(new_rect.left() - _PROBE_OFFSET, new_rect.center().y())
        assert spy.covers(new_probe), "新位置的光晕带未进入重绘区域（光晕会被裁掉）"


class TestResizeRepaintRegions:
    def test_shrinking_node_clears_old_glow_band(self, qapp, make):
        canvas = _make_canvas(qapp, make)
        node, widget = _selected_node(canvas, qapp)
        # 先撑大（大标题），让选中发光也铺到大矩形
        node.set_title("W" * 30)
        qapp.processEvents()
        old_rect = widget.geometry()
        assert old_rect.right() < canvas.width()

        spy = _RegionSpy(canvas)
        node.set_title("短")
        qapp.processEvents()

        assert widget.geometry().width() < old_rect.width()
        old_probe = QPoint(old_rect.right() + _PROBE_OFFSET, old_rect.center().y())
        assert spy.covers(old_probe), "缩小节点后旧位置的光晕带未纳入重绘"
