"""连线与节点控件测试（ElaEdgeWidget / ElaTempWire / ElaNodeWidget / 菜单）。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPainter

import pyqt6_ela_pro.blueprint.viewport as vp_mod
from pyqt6_ela_pro.blueprint import (
    ElaBlueprintCanvas,
    ElaNodeCreationMenu,
    ElaPinDirectionType,
    ElaTempWire,
    bezier_path,
    format_elapsed,
    register_node_type,
)
from pyqt6_ela_pro.blueprint.node_widget import BODY_MIN_ZOOM


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
    c = ElaBlueprintCanvas()
    c.resize(900, 600)
    c.show()  # 可见性断言（spinner / body）依赖父链可见
    qapp.processEvents()
    yield c
    if c.isVisible():
        c.close()
    c.deleteLater()
    qapp.processEvents()


class TestBezier:
    def test_control_offset_clamped(self):
        p1, p2 = QPointF(0, 0), QPointF(1000, 0)
        path = bezier_path(p1, p2)
        # 水平外推被夹在 40–240
        assert path.elementAt(1).x == 240.0
        p3, p4 = QPointF(0, 0), QPointF(50, 0)
        path2 = bezier_path(p3, p4)
        assert path2.elementAt(1).x == 40.0  # 下限

    def test_vertical_stack_has_curve(self):
        path = bezier_path(QPointF(0, 0), QPointF(0, 100))
        # 垂直堆叠：控制点外推 40（下限），路径在两端附近 x 离开 0
        p = path.pointAtPercent(0.25)
        assert abs(p.x()) > 1e-6


class TestEdgeWidget:
    def test_geometry_and_hit(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        n2 = canvas.add_node_at("proc", QPointF(400, 100))
        edge = canvas.graph.add_edge(n1.id, "out", n2.id, "in")
        ew = canvas.edge_widget(edge.id)
        assert ew is not None
        path = ew.path()
        assert path.elementCount() > 0
        # 命中：贝塞尔中点附近
        mid = path.pointAtPercent(0.5)
        assert ew.contains(mid)
        assert not ew.contains(QPointF(-500, -500))

    def test_flowing_state(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        n2 = canvas.add_node_at("proc", QPointF(400, 100))
        edge = canvas.graph.add_edge(n1.id, "out", n2.id, "in")
        ew = canvas.edge_widget(edge.id)
        assert not ew.flowing
        ew.set_flowing(True)
        assert ew.flowing
        ew.advance_dash(1.6)
        ew.set_flowing(False)
        assert not ew.flowing

    def test_invalidate_color_after_theme(self, canvas):
        n1 = canvas.add_node_at("start", QPointF(100, 100))
        n2 = canvas.add_node_at("proc", QPointF(400, 100))
        edge = canvas.graph.add_edge(n1.id, "out", n2.id, "in")
        ew = canvas.edge_widget(edge.id)
        ew._color()  # 惰性缓存
        assert ew._base_color is not None
        ew.invalidate_color()
        assert ew._base_color is None


class TestTempWire:
    def test_draw_no_crash(self, qapp):
        wire = ElaTempWire(QPointF(0, 0), "exec")
        wire.set_end(QPointF(120, 60))
        wire.magnet = True
        pm = qapp.primaryScreen().grabWindow(0)  # 任意 QPixmap 目标
        p = QPainter(pm)
        wire.draw(p)
        p.end()


class TestNodeWidget:
    def test_layout_and_pin_handles(self, canvas):
        node = canvas.add_node_at("start", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        assert widget.pin_widget("out") is not None
        assert widget.node.size.width() >= 160.0
        # 引脚逻辑中心在右缘
        c = widget.pin_logical_center(node.outputs[0])
        assert c.x() == pytest.approx(widget.node.size.width())

    def test_apply_view_zoom(self, canvas):
        node = canvas.add_node_at("start", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        w0 = widget.width()
        canvas.set_zoom(2.0)
        assert widget.width() > w0

    def test_selection_border(self, canvas):
        node = canvas.add_node_at("start", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        assert not widget.is_selected()
        widget.set_selected(True)
        assert widget.is_selected()

    def test_elapsed_badge(self, canvas):
        node = canvas.add_node_at("start", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        node.set_status("done")
        node.set_elapsed_ms(42)
        assert widget.elapsed_text() == "42 ms"
        assert not widget.badge_rect().isNull()
        node.set_status("idle")
        assert widget.elapsed_text() == ""

    def test_status_spinner_visibility(self, canvas):
        node = canvas.add_node_at("start", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        assert not widget._spinner.isVisible()
        node.set_status("running")
        assert widget._spinner.isVisible()
        node.set_status("idle")
        assert not widget._spinner.isVisible()

    def test_body_hidden_below_min_zoom(self, canvas, qapp):
        register_node_type(
            "has_body",
            "带体",
            "测试",
            outputs=[{"id": "o", "data_type": "exec"}],
            body_builder=lambda node, container: None,
        )
        node = canvas.add_node_at("has_body", QPointF(100, 100))
        widget = canvas.node_widget(node.id)
        assert widget._body is not None
        widget.apply_view(QPointF(100, 100), BODY_MIN_ZOOM + 0.1)
        assert widget._body.isVisible()
        widget.apply_view(QPointF(100, 100), BODY_MIN_ZOOM - 0.1)
        assert not widget._body.isVisible()


class TestFormatElapsed:
    def test_ms_and_seconds(self):
        assert format_elapsed(12) == "12 ms"
        assert format_elapsed(1500) == "1.5 s"
        assert format_elapsed(None) == ""


class TestCreationMenu:
    def test_lists_registered_types(self, canvas):
        menu = ElaNodeCreationMenu(canvas)
        menu.popup_at(canvas.mapToGlobal(canvas.rect().topLeft()))
        types = menu.matching_types()
        assert "start" in types and "proc" in types
        menu.close()

    def test_search_filters(self, canvas):
        menu = ElaNodeCreationMenu(canvas)
        menu.search_edit.setText("开始")
        assert menu.matching_types() == ["start"]
        menu.close()

    def test_compatible_filter(self, canvas):
        register_node_type(
            "img_src",
            "图像源",
            "输入",
            outputs=[{"id": "img", "data_type": "image"}],
        )
        register_node_type(
            "img_sink",
            "图像接收",
            "输出",
            inputs=[{"id": "img", "data_type": "image"}],
        )
        menu = ElaNodeCreationMenu(canvas)
        menu.popup_at(
            canvas.mapToGlobal(canvas.rect().topLeft()),
            compatible=(ElaPinDirectionType.Input, "image"),
        )
        types = menu.matching_types()
        assert "img_sink" in types and "img_src" not in types
        menu.close()


class TestViewport:
    def test_gl_env_off_forces_raster(self, qapp, monkeypatch):
        monkeypatch.setenv("ELABLUEPRINT_GL", "off")
        vp_mod._GL_STATE = None  # 重置模块级探测缓存
        c = ElaBlueprintCanvas()
        assert isinstance(c._viewport, vp_mod._RasterViewport)
        assert c._viewport.supports_node_proxy is False
        c.deleteLater()

    def test_gl_env_on(self, qapp, monkeypatch):
        monkeypatch.setenv("ELABLUEPRINT_GL", "on")
        vp_mod._GL_STATE = None
        c = ElaBlueprintCanvas()
        # 支持 GL 的环境用 GL 视口，否则回退软件渲染（两者都是合法路径）
        assert isinstance(c._viewport, (vp_mod._GLViewport, vp_mod._RasterViewport))
        c.deleteLater()

    def test_viewport_mirrors_canvas(self, canvas):
        assert canvas._viewport.size() == canvas.size()
