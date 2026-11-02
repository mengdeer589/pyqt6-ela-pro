"""
蓝图数据模型（纯数据与信号，不涉及界面绘制）。

- ``ElaPinDirectionType`` / ``ElaPin``：引脚方向与引脚描述；
- ``ElaEdge``：一条输出引脚到输入引脚的连线；
- ``ElaBlueprintNode``：节点（引脚、属性、运行状态、耗时），可 JSON 序列化；
- ``ElaBlueprintGraph``：图容器，负责增删查与 ``add_edge`` 全量校验
  （方向相反、类型兼容含 any 通配、单连接替换、禁止自连 / 重复）。

移植自 InstructionX_UIKit.blueprint.model（原库为 PyQt6，
类名 Ela* 前缀；原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

import logging
import math
import uuid
import weakref
from dataclasses import dataclass
from enum import Enum

from PyQt6.QtCore import QObject, QPointF, QSizeF, pyqtSignal

logger = logging.getLogger(__name__)

__all__ = [
    "ElaPinDirectionType",
    "ElaPin",
    "ElaEdge",
    "ElaBlueprintNode",
    "ElaBlueprintGraph",
    "types_compatible",
]


def _new_id() -> str:
    """生成短随机 id（节点 / 边通用）。"""
    return uuid.uuid4().hex[:12]


class ElaPinDirectionType(Enum):
    """引脚方向：``Input`` 输入 / ``Output`` 输出。"""

    Input = "input"
    Output = "output"


def types_compatible(out_type: str, in_type: str) -> bool:
    """判断输出类型与输入类型是否兼容（``"any"`` 双向通配）。"""
    if out_type == "any" or in_type == "any":
        return True
    return out_type == in_type


def _finite_pair(value, default) -> tuple:
    """把外部 ``[x, y]`` 数据转成**有限**二元组；非法一律回退 ``default``。

    与 ``_finite`` 同源：JSON 里的 ``1e999`` 会解析成 ``inf``，而
    ``int(inf)`` 抛的 ``OverflowError`` 穿出 Qt 槽就是 0xC0000409 零
    traceback 终止（见 ``_finite`` 的注释）。
    """
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _finite(value[0], default[0]), _finite(value[1], default[1])
    return float(default[0]), float(default[1])


def _as_bool(value, default: bool = False) -> bool:
    """把外部布尔字段转成 bool：字符串只认显式真 / 假。

    ``bool("false")`` 是 True —— 直接把 JSON 里的字符串塞给 ``bool()``
    会把明确的「关」读成「开」。无法判断时回退 ``default``。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        return default
    if isinstance(value, (int, float)):
        return value != 0
    return default


@dataclass
class ElaPin:
    """引脚描述。

    ``data_type`` 决定颜色（见 ``registry.PIN_COLORS``），``"any"`` 为通配；
    ``multi`` 只对输入引脚有意义 —— 为 ``False`` 时新连线自动替换旧连线。
    """

    id: str
    name: str
    direction: ElaPinDirectionType
    data_type: str = "any"
    multi: bool = False

    def to_dict(self) -> dict:
        """序列化为 JSON 友好字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "direction": self.direction.value,
            "data_type": self.data_type,
            "multi": self.multi,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ElaPin":
        """由 ``to_dict`` 结果重建引脚。

        容错契约（与 chat 的 ``fromDict`` 一致）：缺字段取默认、方向未知
        回退 Input 并记 WARNING；但**没有 id 的引脚**没有存在意义（连线
        找不到它），抛 ``ValueError`` 由上层（``ElaBlueprintNode.from_dict``）
        跳过 —— 上层不会因为这个抛异常。
        """
        if not isinstance(data, dict):
            raise ValueError(f"引脚数据不是字典: {data!r}")
        pin_id = data.get("id")
        if not pin_id:
            raise ValueError("引脚定义缺少 id")
        pin_id = str(pin_id)
        raw_dir = data.get("direction", "input")
        try:
            direction = ElaPinDirectionType(raw_dir)
        except ValueError:
            logger.warning(
                "未知引脚方向 %r（引脚 %r），回退 input",
                raw_dir,
                pin_id,
            )
            direction = ElaPinDirectionType.Input
        return cls(
            id=pin_id,
            name=str(data.get("name") or pin_id),
            direction=direction,
            data_type=str(data.get("data_type", "any") or "any"),
            multi=_as_bool(data.get("multi", False)),
        )


@dataclass
class ElaEdge:
    """一条连线：``from_*`` 为输出端，``to_*`` 为输入端。

    ``label`` 是连线标签（支持 ``\n`` 多行），绘制在贝塞尔曲线中点；
    用 ``graph.set_edge_label(edge, text)`` 修改（会发 ``edge_changed``）。
    """

    id: str
    from_node: str
    from_pin: str
    to_node: str
    to_pin: str
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_node": self.from_node,
            "from_pin": self.from_pin,
            "to_node": self.to_node,
            "to_pin": self.to_pin,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ElaEdge":
        """由 ``to_dict`` 结果重建连线；字段缺失 / 非法抛 ``ValueError``。

        有效性（引脚存在 / 方向 / 类型兼容）不在这里判断 —— 那是
        ``ElaBlueprintGraph.add_edge`` 的职责，``from_dict`` 只保证数据
        形状可用。
        """
        if not isinstance(data, dict):
            raise ValueError(f"连线数据不是字典: {data!r}")
        try:
            edge_id = str(data["id"])
            from_node = str(data["from_node"])
            from_pin = str(data["from_pin"])
            to_node = str(data["to_node"])
            to_pin = str(data["to_pin"])
        except KeyError as exc:
            raise ValueError(f"连线定义缺少字段 {exc.args[0]!r}: {data!r}") from None
        label = data.get("label", "")
        return cls(
            edge_id,
            from_node,
            from_pin,
            to_node,
            to_pin,
            "" if label is None else str(label),
        )


def _finite(value, default: float = 0.0) -> float:
    """把外部数据转成**有限** float；NaN / inf / 不可转一律归 ``default``。

    序列化反序列化的边界上，非有限值只有一个正确去处：丢弃。之所以在这里
    归零而不是让 ``int()`` 去抛 —— ``int(float("inf"))`` 抛的
    ``OverflowError`` 继承 ``ArithmeticError``，既不是 ``ValueError`` 也不是
    ``TypeError``，穿出 Qt 槽就是 0xC0000409 零 traceback 终止。
    """
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _pins_from_dicts(raw) -> list:
    """把外部引脚列表解析成 ``ElaPin`` 列表：非法条目跳过并记 WARNING。

    一条坏引脚定义不应该毁掉整个节点的恢复（连线本来就会按引脚缺失被
    ``add_edge`` 拒掉）。
    """
    if not isinstance(raw, list):
        return []
    pins = []
    for item in raw:
        try:
            pins.append(ElaPin.from_dict(item))
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("跳过非法引脚定义 %r（%s）", item, exc)
    return pins


class ElaBlueprintNode(QObject):
    """蓝图节点（数据 + 状态，不直接绘制）。

    :param type_name: 注册表中的类型名（如 ``"start"``）
    :param title: 节点标题（可修改，重命名即改它）
    :param node_id: 可选固定 id，缺省自动生成

    常用属性：``pos`` / ``size``、``inputs`` / ``outputs``、``properties``、
    ``status``（idle/running/done/error）、``elapsed_ms``、``progress``、
    ``accent``。

    注意：``title`` / ``properties`` 为裸属性，**直接赋值不发射
    ``changed``**；请使用 ``set_title()`` / ``set_properties()``。
    """

    #: 节点任意数据变化（标题 / 引脚 / 属性 / 位置）
    changed = pyqtSignal()
    #: 属性字典被整体替换（供节点体重建控件；交互控件直接改 properties 时不发）
    properties_changed = pyqtSignal()
    #: 运行状态变化，参数为新状态字符串
    status_changed = pyqtSignal(str)
    #: 进度变化，参数为 ``float``（0–1）或 ``None``（见 ``set_progress``）
    progress_changed = pyqtSignal(object)

    def __init__(self, type_name: str, title: str, node_id: str = None, parent=None):
        super().__init__(parent)
        self.id = node_id or _new_id()
        self.type_name = str(type_name)
        self.title = str(title)
        self.pos = QPointF(0.0, 0.0)
        self.size = QSizeF(180.0, 80.0)
        self.inputs = []
        self.outputs = []
        self.properties = {}
        self.accent = None
        self._status = "idle"
        self._elapsed_ms = None
        self._progress = None
        self.error_message = ""
        # 所属图（add_node 时写入弱引用；用于 node.connect(...)，不延长图的生命）
        self._graph_ref = None

    # -- 状态 ------------------------------------------------------------
    @property
    def status(self) -> str:
        """当前运行状态：``idle / running / done / error``。"""
        return self._status

    def set_status(self, status: str) -> None:
        """设置运行状态并发射 ``status_changed``（画布监听以刷新外观）。"""
        if status not in ("idle", "running", "done", "error"):
            raise ValueError(f"未知节点状态: {status!r}")
        if status == self._status:
            return
        self._status = status
        self.status_changed.emit(status)
        self.changed.emit()

    @property
    def elapsed_ms(self):
        """最近一次运行耗时（毫秒），未运行为 ``None``。"""
        return self._elapsed_ms

    def set_elapsed_ms(self, value) -> None:
        """设置耗时（毫秒或 ``None``），触发重绘以更新耗时徽标。"""
        self._elapsed_ms = None if value is None else float(value)
        self.changed.emit()

    @property
    def progress(self):
        """节点进度（0.0–1.0），未开始 / 不适用时为 ``None``。"""
        return self._progress

    def set_progress(self, value) -> None:
        """设置节点进度（``None`` 或 0–1，越界夹紧、非有限归 0）。

        只发 ``progress_changed``（节点体内进度条重绘），**不走** ``changed``
        —— 后者会触发 ``_relayout``（重算宽度 / 重排子控件），训练演示里进度
        每几十毫秒推进一次，每帧全量布局完全不值。
        """
        if value is None:
            progress = None
        else:
            progress = max(0.0, min(1.0, _finite(value, 0.0)))
        if progress == self._progress:
            return
        self._progress = progress
        self.progress_changed.emit(progress)

    # -- 标题 / 属性 ------------------------------------------------------
    def set_title(self, title: str) -> None:
        """设置节点标题并发射 ``changed``（画布据此重排标题栏宽度等）。"""
        self.title = str(title)
        self.changed.emit()

    def set_properties(self, properties: dict) -> None:
        """整体替换属性字典（``properties_changed`` 供节点体重建控件）。"""
        self.properties = dict(properties)
        self.properties_changed.emit()
        self.changed.emit()

    # -- 引脚 ------------------------------------------------------------
    def add_input(
        self, pin_id: str, name: str = None, data_type: str = "any", multi: bool = False
    ) -> ElaPin:
        """追加一个输入引脚并返回它。"""
        pin = ElaPin(
            pin_id,
            name if name is not None else pin_id,
            ElaPinDirectionType.Input,
            data_type,
            multi,
        )
        self.inputs.append(pin)
        self.changed.emit()
        return pin

    def add_output(
        self, pin_id: str, name: str = None, data_type: str = "any", multi: bool = False
    ) -> ElaPin:
        """追加一个输出引脚并返回它（参数同 ``add_input``）。"""
        pin = ElaPin(
            pin_id,
            name if name is not None else pin_id,
            ElaPinDirectionType.Output,
            data_type,
            multi,
        )
        self.outputs.append(pin)
        self.changed.emit()
        return pin

    def pin(self, pin_id: str, direction: "ElaPinDirectionType" = None):
        """按 id 找引脚，找不到返回 ``None``；省略 ``direction`` 时按先输入后输出取首个命中。"""
        if direction is ElaPinDirectionType.Input:
            return next((p for p in self.inputs if p.id == pin_id), None)
        if direction is ElaPinDirectionType.Output:
            return next((p for p in self.outputs if p.id == pin_id), None)
        for pin in self.inputs + self.outputs:
            if pin.id == pin_id:
                return pin
        return None

    def input(self, pin_id: str):
        """按 id 返回输入引脚（找不到为 ``None``）。"""
        return next((p for p in self.inputs if p.id == pin_id), None)

    def output(self, pin_id: str):
        """按 id 返回输出引脚（找不到为 ``None``）。"""
        return next((p for p in self.outputs if p.id == pin_id), None)

    def connect(self, target, from_pin: str, to_pin: str, label: str = "") -> "ElaEdge":
        """把本节点的输出引脚连到 ``target`` 的输入引脚，返回 ``ElaEdge``。

        ``target`` 接受 ``ElaBlueprintNode`` 或 id；``label`` 是连线中点显示
        的标签（支持 ``\n`` 多行）。节点必须已经加入图
        （``graph.add_node`` / ``canvas.create_node``）；非法连接抛
        ``ValueError``（原因见 ``ElaBlueprintGraph.validate_edge``）。
        """
        graph = self._graph_ref() if self._graph_ref is not None else None
        if graph is None:
            raise RuntimeError(
                "节点尚未加入图：先 graph.add_node(node) 或 canvas.create_node(...)"
            )
        return graph.add_edge(self, from_pin, target, to_pin, label=label)

    # -- 序列化 ----------------------------------------------------------
    def to_dict(self) -> dict:
        """序列化为 JSON 友好字典（含位置 / 尺寸 / 引脚 / 属性）。"""
        return {
            "id": self.id,
            "type_name": self.type_name,
            "title": self.title,
            "pos": [self.pos.x(), self.pos.y()],
            "size": [self.size.width(), self.size.height()],
            "accent": self.accent,
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "properties": dict(self.properties),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ElaBlueprintNode":
        """由 ``to_dict`` 结果重建节点（运行时状态不回放，保持 idle）。

        容错契约：非有限坐标 / 尺寸归默认、非法引脚定义**跳过并记
        WARNING**、``properties`` 非字典归空；但缺 ``type_name`` 抛
        ``ValueError``（没有类型的节点无法解析注册表，交给上层决定是否
        跳过），``id`` 缺失 / 非法则自动生成。

        **非有限坐标必须在这里拒收**（归默认值）。这不是洁癖：``json`` 接受
        ``1e999`` 并解析成 ``inf``（``json.dumps(float("inf"))`` 还会写出
        ``Infinity``），而 ``inf`` 一路走到 ``ElaNodeWidget.apply_view`` 的
        ``int(scene_pos.x())`` 就抛 ``OverflowError`` —— ``OverflowError``
        继承 ``ArithmeticError``，既不是 ``ValueError`` 也不是 ``TypeError``，
        穿出 Qt 槽 = **进程 0xC0000409 零traceback 终止**（实测复现）。
        ``NaN`` 同理（``int(nan)`` 抛 ``ValueError``）。
        """
        if not isinstance(data, dict):
            raise ValueError(f"节点数据不是字典: {data!r}")
        type_name = str(data.get("type_name") or "").strip()
        if not type_name:
            raise ValueError(f"节点定义缺少 type_name: {data!r}")
        node_id = data.get("id")
        node = cls(
            type_name,
            data.get("title") or type_name,
            node_id=str(node_id) if node_id else None,
        )
        x, y = _finite_pair(data.get("pos"), (0.0, 0.0))
        w, h = _finite_pair(data.get("size"), (180.0, 80.0))
        node.pos = QPointF(x, y)
        node.size = QSizeF(w, h)
        accent = data.get("accent")
        node.accent = accent if isinstance(accent, str) else None
        node.inputs = _pins_from_dicts(data.get("inputs"))
        node.outputs = _pins_from_dicts(data.get("outputs"))
        properties = data.get("properties")
        node.properties = dict(properties) if isinstance(properties, dict) else {}
        return node


def _node_id(value) -> str:
    """把 ``ElaBlueprintNode`` / 字符串 id 归一成节点 id。"""
    return value.id if isinstance(value, ElaBlueprintNode) else str(value)


def _pin_id(value) -> str:
    """把 ``ElaPin`` / 字符串 id 归一成引脚 id。"""
    return value.id if isinstance(value, ElaPin) else str(value)


class ElaBlueprintGraph(QObject):
    """蓝图图容器：节点与边的增删查、连线校验、序列化。

    ``add_edge`` 校验规则（不满足抛 ``ValueError``，原因可读；不产生副作用）：
    1. 节点与引脚必须存在；2. 必须是输出 → 输入；3. 数据类型兼容（any 通配）；
    4. 禁止自连与完全重复；5. 输入引脚非 multi 时保持单连接（旧边自动移除）。

    节点 / 引脚既可以传对象，也可以传 id：

    .. code-block:: python

        graph.add_edge(encoder, "hidden", head, "hidden")
        # 等价于 graph.add_edge(encoder.id, "hidden", head.id, "hidden")
    """

    node_added = pyqtSignal(object)
    node_removed = pyqtSignal(str)
    edge_added = pyqtSignal(object)
    edge_removed = pyqtSignal(str)
    #: 连线数据变化（当前只有标签）；画布据此失效边部件缓存并局部重绘
    edge_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes = {}
        self._edges = {}

    # -- 节点 ------------------------------------------------------------
    def add_node(self, node: ElaBlueprintNode) -> ElaBlueprintNode:
        """加入节点（id 冲突 / 已属于别的图时抛 ``ValueError``），发射 ``node_added``。"""
        if node.id in self._nodes:
            raise ValueError(f"节点 id 冲突: {node.id}")
        owner = node._graph_ref() if node._graph_ref is not None else None
        if owner is not None and owner is not self:
            raise ValueError("节点已属于另一个图，先从原图移除")
        node._graph_ref = weakref.ref(self)
        self._nodes[node.id] = node
        self.node_added.emit(node)
        return node

    def remove_node(self, node) -> bool:
        """移除节点（对象或 id）并连带移除其全部边；不存在返回 ``False``。"""
        nid = _node_id(node)
        removed = self._nodes.pop(nid, None)
        if removed is None:
            return False
        removed._graph_ref = None
        for edge in list(self._edges.values()):
            if edge.from_node == nid or edge.to_node == nid:
                self.remove_edge(edge.id)
        self.node_removed.emit(nid)
        return True

    def node(self, node_id: str):
        """按 id 取节点，不存在返回 ``None``。"""
        return self._nodes.get(node_id)

    def nodes(self) -> list:
        """全部节点列表（插入序）。"""
        return list(self._nodes.values())

    # -- 边 --------------------------------------------------------------
    def add_edge(
        self,
        from_node,
        from_pin,
        to_node,
        to_pin,
        edge_id: str = None,
        label: str = "",
    ) -> ElaEdge:
        """校验并建立连线，返回 ``ElaEdge``；非法连接抛 ``ValueError``（原因可读）。

        ``from_node`` / ``to_node`` 接受 ``ElaBlueprintNode`` 或字符串 id，
        ``from_pin`` / ``to_pin`` 接受 ``ElaPin`` 或字符串 id。
        ``label`` 是连线中点显示的标签（支持 ``\n`` 多行）。

        ``edge_id`` 仅供 ``from_dict`` 往返时保留原 id（不给则新生成）。
        **它不跳过任何校验**（方向 / 类型 / 存在性 / 单连接替换都要过）；
        与既有边 id 冲突同样拒绝，不允许「同 id 覆盖」这种静默丢边。
        """
        n1, p_out, n2, p_in = self._resolve_edge(from_node, from_pin, to_node, to_pin)
        edge_id = str(edge_id) if edge_id else None
        if edge_id is not None and edge_id in self._edges:
            raise ValueError(f"边 id 冲突: {edge_id!r}")
        if not p_in.multi:
            for edge in list(self._edges.values()):
                if edge.to_node == n2.id and edge.to_pin == p_in.id:
                    self.remove_edge(edge.id)  # 单连接替换
        edge = ElaEdge(
            edge_id or _new_id(),
            n1.id,
            p_out.id,
            n2.id,
            p_in.id,
            "" if label is None else str(label),
        )
        self._edges[edge.id] = edge
        self.edge_added.emit(edge)
        return edge

    def set_edge_label(self, edge, text: str) -> bool:
        """设置连线标签（``edge`` 接受 ``ElaEdge`` 或 id；``text`` 支持多行）。

        发 ``edge_changed``，画布自动失效标签缓存并局部重绘。边不存在 /
        标签没变化返回 ``False``。
        """
        eid = edge.id if isinstance(edge, ElaEdge) else str(edge)
        edge_obj = self._edges.get(eid)
        if edge_obj is None:
            return False
        label = "" if text is None else str(text)
        if edge_obj.label == label:
            return False
        edge_obj.label = label
        self.edge_changed.emit(edge_obj)
        return True

    def validate_edge(self, from_node, from_pin, to_node, to_pin) -> str | None:
        """校验一条连线：可连接返回 ``None``，否则返回人类可读的原因。"""
        try:
            self._resolve_edge(from_node, from_pin, to_node, to_pin)
        except ValueError as exc:
            return str(exc)
        return None

    def _resolve_edge(self, from_node, from_pin, to_node, to_pin):
        """解析并校验连线端点；失败抛 ``ValueError``（供 add_edge / validate_edge）。"""
        from_id, to_id = _node_id(from_node), _node_id(to_node)
        n1 = self._nodes.get(from_id)
        n2 = self._nodes.get(to_id)
        if n1 is None:
            raise ValueError(f"起点节点不存在: {from_id!r}")
        if n2 is None:
            raise ValueError(f"终点节点不存在: {to_id!r}")
        if n1 is n2:
            raise ValueError("不能把节点连到自身")
        p_out = n1.output(_pin_id(from_pin))
        p_in = n2.input(_pin_id(to_pin))
        if p_out is None:
            raise ValueError(f"起点没有输出引脚 {_pin_id(from_pin)!r}")
        if p_in is None:
            raise ValueError(f"终点没有输入引脚 {_pin_id(to_pin)!r}")
        if not types_compatible(p_out.data_type, p_in.data_type):
            raise ValueError(f"类型不兼容: {p_out.data_type!r} → {p_in.data_type!r}")
        for edge in self._edges.values():
            if (
                edge.from_node == n1.id
                and edge.from_pin == p_out.id
                and edge.to_node == n2.id
                and edge.to_pin == p_in.id
            ):
                raise ValueError("这条连线已存在")
        return n1, p_out, n2, p_in

    def remove_edge(self, edge) -> bool:
        """移除边（对象或 id），发射 ``edge_removed``；不存在返回 ``False``。"""
        eid = edge.id if isinstance(edge, ElaEdge) else str(edge)
        removed = self._edges.pop(eid, None)
        if removed is None:
            return False
        self.edge_removed.emit(eid)
        return True

    def edge(self, edge_id: str):
        """按 id 取边，不存在返回 ``None``。"""
        return self._edges.get(edge_id)

    def edges(self) -> list:
        """全部边列表（插入序）。"""
        return list(self._edges.values())

    def edges_of(self, node) -> list:
        """与某节点（对象或 id）相连的全部边（两端任一命中）。"""
        nid = _node_id(node)
        return [
            e for e in self._edges.values() if e.from_node == nid or e.to_node == nid
        ]

    def clear(self) -> None:
        """清空全部节点与边（逐条发射移除信号，界面自动同步）。"""
        for edge_id in list(self._edges.keys()):
            self.remove_edge(edge_id)
        for node_id in list(self._nodes.keys()):
            self.remove_node(node_id)

    # -- 序列化 ----------------------------------------------------------
    def to_dict(self) -> dict:
        """序列化为 JSON 友好字典：``{"nodes": [...], "edges": [...]}``。"""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ElaBlueprintGraph":
        """由 ``to_dict`` 结果重建整张图（节点 / 边顺序保持）。

        **重建即换对象**：返回的是全新的 ``ElaBlueprintNode``（id 保留），
        旧引用不要再用于连接 / 执行。

        与 ``canvas.from_dict`` 同一条契约：**边必须走 ``add_edge()``**
        校验（方向 / 类型兼容 / 存在性 / 单连接替换 / id 冲突），不过的
        丢弃并记 WARNING —— 直接往 ``_edges`` 里塞会把「文件里引脚已改名」
        这类脏数据还原成指向幽灵引脚的边；坏节点同样跳过而不是中断整张
        图的载入。
        """
        graph = cls()
        raw_nodes = data.get("nodes", []) if isinstance(data, dict) else []
        if not isinstance(raw_nodes, list):
            raw_nodes = []
        for nd in raw_nodes:
            try:
                graph.add_node(ElaBlueprintNode.from_dict(nd))
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning("跳过非法节点 %r（%s）", nd, exc)
        raw_edges = data.get("edges", []) if isinstance(data, dict) else []
        if not isinstance(raw_edges, list):
            raw_edges = []
        for ed in raw_edges:
            try:
                raw = ElaEdge.from_dict(ed)
            except (TypeError, ValueError, KeyError) as exc:
                logger.warning("跳过非法连线 %r（%s）", ed, exc)
                continue
            try:
                graph.add_edge(
                    raw.from_node,
                    raw.from_pin,
                    raw.to_node,
                    raw.to_pin,
                    edge_id=raw.id,
                )
            except ValueError as exc:
                logger.warning("跳过非法连线 %r（%s）", raw.id, exc)
        return graph
