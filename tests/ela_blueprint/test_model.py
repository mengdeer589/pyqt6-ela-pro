"""蓝图数据模型测试（ElaBlueprintGraph / ElaBlueprintNode / 引脚 / 边）。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QSizeF

from pyqt6_ela_pro.blueprint import (
    ElaBlueprintGraph,
    ElaBlueprintNode,
    ElaEdge,
    ElaPin,
    ElaPinDirectionType,
    types_compatible,
)


def _mk_node(node_id="n1", title="测试"):
    return ElaBlueprintNode("proc", title, node_id=node_id)


# ---------------------------------------------------------------------------
# 类型兼容
# ---------------------------------------------------------------------------
class TestTypesCompatible:
    def test_same_type(self):
        assert types_compatible("image", "image")

    def test_any_wildcard_both_directions(self):
        assert types_compatible("any", "image")
        assert types_compatible("image", "any")

    def test_different_type_rejected(self):
        assert not types_compatible("image", "tensor")


# ---------------------------------------------------------------------------
# ElaPin / ElaPinDirectionType
# ---------------------------------------------------------------------------
class TestPin:
    def test_to_from_dict_roundtrip(self):
        pin = ElaPin("img", "图像", ElaPinDirectionType.Input, "image", multi=True)
        restored = ElaPin.from_dict(pin.to_dict())
        assert restored == pin

    def test_unknown_direction_falls_back_input(self):
        pin = ElaPin.from_dict({"id": "x", "name": "x", "direction": "bogus"})
        assert pin.direction is ElaPinDirectionType.Input


# ---------------------------------------------------------------------------
# ElaBlueprintNode
# ---------------------------------------------------------------------------
class TestNode:
    def test_pin_lookup_by_direction(self):
        node = _mk_node()
        node.add_input("img", "图像", "image")
        node.add_output("img", "图像", "image")  # 同名 id 允许
        assert node.pin("img", ElaPinDirectionType.Input) is not None
        assert node.pin("img", ElaPinDirectionType.Output) is not None
        assert node.pin("img") is not None  # 无方向先输入后输出

    def test_status_validation_and_signal(self):
        node = _mk_node()
        seen = []
        node.status_changed.connect(lambda s: seen.append(s))
        node.set_status("running")
        node.set_status("running")  # 幂等
        assert seen == ["running"]
        try:
            node.set_status("bogus")
            raise AssertionError("应抛 ValueError")
        except ValueError:
            pass

    def test_set_title_emits_changed(self):
        node = _mk_node()
        fired = []
        node.changed.connect(lambda: fired.append(1))
        node.set_title("新标题")
        assert node.title == "新标题" and len(fired) == 1

    def test_serialization_roundtrip(self):
        node = _mk_node()
        node.pos = QPointF(12.5, -3.0)
        node.size = QSizeF(200.0, 90.0)
        node.accent = "primary"
        node.add_input("in", "进入", "exec", multi=True)
        node.add_output("out", "输出", "image")
        node.set_properties({"width": 512})
        node.set_status("done")
        node.set_elapsed_ms(123.0)
        restored = ElaBlueprintNode.from_dict(node.to_dict())
        assert restored.id == node.id
        assert restored.pos == node.pos
        assert restored.size == node.size
        assert restored.accent == "primary"
        assert [p.id for p in restored.inputs] == ["in"]
        assert restored.properties == {"width": 512}
        # 运行时状态不回放
        assert restored.status == "idle" and restored.elapsed_ms is None


# ---------------------------------------------------------------------------
# ElaBlueprintGraph
# ---------------------------------------------------------------------------
class TestGraph:
    def _graph(self):
        g = ElaBlueprintGraph()
        a = _mk_node("a")
        a.add_output("out", "输出", "exec")
        b = _mk_node("b")
        b.add_input("in", "进入", "exec", multi=True)
        g.add_node(a)
        g.add_node(b)
        return g, a, b

    def test_add_edge_valid(self):
        g, a, b = self._graph()
        edge = g.add_edge(a.id, "out", b.id, "in")
        assert edge is not None and isinstance(edge, ElaEdge)
        assert len(g.edges()) == 1

    def test_add_edge_missing_node(self):
        g, a, b = self._graph()
        assert g.add_edge("nope", "out", b.id, "in") is None

    def test_add_edge_wrong_direction(self):
        g, a, b = self._graph()
        assert g.add_edge(b.id, "in", a.id, "out") is None

    def test_add_edge_type_mismatch(self):
        g = ElaBlueprintGraph()
        a = _mk_node("a")
        a.add_output("out", "输出", "image")
        b = _mk_node("b")
        b.add_input("in", "进入", "tensor")
        g.add_node(a)
        g.add_node(b)
        assert g.add_edge(a.id, "out", b.id, "in") is None

    def test_add_edge_self_loop(self):
        g, a, b = self._graph()
        a.add_input("in", "进入", "exec")
        assert g.add_edge(a.id, "out", a.id, "in") is None

    def test_add_edge_duplicate(self):
        g, a, b = self._graph()
        assert g.add_edge(a.id, "out", b.id, "in") is not None
        assert g.add_edge(a.id, "out", b.id, "in") is None  # 完全重复

    def test_single_connection_replaces(self):
        g = ElaBlueprintGraph()
        a = _mk_node("a")
        a.add_output("out", "输出", "exec")
        b = _mk_node("b")
        b.add_input("in", "进入", "exec")  # multi=False
        c = _mk_node("c")
        c.add_output("out", "输出", "exec")
        g.add_node(a)
        g.add_node(b)
        g.add_node(c)
        g.add_edge(a.id, "out", b.id, "in")
        g.add_edge(c.id, "out", b.id, "in")  # 单连接替换
        edges = g.edges()
        assert len(edges) == 1
        assert edges[0].from_node == c.id

    def test_multi_input_allows_multiple(self):
        g, a, b = self._graph()  # b.in multi=True
        c = _mk_node("c")
        c.add_output("out", "输出", "exec")
        g.add_node(c)
        g.add_edge(a.id, "out", b.id, "in")
        g.add_edge(c.id, "out", b.id, "in")
        assert len(g.edges()) == 2

    def test_remove_node_removes_edges(self):
        g, a, b = self._graph()
        g.add_edge(a.id, "out", b.id, "in")
        g.remove_node(a.id)
        assert len(g.edges()) == 0 and g.node(a.id) is None

    def test_signals(self):
        g = ElaBlueprintGraph()
        a = _mk_node("a")
        a.add_output("out", "输出", "exec")
        b = _mk_node("b")
        b.add_input("in", "进入", "exec")
        g.add_node(a)
        g.add_node(b)
        added, removed = [], []
        g.edge_added.connect(lambda e: added.append(e.id))
        g.edge_removed.connect(lambda i: removed.append(i))
        edge = g.add_edge(a.id, "out", b.id, "in")
        g.remove_edge(edge.id)
        assert added == [edge.id] and removed == [edge.id]

    def test_clear(self):
        g, a, b = self._graph()
        g.add_edge(a.id, "out", b.id, "in")
        g.clear()
        assert not g.nodes() and not g.edges()

    def test_serialization_roundtrip(self):
        g, a, b = self._graph()
        g.add_edge(a.id, "out", b.id, "in")
        data = g.to_dict()
        restored = ElaBlueprintGraph.from_dict(data)
        assert len(restored.nodes()) == 2 and len(restored.edges()) == 1
        assert restored.edges()[0].from_node == a.id
        assert restored.edges()[0].to_node == b.id

    def test_duplicate_node_id_raises(self):
        g = ElaBlueprintGraph()
        g.add_node(_mk_node("x"))
        try:
            g.add_node(_mk_node("x"))
            raise AssertionError("应抛 ValueError")
        except ValueError:
            pass
