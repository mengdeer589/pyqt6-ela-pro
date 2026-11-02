"""可拖动标注（``annotations``）：箭头锚点 / 文本框拖动 / 命中与信号契约。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import GridCoord


def _chart(make, **option) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    opt = {"animation": False}
    opt.update(option)
    chart.setOption(opt)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _annotations(chart) -> list:
    return [c for c in chart._components if c.optionKey == "annotations"]


def _mouse(etype, pos, chart, button=Qt.MouseButton.LeftButton, buttons=None):
    return QMouseEvent(
        etype,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        button,
        buttons if buttons is not None else button,
        Qt.KeyboardModifier.NoModifier,
    )


def _press(chart, pos) -> None:
    chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos, chart))


def _move(chart, pos, buttons=Qt.MouseButton.LeftButton) -> None:
    chart.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, pos, chart, Qt.MouseButton.NoButton, buttons)
    )


def _release(chart, pos) -> None:
    chart.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pos, chart))


def _double_click(chart, pos) -> None:
    chart.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick, pos, chart))


def _drag(chart, start, end) -> None:
    _press(chart, start)
    _move(chart, end)
    _release(chart, end)


def _line_chart(make, **extra) -> ElaChartWidget:
    option = {
        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "值", "data": [10, 20, 30]}],
        "annotations": [
            {"id": "peak", "x": "B", "y": 20, "text": "峰值", "ax": 30, "ay": -40}
        ],
    }
    option.update(extra)
    return _chart(make, **option)


class TestAnchor:
    def test_arrow_anchor_matches_data_point(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        renderer = chart.seriesRenderers[0]
        expected = renderer.valueAtIndex(1)["pos"]
        assert comp.anchor() == expected
        assert comp._arrow_end == expected

    def test_category_y_anchor_uses_row_center(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "value"},
            yAxis={"type": "category", "data": ["A", "B", "C"]},
            series=[{"type": "bar", "name": "值", "data": [10, 20, 30]}],
            annotations=[{"x": 20, "y": "B", "text": "B 行", "ax": 40, "ay": 0}],
        )
        comp = _annotations(chart)[0]
        renderer = chart.seriesRenderers[0]
        assert comp.anchor() == renderer.valueAtIndex(1)["pos"]

    def test_value_axes_anchor(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "value"},
            yAxis={"type": "value"},
            series=[{"type": "line", "name": "值", "data": [[0, 5], [1, 9]]}],
            annotations=[{"x": 1, "y": 9, "text": "点", "ax": 0, "ay": -40}],
        )
        comp = _annotations(chart)[0]
        coord = chart.primaryCoord()
        assert comp.anchor() == coord.mapPoint(1, 9)

    def test_paper_ref_without_grid(self, qapp, make):
        chart = _chart(
            make,
            series=[{"type": "pie", "name": "占比", "data": [1, 2, 3]}],
            annotations=[
                {
                    "x": 0.5,
                    "y": 0.5,
                    "xref": "paper",
                    "yref": "paper",
                    "text": "中心",
                    "showarrow": False,
                }
            ],
        )
        comp = _annotations(chart)[0]
        assert comp.anchor() == QPointF(chart.width() / 2, chart.height() / 2)

    def test_axis_ref_selects_secondary_axis(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "category", "data": ["A", "B"]},
            yAxis=[{"type": "value"}, {"type": "value"}],
            series=[
                {"type": "line", "name": "左", "data": [1, 2]},
                {
                    "type": "line",
                    "name": "右",
                    "yAxisIndex": 1,
                    "data": [100, 200],
                },
            ],
            annotations=[
                {
                    "x": "A",
                    "y": 200,
                    "xref": "x",
                    "yref": "y2",
                    "text": "副轴",
                }
            ],
        )
        comp = _annotations(chart)[0]
        assert comp.anchor().y() < chart.primaryCoord().plot.center().y()

    def test_xanchor_and_yanchor_place_box_around_tail(self, qapp, make):
        chart = _line_chart(
            make,
            annotations=[
                {
                    "x": "B",
                    "y": 20,
                    "text": "角",
                    "ax": 10,
                    "ay": 12,
                    "xanchor": "left",
                    "yanchor": "top",
                }
            ],
        )
        comp = _annotations(chart)[0]
        assert comp.box().left() == comp.anchor().x() + 10
        assert comp.box().top() == comp.anchor().y() + 12

    def test_multi_grid_annotation_uses_owning_grid(self, qapp, make):
        chart = _chart(
            make,
            grid=[
                {"left": 50, "right": "52%", "top": 30, "bottom": 40},
                {"left": "55%", "right": 20, "top": 30, "bottom": 40},
            ],
            xAxis=[
                {"type": "category", "data": ["A", "B"], "gridIndex": 0},
                {"type": "category", "data": ["C", "D"], "gridIndex": 1},
            ],
            yAxis=[
                {"type": "value", "gridIndex": 0},
                {"type": "value", "gridIndex": 1, "position": "right"},
            ],
            series=[
                {"type": "line", "name": "g0", "data": [1, 2], "gridIndex": 0},
                {
                    "type": "bar",
                    "name": "g1",
                    "data": [100, 200],
                    "xAxisIndex": 1,
                    "yAxisIndex": 1,
                },
            ],
            annotations=[
                {
                    "gridIndex": 1,
                    "xref": "x2",
                    "yref": "y2",
                    "x": "C",
                    "y": 100,
                    "text": "第二块网格",
                }
            ],
        )
        comp = _annotations(chart)[0]
        grids = [c for c in chart._coords if isinstance(c, GridCoord)]
        assert grids[1].plot.adjusted(-1, -1, 1, 1).contains(comp.anchor())
        assert not grids[0].plot.contains(comp.anchor())


class TestDrag:
    def test_drag_moves_box_but_not_anchor(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        anchor = comp.anchor()
        box = comp.box()
        delta = QPointF(50, 30)
        _drag(chart, box.center(), box.center() + delta)
        assert comp.anchor() == anchor
        assert comp.box().center() == box.center() + delta

    def test_drag_with_anchors_keeps_box_under_cursor(self, qapp, make):
        chart = _line_chart(
            make,
            annotations=[
                {
                    "x": "B",
                    "y": 20,
                    "text": "角",
                    "ax": 10,
                    "ay": 12,
                    "xanchor": "left",
                    "yanchor": "top",
                }
            ],
        )
        comp = _annotations(chart)[0]
        anchor = comp.anchor()
        box = comp.box()
        delta = QPointF(40, 25)
        _drag(chart, box.center(), box.center() + delta)
        assert comp.anchor() == anchor
        assert comp.box().center() == box.center() + delta

    def test_drag_emits_signal_with_final_offsets(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        events = []
        chart.annotationDragged.connect(events.append)
        box = comp.box()
        _drag(chart, box.center(), box.center() + QPointF(25, -10))
        assert len(events) == 1
        payload = events[0]
        assert payload["index"] == 0
        assert payload["id"] == "peak"
        assert payload["componentType"] == "annotations"
        assert payload["text"] == "峰值"
        assert payload["ax"] == pytest.approx(comp._ax)
        assert payload["ay"] == pytest.approx(comp._ay)
        assert (payload["x"], payload["y"]) == ("B", 20)

    def test_drag_persists_to_get_option(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        box = comp.box()
        _drag(chart, box.center(), box.center() + QPointF(18, 12))
        saved = chart.getOption()["annotations"][0]
        assert saved["ax"] == pytest.approx(comp._ax)
        assert saved["ay"] == pytest.approx(comp._ay)

    def test_drag_starts_only_on_text_box(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        before = comp.box().center()
        # 箭头线上、文本框外：不应开始拖动
        arrow_mid = QPointF(
            (comp._arrow_start.x() + comp._arrow_end.x()) / 2,
            (comp._arrow_start.y() + comp._arrow_end.y()) / 2,
        )
        assert not comp.box().adjusted(-2, -2, 2, 2).contains(arrow_mid)
        _drag(chart, arrow_mid, arrow_mid + QPointF(40, 20))
        assert comp.box().center() == before

    def test_draggable_false_is_not_dragged(self, qapp, make):
        chart = _line_chart(
            make,
            annotations=[
                {
                    "x": "B",
                    "y": 20,
                    "text": "固定",
                    "ax": 30,
                    "ay": -40,
                    "draggable": False,
                }
            ],
        )
        comp = _annotations(chart)[0]
        before = comp.box().center()
        _drag(chart, before, before + QPointF(40, 20))
        assert comp.box().center() == before

    def test_drag_is_clamped_inside_widget(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        box = comp.box()
        _drag(chart, box.center(), QPointF(10000, 10000))
        assert comp.box().right() <= chart.width()
        assert comp.box().bottom() <= chart.height()
        assert comp.box().left() >= 0
        assert comp.box().top() >= 0

    def test_set_option_merge_keeps_offsets(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        box = comp.box()
        _drag(chart, box.center(), box.center() + QPointF(20, 15))
        ax, ay = comp._ax, comp._ay
        chart.setOption({"annotations": [{"id": "peak", "text": "新文案"}]})
        merged = _annotations(chart)[0]
        assert merged.opt["text"] == "新文案"
        assert merged._ax == pytest.approx(ax)
        assert merged._ay == pytest.approx(ay)

    def test_showarrow_false_centers_box_on_anchor(self, qapp, make):
        chart = _line_chart(
            make,
            annotations=[
                {
                    "x": "B",
                    "y": 20,
                    "text": "无箭头",
                    "showarrow": False,
                }
            ],
        )
        comp = _annotations(chart)[0]
        assert comp.box().center() == comp.anchor()
        assert comp._arrow_start is None


class TestInteraction:
    def test_hover_shows_open_hand_and_hides_tooltip(self, qapp, make):
        chart = _line_chart(make, tooltip={"trigger": "item"})
        comp = _annotations(chart)[0]
        _move(chart, comp.box().center(), Qt.MouseButton.NoButton)
        assert chart.cursor().shape() == Qt.CursorShape.OpenHandCursor
        assert not chart.tooltip.active

    def test_drag_uses_closed_hand(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        _press(chart, comp.box().center())
        _move(chart, comp.box().center() + QPointF(10, 0))
        assert chart.cursor().shape() == Qt.CursorShape.ClosedHandCursor
        _release(chart, comp.box().center())

    def test_click_on_annotation_does_not_click_data(self, qapp, make):
        chart = _line_chart(make, tooltip={"trigger": "item"})
        comp = _annotations(chart)[0]
        clicks = []
        chart.itemClicked.connect(clicks.append)
        _press(chart, comp.box().center())
        _release(chart, comp.box().center())
        assert clicks == []

    def test_drag_over_data_does_not_click(self, qapp, make):
        chart = _line_chart(make, tooltip={"trigger": "item"})
        comp = _annotations(chart)[0]
        clicks = []
        chart.itemClicked.connect(clicks.append)
        box = comp.box()
        _drag(chart, box.center(), box.center() + QPointF(0, 60))
        assert clicks == []

    def test_double_click_requests_edit_without_reset(self, qapp, make):
        chart = _line_chart(make, dataZoom=[{"type": "inside"}])
        comp = _annotations(chart)[0]
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 40})
        requests = []
        chart.annotationEditRequested.connect(requests.append)
        chart.mouseDoubleClickEvent(
            _mouse(QEvent.Type.MouseButtonDblClick, comp.box().center(), chart)
        )
        zoom = chart._component("dataZoom")
        assert (zoom.start, zoom.end) == (20.0, 40.0)
        assert requests == [
            {
                "seriesName": "",
                "componentType": "annotations",
                "dataIndex": 0,
                "text": "峰值",
            }
        ]

    def test_disabled_interaction_does_not_drag(self, qapp, make):
        chart = _line_chart(make)
        comp = _annotations(chart)[0]
        chart.setInteractionEnabled("annotations", False)
        before = comp.box().center()
        _drag(chart, before, before + QPointF(40, 20))
        assert comp.box().center() == before

    def test_hidden_annotation_has_no_box(self, qapp, make):
        chart = _line_chart(
            make,
            annotations=[{"x": "B", "y": 20, "text": "隐藏", "show": False}],
        )
        comp = _annotations(chart)[0]
        assert comp.box().isNull()
        _move(chart, QPointF(300, 200), Qt.MouseButton.NoButton)
        assert chart.cursor().shape() != Qt.CursorShape.OpenHandCursor


class TestEditing:
    def test_double_click_opens_editor_and_commits(self, qapp, make):
        chart = _line_chart(make)
        chart.show()
        qapp.processEvents()
        comp = _annotations(chart)[0]
        anchor = comp.anchor()
        edited = []
        chart.annotationEdited.connect(edited.append)
        _double_click(chart, comp.box().center())
        qapp.processEvents()
        editor = chart._annotation_editor
        assert editor is not None and editor.isVisible()
        assert editor.text() == "峰值"
        editor.setText("新文案")
        editor.editingFinished.emit()
        qapp.processEvents()
        assert not editor.isVisible()
        updated = _annotations(chart)[0]
        assert updated.opt["text"] == "新文案"
        assert updated.anchor() == anchor
        assert chart.getOption()["annotations"][0]["text"] == "新文案"
        assert edited == [
            {
                "seriesName": "",
                "componentType": "annotations",
                "dataIndex": 0,
                "text": "新文案",
            }
        ]

    def test_escape_cancels_without_changing_option(self, qapp, make):
        chart = _line_chart(make)
        chart.show()
        qapp.processEvents()
        comp = _annotations(chart)[0]
        _double_click(chart, comp.box().center())
        qapp.processEvents()
        editor = chart._annotation_editor
        editor.setText("丢弃")
        qapp.sendEvent(
            editor,
            QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
            ),
        )
        qapp.processEvents()
        assert not editor.isVisible()
        assert chart.getOption()["annotations"][0]["text"] == "峰值"

    def test_public_set_annotation_text(self, qapp, make):
        chart = _line_chart(make)
        assert chart.setAnnotationText("", "annotations", 0, "API 文案")
        assert chart.getOption()["annotations"][0]["text"] == "API 文案"
        assert not chart.setAnnotationText("", "annotations", 5, "x")

    def test_disabled_builtin_editor_only_emits_request(self, qapp, make):
        chart = _line_chart(make)
        chart.setAnnotationEditingEnabled(False)
        chart.show()
        qapp.processEvents()
        requested = []
        chart.annotationEditRequested.connect(requested.append)
        comp = _annotations(chart)[0]
        _double_click(chart, comp.box().center())
        qapp.processEvents()
        assert requested and requested[0]["componentType"] == "annotations"
        assert (
            chart._annotation_editor is None or not chart._annotation_editor.isVisible()
        )

    def test_multiline_text_preserved_when_unchanged(self, qapp, make):
        chart = _line_chart(
            make,
            annotations=[
                {
                    "x": "B",
                    "y": 20,
                    "text": "第一行\n第二行",
                    "ax": 30,
                    "ay": -40,
                }
            ],
        )
        chart.show()
        qapp.processEvents()
        comp = _annotations(chart)[0]
        _double_click(chart, comp.box().center())
        qapp.processEvents()
        editor = chart._annotation_editor
        assert editor.text() == "第一行 第二行"
        editor.editingFinished.emit()
        qapp.processEvents()
        assert _annotations(chart)[0].opt["text"] == "第一行\n第二行"
