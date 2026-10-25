"""选中态：selectedMode / dispatchAction / selectchanged / getOption。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, *, mode="multiple", **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "tooltip": {"trigger": "item"},
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "line",
                "name": "A",
                "mode": "lines+markers",
                "selectedMode": mode,
                "data": [1, 2, 3],
            }
        ],
    }
    option.update(patch)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _send(chart, event_type, pos, button=Qt.MouseButton.LeftButton):
    event = QMouseEvent(
        event_type,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    if event_type == QEvent.Type.MouseMove:
        event = QMouseEvent(
            event_type,
            QPointF(pos),
            QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        chart.mouseMoveEvent(event)
    elif event_type == QEvent.Type.MouseButtonPress:
        chart.mousePressEvent(event)
    else:
        chart.mouseReleaseEvent(event)


def _click(chart, pos):
    _send(chart, QEvent.Type.MouseMove, pos)
    _send(chart, QEvent.Type.MouseButtonPress, pos)
    _send(chart, QEvent.Type.MouseButtonRelease, pos)


class TestClickSelection:
    def test_default_selected_mode_is_false(self, qapp, make):
        chart = _chart(make, mode="false")
        renderer = chart.seriesRenderers[0]
        _click(chart, renderer._points[1])
        assert chart.selectedIndices(renderer) == set()

    def test_multiple_toggles_on_and_off(self, qapp, make):
        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        seen = []
        chart.on("selectchanged", seen.append)
        _click(chart, renderer._points[1])
        assert chart.isSelected(renderer, 1) is True
        assert seen and seen[-1]["selected"][0]["dataIndex"] == 1
        _click(chart, renderer._points[1])
        assert chart.isSelected(renderer, 1) is False

    def test_single_keeps_only_one(self, qapp, make):
        chart = _chart(make, mode="single")
        renderer = chart.seriesRenderers[0]
        _click(chart, renderer._points[0])
        _click(chart, renderer._points[2])
        assert chart.selectedIndices(renderer) == {2}


class TestSelectionActions:
    def test_select_and_unselect(self, qapp, make):
        chart = _chart(make)
        assert chart.dispatchAction(
            {"type": "select", "seriesName": "A", "dataIndex": [0, 2]}
        )
        renderer = chart.seriesRenderers[0]
        assert chart.selectedIndices(renderer) == {0, 2}
        assert chart.dispatchAction(
            {"type": "unselect", "seriesName": "A", "dataIndex": 0}
        )
        assert chart.selectedIndices(renderer) == {2}

    def test_toggle_select(self, qapp, make):
        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        chart.dispatchAction(
            {"type": "toggleSelect", "seriesName": "A", "dataIndex": 1}
        )
        assert chart.selectedIndices(renderer) == {1}
        chart.dispatchAction(
            {"type": "toggleSelect", "seriesName": "A", "dataIndex": 1}
        )
        assert chart.selectedIndices(renderer) == set()

    def test_option_selected_is_initial_state(self, qapp, make):
        chart = _chart(make)
        chart.setOption({"series": [{"selected": [0, 2]}]})
        renderer = chart.seriesRenderers[0]
        assert chart.selectedIndices(renderer) == {0, 2}

    def test_get_option_exposes_selected_map(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "select", "seriesName": "A", "dataIndex": 1})
        assert chart.getOption()["series"][0]["selectedMap"] == {"1": True}

    def test_selection_survives_set_option(self, qapp, make):
        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        _click(chart, renderer._points[1])
        chart.setOption({"series": [{"name": "A", "data": [1, 2, 3]}]})
        assert chart.selectedIndices(chart.seriesRenderers[0]) == {1}

    def test_not_merge_clears_selection(self, qapp, make):
        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        _click(chart, renderer._points[1])
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "line", "name": "A", "data": [1, 2, 3]}
                ],
            },
            notMerge=True,
        )
        assert chart.selectedIndices(chart.seriesRenderers[0]) == set()


class TestSelectionStyle:
    def test_select_item_style(self, qapp, make):
        chart = _chart(make)
        chart.setOption(
            {
                "series": [
                    {
                        "type": "line",
                        "name": "A",
                        "data": [1, 2, 3],
                        "select": {"itemStyle": {"color": "#ff0000"}},
                    }
                ]
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.selectColor(0).name() == "#ff0000"
