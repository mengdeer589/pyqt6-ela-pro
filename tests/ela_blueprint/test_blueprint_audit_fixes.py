"""blueprint 深度审计修复回归（2026-10）。

每条对应一个**实测确认**过的缺陷：

1. ``canvas.from_dict`` / 模型 ``from_dict`` 对脏数据零容错 —— 异常穿出
   Qt 槽 = 0xC0000409 零 traceback（实测 exit=-1073740791）；
2. ``ElaBlueprintGraph.from_dict`` 绕过 ``add_edge``（幽灵边）；``add_edge``
   对 ``edge_id`` 冲突静默覆盖（旧边无信号、部件泄漏）；
3. 节点标题 ``_text_on`` 在深色主题下整支取反：亮色 accent 配白字只有
   ~1.6–2.0:1 对比度（浅色琥珀白字 ~2.4:1）；
4. 节点体被整体置为鼠标透明 —— body_builder 里的控件全部点不动；
5. 空格+左键按在节点 / 引脚上走的是拖节点 / 拖线而不是平移；
6. 拖线中失焦：``ElaTempWire`` 对象残留、``_wire_src`` 陈旧；
7. ``execution.finish`` 对从未 start 的节点也发 ``finished``；显式耗时
   残留 ``_t0``；``set_path`` 漏掉分支 DAG 的边；
8. 画布未显示时 ``apply_view`` 每次触发全量重排；
9. 鼠标离开画布后边 hover 不清除；
10. 注册期不校验引脚定义（缺 id → create 期 KeyError → 槽内异常）；
11. ``ElaPin.from_dict`` 的 ``bool("false")`` 是 True。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QFocusEvent, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro.blueprint import (
    ElaBlueprintCanvas,
    ElaBlueprintGraph,
    ElaBlueprintNode,
    ElaNodeCreationMenu,
    ElaPin,
    ElaTempWire,
    register_node_type,
)
from pyqt6_ela_pro.blueprint import node_widget as _nw

# ---------------------------------------------------------------------------
# 事件工具（offscreen 下 QTest 的命中路由不可靠，统一 sendEvent 直达目标）
# ---------------------------------------------------------------------------


def _mouse(kind, pos, button=Qt.MouseButton.LeftButton, buttons=None):
    if buttons is None:
        if kind == QEvent.Type.MouseMove:
            buttons = Qt.MouseButton.LeftButton
        elif kind == QEvent.Type.MouseButtonRelease:
            buttons = Qt.MouseButton.NoButton
        else:
            buttons = button
    return QMouseEvent(
        kind,
        QPointF(pos),
        QPointF(pos),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _key(kind, key):
    return QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier)


def _send(widget, event):
    QApplication.instance().sendEvent(widget, event)


def _flush_deferred():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def canvas(qapp, clean_registry, make):
    register_node_type(
        "a",
        "A",
        "测试",
        inputs=[{"id": "i", "name": "in", "data_type": "exec", "multi": True}],
        outputs=[{"id": "o", "name": "out", "data_type": "exec"}],
    )
    c = make(ElaBlueprintCanvas)
    c.resize(900, 600)
    c.show()
    qapp.processEvents()
    return c


def _node_payload(node_id="x", type_name="a", title="X", **overrides):
    payload = {
        "id": node_id,
        "type_name": type_name,
        "title": title,
        "pos": [0.0, 0.0],
        "size": [180.0, 80.0],
        "inputs": [],
        "outputs": [
            {
                "id": "o",
                "name": "out",
                "direction": "output",
                "data_type": "exec",
                "multi": False,
            }
        ],
    }
    payload.update(overrides)
    return payload


# =========================================================== P0：from_dict 容错
class TestFromDictTolerance:
    @pytest.mark.parametrize(
        "data",
        [
            {"graph": {"nodes": [{"id": "a"}], "edges": []}},
            {"graph": {"nodes": {"a": 1}, "edges": []}},
            {"graph": {"nodes": [_node_payload(), _node_payload()], "edges": []}},
            {"graph": {"nodes": [], "edges": []}, "view": {"zoom": 1.0, "offset": 5}},
            {
                "graph": {
                    "nodes": [
                        _node_payload(inputs=[{"name": "no-id"}]),
                    ],
                    "edges": [],
                }
            },
            "完全不是字典",
            {"graph": {"nodes": "junk", "edges": "junk"}},
        ],
        ids=[
            "missing-type_name",
            "nodes-not-list",
            "duplicate-id",
            "offset-not-list",
            "pin-missing-id",
            "not-a-dict",
            "graph-fields-junk",
        ],
    )
    def test_canvas_never_raises_on_dirty_data(self, canvas, data, caplog):
        """脏数据不得抛异常（异常穿出 Qt 槽 = 进程终止）。"""
        canvas.from_dict(data)  # 不得抛

    def test_missing_type_name_skipped_others_load(self, canvas, caplog):
        canvas.from_dict(
            {
                "graph": {
                    "nodes": [
                        _node_payload("bad", type_name=None),
                        _node_payload("ok"),
                    ],
                    "edges": [],
                }
            }
        )
        assert canvas.graph.node("bad") is None
        assert canvas.graph.node("ok") is not None

    def test_duplicate_node_id_keeps_first(self, canvas, caplog):
        canvas.from_dict(
            {
                "graph": {
                    "nodes": [
                        _node_payload("dup", title="first"),
                        _node_payload("dup", title="second"),
                    ],
                    "edges": [],
                }
            }
        )
        assert [n.title for n in canvas.graph.nodes()] == ["first"]

    def test_view_junk_sanitized(self, canvas):
        canvas.from_dict(
            {"graph": {"nodes": [], "edges": []}, "view": {"zoom": "bad", "offset": 5}}
        )
        assert canvas.zoom() == 1.0
        assert canvas._offset == QPointF(0.0, 0.0)

    def test_pin_missing_id_skipped_node_kept(self, canvas, caplog):
        canvas.from_dict(
            {
                "graph": {
                    "nodes": [
                        _node_payload(
                            "p",
                            inputs=[
                                {"name": "no-id"},
                                {"id": "ok", "direction": "input"},
                            ],
                        )
                    ],
                    "edges": [],
                }
            }
        )
        node = canvas.graph.node("p")
        assert node is not None
        assert [p.id for p in node.inputs] == ["ok"]

    def test_model_graph_from_dict_drops_ghost_edges(self, caplog):
        data = {
            "nodes": [_node_payload("a")],
            "edges": [
                {
                    "id": "ghost",
                    "from_node": "a",
                    "from_pin": "o",
                    "to_node": "missing",
                    "to_pin": "x",
                }
            ],
        }
        graph = ElaBlueprintGraph.from_dict(data)
        assert graph.node("a") is not None
        assert graph.edges() == []

    def test_model_graph_from_dict_skips_bad_nodes(self, caplog):
        data = {
            "nodes": [{"id": "bad"}, _node_payload("ok")],
            "edges": [],
        }
        graph = ElaBlueprintGraph.from_dict(data)
        assert [n.id for n in graph.nodes()] == ["ok"]


# ======================================================= P0：edge_id 冲突
class TestEdgeIdCollision:
    @staticmethod
    def _two_pins():
        g = ElaBlueprintGraph()
        a = ElaBlueprintNode("t", "A")
        a.add_output("o1", "o1", "exec")
        a.add_output("o2", "o2", "exec")
        b = ElaBlueprintNode("t", "B")
        b.add_input("i1", "i1", "exec", multi=True)
        b.add_input("i2", "i2", "exec", multi=True)
        g.add_node(a)
        g.add_node(b)
        return g, a, b

    def test_add_edge_rejects_duplicate_id(self):
        g, a, b = self._two_pins()
        e1 = g.add_edge(a.id, "o1", b.id, "i1", edge_id="dup")
        e2 = g.add_edge(a.id, "o2", b.id, "i2", edge_id="dup")
        assert e1 is not None and e2 is None, (
            "同 id 覆盖会静默丢边（无 edge_removed 信号）"
        )
        assert [e.id for e in g.edges()] == ["dup"]

    def test_canvas_from_dict_duplicate_edge_id_keeps_first(self, canvas, caplog):
        payload = {
            "graph": {
                "nodes": [
                    _node_payload(
                        "a",
                        outputs=[
                            {"id": "o1", "direction": "output", "data_type": "exec"},
                            {"id": "o2", "direction": "output", "data_type": "exec"},
                        ],
                    ),
                    _node_payload(
                        "b",
                        inputs=[
                            {
                                "id": "i1",
                                "direction": "input",
                                "data_type": "exec",
                                "multi": True,
                            },
                            {
                                "id": "i2",
                                "direction": "input",
                                "data_type": "exec",
                                "multi": True,
                            },
                        ],
                        outputs=[],
                    ),
                ],
                "edges": [
                    {
                        "id": "dup",
                        "from_node": "a",
                        "from_pin": "o1",
                        "to_node": "b",
                        "to_pin": "i1",
                    },
                    {
                        "id": "dup",
                        "from_node": "a",
                        "from_pin": "o2",
                        "to_node": "b",
                        "to_pin": "i2",
                    },
                ],
            }
        }
        canvas.from_dict(payload)
        assert len(canvas.graph.edges()) == 1
        assert list(canvas._edge_widgets) == ["dup"]

    def test_graph_from_dict_duplicate_edge_id(self, caplog):
        payload = {
            "nodes": [
                _node_payload(
                    "a",
                    outputs=[
                        {"id": "o1", "direction": "output", "data_type": "exec"},
                        {"id": "o2", "direction": "output", "data_type": "exec"},
                    ],
                ),
                _node_payload(
                    "b",
                    inputs=[
                        {
                            "id": "i1",
                            "direction": "input",
                            "data_type": "exec",
                            "multi": True,
                        },
                        {
                            "id": "i2",
                            "direction": "input",
                            "data_type": "exec",
                            "multi": True,
                        },
                    ],
                    outputs=[],
                ),
            ],
            "edges": [
                {
                    "id": "dup",
                    "from_node": "a",
                    "from_pin": "o1",
                    "to_node": "b",
                    "to_pin": "i1",
                },
                {
                    "id": "dup",
                    "from_node": "a",
                    "from_pin": "o2",
                    "to_node": "b",
                    "to_pin": "i2",
                },
            ],
        }
        graph = ElaBlueprintGraph.from_dict(payload)
        assert [e.id for e in graph.edges()] == ["dup"]


# ======================================================= P1：标题对比度
class TestTitleTextContrast:
    @pytest.mark.parametrize(
        "mode",
        [ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark],
        ids=["light", "dark"],
    )
    @pytest.mark.parametrize("token", ["warning", "primary", "danger"])
    def test_text_on_meets_contrast(self, qapp, mode, token):
        previous = eTheme.getThemeMode()
        eTheme.setThemeMode(mode)
        try:
            accent = QColor(str(_nw.T(f"color.{token}")))
            fg = _nw._text_on(accent)
            ratio = _nw._contrast_ratio(accent, fg)
            assert ratio >= 4.5, (
                f"{mode} / {token}: {fg.name()} on {accent.name()} 只有 {ratio:.2f}:1"
            )
        finally:
            eTheme.setThemeMode(previous)

    def test_light_warning_picks_dark_text(self, qapp):
        """浅色琥珀（#c08a3e）白字只有 ~2.4:1，必须选深字（~7:1）。"""
        previous = eTheme.getThemeMode()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
        try:
            fg = _nw._text_on(QColor(str(_nw.T("color.warning"))))
            assert fg.name() != "#ffffff"
        finally:
            eTheme.setThemeMode(previous)

    def test_dark_primary_picks_dark_text(self, qapp):
        """深色主题的亮蓝 accent（#4cc2ff）配白字只有 ~1.6:1。"""
        previous = eTheme.getThemeMode()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        try:
            fg = _nw._text_on(QColor(str(_nw.T("color.primary"))))
            assert fg.name() != "#ffffff"
        finally:
            eTheme.setThemeMode(previous)


# ======================================================= P1：节点体可交互
class TestBodyInteraction:
    @pytest.fixture
    def body_canvas(self, qapp, clean_registry, make):
        clicked = []

        def build(node, container):
            btn = QPushButton("click", container)
            btn.clicked.connect(lambda: clicked.append(1))
            container.layout().addWidget(btn)

        register_node_type(
            "with_body", "WB", "测试", outputs=[{"id": "o"}], body_builder=build
        )
        c = make(ElaBlueprintCanvas)
        c.resize(900, 600)
        c.show()
        qapp.processEvents()
        node = c.add_node_at("with_body", QPointF(60, 60))
        qapp.processEvents()
        return c, node, c.node_widget(node.id), clicked

    def test_body_not_mouse_transparent(self, body_canvas):
        _c, _n, widget, _clicked = body_canvas
        assert (
            widget._body.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            is False
        )

    def test_body_control_receives_click(self, qapp, body_canvas):
        _c, _n, widget, clicked = body_canvas
        btn = widget._body.findChild(QPushButton)
        assert btn is not None
        center = btn.rect().center()
        _send(btn, _mouse(QEvent.Type.MouseButtonPress, center))
        _send(btn, _mouse(QEvent.Type.MouseButtonRelease, center))
        qapp.processEvents()
        assert clicked == [1], "body_builder 里的控件必须能收到自己的鼠标事件"

    def test_control_press_does_not_drag_node(self, body_canvas):
        _c, _n, widget, _clicked = body_canvas
        c = _c
        btn = widget._body.findChild(QPushButton)
        _send(btn, _mouse(QEvent.Type.MouseButtonPress, btn.rect().center()))
        assert c._drag is None

    def test_empty_body_area_drag_moves_node(self, qapp, body_canvas):
        c, node, widget, _clicked = body_canvas
        moved = []
        c.node_moved.connect(lambda nid, pos: moved.append((nid, pos)))
        body = widget._body
        empty = QPoint(body.width() - 3, body.height() - 2)
        _send(body, _mouse(QEvent.Type.MouseButtonPress, empty))
        # 体空白处按下会冒泡到节点控件 → 画布照常开始拖动
        assert c._drag is not None
        start = QPointF(node.pos)
        _send(
            widget,
            _mouse(
                QEvent.Type.MouseMove, QPoint(60, 60), button=Qt.MouseButton.NoButton
            ),
        )
        assert node.pos != start
        _send(widget, _mouse(QEvent.Type.MouseButtonRelease, QPoint(60, 60)))
        assert c._drag is None
        assert moved and moved[0][0] == node.id


# ======================================================= P1：空格强制平移
class TestSpacePanOverChildren:
    def test_space_left_on_node_pans_not_drags(self, canvas):
        n = canvas.add_node_at("a", QPointF(100, 100))
        widget = canvas.node_widget(n.id)
        canvas.keyPressEvent(_key(QEvent.Type.KeyPress, Qt.Key.Key_Space))
        center = widget.rect().center()
        _send(widget, _mouse(QEvent.Type.MouseButtonPress, center))
        assert canvas._panning is True
        assert canvas._drag is None, "空格+左键按在节点上仍走了拖节点"
        _send(
            widget,
            _mouse(
                QEvent.Type.MouseMove,
                QPoint(center.x() + 30, center.y() + 20),
                button=Qt.MouseButton.NoButton,
            ),
        )
        assert canvas._offset != QPointF(0.0, 0.0)
        _send(widget, _mouse(QEvent.Type.MouseButtonRelease, center))
        assert canvas._panning is False

    def test_space_left_on_pin_pans_not_wire(self, canvas):
        n = canvas.add_node_at("a", QPointF(100, 100))
        handle = canvas.node_widget(n.id).pin_widget("o", None)
        canvas.keyPressEvent(_key(QEvent.Type.KeyPress, Qt.Key.Key_Space))
        _send(handle, _mouse(QEvent.Type.MouseButtonPress, handle.rect().center()))
        assert canvas._panning is True
        assert canvas._wire is None
        _send(handle, _mouse(QEvent.Type.MouseButtonRelease, handle.rect().center()))
        assert canvas._panning is False


# ======================================================= P1：拖线失焦清理
class TestWireCancelCleanup:
    def test_focus_out_reclaims_temp_wire(self, canvas):
        n = canvas.add_node_at("a", QPointF(100, 100))
        handle = canvas.node_widget(n.id).pin_widget("o", None)
        _send(handle, _mouse(QEvent.Type.MouseButtonPress, handle.rect().center()))
        assert canvas._wire is not None
        canvas.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut))
        assert canvas._wire is None
        assert canvas._wire_src is None
        assert canvas._wire_target is None
        _flush_deferred()
        assert canvas.findChildren(ElaTempWire) == []

    def test_hide_reclaims_too(self, canvas):
        n = canvas.add_node_at("a", QPointF(100, 100))
        handle = canvas.node_widget(n.id).pin_widget("o", None)
        _send(handle, _mouse(QEvent.Type.MouseButtonPress, handle.rect().center()))
        canvas.hide()
        _flush_deferred()
        assert canvas._wire is None
        assert canvas.findChildren(ElaTempWire) == []


# ======================================================= P2：执行控制器语义
class TestExecutionSemantics:
    def test_finish_without_start_no_finished(self, canvas):
        n = canvas.add_node_at("a", QPointF(100, 100))
        ex = canvas.execution()
        fired = []
        ex.finished.connect(lambda: fired.append(1))
        ex.finish(n.id, 1.0)
        assert fired == [], "从未 start 的 finish 不是「一轮执行结束」"

    def test_fail_without_start_no_finished(self, canvas):
        n = canvas.add_node_at("a", QPointF(100, 100))
        ex = canvas.execution()
        fired = []
        ex.finished.connect(lambda: fired.append(1))
        ex.fail(n.id, "x")
        assert fired == []

    def test_explicit_elapsed_clears_timer_start(self, canvas):
        n = canvas.add_node_at("a", QPointF(100, 100))
        ex = canvas.execution()
        ex.start(n.id)
        ex.finish(n.id, 5.0)
        assert n.id not in ex._t0

    def test_finish_twice_emits_finished_once(self, canvas):
        n = canvas.add_node_at("a", QPointF(100, 100))
        ex = canvas.execution()
        fired = []
        ex.finished.connect(lambda: fired.append(1))
        ex.start(n.id)
        ex.finish(n.id, 1.0)
        ex.finish(n.id, 2.0)
        assert len(fired) == 1

    def test_linear_round_still_emits_when_all_done(self, canvas):
        n1 = canvas.add_node_at("a", QPointF(100, 100))
        n2 = canvas.add_node_at("a", QPointF(400, 100))
        ex = canvas.execution()
        fired = []
        ex.finished.connect(lambda: fired.append(1))
        ex.start(n1.id)
        ex.start(n2.id)
        ex.finish(n1.id, 1.0)
        assert fired == []
        ex.finish(n2.id, 2.0)
        assert fired == [1]


class TestSetPathDag:
    def test_branch_edges_are_highlighted(self, canvas):
        a = canvas.add_node_at("a", QPointF(0, 0))
        b = canvas.add_node_at("a", QPointF(200, 0))
        c = canvas.add_node_at("a", QPointF(200, 200))
        d = canvas.add_node_at("a", QPointF(400, 100))
        e1 = canvas.graph.add_edge(a.id, "o", b.id, "i")
        e2 = canvas.graph.add_edge(a.id, "o", c.id, "i")
        e3 = canvas.graph.add_edge(b.id, "o", d.id, "i")
        e4 = canvas.graph.add_edge(c.id, "o", d.id, "i")
        canvas.execution().set_path([a.id, b.id, c.id, d.id])
        assert set(canvas.execution().path_edge_ids()) == {e1.id, e2.id, e3.id, e4.id}

    def test_backward_edge_not_highlighted(self, canvas):
        a = canvas.add_node_at("a", QPointF(0, 0))
        b = canvas.add_node_at("a", QPointF(300, 0))
        forward = canvas.graph.add_edge(a.id, "o", b.id, "i")
        backward = canvas.graph.add_edge(b.id, "o", a.id, "i")
        canvas.execution().set_path([a.id, b.id])
        ids = canvas.execution().path_edge_ids()
        assert ids == [forward.id]
        assert backward.id not in ids


# ======================================================= P2：布局 / hover / 注册
class TestApplyViewNoChurn:
    def test_hidden_canvas_does_not_relayout_every_call(
        self, qapp, clean_registry, make
    ):
        register_node_type(
            "with_body2",
            "WB2",
            "测试",
            outputs=[{"id": "o"}],
            body_builder=lambda node, container: QPushButton("x", container),
        )
        c = make(ElaBlueprintCanvas)  # 故意不 show（父链不可见）
        node = c.add_node_at("with_body2", QPointF(0, 0))
        widget = c.node_widget(node.id)
        rev = widget._layout_rev
        for _ in range(5):
            widget.apply_view(QPointF(0, 0), 1.0)
        assert widget._layout_rev == rev, "画布不可见时每次 apply_view 都触发全量重排"


class TestEdgeHoverClearsOnLeave:
    def test_leave_event_clears_hover(self, qapp, canvas):
        n1 = canvas.add_node_at("a", QPointF(100, 100))
        n2 = canvas.add_node_at("a", QPointF(400, 100))
        edge = canvas.graph.add_edge(n1.id, "o", n2.id, "i")
        ew = canvas.edge_widget(edge.id)
        mid = ew.path().pointAtPercent(0.5)
        canvas._update_edge_hover(mid)
        assert ew.hovered is True
        _send(canvas._viewport, QEvent(QEvent.Type.Leave))
        qapp.processEvents()
        assert ew.hovered is False


class TestPinDefinitionValidation:
    def test_register_rejects_pin_without_id(self, clean_registry):
        with pytest.raises(ValueError):
            register_node_type("bad", "Bad", "测试", inputs=[{"name": "x"}])

    def test_register_rejects_non_dict_pin(self, clean_registry):
        with pytest.raises(ValueError):
            register_node_type("bad", "Bad", "测试", outputs=["not-a-dict"])

    def test_valid_still_creates(self, clean_registry):
        register_node_type("ok", "Ok", "测试", inputs=[{"id": "i"}])
        node = clean_registry.create("ok")
        assert node.inputs[0].id == "i"


class TestPinFromDictTolerance:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (True, True),
            ("true", True),
            ("1", True),
            (1, True),
            ("false", False),
            ("0", False),
            (0, False),
            (None, False),
        ],
    )
    def test_multi_forms(self, raw, expected):
        pin = ElaPin.from_dict({"id": "p", "direction": "input", "multi": raw})
        assert pin.multi is expected, f"multi={raw!r} 解析成 {pin.multi!r}"

    def test_missing_id_raises_value_error(self):
        with pytest.raises(ValueError):
            ElaPin.from_dict({"name": "x"})

    def test_name_defaults_to_id(self):
        assert ElaPin.from_dict({"id": "p"}).name == "p"


class TestCreationMenuPickIdempotent:
    def test_double_pick_emits_once(self, canvas):
        menu = ElaNodeCreationMenu(canvas)
        seen = []
        menu.type_chosen.connect(seen.append)
        menu._pick("a")
        menu._pick("b")
        assert seen == ["a"]

    def test_popup_corners_are_rounded(self, canvas):
        """弹层是真圆角：窗口透明 + 四角不铺底（grab 会把窗口底色铺满，
        用 ``render(DrawChildren)`` 跳过窗口底色才测得到）。"""
        from PyQt6.QtGui import QImage, QRegion

        menu = ElaNodeCreationMenu(canvas)
        menu.resize(300, 300)
        assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        img = QImage(menu.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor(255, 0, 255))
        menu.render(img, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        assert QColor(img.pixel(0, 0)).name() == "#ff00ff", "圆角外应保持未绘制"
        assert QColor(img.pixel(150, 150)).name() != "#ff00ff", "盒内应铺底"


class TestContextMenuSignalsReemitted:
    def test_rename_and_properties_forwarded(self, canvas, monkeypatch):
        import pyqt6_ela_pro.blueprint.canvas as canvas_mod

        captured = {}
        monkeypatch.setattr(
            canvas_mod, "execElaMenu", lambda menu, pos: captured.update(menu=menu)
        )
        node = canvas.add_node_at("a", QPointF(10, 10))
        canvas._open_node_menu(canvas.node_widget(node.id), QPoint(0, 0))
        menu = captured["menu"]
        renamed, props = [], []
        canvas.node_rename_requested.connect(renamed.append)
        canvas.node_properties_requested.connect(props.append)
        menu.rename_requested.emit(node.id)
        menu.properties_requested.emit(node.id)
        assert renamed == [node.id]
        assert props == [node.id]
        menu.deleteLater()
