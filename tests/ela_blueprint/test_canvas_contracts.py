"""blueprint 的输入面与状态残留契约。

五条独立故障：

1. **非有限坐标**（``json`` 接受 ``1e999`` → ``inf``；``json.dumps(inf)``
   还会写出 ``Infinity``）一路走到 ``apply_view`` 的 ``int(...)`` 就抛
   ``OverflowError`` —— 继承 ``ArithmeticError``，不是 ``ValueError``
   子类，穿出 Qt 槽 = **进程 0xC0000409 零 traceback 终止**（实测复现）；
2. **引脚配色不在注册期校验** → ``T()`` 的 ``KeyError`` 在 ``paintEvent``
   链上抛出（实测复现）；
3. **失焦不复位手势** → 按住空格后 Alt+Tab，之后**每次左键都变成平移**，
   框选彻底失效；框选进行中失焦则 ``_band`` 起点残留；
4. ``from_dict`` **绕过** ``add_edge`` 的全量校验 → 还原出指向幽灵引脚的边；
5. ``from_dict`` **不复位执行态** → 上一轮的「运行中」徽标留在新载入的图上。
"""

from __future__ import annotations

import json
import math

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import (
    QFocusEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
)

from pyqt6_ela_pro.blueprint import registry as reg
from pyqt6_ela_pro.blueprint.canvas import ElaBlueprintCanvas
from pyqt6_ela_pro.blueprint.model import ElaBlueprintNode

BAD_POS_JSON = (
    '{"graph": {"nodes": [{"id":"n1","type_name":"t","title":"T",'
    '"pos":[1e999, 1e999], "size":[180.0,80.0]}], "edges":[]},'
    '"view": {"zoom": 1.0, "offset": [0.0, 0.0]}}'
)


class TestNonFiniteGeometry:
    @pytest.mark.parametrize(
        "raw_pos",
        ["[1e999, 1e999]", "[NaN, NaN]", '["inf", "0"]'],
        ids=["1e999", "nan-literal", "string-inf"],
    )
    def test_from_dict_sanitizes_pos(self, raw_pos):
        payload = json.loads(
            '{"id":"n1","type_name":"t","title":"T",'
            f'"pos":{raw_pos}, "size":[180.0,80.0]}}'
        )
        node = ElaBlueprintNode.from_dict(payload)
        assert math.isfinite(node.pos.x())
        assert math.isfinite(node.pos.y())

    def test_from_dict_sanitizes_size(self):
        node = ElaBlueprintNode.from_dict(
            json.loads(
                '{"id":"n1","type_name":"t","title":"T",'
                '"pos":[10.0,20.0], "size":[1e999,1e999]}'
            )
        )
        # size 走默认值而不是 0（0 宽的节点画不出引脚）
        assert (node.size.width(), node.size.height()) == (180.0, 80.0)

    def test_unconvertible_falls_back(self):
        node = ElaBlueprintNode.from_dict(
            {
                "type_name": "t",
                "pos": [None, "abc"],
                "size": [None, None],
            }
        )
        assert (node.pos.x(), node.pos.y()) == (0.0, 0.0)
        assert (node.size.width(), node.size.height()) == (180.0, 80.0)

    def test_canvas_from_dict_survives_and_renders(self, make):
        """整条 from_dict -> 布局 -> render 必须跑通（原先 0xC0000409）。"""
        canvas = make(ElaBlueprintCanvas)
        canvas.from_dict(json.loads(BAD_POS_JSON))
        node = canvas.graph.node("n1")
        assert math.isfinite(node.pos.x())
        pixmap = QPixmap(400, 300)
        canvas.render(pixmap)  # 不得崩
        assert not pixmap.isNull()

    def test_view_zoom_and_offset_are_sanitized(self, make):
        canvas = make(ElaBlueprintCanvas)
        canvas.from_dict(
            json.loads(
                '{"graph": {"nodes": [], "edges": []},'
                '"view": {"zoom": 1e999, "offset": [1e999, NaN]}}'
            )
        )
        assert math.isfinite(canvas._zoom)
        assert math.isfinite(canvas._offset.x())
        assert math.isfinite(canvas._offset.y())

    def test_apply_view_is_last_line_of_defense(self, make):
        """数据入口已拦，但 ``apply_view`` 本身也不能因int() 崩。"""
        from pyqt6_ela_pro.blueprint.node_widget import ElaNodeWidget

        node = ElaBlueprintNode("t", "T")
        node.pos = QPointF(float("inf"), float("inf"))
        widget = make(ElaNodeWidget, node)
        widget.apply_view(QPointF(float("inf"), float("nan")), float("inf"))
        r = widget.geometry()
        assert r.width() >= 20 and r.height() >= 20


class TestPinColorValidatedAtRegistration:
    @pytest.mark.parametrize(
        "bad",
        ["totally-unknown-token", "#12345", "rgb(1,2,3)", "", "#gg0000", "not-a-color"],
        ids=["unknown-token", "hex-5", "css-rgb", "empty", "hex-bad", "plain"],
    )
    def test_bad_color_rejected_at_registration(self, bad):
        with pytest.raises(ValueError):
            reg.register_pin_type(f"bad_{abs(hash(bad)) % 9999}", bad)

    def test_bad_color_never_enters_the_table(self):
        key = "bad_never"
        with pytest.raises(ValueError):
            reg.register_pin_type(key, "totally-unknown-token")
        assert key not in reg.PIN_COLORS

    def test_any_is_protected(self):
        """``any`` 是未知类型的兜底目标，覆盖它就剪断了降级链。"""
        with pytest.raises(ValueError):
            reg.register_pin_type("any", "#123456")

    @pytest.mark.parametrize(
        "good", ["success", "#C080D0", "red"], ids=["token", "hex", "named"]
    )
    def test_good_color_accepted(self, good):
        key = f"good_{abs(hash(good)) % 9999}"
        try:
            reg.register_pin_type(key, good)
            assert key in reg.PIN_COLORS
        finally:
            reg.PIN_COLORS.pop(key, None)

    def test_resolved_value_is_always_hex(self):
        """``pin_color`` 的契约是「hex 字符串」—— 上游按 ``.name()`` 比对。"""
        for name in list(reg.PIN_COLORS):
            value = reg.pin_color(name)
            assert value.startswith("#") and len(value) == 7, (name, value)

    def test_direct_dict_write_still_degrades(self, caplog):
        """``PIN_COLORS`` 是公开 dict，宿主可以绕过注册期 —— 读取期仍要兜底。"""
        reg.PIN_COLORS["_dirty"] = "totally-unknown-token"
        try:
            color = reg.pin_color("_dirty")
            assert color.startswith("#"), f"应降级成合法色，实际 {color!r}"
            assert color == reg.pin_color("any")
        finally:
            reg.PIN_COLORS.pop("_dirty", None)

    def test_dirty_color_does_not_break_paint(self, make, caplog):
        """实测：绘制期抛 KeyError = paintEvent 里 0xC0000409。"""
        reg.PIN_COLORS["_dirty2"] = "totally-unknown-token"
        try:
            node = ElaBlueprintNode("t", "T")
            node.add_output("o", "out", "_dirty2")
            widget = make(
                __import__(
                    "pyqt6_ela_pro.blueprint.node_widget",
                    fromlist=["ElaNodeWidget"],
                ).ElaNodeWidget,
                node,
            )
            pixmap = QPixmap(240, 160)
            painter = QPainter(pixmap)
            try:
                widget._draw_pins(painter)  # 不得抛
            finally:
                painter.end()
        finally:
            reg.PIN_COLORS.pop("_dirty2", None)

    def test_builtin_types_all_resolve(self):
        """内置表逐个能解析（``pin_color`` 的兜底目标依赖这一点）。"""
        for name in reg.PIN_COLORS:
            assert reg.pin_color(name).startswith("#"), name


class TestAccentColorDegrades:
    """``node_widget._resolve_color`` 与 ``pin_color`` 同源的问题。

    原先的 ``value.startswith("rgb")`` 分支把 ``rgb(1,2,3)`` 原样交给
    ``QColor``，而 ``QColor`` 不解析 CSS 函数记法 → accent 栏**静默变黑**。
    """

    @pytest.mark.parametrize(
        "value", ["#C080D0", "red", "primary", None]
    )
    def test_valid_values_still_work(self, value):
        from pyqt6_ela_pro.blueprint.node_widget import _resolve_color

        color = _resolve_color(value, "text.tertiary")
        assert color.isValid()

    @pytest.mark.parametrize(
        "value", ["rgb(1,2,3)", "rgba(1,2,3,255)", "#12345", "", "nope"]
    )
    def test_invalid_values_fall_back_to_valid_color(self, value):
        """绝不能返回无效 QColor（那是「静默变黑」）。"""
        from pyqt6_ela_pro.blueprint.node_widget import _resolve_color

        color = _resolve_color(value, "text.tertiary")
        assert color.isValid(), f"{value!r} 解析成无效色 {color.name()!r}"

    def test_node_accent_never_invalid(self, make):
        node = ElaBlueprintNode("t", "T")
        node.accent = "rgb(1,2,3)"
        widget = make(
            __import__(
                "pyqt6_ela_pro.blueprint.node_widget",
                fromlist=["ElaNodeWidget"],
            ).ElaNodeWidget,
            node,
        )
        assert widget.accent_color().isValid()


def _key_event(kind, key):
    return QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier)


def _mouse(kind, button, pos=QPoint(50, 50)):
    return QMouseEvent(
        kind,
        QPointF(pos),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


class TestGesturesCancelledOnFocusOut:
    def test_space_pan_does_not_stick(self, make):
        """按住空格后失焦 -> 之后每次左键都平移，框选彻底失效（实测）。"""
        canvas = make(ElaBlueprintCanvas)
        canvas.keyPressEvent(_key_event(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space))
        assert canvas._space_down is True
        canvas.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut))
        assert canvas._space_down is False
        canvas.mousePressEvent(
            _mouse(QEvent_Type_MouseButtonPress, Qt.MouseButton.LeftButton)
        )
        assert canvas._panning is False
        assert canvas._band is not None

    def test_band_start_point_does_not_persist(self, make):
        canvas = make(ElaBlueprintCanvas)
        canvas.mousePressEvent(
            _mouse(QEvent_Type_MouseButtonPress, Qt.MouseButton.LeftButton)
        )
        assert canvas._band is not None
        canvas.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut))
        assert canvas._band is None

    def test_right_press_state_does_not_persist(self, make):
        canvas = make(ElaBlueprintCanvas)
        canvas.mousePressEvent(
            _mouse(QEvent_Type_MouseButtonPress, Qt.MouseButton.RightButton)
        )
        assert canvas._rpress is not None
        canvas.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut))
        assert canvas._rpress is None

    def test_hide_cancels_too(self, make):
        canvas = make(ElaBlueprintCanvas)
        canvas.mousePressEvent(
            _mouse(QEvent_Type_MouseButtonPress, Qt.MouseButton.LeftButton)
        )
        canvas.hideEvent(_hide_event())
        assert canvas._band is None

    def test_panning_cursor_is_reset(self, make):
        canvas = make(ElaBlueprintCanvas)
        canvas.keyPressEvent(_key_event(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space))
        canvas.mousePressEvent(
            _mouse(QEvent_Type_MouseButtonPress, Qt.MouseButton.LeftButton)
        )
        assert canvas._panning is True
        canvas.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut))
        assert canvas._panning is False
        assert canvas.cursor().shape() != Qt.CursorShape.ClosedHandCursor

    def test_cancel_is_idempotent(self, make):
        canvas = make(ElaBlueprintCanvas)
        canvas._cancel_gestures()
        canvas._cancel_gestures()

    def test_from_dict_cancels_gestures(self, make):
        canvas = make(ElaBlueprintCanvas)
        canvas.mousePressEvent(
            _mouse(QEvent_Type_MouseButtonPress, Qt.MouseButton.LeftButton)
        )
        canvas.keyPressEvent(_key_event(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space))
        canvas.from_dict({"graph": {"nodes": [], "edges": []}, "view": {}})
        assert canvas._band is None
        assert canvas._space_down is False


class TestFromDictValidatesEdges:
    @staticmethod
    def _payload():
        return {
            "graph": {
                "nodes": [
                    {
                        "id": "a",
                        "type_name": "t",
                        "title": "A",
                        "pos": [0, 0],
                        "size": [180, 80],
                        "inputs": [
                            {"id": "i1", "name": "in", "direction": "input",
                             "data_type": "int", "multi": False}
                        ],
                        "outputs": [
                            {"id": "o1", "name": "out", "direction": "output",
                             "data_type": "int", "multi": False}
                        ],
                    },
                    {
                        "id": "b",
                        "type_name": "t",
                        "title": "B",
                        "pos": [300, 0],
                        "size": [180, 80],
                        "inputs": [
                            {"id": "i1", "name": "in", "direction": "input",
                             "data_type": "int", "multi": False},
                            {"id": "is", "name": "s", "direction": "input",
                             "data_type": "str", "multi": True},
                        ],
                        "outputs": [],
                    },
                ],
                "edges": [
                    {"id": "e_ok", "from_node": "a", "from_pin": "o1",
                     "to_node": "b", "to_pin": "i1"},
                    {"id": "e_dup", "from_node": "a", "from_pin": "o1",
                     "to_node": "b", "to_pin": "i1"},
                    {"id": "e_ghost", "from_node": "a", "from_pin": "o1",
                     "to_node": "zzz", "to_pin": "nope"},
                    {"id": "e_self", "from_node": "a", "from_pin": "o1",
                     "to_node": "a", "to_pin": "i1"},
                ],
            },
            "view": {"zoom": 1.0, "offset": [0.0, 0.0]},
        }

    def test_invalid_edges_are_dropped(self, make, caplog):
        canvas = make(ElaBlueprintCanvas)
        canvas.from_dict(self._payload())
        assert set(canvas.graph._edges) == {"e_ok"}

    def test_ghost_edge_does_not_reach_edge_widgets(self, make, caplog):
        canvas = make(ElaBlueprintCanvas)
        canvas.from_dict(self._payload())
        assert "e_ghost" not in canvas._edge_widgets

    def test_edge_ids_survive_roundtrip(self, make):
        """保留 id 是 ``from_dict`` 的既有契约（往返测试钉着它）。"""
        canvas = make(ElaBlueprintCanvas)
        canvas.from_dict(self._payload())
        exported = canvas.to_dict()
        assert [e["id"] for e in exported["graph"]["edges"]] == ["e_ok"]

    def test_roundtrip_is_stable(self, make):
        canvas = make(ElaBlueprintCanvas)
        canvas.from_dict(self._payload())
        first = canvas.to_dict()
        canvas2 = make(ElaBlueprintCanvas)
        canvas2.from_dict(first)
        assert canvas2.to_dict() == first

    def test_one_bad_edge_does_not_abort_the_load(self, make, caplog):
        canvas = make(ElaBlueprintCanvas)
        canvas.from_dict(self._payload())  # 不得抛
        assert len(canvas.graph.nodes()) == 2

    def test_execution_state_is_reset(self, make):
        """``graph.clear()`` 不碰 status / elapsed / error，``to_dict`` 也不
        序列化这三项 —— 复用节点对象时上一轮徽标会留在新图上。"""
        canvas = make(ElaBlueprintCanvas)
        canvas.from_dict(self._payload())
        a = canvas.graph.node("a")
        a.set_status("running")
        a.set_elapsed_ms(1234)
        a.error_message = "上一轮的错"

        canvas.from_dict(
            {
                "graph": {
                    "nodes": self._payload()["graph"]["nodes"],
                    "edges": [],
                },
                "view": {"zoom": 1.0, "offset": [0.0, 0.0]},
            }
        )
        a2 = canvas.graph.node("a")
        assert a2 is not None
        assert a2.status == "idle", f"残留 status={a2.status!r}"
        assert a2.elapsed_ms is None
        assert a2.error_message == ""


def _hide_event():
    from PyQt6.QtGui import QHideEvent

    return QHideEvent()


from PyQt6.QtCore import QEvent as _QEvent  # noqa: E402

QEvent_Type_MouseButtonPress = _QEvent.Type.MouseButtonPress