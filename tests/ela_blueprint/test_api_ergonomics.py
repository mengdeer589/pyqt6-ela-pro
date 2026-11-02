"""用户使用接口契约：`pin()` / `create_node()` / `node.connect()` / 对象化执行。

这些用例直接按文档里的「优雅用法」写：节点对象贯穿建图、连线、执行，
属性在节点体构建前写入；非法连线给出可读原因。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPointF, QRectF
from PyQt6ElaWidgetTools import ElaSpinBox

from pyqt6_ela_pro.blueprint import (
    ElaBlueprintCanvas,
    ElaNodeRegistry,
    pin,
    register_node_type,
)


def _register_batch_types():
    def batch_body(node, container):
        spin = ElaSpinBox()
        spin.setRange(1, 4096)
        spin.setValue(int(node.properties.get("batch", 1)))
        container.layout().addWidget(spin)

    register_node_type(
        "batch_src",
        "数据源",
        "测试",
        inputs=pin("in", "输入"),
        outputs=pin("out", "批次", "tensor"),
    )
    register_node_type(
        "batch_dst",
        "加载器",
        "测试",
        inputs=pin("in", "批次", "tensor"),
        outputs=pin("out", "批次", "tensor"),
        body_builder=batch_body,
    )


class TestPinHelper:
    def test_pin_declaration(self):
        assert pin("out", "输出", "tensor", multi=True) == {
            "id": "out",
            "name": "输出",
            "data_type": "tensor",
            "multi": True,
        }

    def test_single_pin_is_normalized(self):
        _register_batch_types()
        # register_node_type 接受单个 pin（不必包成列表）
        spec = ElaNodeRegistry.instance().spec("batch_src")
        assert spec is not None
        assert [p["id"] for p in spec.outputs] == ["out"]


class TestCreateNodeErgonomics:
    def test_tuple_position_and_properties_before_body(self, qapp, make):
        _register_batch_types()
        canvas = make(ElaBlueprintCanvas)
        node = canvas.create_node("batch_dst", (120, 80), {"batch": 256})
        try:
            assert node.pos == QPointF(120, 80)
            widget = canvas.node_widget(node)
            spin = widget._body.findChild(ElaSpinBox)
            assert spin is not None and spin.value() == 256
        finally:
            canvas.deleteLater()

    def test_set_properties_rebuilds_body(self, qapp, make):
        _register_batch_types()
        canvas = make(ElaBlueprintCanvas)
        node = canvas.create_node("batch_dst", (120, 80), {"batch": 256})
        try:
            node.set_properties({"batch": 64})
            qapp.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            widget = canvas.node_widget(node)
            spins = widget._body.findChildren(ElaSpinBox)
            assert [s.value() for s in spins] == [64]
        finally:
            canvas.deleteLater()


class TestObjectThreading:
    def test_connect_and_selection_return_objects(self, qapp, make):
        _register_batch_types()
        canvas = make(ElaBlueprintCanvas)
        src = canvas.create_node("batch_src", (40, 80))
        dst = canvas.create_node("batch_dst", (240, 80))
        edge = src.connect(dst, "out", "in")
        try:
            assert canvas.graph.edges() == [edge]
            canvas.select_nodes(src)  # 单个节点对象 / 列表都接受
            assert canvas.selected_nodes() == [src]
            assert canvas.selected_node_ids() == [src.id]
            assert canvas.selected_edges() == []
        finally:
            canvas.deleteLater()

    def test_execution_accepts_node_objects(self, qapp, make):
        _register_batch_types()
        canvas = make(ElaBlueprintCanvas)
        node = canvas.create_node("batch_src", (40, 80))
        try:
            ex = canvas.execution()
            ex.start(node)
            assert node.status == "running"
            ex.finish(node, 12)
            assert node.status == "done"
            assert node.elapsed_ms == 12
        finally:
            canvas.deleteLater()

    def test_edge_label_geometry_and_repaint(self, qapp, make):
        _register_batch_types()
        canvas = make(ElaBlueprintCanvas)
        src = canvas.create_node("batch_src", (40, 80))
        dst = canvas.create_node("batch_dst", (460, 80))
        edge = src.connect(dst, "out", "in", label="batch 128")
        try:
            widget = canvas.edge_widget(edge)
            label = widget.label_rect()
            assert not label.isNull()
            assert widget.bounding_rect().contains(label)
            assert widget.contains(label.center())
            regions = []
            real = canvas.update

            def spy(*args):
                if args:
                    regions.append(args[0])
                return real(*args)

            canvas.update = spy
            probe = label.center().toPoint()
            assert canvas.set_edge_label(edge, "batch 128\nbf16") is True
            assert any(r is not None and r.contains(probe) for r in regions)
        finally:
            canvas.deleteLater()

    def test_edge_label_is_moved_out_of_nodes(self, qapp, make):
        _register_batch_types()
        canvas = make(ElaBlueprintCanvas)
        canvas.resize(900, 600)
        src = canvas.create_node("batch_src", (40, 80))
        dst = canvas.create_node("batch_dst", (240, 80))
        edge = src.connect(dst, "out", "in", label="batch 128")
        try:
            canvas.edge_widget(edge)._ensure_label()  # 强制布局
            rect = canvas.edge_widget(edge).label_rect()
            assert not rect.isNull()
            for node in (src, dst):
                assert not rect.intersects(QRectF(node.pos, node.size))
        finally:
            canvas.deleteLater()

    def test_invalid_connect_raises_readable_reason(self, qapp, make):
        _register_batch_types()
        canvas = make(ElaBlueprintCanvas)
        src = canvas.create_node("batch_src", (40, 80))
        dst = canvas.create_node("batch_dst", (240, 80))
        try:
            with pytest.raises(ValueError, match="输出引脚"):
                src.connect(dst, "in", "in")
            with pytest.raises(ValueError, match="已存在"):
                src.connect(dst, "out", "in")
                src.connect(dst, "out", "in")
        finally:
            canvas.deleteLater()

    def test_clear(self, qapp, make):
        _register_batch_types()
        canvas = make(ElaBlueprintCanvas)
        canvas.create_node("batch_src", (40, 80))
        canvas.clear()
        assert canvas.graph.nodes() == []
        assert canvas.selected_nodes() == []
