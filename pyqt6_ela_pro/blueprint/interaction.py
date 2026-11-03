"""蓝图画布的鼠标 / 键盘手势控制器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRectF, QSizeF, Qt
from PyQt6.QtWidgets import QWidget

from .edge_widget import ElaTempWire, bezier_path
from .menu import ElaNodeCreationMenu
from .model import ElaPinDirectionType, types_compatible
from .node_widget import ElaNodeWidget, ElaPinHandle

if TYPE_CHECKING:
    from .canvas import ElaBlueprintCanvas

#: 缩放范围
ZOOM_MIN, ZOOM_MAX = 0.25, 2.5
#: 磁吸半径（视图像素）
MAGNET_R = 22.0
#: 右键抬起判定为点击的位移阈值（px）
CLICK_TOL = 4.0


class CanvasInteraction:
    """把画布上的指针 / 键盘手势从 ``ElaBlueprintCanvas`` 中拆出来。"""

    def __init__(self, canvas: "ElaBlueprintCanvas") -> None:
        self._canvas = canvas

    def handle_event(self, obj, event) -> bool:
        """子控件事件过滤器（节点 / 引脚热区）。"""
        c = self._canvas
        etype = event.type()
        if etype not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseMove,
        ):
            return False
        if c._panning:
            if etype == QEvent.Type.MouseMove:
                c._offset = c._offset_start + (
                    self.view_pos_of_event(obj, event) - c._pan_start
                )
                c._view_changed(gesture=True)
                return True
            if (
                etype == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                c._panning = False
                c.unsetCursor()
                c._settle_view_gesture()
                return True
            return False
        if isinstance(obj, ElaPinHandle):
            if (
                etype == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                if c._space_down:
                    self.start_pan(self.view_pos_of_event(obj, event))
                    return True
                self.begin_wire(obj)
                return True
            if c._wire is not None:
                if etype == QEvent.Type.MouseMove:
                    self.update_wire(self.view_pos_of_event(obj, event))
                    return True
                if (
                    etype == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    self.finish_wire(self.view_pos_of_event(obj, event))
                    return True
            return False
        if isinstance(obj, ElaNodeWidget):
            if etype == QEvent.Type.MouseButtonPress:
                view_pos = self.view_pos_of_event(obj, event)
                if event.button() == Qt.MouseButton.LeftButton:
                    if c._space_down:
                        self.start_pan(view_pos)
                        return True
                    self.node_press(obj, view_pos, event.modifiers())
                    return True
                if event.button() == Qt.MouseButton.RightButton:
                    c._rpress = (view_pos, obj)
                    c._rpan = False
                    c._rpress_edge = None
                    c._pan_start = QPointF(view_pos)
                    c._offset_start = QPointF(c._offset)
                    return True
            if etype == QEvent.Type.MouseMove:
                view_pos = self.view_pos_of_event(obj, event)
                if c._drag is not None:
                    self.drag_to(view_pos)
                    return True
                if (
                    c._rpress is not None
                    and event.buttons() & Qt.MouseButton.RightButton
                ):
                    start, _target = c._rpress
                    if (QPointF(view_pos) - start).manhattanLength() > CLICK_TOL:
                        c._rpan = True
                        c.setCursor(Qt.CursorShape.ClosedHandCursor)
                    if c._rpan:
                        c._offset = c._offset_start + (QPointF(view_pos) - c._pan_start)
                        c._view_changed(gesture=True)
                    return True
            if etype == QEvent.Type.MouseButtonRelease:
                view_pos = self.view_pos_of_event(obj, event)
                if event.button() == Qt.MouseButton.LeftButton and c._drag is not None:
                    self.end_drag()
                    return True
                if (
                    event.button() == Qt.MouseButton.RightButton
                    and c._rpress is not None
                ):
                    target_node = c._rpress[1]
                    was_pan = c._rpan
                    c._rpress = None
                    c._rpan = False
                    if was_pan:
                        c.unsetCursor()
                        c._settle_view_gesture()
                    elif target_node is obj:
                        c._open_node_menu(obj, event.globalPosition().toPoint())
                    return True
        return False

    def view_pos_of_event(self, obj, event) -> QPointF:
        """把子控件上的事件坐标换算为画布视图坐标。"""
        return QPointF(obj.mapTo(self._canvas, event.position().toPoint()))

    def node_press(self, widget: ElaNodeWidget, view_pos: QPointF, modifiers) -> None:
        c = self._canvas
        # 焦点交给绘制视口（键盘事件由它转发给画布）：点节点后方向键 /
        # Ctrl+A 等快捷键立即可用
        c._viewport.setFocus(Qt.FocusReason.MouseFocusReason)
        nid = widget.node.id
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            c.toggle_node_selected(nid)
        elif nid not in c._selected_nodes:
            c.select_nodes([nid])
        if nid in c._selected_nodes:
            starts = {
                i: QPointF(c.graph.node(i).pos)
                for i in c._selected_nodes
                if c.graph.node(i)
            }
            c._drag = (QPointF(view_pos), starts)
            c._drag_moved = False

    def drag_to(self, view_pos: QPointF) -> None:
        c = self._canvas
        start_view, starts = c._drag
        delta = (QPointF(view_pos) - start_view) / c._zoom
        if not c._drag_moved and delta.manhattanLength() * c._zoom < 2.0:
            return
        if c.grid_snap():
            step = c._grid_scene_step()
            delta = QPointF(
                round(delta.x() / step) * step, round(delta.y() / step) * step
            )
        c._drag_moved = True
        defer = bool(getattr(c._viewport, "supports_node_proxy", False))
        affected = []
        old_edge_rects = []
        old_node_rects = []
        new_node_rects = []
        if not defer:
            for nid in starts:
                node = c.graph.node(nid)
                if node is None:
                    continue
                # 选中发光画在画布层、超出节点控件矩形：旧位置的光晕带必须
                # 纳入脏区，只靠 Qt 的控件移动失效会留下拖影
                old_node_rects.append(c._node_repaint_view_rect(node))
                for edge in c.graph.edges_of(nid):
                    widget = c._edge_widgets.get(edge.id)
                    if widget is not None and widget not in affected:
                        affected.append(widget)
                        old_edge_rects.append(widget.bounding_rect())
        for nid, start_pos in starts.items():
            node = c.graph.node(nid)
            if node is None:
                continue
            node.pos = start_pos + delta
            widget = c._node_widgets.get(nid)
            if widget is not None and defer:
                widget.begin_gesture_proxy()
            if widget is not None and not (defer and widget.uses_proxy()):
                widget.apply_view(c.scene_to_view(node.pos), c._zoom)
                if not defer:
                    new_node_rects.append(c._node_repaint_view_rect(node))
        if defer:
            c._gesture_deferred = True
            c.update()
        else:
            c._update_scene_rects(
                old_edge_rects + [ew.bounding_rect() for ew in affected]
            )
            c._update_view_rects(old_node_rects + new_node_rects)

    def end_drag(self) -> None:
        c = self._canvas
        _start_view, starts = c._drag
        c._drag = None
        if c._drag_moved:
            for nid in starts:
                node = c.graph.node(nid)
                if node is not None:
                    c.node_moved.emit(nid, QPointF(node.pos))
        c._drag_moved = False
        c._settle_view_gesture()

    def begin_wire(self, handle: ElaPinHandle) -> None:
        c = self._canvas
        pin = handle.pin
        node = handle.node_widget.node
        start = node.pos + handle.logical_center()
        c._wire = ElaTempWire(start, pin.data_type, parent=c)
        c._wire_src = (node.id, pin)
        c._wire_target = None
        c._update_scene_rects([self.wire_scene_rect(c._wire)])

    @staticmethod
    def wire_scene_rect(wire: ElaTempWire) -> QRectF:
        """临时线（含端点小圆点与描边余量）的场景包围盒。"""
        rect = bezier_path(wire.start, wire.end).boundingRect()
        return rect.adjusted(-12.0, -12.0, 12.0, 12.0)

    def wire_ring_rect(self, target) -> QRectF:
        """磁吸高亮圈的场景包围盒（无目标时返回空矩形）。"""
        if target is None:
            return QRectF()
        nid, pin = target
        center = self._canvas.pin_scene_pos(nid, pin.id, pin.direction)
        return QRectF(center - QPointF(12.0, 12.0), QSizeF(24.0, 24.0))

    def update_wire(self, view_pos: QPointF) -> None:
        c = self._canvas
        wire = c._wire
        old_rects = [self.wire_scene_rect(wire), self.wire_ring_rect(c._wire_target)]
        scene_pt = c.view_to_scene(view_pos)
        wire.set_end(scene_pt)
        c._wire_target = self.find_compatible_pin(scene_pt)
        wire.magnet = c._wire_target is not None
        if c._wire_target is not None:
            nid, pin = c._wire_target
            wire.set_end(c.pin_scene_pos(nid, pin.id, pin.direction))
        c._update_scene_rects(
            old_rects
            + [self.wire_scene_rect(wire), self.wire_ring_rect(c._wire_target)]
        )

    def find_compatible_pin(self, scene_pt: QPointF):
        """在磁吸半径内找最近的兼容引脚（方向相反 + 类型兼容 + 非本节点）。"""
        c = self._canvas
        src_nid, src_pin = c._wire_src
        want_dir = (
            ElaPinDirectionType.Input
            if src_pin.direction is ElaPinDirectionType.Output
            else ElaPinDirectionType.Output
        )
        radius = MAGNET_R / c._zoom
        probe = QRectF(scene_pt, scene_pt).adjusted(-radius, -radius, radius, radius)
        best = None
        best_d = radius
        for nid, widget in c._node_widgets.items():
            if nid == src_nid:
                continue
            if not probe.intersects(QRectF(widget.node.pos, widget.node.size)):
                continue
            pins = (
                widget.node.inputs
                if want_dir is ElaPinDirectionType.Input
                else widget.node.outputs
            )
            for pin in pins:
                if src_pin.direction is ElaPinDirectionType.Output:
                    ok = types_compatible(src_pin.data_type, pin.data_type)
                else:
                    ok = types_compatible(pin.data_type, src_pin.data_type)
                if not ok:
                    continue
                center = c.pin_scene_pos(nid, pin.id, pin.direction)
                distance = (center - scene_pt).manhattanLength()
                if distance < best_d:
                    best = (nid, pin)
                    best_d = distance
        return best

    def finish_wire(self, view_pos: QPointF) -> None:
        c = self._canvas
        src_nid, src_pin = c._wire_src
        target = self.find_compatible_pin(c.view_to_scene(view_pos))
        wire, c._wire, c._wire_src, c._wire_target = (
            c._wire,
            None,
            None,
            None,
        )
        dirty = []
        if wire is not None:
            dirty.append(self.wire_scene_rect(wire))
            wire.deleteLater()
        if target is not None:
            dirty.append(self.wire_ring_rect(target))
            tgt_nid, tgt_pin = target
            try:
                if src_pin.direction is ElaPinDirectionType.Output:
                    c.graph.add_edge(src_nid, src_pin.id, tgt_nid, tgt_pin.id)
                else:
                    c.graph.add_edge(tgt_nid, tgt_pin.id, src_nid, src_pin.id)
            except ValueError:
                pass  # 同一条连线已存在：拖放到同一目标上时静默忽略
        else:
            scene_pt = c.view_to_scene(view_pos)
            c._pending_wire = (src_nid, src_pin, scene_pt)
            menu = ElaNodeCreationMenu(c, owner=c._owner)
            want_dir = (
                ElaPinDirectionType.Input
                if src_pin.direction is ElaPinDirectionType.Output
                else ElaPinDirectionType.Output
            )
            menu.type_chosen.connect(self.create_node_for_wire)
            menu.popup_at(
                c.mapToGlobal(QPoint(int(view_pos.x()), int(view_pos.y()))),
                compatible=(want_dir, src_pin.data_type),
            )
        if dirty:
            c._update_scene_rects(dirty)

    def create_node_for_wire(self, type_name: str) -> None:
        """拖线松开菜单回调：创建节点并自动连接对应引脚。"""
        c = self._canvas
        pending = c._pending_wire
        c._pending_wire = None
        if pending is None:
            return
        src_nid, src_pin, scene_pt = pending
        node = c.create_node(type_name, scene_pt)
        want_dir = (
            ElaPinDirectionType.Input
            if src_pin.direction is ElaPinDirectionType.Output
            else ElaPinDirectionType.Output
        )
        pins = node.inputs if want_dir is ElaPinDirectionType.Input else node.outputs
        for pin in pins:
            if src_pin.direction is ElaPinDirectionType.Output:
                ok = types_compatible(src_pin.data_type, pin.data_type)
            else:
                ok = types_compatible(pin.data_type, src_pin.data_type)
            if not ok:
                continue
            if src_pin.direction is ElaPinDirectionType.Output:
                edge = (src_nid, src_pin.id, node.id, pin.id)
            else:
                edge = (node.id, pin.id, src_nid, src_pin.id)
            try:
                c.graph.add_edge(*edge)
            except ValueError:
                pass
            break

    def mouse_press(self, event) -> None:
        c = self._canvas
        pos = QPointF(event.position().toPoint())
        if event.button() == Qt.MouseButton.MiddleButton:
            self.start_pan(pos)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if c._space_down:
                self.start_pan(pos)
                return
            hit = c._edge_at(c.view_to_scene(pos))
            if hit is not None:
                c._select_edge(
                    hit, bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                )
                return
            c._band = (pos, pos)
            c._band_additive = bool(
                event.modifiers() & Qt.KeyboardModifier.ControlModifier
            )
            if not c._band_additive:
                c.clear_selection()
            c.update()
            return
        if event.button() == Qt.MouseButton.RightButton:
            hit = c._edge_at(c.view_to_scene(pos))
            c._rpress = (pos, None)
            c._rpan = False
            c._rpress_edge = hit
            c._pan_start = QPointF(pos)
            c._offset_start = QPointF(c._offset)
            return
        QWidget.mousePressEvent(c, event)

    def mouse_move(self, event) -> None:
        c = self._canvas
        pos = QPointF(event.position().toPoint())
        if c._wire is not None:
            self.update_wire(pos)
            return
        if c._panning:
            c._offset = c._offset_start + (pos - c._pan_start)
            c._view_changed(gesture=True)
            return
        if c._rpress is not None and event.buttons() & Qt.MouseButton.RightButton:
            start, _target = c._rpress
            if (pos - start).manhattanLength() > CLICK_TOL:
                c._rpan = True
                c.setCursor(Qt.CursorShape.ClosedHandCursor)
            if c._rpan:
                c._offset = c._offset_start + (pos - c._pan_start)
                c._view_changed(gesture=True)
            return
        if c._band is not None:
            old_rect = QRectF(c._band[0], c._band[1]).normalized()
            c._band = (c._band[0], pos)
            new_rect = QRectF(c._band[0], c._band[1]).normalized()
            dirty = old_rect.united(new_rect).adjusted(-3.0, -3.0, 3.0, 3.0)
            c.update(dirty.toAlignedRect().intersected(c.rect()))
            return
        c._update_edge_hover(c.view_to_scene(pos))
        QWidget.mouseMoveEvent(c, event)

    def mouse_release(self, event) -> None:
        c = self._canvas
        pos = QPointF(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and c._wire is not None:
            self.finish_wire(pos)
            return
        if event.button() == Qt.MouseButton.MiddleButton and c._panning:
            c._panning = False
            c.unsetCursor()
            c._settle_view_gesture()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if c._panning:
                c._panning = False
                c.unsetCursor()
                c._settle_view_gesture()
                return
            if c._band is not None:
                self.finish_band()
                return
        if event.button() == Qt.MouseButton.RightButton and c._rpress is not None:
            was_pan = c._rpan
            edge_id = c._rpress_edge
            c._rpress = None
            c._rpan = False
            c._rpress_edge = None
            if was_pan:
                c._panning = False
                c.unsetCursor()
                c._settle_view_gesture()
            elif edge_id is not None:
                c._select_edge(edge_id, False)
                c._open_edge_menu(edge_id, event.globalPosition().toPoint())
            else:
                scene_pt = c.view_to_scene(pos)
                menu = ElaNodeCreationMenu(c, owner=c._owner)
                menu.type_chosen.connect(lambda t, sp=scene_pt: c.create_node(t, sp))
                menu.popup_at(event.globalPosition().toPoint())
            return
        QWidget.mouseReleaseEvent(c, event)

    def wheel(self, event) -> None:
        c = self._canvas
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 ** (delta / 120.0)
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, c._zoom * factor))
        if abs(new_zoom - c._zoom) < 1e-6:
            return
        cursor = event.position()
        c._offset = cursor - (cursor - c._offset) * (new_zoom / c._zoom)
        c._zoom = new_zoom
        c._view_changed(gesture=True)
        c._zooming = True
        c._zoom_settle.start()
        event.accept()

    def end_zoom_gesture(self) -> None:
        c = self._canvas
        c._zooming = False
        c._settle_view_gesture()
        c.update()

    def start_pan(self, view_pos: QPointF) -> None:
        c = self._canvas
        c._panning = True
        c._pan_start = QPointF(view_pos)
        c._offset_start = QPointF(c._offset)
        c.setCursor(Qt.CursorShape.ClosedHandCursor)

    def finish_band(self) -> None:
        c = self._canvas
        start, end = c._band
        c._band = None
        rect = QRectF(c.view_to_scene(start), c.view_to_scene(end)).normalized()
        ids = []
        if rect.width() > 2 / c._zoom or rect.height() > 2 / c._zoom:
            for nid, widget in c._node_widgets.items():
                node = widget.node
                if rect.intersects(QRectF(node.pos, node.size)):
                    ids.append(nid)
        if ids:
            c.select_nodes(ids, additive=c._band_additive)
        c.update()

    def cancel(self) -> None:
        """复位所有「按住类」手势状态（失焦 / 隐藏 / 载入新图时调用）。"""
        c = self._canvas
        c._space_down = False
        c._band = None
        c._band_additive = False
        c._rpress = None
        c._rpan = False
        c._rpress_edge = None
        if c._wire is not None:
            c._wire.deleteLater()
        c._wire = None
        c._wire_src = None
        c._wire_target = None
        c._pending_wire = None
        if c._panning:
            c._panning = False
            c.unsetCursor()

    def key_press(self, event) -> None:
        c = self._canvas
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            c._space_down = True
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            c.delete_selection()
            return
        if key == Qt.Key.Key_Escape:
            self.cancel()
            c.clear_selection()
            return
        if mods & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_A:
                c.select_all()
                return
            if key == Qt.Key.Key_D:
                c.duplicate_selection()
                return
        if key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            self.nudge(key, bool(mods & Qt.KeyboardModifier.ShiftModifier))
            return
        QWidget.keyPressEvent(c, event)

    def nudge(self, key, big: bool) -> None:
        """方向键微调选中节点（Shift = 10px，其余 1px，场景单位）。"""
        step = 10.0 if big else 1.0
        dx = dy = 0.0
        if key == Qt.Key.Key_Left:
            dx = -step
        elif key == Qt.Key.Key_Right:
            dx = step
        elif key == Qt.Key.Key_Up:
            dy = -step
        elif key == Qt.Key.Key_Down:
            dy = step
        if dx or dy:
            self._canvas.nudge_selection(dx, dy)

    def key_release(self, event) -> None:
        c = self._canvas
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            c._space_down = False
            if c._panning:
                c._panning = False
                c.unsetCursor()
                c._settle_view_gesture()
            return
        QWidget.keyReleaseEvent(c, event)
