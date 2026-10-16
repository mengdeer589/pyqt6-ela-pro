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
    """一条连线：``from_*`` 为输出端，``to_*`` 为输入端。"""

    id: str
    from_node: str
    from_pin: str
    to_node: str
    to_pin: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_node": self.from_node,
            "from_pin": self.from_pin,
            "to_node": self.to_node,
            "to_pin": self.to_pin,
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
        return cls(edge_id, from_node, from_pin, to_node, to_pin)


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
    ``status``（idle/running/done/error）、``elapsed_ms``、``accent``。

    注意：``title`` / ``properties`` 为裸属性，**直接赋值不发射
    ``changed``**；请使用 ``set_title()`` / ``set_properties()``。
    """

    #: 节点任意数据变化（标题 / 引脚 / 属性 / 位置）
    changed = pyqtSignal()
    #: 运行状态变化，参数为新状态字符串
    status_changed = pyqtSignal(str)

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
        self.error_message = ""

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

    # -- 标题 / 属性 ------------------------------------------------------
    def set_title(self, title: str) -> None:
        """设置节点标题并发射 ``changed``（画布据此重排标题栏宽度等）。"""
        self.title = str(title)
        self.changed.emit()

    def set_properties(self, properties: dict) -> None:
        """整体替换属性字典并发射 ``changed``（节点体重建展示）。"""
        self.properties = dict(properties)
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


class ElaBlueprintGraph(QObject):
    """蓝图图容器：节点与边的增删查、连线校验、序列化。

    ``add_edge`` 校验规则（任一不满足返回 ``None``，不产生副作用）：
    1. 节点与引脚必须存在；2. 方向必须相反；3. 数据类型兼容（any 通配）；
    4. 禁止自连与完全重复；5. 输入引脚非 multi 时保持单连接（旧边自动移除）。
    """

    node_added = pyqtSignal(object)
    node_removed = pyqtSignal(str)
    edge_added = pyqtSignal(object)
    edge_removed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes = {}
        self._edges = {}

    # -- 节点 ------------------------------------------------------------
    def add_node(self, node: ElaBlueprintNode) -> ElaBlueprintNode:
        """加入节点（id 冲突时抛 ``ValueError``），发射 ``node_added``。"""
        if node.id in self._nodes:
            raise ValueError(f"节点 id 冲突: {node.id}")
        self._nodes[node.id] = node
        self.node_added.emit(node)
        return node

    def remove_node(self, node_id: str) -> bool:
        """移除节点并连带移除其全部边，发射相应信号；不存在返回 ``False``。"""
        node = self._nodes.pop(node_id, None)
        if node is None:
            return False
        for edge in list(self._edges.values()):
            if edge.from_node == node_id or edge.to_node == node_id:
                self.remove_edge(edge.id)
        self.node_removed.emit(node_id)
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
        from_node: str,
        from_pin: str,
        to_node: str,
        to_pin: str,
        edge_id: str = None,
    ):
        """校验并建立连线，成功返回 ``ElaEdge``，失败返回 ``None``。

        ``edge_id`` 仅供 ``from_dict`` 往返时保留原 id（不给则新生成）。
        **它不跳过任何校验**（方向 / 类型 / 存在性 / 单连接替换都要过）；
        与既有边 id 冲突同样拒绝，不允许「同 id 覆盖」这种静默丢边的
        行为（被覆盖的旧边不会发 ``edge_removed``，画布会把旧部件泄漏在
        ``_edge_widgets`` 之外）。
        """
        n1, n2 = self._nodes.get(from_node), self._nodes.get(to_node)
        if n1 is None or n2 is None:
            return None
        edge_id = str(edge_id) if edge_id else None
        if edge_id is not None and edge_id in self._edges:
            return None  # id 冲突：拒绝而不是覆盖
        p_out = next((p for p in n1.outputs if p.id == from_pin), None)
        p_in = next((p for p in n2.inputs if p.id == to_pin), None)
        if p_out is None or p_in is None:
            return None
        if from_node == to_node:
            return None
        if not types_compatible(p_out.data_type, p_in.data_type):
            return None
        for edge in self._edges.values():
            if (
                edge.from_node == from_node
                and edge.from_pin == from_pin
                and edge.to_node == to_node
                and edge.to_pin == to_pin
            ):
                return None  # 完全重复
        if not p_in.multi:
            for edge in list(self._edges.values()):
                if edge.to_node == to_node and edge.to_pin == to_pin:
                    self.remove_edge(edge.id)  # 单连接替换
        edge = ElaEdge(edge_id or _new_id(), from_node, from_pin, to_node, to_pin)
        self._edges[edge.id] = edge
        self.edge_added.emit(edge)
        return edge

    def remove_edge(self, edge_id: str) -> bool:
        """移除边，发射 ``edge_removed``；不存在返回 ``False``。"""
        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return False
        self.edge_removed.emit(edge_id)
        return True

    def edge(self, edge_id: str):
        """按 id 取边，不存在返回 ``None``。"""
        return self._edges.get(edge_id)

    def edges(self) -> list:
        """全部边列表（插入序）。"""
        return list(self._edges.values())

    def edges_of(self, node_id: str) -> list:
        """与某节点相连的全部边（两端任一命中）。"""
        return [
            e
            for e in self._edges.values()
            if e.from_node == node_id or e.to_node == node_id
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
            added = graph.add_edge(
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
        return graph
