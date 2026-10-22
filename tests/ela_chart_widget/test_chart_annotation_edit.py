"""标注标签双击编辑：内置行内编辑器 / 信号 / 取消 / 复位竞争。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent

from pyqt6_ela_pro.charts import ElaChartWidget


def _chart(make, *, editable=True):
    chart = make(ElaChartWidget)
    chart.resize(640, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "S",
                    "data": [1, 3, 2],
                    "markPoint": {"data": [{"type": "max", "name": "peak"}]},
                }
            ],
        }
    )
    chart.setAnnotationEditingEnabled(editable)
    chart.show()
    chart.anim.setProgress(1.0)
    return chart


def _double_click(chart, pos):
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    chart.mouseDoubleClickEvent(event)
    return event


def _mark_point(chart):
    comp = chart._component("markPoint")
    assert comp is not None and comp._marks
    return comp, comp._marks[0]


def _label_chart(make, *, editable=True):
    chart = make(ElaChartWidget)
    chart.resize(640, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "S",
                    "data": [1, 3, 2],
                    "label": {"show": True},
                }
            ],
        }
    )
    chart.setAnnotationEditingEnabled(editable)
    chart.show()
    chart.anim.setProgress(1.0)
    chart.grab()
    return chart


class TestAnnotationEditing:
    def test_double_click_label_opens_editor_and_commits(self, qapp, make):
        chart = _chart(make)
        edited = []
        chart.annotationEdited.connect(edited.append)
        comp, mark = _mark_point(chart)
        _double_click(chart, mark["rect"].center())
        qapp.processEvents()
        editor = chart._annotation_editor
        assert editor is not None and editor.isVisible()
        assert editor.text() == "peak"
        editor.setText("new peak")
        editor.editingFinished.emit()
        qapp.processEvents()
        assert not editor.isVisible()
        assert chart.getOption()["series"][0]["markPoint"]["data"][0]["name"] == (
            "new peak"
        )
        assert edited and edited[0]["componentType"] == "markPoint"
        assert edited[0]["dataIndex"] == 0
        assert edited[0]["text"] == "new peak"

    def test_escape_cancels_without_changing_option(self, qapp, make):
        chart = _chart(make)
        comp, mark = _mark_point(chart)
        _double_click(chart, mark["rect"].center())
        qapp.processEvents()
        editor = chart._annotation_editor
        editor.setText("discard me")
        qapp.sendEvent(
            editor,
            QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
            ),
        )
        qapp.processEvents()
        assert not editor.isVisible()
        assert chart.getOption()["series"][0]["markPoint"]["data"][0]["name"] == "peak"

    def test_double_click_elsewhere_still_resets_view(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 80})
        comp = chart._component("dataZoom")
        assert (comp.start, comp.end) != (0.0, 100.0)
        _double_click(chart, chart.primaryCoord().plot.center())
        qapp.processEvents()
        assert (comp.start, comp.end) == (0.0, 100.0)
        assert (
            chart._annotation_editor is None or not chart._annotation_editor.isVisible()
        )

    def test_disabled_builtin_editor_only_emits_request(self, qapp, make):
        chart = _chart(make, editable=False)
        requested = []
        chart.annotationEditRequested.connect(requested.append)
        comp, mark = _mark_point(chart)
        _double_click(chart, mark["rect"].center())
        qapp.processEvents()
        assert requested and requested[0]["componentType"] == "markPoint"
        assert (
            chart._annotation_editor is None or not chart._annotation_editor.isVisible()
        )

    def test_public_set_annotation_text(self, qapp, make):
        chart = _chart(make)
        assert chart.setAnnotationText("S", "markPoint", 0, "api label")
        assert chart.getOption()["series"][0]["markPoint"]["data"][0]["name"] == (
            "api label"
        )
        assert not chart.setAnnotationText("missing", "markPoint", 0, "x")

    def test_markline_label_can_be_edited(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(640, 400)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "line",
                        "name": "S",
                        "data": [1, 3, 2],
                        "markLine": {"data": [{"type": "average", "name": "avg"}]},
                    }
                ],
            }
        )
        chart.show()
        chart.anim.setProgress(1.0)
        qapp.processEvents()
        comp = chart._component("markLine")
        assert comp is not None and comp._lines
        line = comp._lines[0]
        _double_click(chart, line["rect"].center())
        qapp.processEvents()
        assert chart._annotation_editor is not None
        chart._annotation_editor.setText("mean")
        chart._annotation_editor.editingFinished.emit()
        qapp.processEvents()
        assert chart.getOption()["series"][0]["markLine"]["data"][0]["name"] == "mean"


class TestPointLabelEditing:
    def test_double_click_point_label_edits_series_label(self, qapp, make):
        chart = _label_chart(make)
        renderer = chart.seriesRenderers[0]
        assert renderer._label_rects
        edited = []
        chart.annotationEdited.connect(edited.append)
        index, rect, text = renderer._label_rects[1]
        assert text == "3"
        _double_click(chart, rect.center())
        qapp.processEvents()
        editor = chart._annotation_editor
        assert editor is not None and editor.isVisible()
        assert editor.text() == "3"
        editor.setText("target")
        editor.editingFinished.emit()
        qapp.processEvents()
        assert chart.getOption()["series"][0]["labelTexts"] == {"1": "target"}
        assert chart.seriesRenderers[0].labelText(1, 3, "b") == "target"
        assert edited and edited[0]["componentType"] == "seriesLabel"
        assert edited[0]["dataIndex"] == 1

    def test_set_series_label_text_and_clear_override(self, qapp, make):
        chart = _label_chart(make)
        assert chart.setSeriesLabelText("S", 1, "custom")
        assert chart.seriesRenderers[0].labelText(1, 3, "b") == "custom"
        assert chart.getOption()["series"][0]["labelTexts"] == {"1": "custom"}
        assert chart.setSeriesLabelText("S", 1, "")
        assert chart.seriesRenderers[0].labelText(1, 3, "b") == "3"
        assert chart.getOption()["series"][0]["labelTexts"] == {}

    def test_label_editable_false_does_not_capture_double_click(self, qapp, make):
        chart = _label_chart(make)
        chart.setOption(
            {"series": [{"name": "S", "label": {"show": True, "editable": False}}]}
        )
        chart.grab()
        renderer = chart.seriesRenderers[0]
        assert renderer._label_rects
        pos = renderer._label_rects[0][1].center()
        _double_click(chart, pos)
        qapp.processEvents()
        assert (
            chart._annotation_editor is None or not chart._annotation_editor.isVisible()
        )
        assert renderer.labelText(0, 1, "a") == "1"

    def test_bar_label_is_editable(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(640, 400)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar",
                        "name": "B",
                        "data": [1, 3, 2],
                        "label": {"show": True},
                    }
                ],
            }
        )
        chart.show()
        chart.anim.setProgress(1.0)
        chart.grab()
        qapp.processEvents()
        renderer = chart.seriesRenderers[0]
        assert renderer._label_rects
        _double_click(chart, renderer._label_rects[1][1].center())
        qapp.processEvents()
        editor = chart._annotation_editor
        assert editor is not None and editor.isVisible()
        editor.setText("bar label")
        editor.editingFinished.emit()
        qapp.processEvents()
        assert chart.getOption()["series"][0]["labelTexts"] == {"1": "bar label"}
