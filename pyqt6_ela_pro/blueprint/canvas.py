"""蓝图节点图编辑器画布：平移 / 缩放 / 选择 / 连线 / 序列化。

交互与扩展点见 ``docs/blueprint.md``。"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSizeF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from .._internal import execElaMenu
from .._motion import start_idle_loop
from ._tokens import T, shadow_md, theme_changed_slot
from .edge_widget import (
    ElaEdgeWidget,
    _cached_color,
    _cached_pen,
)
from .execution import ElaExecutionController
from .interaction import ZOOM_MAX, ZOOM_MIN, CanvasInteraction
from .menu import ElaEdgeContextMenu, ElaNodeContextMenu
from .model import (
    ElaBlueprintGraph,
    ElaBlueprintNode,
    ElaEdge,
    _finite,
    _node_id,
    _pin_id,
)
from .node_widget import ElaNodeWidget
from .registry import ElaNodeRegistry
from .viewport import create_viewport

__all__ = ["ElaBlueprintCanvas"]

logger = logging.getLogger(__name__)

#: 流动边线虚线相位的推进间隔（ms）。持续动效，Reduced/Disabled 下冻结。
EDGE_FLOW_TICK_MS = 50
#: 背景网格点半径（视图像素）
GRID_DOT_R = 1.3


def _glow_steps(blur: float) -> tuple[int, float]:
    """选中发光的层数与笔宽（绘制与重绘外扩共用同一套参数）。"""
    steps = max(3, int(blur / 2))
    return steps, max(1.0, blur / steps + 0.5)


def _selection_glow_pad() -> float:
    """选中发光在节点矩形外的最大外扩（视图像素）。
    与 ``_draw_selection_glow`` 同源：最大 grow + 半个笔宽 + 阴影偏移 +
    的局部重绘必须按这个值外扩，否则旧位置会留下光晕残影。
    """
    spec = shadow_md()
    blur = float(spec["blur"])
    steps, pen_w = _glow_steps(blur)
    ox, oy = spec["offset"]
    grow = blur * 0.75 * (1.0 - 0.5 / steps)
    return grow + pen_w / 2.0 + max(abs(ox), abs(oy)) + 2.0


def _as_point(pos) -> QPointF:
    """把 ``QPointF`` / ``QPoint`` / ``(x, y)`` 归一成 ``QPointF``。"""
    if isinstance(pos, QPointF):
        return QPointF(pos)
    if isinstance(pos, QPoint):
        return QPointF(pos)
    try:
        x, y = pos
    except (TypeError, ValueError):
        raise TypeError("pos 需要 QPointF / QPoint / (x, y)") from None
    return QPointF(_finite(x), _finite(y))


class ElaBlueprintCanvas(QWidget):
    """蓝图节点图画布控件。

    :param graph: ``ElaBlueprintGraph`` 数据图（节点 / 边变化自动同步到界面）
    :param parent: 父控件
    :param owner: 注册表命名空间标识（缺省 None）；给定时节点创建 /
        创建菜单 / 节点体解析范围均为「该 owner + 全局」

    节点体是可交互的（不能置 ``WA_TransparentForMouseEvents``）：体里的控件
    吃自己的事件，其余区域冒泡到节点控件用于选中 / 拖动。
    """

    node_moved = pyqtSignal(str, QPointF)
    node_rename_requested = pyqtSignal(str)
    node_properties_requested = pyqtSignal(str)
    edge_created = pyqtSignal(object)
    edge_removed = pyqtSignal(str)
    selection_changed = pyqtSignal(list)

    def __init__(self, graph: ElaBlueprintGraph = None, parent=None, owner: str = None):
        super().__init__(parent)
        if graph is None:
            graph = ElaBlueprintGraph()
        self.graph = graph
        self._owner = owner
        self._zoom = 1.0
        self._offset = QPointF(0.0, 0.0)
        # 拖动吸附：基础间距 24（场景单位），屏幕间距随缩放按 2 的幂自适应
        self._grid_snap = False
        self._grid_step = 24.0
        self._node_widgets = {}
        self._edge_widgets = {}
        self._selected_nodes = []
        self._selected_edges = []

        # 网格平铺纹理缓存（键：间距档位 / 颜色 / DPR）
        self._grid_tile_cache = None
        self._grid_tile_key = None

        # 交互状态
        self._panning = False
        self._pan_start = QPointF()
        self._offset_start = QPointF()
        self._space_down = False
        self._rpress = None
        self._rpan = False
        self._rpress_edge = None
        self._drag = None  # (start_view, {node_id: start_scene_pos})
        self._drag_moved = False
        self._band = None  # (start_view, current_view)
        self._band_additive = False
        self._wire = None  # ElaTempWire
        self._wire_src = None  # (node_id, ElaPin)
        self._wire_target = None  # (node_id, ElaPin)
        self._pending_wire = None  # 菜单创建后自动连接用
        # 视图手势（平移 / 滚轮缩放）中跳过的节点几何落位待补偿标记
        self._gesture_deferred = False

        self._flow_timer = QTimer(self)
        self._flow_timer.setInterval(EDGE_FLOW_TICK_MS)
        self._flow_timer.timeout.connect(self._tick_flow)

        # 滚轮缩放手势标记：手势期间 GL 代理节点位图按纹理缩放（不重建
        # 缓存），手势结束 150ms 后触发一次全量重建恢复清晰
        self._zooming = False
        self._zoom_settle = QTimer(self)
        self._zoom_settle.setSingleShot(True)
        self._zoom_settle.setInterval(150)

        self._interaction = CanvasInteraction(self)
        self._zoom_settle.timeout.connect(self._interaction.end_zoom_gesture)

        self._execution = ElaExecutionController(self)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 240)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        # 绘制视口：GL 可用时为 QOpenGLWidget（GPU 加速），否则软件回退；
        # 与画布 1:1 重合（resizeEvent 同步几何），节点控件挂在其下。
        self._viewport = create_viewport(self)
        self._viewport.setGeometry(self.rect())
        self._viewport.show()

        graph.node_added.connect(self._on_node_added)
        graph.node_removed.connect(self._on_node_removed)
        graph.edge_added.connect(self._on_edge_added)
        graph.edge_removed.connect(self._on_edge_removed)
        graph.edge_changed.connect(self._on_edge_changed)
        # 绑定方法连接：receiver（本画布）销毁时 Qt 自动断连
        theme_changed_slot(self, self._retheme)

        for node in graph.nodes():
            self._on_node_added(node)
        for edge in graph.edges():
            self._on_edge_added(edge)

    # 公共 API
    def create_node(
        self,
        type_name: str,
        pos,
        properties: dict = None,
        title: str = None,
    ) -> ElaBlueprintNode:
        """按注册类型创建节点并放入画布，返回 ``ElaBlueprintNode``。

        :param type_name: 注册表里的类型名（按画布 ``owner`` 解析）
        :param pos: ``QPointF`` / ``QPoint`` / ``(x, y)``
        :param properties: 初始属性；**在节点体构建之前写入**，节点体里的
            控件（SpinBox / ComboBox）会读到正确的初始值
        :param title: 可选标题覆盖（在节点体构建前写入，避免二次重排）

        非法类型抛 ``KeyError``，节点 id 冲突抛 ``ValueError``。
        """
        node = ElaNodeRegistry.instance().create(type_name, owner=self._owner)
        node.pos = _as_point(pos)
        if title is not None:
            node.title = str(title)
        if properties:
            node.set_properties(properties)
        self.graph.add_node(node)
        return node

    def add_node(self, node: ElaBlueprintNode, pos=None) -> ElaBlueprintNode:
        """把既有 ``ElaBlueprintNode`` 放入图（可选指定场景坐标）。"""
        if pos is not None:
            node.pos = _as_point(pos)
        self.graph.add_node(node)
        return node

    def clear(self) -> None:
        """清空画布（节点 / 连线 / 选择），等价 ``clear_selection`` + ``graph.clear``。"""
        self.clear_selection()
        self.graph.clear()

    def set_edge_label(self, edge, text: str) -> bool:
        """设置连线中点标签（``edge`` 接受 ``ElaEdge`` 或 id，``text`` 支持多行）。

        返回是否实际变化；画布会自动失效标签缓存并局部重绘。
        """
        return self.graph.set_edge_label(edge, text)

    def set_zoom(self, z: float) -> None:
        """设置缩放（夹在 0.25–2.5），视图中心保持不变。"""
        z = max(ZOOM_MIN, min(ZOOM_MAX, float(z)))
        if abs(z - self._zoom) < 1e-6:
            return
        center_scene = self.view_to_scene(QPointF(self.width() / 2, self.height() / 2))
        self._zoom = z
        self._offset = QPointF(self.width() / 2, self.height() / 2) - center_scene * z
        self._update_view()
        # 程序化连续缩放同样按手势处理：期间节点缓存位图拉伸显示，
        # 停顿 150ms 后统一重建（避免每帧全量离屏重渲染）
        self._zooming = True
        self._zoom_settle.start()

    def zoom(self) -> float:
        """当前缩放系数。"""
        return self._zoom

    def set_grid_snap(self, on: bool) -> None:
        """拖节点时是否吸附到点阵网格（默认关）。
        吸附作用在**拖动位移**上（而不是逐个节点取整）：多选拖动保持节点间
        的相对布局，不会因为各自取整而互相挤开。
        """
        self._grid_snap = bool(on)

    def grid_snap(self) -> bool:
        """拖节点是否吸附到网格。"""
        return self._grid_snap

    def set_grid_step(self, step: float) -> None:
        """吸附网格的基础间距（场景单位，默认 24）。
        实际生效间距随缩放按 2 的幂自适应（与 ``_draw_grid`` 同源），
        保证吸附后节点落在看得见的网格点上。
        """
        self._grid_step = max(4.0, _finite(step, 24.0))

    def grid_step(self) -> float:
        """当前缩放下实际生效的吸附间距（场景单位）。"""
        return self._grid_scene_step()

    def select_all(self) -> None:
        """选中全部节点（Ctrl+A）。"""
        self.select_nodes(self.graph.nodes())

    def duplicate_selection(self) -> list:
        """复制选中节点（Ctrl+D），副本错开 24px 并成为新的选择。
        返回副本 id 列表；连同节点属性（含按钮体读的 ``properties``）一起
        复制，但**不**复制节点之间的连线。
        """
        copies = []
        for nid in list(self._selected_nodes):
            node = self.graph.node(nid)
            if node is None:
                continue
            copy = self._clone_node(node)
            self.graph.add_node(copy)
            copies.append(copy.id)
        if copies:
            self.select_nodes(copies)
        return copies

    def nudge_selection(self, dx: float, dy: float) -> bool:
        """按场景单位平移选中节点（方向键微调），返回是否真的移动。
        与拖动走同一套脏区：旧 / 新节点矩形（含选中发光带）+ 相连边的新旧
        包围盒，否则微调一样会留下光晕残影。
        """
        dx, dy = _finite(dx), _finite(dy)
        if (dx == 0.0 and dy == 0.0) or not self._selected_nodes:
            return False
        moved = [
            node
            for node in (self.graph.node(nid) for nid in self._selected_nodes)
            if node is not None
        ]
        if not moved:
            return False
        old_node_rects = [self._node_repaint_view_rect(node) for node in moved]
        old_edge_rects = []
        edge_ids = []
        for node in moved:
            for edge in self.graph.edges_of(node.id):
                if edge.id in edge_ids:
                    continue
                edge_ids.append(edge.id)
                widget = self._edge_widgets.get(edge.id)
                if widget is not None:
                    old_edge_rects.append(widget.bounding_rect())
        for node in moved:
            node.pos = node.pos + QPointF(dx, dy)
            widget = self._node_widgets.get(node.id)
            if widget is not None:
                widget.apply_view(self.scene_to_view(node.pos), self._zoom)
        new_node_rects = [self._node_repaint_view_rect(node) for node in moved]
        new_edge_rects = [
            widget.bounding_rect()
            for widget in (self._edge_widgets.get(eid) for eid in edge_ids)
            if widget is not None
        ]
        self._update_scene_rects(old_edge_rects + new_edge_rects)
        self._update_view_rects(old_node_rects + new_node_rects)
        for node in moved:
            self.node_moved.emit(node.id, QPointF(node.pos))
        return True

    def center_on(self, node) -> None:
        """把视图中心对准某节点（``ElaBlueprintNode`` 或 id，缩放不变）。"""
        self._settle_view_gesture()
        node = self.graph.node(_node_id(node))
        if node is None:
            return
        center = node.pos + QPointF(node.size.width() / 2, node.size.height() / 2)
        self._offset = (
            QPointF(self.width() / 2, self.height() / 2) - center * self._zoom
        )
        self._update_view()

    def fit_view(self) -> None:
        """适应视图：全部节点居中可见（含边距，缩放夹在合法范围）。"""
        self._settle_view_gesture()
        nodes = self.graph.nodes()
        if not nodes:
            self._zoom = 1.0
            self._offset = QPointF(0.0, 0.0)
        else:
            rect = None
            for node in nodes:
                r = QRectF(node.pos, node.size)
                rect = r if rect is None else rect.united(r)
            margin = 60.0
            rect = rect.adjusted(-margin, -margin, margin, margin)
            vw, vh = max(1, self.width()), max(1, self.height())
            z = min(vw / max(rect.width(), 1.0), vh / max(rect.height(), 1.0))
            self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, z))
            self._offset = QPointF(vw / 2, vh / 2) - rect.center() * self._zoom
        self._update_view()
        self._zooming = True
        self._zoom_settle.start()

    def execution(self) -> ElaExecutionController:
        """返回运行指示控制器（画布持有唯一实例）。"""
        return self._execution

    def node_widget(self, node):
        """按 ``ElaBlueprintNode`` / id 取节点控件，不存在返回 ``None``。"""
        return self._node_widgets.get(_node_id(node))

    def edge_widget(self, edge):
        """按 ``ElaEdge`` / id 取边部件，不存在返回 ``None``。"""
        eid = edge.id if isinstance(edge, ElaEdge) else str(edge)
        return self._edge_widgets.get(eid)

    def pin_scene_pos(self, node, pin_id: str, direction=None) -> QPointF:
        """引脚圆心的场景坐标（找不到时回退节点左上角）。
        ``node`` 接受 ``ElaBlueprintNode`` 或 id；``pin_id`` 接受
        ``ElaPin`` 或字符串 id。
        """
        nid = _node_id(node)
        node_obj = self.graph.node(nid)
        widget = self._node_widgets.get(nid)
        if widget is not None and node_obj is not None:
            pin = node_obj.pin(_pin_id(pin_id), direction)
            if pin is not None:
                return node_obj.pos + widget.pin_logical_center(pin)
        return QPointF(node_obj.pos) if node_obj is not None else QPointF()

    def selected_nodes(self) -> list:
        """当前选中的节点对象列表（顺序与选择顺序一致）。"""
        return [
            node
            for node in (self.graph.node(nid) for nid in self._selected_nodes)
            if node is not None
        ]

    def selected_node_ids(self) -> list:
        """当前选中的节点 id 列表。"""
        return list(self._selected_nodes)

    def selected_edges(self) -> list:
        """当前选中的边对象列表（顺序与选择顺序一致）。"""
        return [
            edge
            for edge in (self.graph.edge(eid) for eid in self._selected_edges)
            if edge is not None
        ]

    def selected_edge_ids(self) -> list:
        """当前选中的边 id 列表。"""
        return list(self._selected_edges)

    def scene_to_view(self, pt: QPointF) -> QPointF:
        """场景坐标 → 视图（控件）坐标。"""
        return pt * self._zoom + self._offset

    def view_to_scene(self, pt: QPointF) -> QPointF:
        """视图（控件）坐标 → 场景坐标。"""
        return (QPointF(pt) - self._offset) / self._zoom

    def to_dict(self) -> dict:
        """序列化整张图与视图状态：``{"graph": ..., "view": {...}}``。"""
        return {
            "graph": self.graph.to_dict(),
            "view": {
                "zoom": self._zoom,
                "offset": [self._offset.x(), self._offset.y()],
            },
        }

    def from_dict(self, data: dict) -> None:
        """从 ``to_dict`` 结果恢复（节点对象会被重建，旧引用失效）。
        常在宿主「加载文件」的 Qt 槽里调用，因此脏数据逐条跳过并记 WARNING：
        抛出去 = 槽内异常 = 0xC0000409。边必须走 ``graph.add_edge()``，绕过
        """
        self._settle_view_gesture()
        self._cancel_gestures()
        self.clear_selection()
        self.graph.clear()
        gdata = data.get("graph", data) if isinstance(data, dict) else {}
        if not isinstance(gdata, dict):
            gdata = {}
        raw_nodes = gdata.get("nodes", [])
        if not isinstance(raw_nodes, list):
            logger.warning("nodes 不是列表（%r），按空处理", type(raw_nodes).__name__)
            raw_nodes = []
        for nd in raw_nodes:
            try:
                self.graph.add_node(ElaBlueprintNode.from_dict(nd))
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning("跳过非法节点 %r（%s）", nd, exc)
        raw_edges = gdata.get("edges", [])
        if not isinstance(raw_edges, list):
            logger.warning("edges 不是列表（%r），按空处理", type(raw_edges).__name__)
            raw_edges = []
        for ed in raw_edges:
            try:
                raw = ElaEdge.from_dict(ed)
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning("跳过非法连线 %r（%s）", ed, exc)
                continue
            # 走 add_edge 校验（保留原 id 以便往返），不过就丢弃：
            # 一条坏边不该让整张图载入失败
            try:
                self.graph.add_edge(
                    raw.from_node,
                    raw.from_pin,
                    raw.to_node,
                    raw.to_pin,
                    edge_id=raw.id,
                )
            except ValueError as exc:
                logger.warning("跳过非法连线 %r（%s）", raw.id, exc)
        self._execution.reset()
        view = data.get("view", {}) if isinstance(data, dict) else {}
        if not isinstance(view, dict):
            view = {}
        zoom = _finite(view.get("zoom", 1.0), 1.0)
        off = view.get("offset", [0.0, 0.0])
        if not (isinstance(off, (list, tuple)) and len(off) >= 2):
            off = [0.0, 0.0]
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        self._offset = QPointF(_finite(off[0]), _finite(off[1]))
        self._update_view()

    # 图信号 → 界面同步
    def _on_node_added(self, node: ElaBlueprintNode) -> None:
        widget = ElaNodeWidget(node, self._viewport, owner=self._owner)
        widget.installEventFilter(self)
        # 节点后续 add_input/add_output 会新建热区（ElaNodeWidget.sync_pins），
        # 那时也要装事件过滤器，否则新引脚拖不出连线。
        widget.pinsSynced.connect(self._on_widget_pins_synced)
        for pin in node.inputs + node.outputs:
            handle = widget.pin_widget(pin.id, pin.direction)
            if handle is not None:
                handle.installEventFilter(self)
        # 节点体保持可交互：体里的控件收自己的事件，体空白处按下会冒泡到
        # 节点控件（事件过滤器照常收到）→ 照常选中 / 拖动节点。**不要**
        # 给体置 WA_TransparentForMouseEvents —— 那会把体里的控件全变成装饰。
        widget._spinner.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        widget.apply_view(self.scene_to_view(node.pos), self._zoom)
        widget.show()
        self._node_widgets[node.id] = widget
        self.update()

    def _on_widget_pins_synced(self, handles) -> None:
        """节点新增引脚后，widget 交回新建的热区，补装事件过滤器。"""
        for handle in handles or ():
            try:
                handle.installEventFilter(self)
            except RuntimeError:  # 已被销毁
                continue

    def _on_node_removed(self, node_id: str) -> None:
        widget = self._node_widgets.pop(node_id, None)
        if widget is not None:
            widget.removeEventFilter(self)
            widget.hide()
            widget.deleteLater()
        if node_id in self._selected_nodes:
            self._selected_nodes.remove(node_id)
            self.selection_changed.emit(list(self._selected_nodes))
        self.update()

    def _on_edge_added(self, edge) -> None:
        self._edge_widgets[edge.id] = ElaEdgeWidget(self, edge, self)
        self.edge_created.emit(edge)
        self.update()

    def _on_edge_changed(self, edge) -> None:
        """连线数据变化（标签）：失效缓存并重绘新旧包围盒。"""
        widget = self._edge_widgets.get(edge.id)
        if widget is None:
            return
        old = widget.bounding_rect()
        widget.invalidate_label()
        new = widget.bounding_rect()
        self._update_scene_rects([old, new])

    def _on_edge_removed(self, edge_id: str) -> None:
        widget = self._edge_widgets.pop(edge_id, None)
        if widget is not None:
            widget.deleteLater()
        if edge_id in self._selected_edges:
            self._selected_edges.remove(edge_id)
        self.edge_removed.emit(edge_id)
        self.update()

    def _node_layout_changed(self, node_widget: ElaNodeWidget) -> None:
        """节点尺寸变化（属性 / 引脚变化）后重新落位并清掉旧区域。
        此时控件几何还是旧尺寸，取它作为旧矩形；画布层的选中发光范围也随
        尺寸变化，旧光晕带不一起重绘就会残留在原处。
        """
        pad = _selection_glow_pad()
        old_rect = QRectF(node_widget.geometry()).adjusted(-pad, -pad, pad, pad)
        node_widget.apply_view(self.scene_to_view(node_widget.node.pos), self._zoom)
        self._update_view_rects(
            [old_rect, self._node_repaint_view_rect(node_widget.node)]
        )

    def _retheme(self) -> None:
        self._settle_view_gesture()
        for widget in self._node_widgets.values():
            widget.refresh_theme()
        # 边基础色按引脚类型惰性缓存，主题切换后须失效重建（实时取色）
        for ew in self._edge_widgets.values():
            ew.invalidate_color()
        self._update_view()

    def _update_view(self) -> None:
        for node_id, widget in self._node_widgets.items():
            node = self.graph.node(node_id)
            if node is not None:
                widget.apply_view(self.scene_to_view(node.pos), self._zoom)
        self.update()

    def _view_changed(self, gesture: bool = False) -> None:
        """视图变换（zoom / offset 变化）后的界面同步。

        ``gesture=True``（平移拖拽 / 滚轮缩放进行中）且视口支持节点位图
        代理时：跳过全部节点的逐帧几何落位，仅重绘视口——节点由视口按
        场景坐标实时绘制缓存位图。带可见自定义体的节点在手势开始时被
        临时切换为位图代理（``ElaNodeWidget.begin_gesture_proxy``），
        避免 GL 视口上逐帧真实子控件落位 + 重绘的高额合成开销。手势
        结束时由 ``_settle_view_gesture`` 统一补偿恢复。
        """
        if gesture and getattr(self._viewport, "supports_node_proxy", False):
            if not self._gesture_deferred:
                for widget in self._node_widgets.values():
                    widget.begin_gesture_proxy()
            self._gesture_deferred = True
            self.update()
            return
        self._update_view()

    def _settle_view_gesture(self) -> None:
        """视图手势结束：恢复真实控件并补偿几何落位。"""
        if self._gesture_deferred:
            self._gesture_deferred = False
            for widget in self._node_widgets.values():
                widget.end_gesture_proxy()
            self._update_view()

    # 选择
    def clear_selection(self) -> None:
        """清空节点与边的选中态。"""
        for nid in self._selected_nodes:
            w = self._node_widgets.get(nid)
            if w is not None:
                w.set_selected(False)
        for eid in self._selected_edges:
            ew = self._edge_widgets.get(eid)
            if ew is not None:
                ew.selected = False
        self._selected_nodes = []
        self._selected_edges = []
        self.selection_changed.emit([])
        self.update()

    def select_nodes(self, nodes, additive: bool = False) -> None:
        """选中节点（``nodes`` 接受单个 / 列表，元素为节点对象或 id）。"""
        if isinstance(nodes, (ElaBlueprintNode, str)):
            nodes = [nodes]
        if not additive:
            self.clear_selection()
        changed = False
        for value in nodes:
            nid = _node_id(value)
            if nid in self._selected_nodes:
                continue
            w = self._node_widgets.get(nid)
            if w is None:
                continue
            self._selected_nodes.append(nid)
            w.set_selected(True)
            changed = True
        if changed:
            self.selection_changed.emit(list(self._selected_nodes))
        self.update()

    def toggle_node_selected(self, node) -> None:
        """Ctrl 点选：切换节点（对象或 id）的选中态。"""
        nid = _node_id(node)
        if nid in self._selected_nodes:
            self._selected_nodes.remove(nid)
            w = self._node_widgets.get(nid)
            if w is not None:
                w.set_selected(False)
        else:
            self._selected_nodes.append(nid)
            w = self._node_widgets.get(nid)
            if w is not None:
                w.set_selected(True)
        self.selection_changed.emit(list(self._selected_nodes))
        self.update()

    def _select_edge(self, edge_id: str, additive: bool) -> None:
        if not additive:
            self.clear_selection()
        if edge_id not in self._selected_edges:
            self._selected_edges.append(edge_id)
            ew = self._edge_widgets.get(edge_id)
            if ew is not None:
                ew.selected = True
        self.update()

    # 事件过滤（节点控件 / 引脚热区）
    def eventFilter(self, obj, event):
        return self._interaction.handle_event(obj, event)

    def view_pos_of_event(self, obj, event) -> QPointF:
        """把子控件上的事件坐标换算为画布视图坐标。"""
        return self._interaction.view_pos_of_event(obj, event)

    # 画布鼠标事件（空白区）
    def mousePressEvent(self, event) -> None:
        self._interaction.mouse_press(event)

    def mouseMoveEvent(self, event) -> None:
        self._interaction.mouse_move(event)

    def mouseReleaseEvent(self, event) -> None:
        self._interaction.mouse_release(event)

    def wheelEvent(self, event) -> None:
        self._interaction.wheel(event)

    def keyPressEvent(self, event) -> None:
        self._interaction.key_press(event)

    def keyReleaseEvent(self, event) -> None:
        self._interaction.key_release(event)

    def _cancel_gestures(self) -> None:
        """复位所有「按住类」手势状态（失焦 / 隐藏 / 载入新图时调用）。"""
        self._interaction.cancel()

    def leaveEvent(self, event) -> None:
        """鼠标离开画布：清掉边 hover（否则最后一次悬停的边一直保持加粗）。"""
        self._clear_edge_hover()
        super().leaveEvent(event)

    def focusOutEvent(self, event) -> None:
        self._cancel_gestures()
        self.update()
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:
        self._cancel_gestures()
        super().hideEvent(event)

    def delete_selection(self) -> None:
        """删除选中的边与节点（节点连带其全部边），发相应信号。"""
        for eid in list(self._selected_edges):
            self.graph.remove_edge(eid)
        for nid in list(self._selected_nodes):
            self.graph.remove_node(nid)
        self._selected_edges = []
        self._selected_nodes = []
        self.selection_changed.emit([])
        self.update()

    def _edge_at(self, scene_pt: QPointF):
        for eid, ew in self._edge_widgets.items():
            if ew.contains(scene_pt, tol=7.0 / self._zoom + 3.0):
                return eid
        return None

    def _update_edge_hover(self, scene_pt: QPointF) -> None:
        hit = self._edge_at(scene_pt)
        rects = []
        for eid, ew in self._edge_widgets.items():
            want = eid == hit
            if ew.hovered != want:
                ew.hovered = want
                rects.append(ew.bounding_rect())
        if rects:
            self._update_scene_rects(rects)

    def _clear_edge_hover(self) -> None:
        """清除全部边的 hover 态（鼠标离开画布时调用）。"""
        rects = []
        for ew in self._edge_widgets.values():
            if ew.hovered:
                ew.hovered = False
                rects.append(ew.bounding_rect())
        if rects:
            self._update_scene_rects(rects)

    def _open_node_menu(self, widget: ElaNodeWidget, global_pos: QPoint) -> None:
        nid = widget.node.id
        menu = ElaNodeContextMenu(nid, self)
        menu.duplicate_requested.connect(self._duplicate_node)
        menu.disconnect_requested.connect(
            lambda i: [self.graph.remove_edge(e.id) for e in self.graph.edges_of(i)]
        )
        menu.delete_requested.connect(lambda i: self.graph.remove_node(i))
        # 菜单在 ``_open_node_menu`` 里创建并随 exec 结束销毁，宿主没有
        # 句柄可连「重命名 / 属性」—— 画布转发出同名信号（自身不实现行为）
        menu.rename_requested.connect(self.node_rename_requested)
        menu.properties_requested.connect(self.node_properties_requested)
        # 走 ``execElaMenu``：它在 ``exec_`` 前 ``setMinimumSize(sizeHint())``，
        # 兜住「非主屏上 ElaMenu 偶发只显示第一项」，返回后再回收
        execElaMenu(menu, global_pos)

    def _open_edge_menu(self, edge_id: str, global_pos: QPoint) -> None:
        """连线右键菜单：删除（右键连线时由交互层调用）。"""
        if self.graph.edge(edge_id) is None:
            return
        menu = ElaEdgeContextMenu(edge_id, self)
        menu.delete_requested.connect(self.graph.remove_edge)
        execElaMenu(menu, global_pos)

    def _duplicate_node(self, node_id: str) -> None:
        """右键菜单「复制」：复制单节点并选中副本。"""
        node = self.graph.node(node_id)
        if node is None:
            return
        copy = self._clone_node(node)
        self.graph.add_node(copy)
        self.select_nodes([copy.id])

    @staticmethod
    def _clone_node(node: ElaBlueprintNode) -> ElaBlueprintNode:
        """复制节点数据（新 id、位置错开 24px），不自动入图。"""
        data = node.to_dict()
        data.pop("id", None)
        copy = ElaBlueprintNode.from_dict(data)
        copy.pos = node.pos + QPointF(24.0, 24.0)
        return copy

    # 流动动画
    def _ensure_flow_timer(self) -> None:
        # 持续动效：Reduced/Disabled 下不流动。停掉时虚线相位冻结在当前值 ——
        # 边线仍然是流动虚线图案，只是不动，所以不需要摆姿态钩子。
        start_idle_loop(self._flow_timer, EDGE_FLOW_TICK_MS)

    def _tick_flow(self) -> None:
        any_flowing = False
        rects = []
        for ew in self._edge_widgets.values():
            if ew.flowing:
                ew.advance_dash()
                rects.append(ew.bounding_rect())
                any_flowing = True
        if not any_flowing:
            self._flow_timer.stop()
            return
        # 仅重绘流动边的包围盒
        self._update_scene_rects(rects)

    # 绘制（由内部视口承载，见 viewport.py）
    def paintEvent(self, _event) -> None:
        # 画布本体被视口 1:1 覆盖；此处仅在视口尚未就位时兜底填底。
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(str(T("color.bg.base"))))
        p.end()

    def resizeEvent(self, event) -> None:
        """视口几何同步：始终与画布 1:1 重合。"""
        vp = getattr(self, "_viewport", None)
        if vp is not None:
            vp.setGeometry(self.rect())
        super().resizeEvent(event)

    def update(self, *args) -> None:
        """重绘请求转发到内部绘制视口（保持外部 ``canvas.update()`` 习惯）。"""
        vp = getattr(self, "_viewport", None)
        if vp is not None:
            vp.update(*args)
        else:
            super().update(*args)

    def _paint_contents(self, p: QPainter, dirty_view: QRect = None) -> None:
        """画布全部自绘内容：背景 / 网格 / 选中发光 / 边 / 临时线 / 框选。

        ``dirty_view`` 是控件坐标的局部重绘脏矩形，``None`` 表示整幅。
        """
        p.fillRect(self.rect(), QColor(str(T("color.bg.base"))))
        self._draw_grid(p)
        self._draw_selection_glow(p)
        if dirty_view is not None and not dirty_view.isNull():
            tl = self.view_to_scene(QPointF(dirty_view.topLeft()))
            br = self.view_to_scene(QPointF(dirty_view.bottomRight()))
        else:
            tl = self.view_to_scene(QPointF(0.0, 0.0))
            br = self.view_to_scene(QPointF(self.width(), self.height()))
        dirty_scene = QRectF(tl, br).normalized()
        p.save()
        p.translate(self._offset)
        p.scale(self._zoom, self._zoom)
        visible_edges = [
            ew
            for ew in self._edge_widgets.values()
            if ew.bounding_rect().intersects(dirty_scene)
        ]
        # 两趟：先全部线，再全部标签 —— 后面的边线不会盖住前面的标签
        for ew in visible_edges:
            ew.draw(p, label=False)
        for ew in visible_edges:
            ew.draw_label(p)
        if self._wire is not None:
            self._wire.draw(p)
            if self._wire_target is not None:
                nid, pin = self._wire_target
                c = self.pin_scene_pos(nid, pin.id, pin.direction)
                p.setPen(_cached_pen(_cached_color(str(T("color.primary"))), 2.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, 9.0, 9.0)
        p.restore()
        if self._band is not None:
            rect = QRectF(self._band[0], self._band[1]).normalized()
            # _cached_color 返回副本，setAlpha 原地修改不影响缓存条目
            fill = _cached_color(str(T("color.primary")))
            fill.setAlpha(28)
            border = _cached_color(str(T("color.primary")))
            border.setAlpha(140)
            p.setPen(QPen(border, 1.2))
            p.setBrush(fill)
            p.drawRect(rect)

    def _update_scene_rects(self, scene_rects) -> None:
        """按场景坐标矩形列表请求局部重绘（换算视图坐标后逐个提交）。"""
        self._update_view_rects(
            QRectF(
                self.scene_to_view(r.topLeft()), self.scene_to_view(r.bottomRight())
            ).normalized()
            for r in scene_rects
            if r is not None and not r.isNull()
        )

    def _update_view_rects(self, view_rects) -> None:
        """按视图坐标矩形逐个请求重绘（每块自带 2px 描边余量）。
        逐矩形提交而不是合并成一个大矩形：多选拖动 / 多条流动边分散在画布
        两端时，合并会退化成整幅重绘。
        """
        for r in view_rects:
            if r is None or r.isNull():
                continue
            rect = r.adjusted(-2.0, -2.0, 2.0, 2.0)
            self.update(rect.toAlignedRect().intersected(self.rect()))

    def _node_view_rect(self, node) -> QRectF:
        """节点在视图坐标下的矩形（与控件几何同口径）。"""
        return QRectF(
            self.scene_to_view(node.pos),
            QSizeF(node.size.width() * self._zoom, node.size.height() * self._zoom),
        )

    def _node_repaint_view_rect(self, node) -> QRectF:
        """节点重绘区域：节点矩形 + 选中发光外扩（视图坐标）。
        光晕由画布层自绘、超出节点控件矩形：节点移动时只依赖 Qt 对子控件
        移动的自动失效（控件自身旧 / 新矩形）会留下旧位置的光晕残影。
        """
        pad = _selection_glow_pad()
        return self._node_view_rect(node).adjusted(-pad, -pad, pad, pad)

    def _draw_selection_glow(self, p: QPainter) -> None:
        """选中节点的外发光（画布层自绘，替代 QGraphicsEffect）。

        以多层递增外扩的圆角描边逼近高斯模糊：透明度由近及远递减。
        """
        if not self._selected_nodes:
            return
        spec = shadow_md()
        r, g, b, a = spec["color"]
        blur = float(spec["blur"])
        ox, oy = spec["offset"]
        steps, pen_w = _glow_steps(blur)
        base_radius = float(T("radius.lg")) * self._zoom
        p.setBrush(Qt.BrushStyle.NoBrush)
        for nid in self._selected_nodes:
            node = self.graph.node(nid)
            if node is None:
                continue
            tl = self.scene_to_view(node.pos)
            rect = QRectF(
                tl,
                QSizeF(node.size.width() * self._zoom, node.size.height() * self._zoom),
            )
            rect.translate(float(ox), float(oy))
            for i in range(steps):
                t = (i + 0.5) / steps
                grow = t * blur * 0.75
                alpha = int(a * (1.0 - t) * 0.9)
                if alpha <= 0:
                    continue
                pen = QPen(QColor(r, g, b, alpha), pen_w)
                p.setPen(pen)
                rr = rect.adjusted(-grow, -grow, grow, grow)
                rad = base_radius + grow
                p.drawRoundedRect(rr, rad, rad)

    # 网格（平铺纹理缓存）
    def _grid_tile(self, step_px: float) -> QPixmap:
        """网格平铺块（按 间距档位 / 颜色 / DPR 缓存）。

        块内四角各绘 1/4 圆点，平铺拼接后每个网格交叉点合成完整圆点。
        """
        dpr = self.devicePixelRatioF()
        si = max(2, int(round(step_px)))
        color = QColor(str(T("color.border")))
        key = (si, color.rgba(), dpr)
        if self._grid_tile_key == key and self._grid_tile_cache is not None:
            return self._grid_tile_cache
        pm = QPixmap(max(1, int(si * dpr + 0.5)), max(1, int(si * dpr + 0.5)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        tp = QPainter(pm)
        tp.setRenderHint(QPainter.RenderHint.Antialiasing)
        tp.setPen(Qt.PenStyle.NoPen)
        tp.setBrush(color)
        side = pm.width() / dpr
        for cx, cy in ((0.0, 0.0), (side, 0.0), (0.0, side), (side, side)):
            tp.drawEllipse(QPointF(cx, cy), GRID_DOT_R, GRID_DOT_R)
        tp.end()
        self._grid_tile_key = key
        self._grid_tile_cache = pm
        return pm

    def _grid_scene_step(self) -> float:
        """当前缩放下点阵网格的场景间距（屏幕间距保持 18–72px）。"""
        step = self._grid_step
        while step * self._zoom < 18.0:
            step *= 2.0
        while step * self._zoom > 72.0:
            step /= 2.0
        return step

    def _draw_grid(self, p: QPainter) -> None:
        """点阵网格：间距随缩放自适应（屏幕间距保持在 18–72px 之间）。"""
        step = self._grid_scene_step()
        tile = self._grid_tile(step * self._zoom)
        side = tile.width() / tile.devicePixelRatioF()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(tile))
        p.setBrushOrigin(QPointF(self._offset.x() % side, self._offset.y() % side))
        p.drawRect(self.rect())
