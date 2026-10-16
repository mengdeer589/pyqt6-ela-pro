"""
蓝图节点图编辑器画布。

``ElaBlueprintCanvas`` 是节点图编辑器的主控件：

- 平移：中键拖拽 / 空格+左键拖拽 / 右键拖拽空白（右键抬起位移 <4px
  弹 ``ElaNodeCreationMenu``）；
- 缩放：滚轮以光标为中心，0.25x–2.5x；
- 背景：主题感知点阵网格，间距随缩放自适应疏密；
- 选择：Ctrl+点选多选、空白左键橡皮筋框选（半透明）；
- Delete 删除选中节点（连带边）与选中边；
- 连线：引脚按下拖出贝塞尔临时线 → 磁吸高亮兼容引脚 → 松开经
  ``graph.add_edge`` 校验建边；拖到空白松开 → 创建菜单，创建后自动连接；
- 边：hover 加粗、点击选中、running 路径 flowing 虚线动画；
- 序列化：``to_dict`` / ``from_dict``（含节点位置与画布 zoom/offset）。

节点为真实子控件（``ElaNodeWidget``，挂在内部绘制视口之下）；边、临时线、
网格、选中发光由视口统一自绘——**默认软件视口**（``QWidget``），设
``ELABLUEPRINT_GL=on`` 才用 ``QOpenGLWidget``（GPU 加速；它是原生子窗口，
须在 ``window.show()`` 之前构建画布，否则顶层 HWND 会被重建、窗口闪一下，
见 ``viewport.py`` 与 ``docs/performance.md``）。

移植自 InstructionX_UIKit.blueprint.canvas（原库为 PyQt6，
类名 Ela* 前缀；主题令牌经 blueprint._tokens 适配 eTheme；原库无 LICENSE，
保留出处）。
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QEvent,
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
    ElaTempWire,
    _cached_color,
    _cached_pen,
    bezier_path,
)
from .execution import ElaExecutionController
from .menu import ElaNodeContextMenu, ElaNodeCreationMenu
from .model import (
    ElaBlueprintGraph,
    ElaBlueprintNode,
    ElaEdge,
    ElaPinDirectionType,
    _finite,
    types_compatible,
)
from .node_widget import ElaNodeWidget, ElaPinHandle
from .registry import ElaNodeRegistry
from .viewport import create_viewport

__all__ = ["ElaBlueprintCanvas"]

logger = logging.getLogger(__name__)

#: 缩放范围
ZOOM_MIN, ZOOM_MAX = 0.25, 2.5
#: 流动边线虚线相位的推进间隔（ms）。持续动效，Reduced/Disabled 下冻结。
EDGE_FLOW_TICK_MS = 50
#: 磁吸半径（视图像素）
MAGNET_R = 22.0
#: 右键抬起判定为点击的位移阈值（px）
CLICK_TOL = 4.0
#: 背景网格点半径（视图像素）
GRID_DOT_R = 1.3


class ElaBlueprintCanvas(QWidget):
    """蓝图节点图画布控件。

    :param graph: ``ElaBlueprintGraph`` 数据图（节点 / 边变化自动同步到界面）
    :param parent: 父控件
    :param owner: 注册表命名空间标识（缺省 None）；给定时节点创建 /
        创建菜单 / 节点体解析范围均为「该 owner + 全局」

    信号:
        node_moved(str, QPointF): 节点拖动结束（节点 id + 新场景坐标）。
        node_rename_requested(str): 右键菜单「重命名」（画布本身不实现，
            由宿主接住）。
        node_properties_requested(str): 右键菜单「属性…」（同上）。
        edge_created(object): 新边建立（``ElaEdge``，含菜单自动连接产生的）。
        edge_removed(str): 边被移除（边 id）。
        selection_changed(list): 选中节点 id 列表变化。

    交互注记（节点体是可交互的）：``body_builder`` 注入的节点体容器不会被
    置为鼠标透明 —— 体里的控件（输入框 / 按钮…）正常接收自己的鼠标事件；
    体空白处按下会冒泡到节点控件，照常选中 / 拖动节点；标题栏、引脚行与
    体空白处都是拖动区。也就是说「控件吃掉自己的事件、其余区域拖动节点」，
    不需要也不能靠 ``WA_TransparentForMouseEvents`` 换取拖动能力（置透明
    等于把体里的控件全部变成装饰）。
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
        self._zoom_settle.timeout.connect(self._end_zoom_gesture)

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
        # 绑定方法连接：receiver（本画布）销毁时 Qt 自动断连
        theme_changed_slot(self, self._retheme)

        for node in graph.nodes():
            self._on_node_added(node)
        for edge in graph.edges():
            self._on_edge_added(edge)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def add_node_at(self, type_name: str, scene_pos: QPointF) -> ElaBlueprintNode:
        """经注册表创建节点并放置到场景坐标，返回 ``ElaBlueprintNode``。

        按画布 ``owner`` 解析类型（「本 owner + 全局」范围）。
        """
        node = ElaNodeRegistry.instance().create(type_name, owner=self._owner)
        node.pos = QPointF(scene_pos)
        self.graph.add_node(node)
        return node

    def add_node(
        self, node: ElaBlueprintNode, scene_pos: QPointF = None
    ) -> ElaBlueprintNode:
        """直接把既有 ``ElaBlueprintNode`` 放入图（可选指定场景坐标）。"""
        if scene_pos is not None:
            node.pos = QPointF(scene_pos)
        self.graph.add_node(node)
        return node

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

    def center_on(self, node_id: str) -> None:
        """把视图中心对准某节点（缩放不变）。"""
        self._settle_view_gesture()
        node = self.graph.node(node_id)
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

    # -- 部件访问 ---------------------------------------------------------
    def node_widget(self, node_id: str):
        """按节点 id 取 ``ElaNodeWidget``，不存在返回 ``None``。"""
        return self._node_widgets.get(node_id)

    def edge_widget(self, edge_id: str):
        """按边 id 取 ``ElaEdgeWidget``，不存在返回 ``None``。"""
        return self._edge_widgets.get(edge_id)

    def pin_scene_pos(self, node_id: str, pin_id: str, direction=None) -> QPointF:
        """引脚圆心的场景坐标（找不到时回退节点左上角）。"""
        widget = self._node_widgets.get(node_id)
        node = self.graph.node(node_id)
        if widget is not None and node is not None:
            pin = node.pin(pin_id, direction)
            if pin is not None:
                return node.pos + widget.pin_logical_center(pin)
        return QPointF(node.pos) if node is not None else QPointF()

    def selected_nodes(self) -> list:
        """当前选中节点 id 列表。"""
        return list(self._selected_nodes)

    def selected_edges(self) -> list:
        """当前选中边 id 列表。"""
        return list(self._selected_edges)

    # -- 坐标换算 ---------------------------------------------------------
    def scene_to_view(self, pt: QPointF) -> QPointF:
        """场景坐标 → 视图（控件）坐标。"""
        return pt * self._zoom + self._offset

    def view_to_scene(self, pt: QPointF) -> QPointF:
        """视图（控件）坐标 → 场景坐标。"""
        return (QPointF(pt) - self._offset) / self._zoom

    # -- 序列化 -----------------------------------------------------------
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
        """从 ``to_dict`` 结果恢复：重建节点 / 边并还原 zoom 与 offset。

        **整体容错**（与 chat 的序列化契约一致）：这是宿主「加载文件」
        这类 Qt 槽里最常见的入口，脏数据 / 旧版格式抛出去 = 槽内异常 =
        0xC0000409 零 traceback 终止。所以坏节点 / 坏边**逐条跳过并记
        WARNING**，而不是让整张图载入失败：

        1. **边必须走 ``graph.add_edge()``**。直接往 ``graph._edges`` 里塞
           会跳过 ``add_edge`` 的全量校验（方向 / 类型兼容 / 存在性 /
           单连接替换 / id 冲突），于是「文件里引脚已经被改名」这类脏数据
           会还原成一批**指向幽灵引脚的边** —— 它们照样进 ``_edge_widgets``、
           照样被绘制与命中，只是两端都退化成默认点，表现为「有根看不见
           的线」，而且删不掉（``delete_selection`` 只按 id 删边）。
        2. **必须复位执行态**。``graph.clear()`` 只发移除信号，不碰节点的
           ``status`` / ``elapsed_ms`` / ``error_message``；而 ``to_dict``
           并不序列化这三项，所以复用同一批节点对象时上一轮的「运行中」
           徽标会留在刚载入的图上。
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
            added = self.graph.add_edge(
                raw.from_node,
                raw.from_pin,
                raw.to_node,
                raw.to_pin,
                edge_id=raw.id,
            )
            if added is None:
                logger.warning(
                    "跳过非法连线 %r（引脚缺失 / 类型不兼容 / id 冲突）", raw.id
                )
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

    # ------------------------------------------------------------------
    # 图信号 → 界面同步
    # ------------------------------------------------------------------
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

    def _on_edge_removed(self, edge_id: str) -> None:
        widget = self._edge_widgets.pop(edge_id, None)
        if widget is not None:
            widget.deleteLater()
        if edge_id in self._selected_edges:
            self._selected_edges.remove(edge_id)
        self.edge_removed.emit(edge_id)
        self.update()

    def _node_layout_changed(self, node_widget: ElaNodeWidget) -> None:
        """节点尺寸变化（属性 / 引脚变化）后重新落位。"""
        node_widget.apply_view(self.scene_to_view(node_widget.node.pos), self._zoom)

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

    # ------------------------------------------------------------------
    # 选择
    # ------------------------------------------------------------------
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

    def select_nodes(self, node_ids, additive: bool = False) -> None:
        """选中节点（``additive`` 为 Ctrl 语义：并入现有选择）。"""
        if not additive:
            self.clear_selection()
        changed = False
        for nid in node_ids:
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

    def toggle_node_selected(self, node_id: str) -> None:
        """Ctrl 点选：切换单个节点的选中态。"""
        if node_id in self._selected_nodes:
            self._selected_nodes.remove(node_id)
            w = self._node_widgets.get(node_id)
            if w is not None:
                w.set_selected(False)
        else:
            self._selected_nodes.append(node_id)
            w = self._node_widgets.get(node_id)
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

    # ------------------------------------------------------------------
    # 事件过滤（节点控件 / 引脚热区）
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        etype = event.type()
        if etype not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseMove,
        ):
            return False
        # 平移进行中：事件此时可能落在节点 / 引脚热区上（中键或空格+左键
        # 从它们上面起手，隐式 grab 留在子控件），统一在这里推进 / 收尾。
        if self._panning:
            if etype == QEvent.Type.MouseMove:
                self._offset = self._offset_start + (
                    self.view_pos_of_event(obj, event) - self._pan_start
                )
                self._view_changed(gesture=True)
                return True
            if (
                etype == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._panning = False
                self.unsetCursor()
                self._settle_view_gesture()
                return True
            return False
        if isinstance(obj, ElaPinHandle):
            if (
                etype == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                if self._space_down:
                    # 空格 = 强制平移：按在引脚上也不起拖线
                    self._start_pan(self.view_pos_of_event(obj, event))
                    return True
                self._begin_wire(obj)
                return True
            if self._wire is not None:
                if etype == QEvent.Type.MouseMove:
                    self._update_wire(self.view_pos_of_event(obj, event))
                    return True
                if (
                    etype == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    self._finish_wire(self.view_pos_of_event(obj, event))
                    return True
            return False
        if isinstance(obj, ElaNodeWidget):
            if etype == QEvent.Type.MouseButtonPress:
                view_pos = self.view_pos_of_event(obj, event)
                if event.button() == Qt.MouseButton.LeftButton:
                    if self._space_down:
                        # 空格 = 强制平移：按在节点上也不拖节点
                        self._start_pan(view_pos)
                        return True
                    self._node_press(obj, view_pos, event.modifiers())
                    return True
                if event.button() == Qt.MouseButton.RightButton:
                    self._rpress = (view_pos, obj)
                    self._rpan = False
                    self._pan_start = QPointF(view_pos)
                    self._offset_start = QPointF(self._offset)
                    return True
            if etype == QEvent.Type.MouseMove:
                view_pos = self.view_pos_of_event(obj, event)
                if self._drag is not None:
                    self._drag_to(view_pos)
                    return True
                if (
                    self._rpress is not None
                    and event.buttons() & Qt.MouseButton.RightButton
                ):
                    # 节点上右键拖拽平移：与空画布右键拖拽行为一致
                    start, _target = self._rpress
                    if (QPointF(view_pos) - start).manhattanLength() > CLICK_TOL:
                        self._rpan = True
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    if self._rpan:
                        self._offset = self._offset_start + (
                            QPointF(view_pos) - self._pan_start
                        )
                        self._view_changed(gesture=True)
                    return True
            if etype == QEvent.Type.MouseButtonRelease:
                view_pos = self.view_pos_of_event(obj, event)
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and self._drag is not None
                ):
                    self._end_drag()
                    return True
                if (
                    event.button() == Qt.MouseButton.RightButton
                    and self._rpress is not None
                ):
                    target_node = self._rpress[1]
                    was_pan = self._rpan
                    self._rpress = None
                    self._rpan = False
                    if was_pan:
                        # 平移结束：恢复光标并结算手势（补偿节点几何落位）
                        self.unsetCursor()
                        self._settle_view_gesture()
                    elif target_node is obj:
                        self._open_node_menu(obj, event.globalPosition().toPoint())
                    return True
        return False

    def view_pos_of_event(self, obj, event) -> QPointF:
        """把子控件上的事件坐标换算为画布视图坐标。"""
        return QPointF(obj.mapTo(self, event.position().toPoint()))

    # -- 节点拖动 ---------------------------------------------------------
    def _node_press(self, widget: ElaNodeWidget, view_pos: QPointF, modifiers) -> None:
        nid = widget.node.id
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self.toggle_node_selected(nid)
        elif nid not in self._selected_nodes:
            self.select_nodes([nid])
        if nid in self._selected_nodes:
            starts = {
                i: QPointF(self.graph.node(i).pos)
                for i in self._selected_nodes
                if self.graph.node(i)
            }
            self._drag = (QPointF(view_pos), starts)
            self._drag_moved = False

    def _drag_to(self, view_pos: QPointF) -> None:
        start_view, starts = self._drag
        delta = (QPointF(view_pos) - start_view) / self._zoom
        if not self._drag_moved and delta.manhattanLength() * self._zoom < 2.0:
            return
        self._drag_moved = True
        defer = bool(getattr(self._viewport, "supports_node_proxy", False))
        # 受影响边（两端任一在被拖节点上）的旧包围盒仅软件模式的局部
        # 重绘需要；GL 代理模式整幅重绘，跳过该统计开销
        affected = []
        old_rects = []
        if not defer:
            for nid in starts:
                for e in self.graph.edges_of(nid):
                    ew = self._edge_widgets.get(e.id)
                    if ew is not None and ew not in affected:
                        affected.append(ew)
                        old_rects.append(ew.bounding_rect())
        for nid, start_pos in starts.items():
            node = self.graph.node(nid)
            if node is None:
                continue
            node.pos = start_pos + delta
            w = self._node_widgets.get(nid)
            if w is not None and defer:
                # 带可见自定义体的被拖节点同样切换手势位图代理（幂等）
                w.begin_gesture_proxy()
            # 位图代理节点由视口按场景坐标实时绘制，拖动期间无需逐帧落位
            if w is not None and not (defer and w.uses_proxy()):
                w.apply_view(self.scene_to_view(node.pos), self._zoom)
        if defer:
            self._gesture_deferred = True
            self.update()
        else:
            # 局部重绘：边的新旧包围盒即可（节点控件自行随几何移动重绘）
            self._update_scene_rects(
                old_rects + [ew.bounding_rect() for ew in affected]
            )

    def _end_drag(self) -> None:
        start_view, starts = self._drag
        self._drag = None
        if self._drag_moved:
            for nid in starts:
                node = self.graph.node(nid)
                if node is not None:
                    self.node_moved.emit(nid, QPointF(node.pos))
        self._drag_moved = False
        # 拖动中跳过的代理节点几何落位补偿（引脚热区恢复精确）
        self._settle_view_gesture()

    # ------------------------------------------------------------------
    # 连线（引脚拖拽）
    # ------------------------------------------------------------------
    def _begin_wire(self, handle: ElaPinHandle) -> None:
        pin = handle.pin
        node = handle.node_widget.node
        start = node.pos + handle.logical_center()
        self._wire = ElaTempWire(start, pin.data_type, parent=self)
        self._wire_src = (node.id, pin)
        self._wire_target = None
        self._update_scene_rects([self._wire_scene_rect(self._wire)])

    def _wire_scene_rect(self, wire: ElaTempWire) -> QRectF:
        """临时线（含端点小圆点与描边余量）的场景包围盒。"""
        r = bezier_path(wire.start, wire.end).boundingRect()
        return r.adjusted(-12.0, -12.0, 12.0, 12.0)

    def _wire_ring_rect(self, target) -> QRectF:
        """磁吸高亮圈的场景包围盒（无目标时返回空矩形）。"""
        if target is None:
            return QRectF()
        nid, pin = target
        c = self.pin_scene_pos(nid, pin.id, pin.direction)
        return QRectF(c - QPointF(12.0, 12.0), QSizeF(24.0, 24.0))

    def _update_wire(self, view_pos: QPointF) -> None:
        old_rects = [
            self._wire_scene_rect(self._wire),
            self._wire_ring_rect(self._wire_target),
        ]
        scene_pt = self.view_to_scene(view_pos)
        self._wire.set_end(scene_pt)
        self._wire_target = self._find_compatible_pin(scene_pt)
        self._wire.magnet = self._wire_target is not None
        if self._wire_target is not None:
            nid, pin = self._wire_target
            self._wire.set_end(self.pin_scene_pos(nid, pin.id, pin.direction))
        self._update_scene_rects(
            old_rects
            + [
                self._wire_scene_rect(self._wire),
                self._wire_ring_rect(self._wire_target),
            ]
        )

    def _find_compatible_pin(self, scene_pt: QPointF):
        """在磁吸半径内找最近的兼容引脚（方向相反 + 类型兼容 + 非本节点）。"""
        src_nid, src_pin = self._wire_src
        want_dir = (
            ElaPinDirectionType.Input
            if src_pin.direction is ElaPinDirectionType.Output
            else ElaPinDirectionType.Output
        )
        radius = MAGNET_R / self._zoom
        probe = QRectF(scene_pt, scene_pt).adjusted(-radius, -radius, radius, radius)
        best = None
        best_d = radius
        for nid, widget in self._node_widgets.items():
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
                c = self.pin_scene_pos(nid, pin.id, pin.direction)
                d = (c - scene_pt).manhattanLength()
                if d < best_d:
                    best = (nid, pin)
                    best_d = d
        return best

    def _finish_wire(self, view_pos: QPointF) -> None:
        src_nid, src_pin = self._wire_src
        target = self._find_compatible_pin(self.view_to_scene(view_pos))
        wire, self._wire, self._wire_src, self._wire_target = (
            self._wire,
            None,
            None,
            None,
        )
        dirty = []
        if wire is not None:
            dirty.append(self._wire_scene_rect(wire))
            wire.deleteLater()
        if target is not None:
            dirty.append(self._wire_ring_rect(target))
            tgt_nid, tgt_pin = target
            if src_pin.direction is ElaPinDirectionType.Output:
                self.graph.add_edge(src_nid, src_pin.id, tgt_nid, tgt_pin.id)
            else:
                self.graph.add_edge(tgt_nid, tgt_pin.id, src_nid, src_pin.id)
        else:
            # 拖到空白松开：弹创建菜单，创建后自动连接（UE5 行为）
            scene_pt = self.view_to_scene(view_pos)
            self._pending_wire = (src_nid, src_pin, scene_pt)
            menu = ElaNodeCreationMenu(self, owner=self._owner)
            want_dir = (
                ElaPinDirectionType.Input
                if src_pin.direction is ElaPinDirectionType.Output
                else ElaPinDirectionType.Output
            )
            menu.type_chosen.connect(self._create_node_for_wire)
            menu.popup_at(
                self.mapToGlobal(QPoint(int(view_pos.x()), int(view_pos.y()))),
                compatible=(want_dir, src_pin.data_type),
            )
        if dirty:
            self._update_scene_rects(dirty)

    def _create_node_for_wire(self, type_name: str) -> None:
        """拖线松开菜单回调：创建节点并自动连接对应引脚。"""
        pending = self._pending_wire
        self._pending_wire = None
        if pending is None:
            return
        src_nid, src_pin, scene_pt = pending
        node = self.add_node_at(type_name, scene_pt)
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
                self.graph.add_edge(src_nid, src_pin.id, node.id, pin.id)
            else:
                self.graph.add_edge(node.id, pin.id, src_nid, src_pin.id)
            break

    # ------------------------------------------------------------------
    # 画布鼠标事件（空白区）
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        pos = QPointF(event.position().toPoint())
        if event.button() == Qt.MouseButton.MiddleButton:
            self._start_pan(pos)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._space_down:
                self._start_pan(pos)
                return
            hit = self._edge_at(self.view_to_scene(pos))
            if hit is not None:
                self._select_edge(
                    hit, bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                )
                return
            self._band = (pos, pos)
            self._band_additive = bool(
                event.modifiers() & Qt.KeyboardModifier.ControlModifier
            )
            if not self._band_additive:
                self.clear_selection()
            self.update()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._rpress = (pos, None)
            self._rpan = False
            self._pan_start = QPointF(pos)
            self._offset_start = QPointF(self._offset)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.position().toPoint())
        if self._wire is not None:
            # 拖线中：某些平台事件直接投递到画布而非引脚热区
            self._update_wire(pos)
            return
        if self._panning:
            self._offset = self._offset_start + (pos - self._pan_start)
            self._view_changed(gesture=True)
            return
        if self._rpress is not None and event.buttons() & Qt.MouseButton.RightButton:
            start, _target = self._rpress
            if (pos - start).manhattanLength() > CLICK_TOL:
                self._rpan = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self._rpan:
                self._offset = self._offset_start + (pos - self._pan_start)
                self._view_changed(gesture=True)
            return
        if self._band is not None:
            old_rect = QRectF(self._band[0], self._band[1]).normalized()
            self._band = (self._band[0], pos)
            new_rect = QRectF(self._band[0], self._band[1]).normalized()
            dirty = old_rect.united(new_rect).adjusted(-3.0, -3.0, 3.0, 3.0)
            self.update(dirty.toAlignedRect().intersected(self.rect()))
            return
        self._update_edge_hover(self.view_to_scene(pos))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pos = QPointF(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and self._wire is not None:
            self._finish_wire(pos)
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            self._settle_view_gesture()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._panning:
                self._panning = False
                self.unsetCursor()
                self._settle_view_gesture()
                return
            if self._band is not None:
                self._finish_band()
                return
        if event.button() == Qt.MouseButton.RightButton and self._rpress is not None:
            was_pan = self._rpan
            self._rpress = None
            self._rpan = False
            if was_pan:
                self._panning = False
                self.unsetCursor()
                self._settle_view_gesture()
            else:
                scene_pt = self.view_to_scene(pos)
                menu = ElaNodeCreationMenu(self, owner=self._owner)
                menu.type_chosen.connect(lambda t, sp=scene_pt: self.add_node_at(t, sp))
                menu.popup_at(event.globalPosition().toPoint())
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 ** (delta / 120.0)
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        cursor = event.position()
        self._offset = cursor - (cursor - self._offset) * (new_zoom / self._zoom)
        self._zoom = new_zoom
        self._view_changed(gesture=True)
        self._zooming = True
        self._zoom_settle.start()
        event.accept()

    def _end_zoom_gesture(self) -> None:
        """滚轮缩放手势结束：补偿几何落位并触发节点缓存按最终缩放重建。"""
        self._zooming = False
        self._settle_view_gesture()
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selection()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            if self._panning:
                self._panning = False
                self.unsetCursor()
                # 空格提前松开也必须完整结算（与左键松开路径一致）
                self._settle_view_gesture()
            return
        super().keyReleaseEvent(event)

    # -- 平移 / 框选 -------------------------------------------------------
    def _cancel_gestures(self) -> None:
        """复位所有「按住类」手势状态（失焦 / 隐藏 / 载入新图时调用）。

        这些状态**只由成对的按下-松开维护**，而松开事件在若干情况下根本
        不会到达：

        - 按住空格后 Alt+Tab / 点到别的控件 → ``focusOutEvent`` 之后没有
          ``keyRelease``，``_space_down`` 永远True → **之后每次左键都变成
          平移，框选彻底失效**（实测）；
        - 框选进行中失焦 → ``_band`` 的起点留在上一个位置，下次鼠标移动
          会对着它画框（实测）。

        顺带把 ``_rpress`` / ``_wire`` 一起清掉：它们会与 ``_band`` 并存
        （框选中按下右键时两者同时非None），松右键会弹创建菜单而框选状态
        继续挂着。临时线要**回收对象**（``deleteLater``）并清掉端点邻居
        状态 —— 只把 ``_wire`` 置 None 会让 ``ElaTempWire`` 永久挂在画布
        底下，``_wire_src`` / ``_wire_target`` 也停在上一笔上。
        """
        self._space_down = False
        self._band = None
        self._band_additive = False
        self._rpress = None
        self._rpan = False
        if self._wire is not None:
            self._wire.deleteLater()
        self._wire = None
        self._wire_src = None
        self._wire_target = None
        self._pending_wire = None
        if self._panning:
            self._panning = False
            self.unsetCursor()

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

    def _start_pan(self, view_pos: QPointF) -> None:
        self._panning = True
        self._pan_start = QPointF(view_pos)
        self._offset_start = QPointF(self._offset)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _finish_band(self) -> None:
        start, end = self._band
        self._band = None
        rect = QRectF(self.view_to_scene(start), self.view_to_scene(end)).normalized()
        ids = []
        if rect.width() > 2 / self._zoom or rect.height() > 2 / self._zoom:
            for nid, widget in self._node_widgets.items():
                node = widget.node
                if rect.intersects(QRectF(node.pos, node.size)):
                    ids.append(nid)
        if ids:
            self.select_nodes(ids, additive=self._band_additive)
        self.update()

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

    # -- 边 hover / 命中 ---------------------------------------------------
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

    # -- 节点右键菜单 ------------------------------------------------------
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

    def _duplicate_node(self, node_id: str) -> None:
        """默认复制实现：同类型新节点 + 拷贝属性，位置错开 24px。"""
        node = self.graph.node(node_id)
        if node is None:
            return
        data = node.to_dict()
        data.pop("id", None)
        copy = ElaBlueprintNode.from_dict(data)
        copy.pos = node.pos + QPointF(24.0, 24.0)
        self.graph.add_node(copy)
        self.select_nodes([copy.id])

    # ------------------------------------------------------------------
    # 流动动画
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 绘制（由内部视口承载，见 viewport.py）
    # ------------------------------------------------------------------
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
        for ew in self._edge_widgets.values():
            if not ew.bounding_rect().intersects(dirty_scene):
                continue
            ew.draw(p)
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
        """按场景坐标矩形列表请求局部重绘（换算视图坐标并合并求并集）。"""
        rect = None
        for r in scene_rects:
            if r is None or r.isNull():
                continue
            vr = QRectF(
                self.scene_to_view(r.topLeft()), self.scene_to_view(r.bottomRight())
            ).normalized()
            vr = vr.adjusted(-2.0, -2.0, 2.0, 2.0)
            rect = vr if rect is None else rect.united(vr)
        if rect is not None:
            self.update(rect.toAlignedRect().intersected(self.rect()))

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
        steps = max(3, int(blur / 2))
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
                pen = QPen(QColor(r, g, b, alpha), max(1.0, blur / steps + 0.5))
                p.setPen(pen)
                rr = rect.adjusted(-grow, -grow, grow, grow)
                rad = base_radius + grow
                p.drawRoundedRect(rr, rad, rad)

    # ------------------------------------------------------------------
    # 网格（平铺纹理缓存）
    # ------------------------------------------------------------------
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

    def _draw_grid(self, p: QPainter) -> None:
        """点阵网格：间距随缩放自适应（屏幕间距保持在 18–72px 之间）。"""
        step = 24.0
        while step * self._zoom < 18.0:
            step *= 2.0
        while step * self._zoom > 72.0:
            step /= 2.0
        tile = self._grid_tile(step * self._zoom)
        side = tile.width() / tile.devicePixelRatioF()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(tile))
        p.setBrushOrigin(QPointF(self._offset.x() % side, self._offset.y() % side))
        p.drawRect(self.rect())
