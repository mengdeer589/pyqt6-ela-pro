"""axisPointer.link / graph edgeSymbol / progressive / universalTransition。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QPainter

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import connectCharts, disconnectCharts


def _paint(chart) -> None:
    image = QImage(chart.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        chart._paint_content(painter, use_series_cache=False)
    finally:
        painter.end()


def _axis_chart(make) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(480, 360)
    chart.setOption(
        {
            "animation": False,
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": ["A", "B"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "name": "S", "data": [1, 2]}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def test_axis_pointer_link_same_chart(make):
    chart = make(ElaChartWidget)
    chart.resize(520, 380)
    chart.setOption(
        {
            "animation": False,
            "tooltip": {"trigger": "axis"},
            "axisPointer": {"type": "line", "link": [{"xAxisIndex": [0, 1]}]},
            "xAxis": [
                {"type": "category", "data": ["A", "B"]},
                {"type": "category", "data": ["A", "B"]},
            ],
            "yAxis": {"type": "value"},
            "series": [
                {"type": "line", "data": [1, 2]},
                {"type": "line", "xAxisIndex": 1, "data": [2, 1]},
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    coord = chart.primaryCoord()
    chart._tooltip_axis(coord.plot.center())
    assert chart.tooltip._linked_axes
    assert chart.tooltip._linked_axes[0][1] == 1


def test_axis_pointer_link_all_and_y_axis(make):
    chart = make(ElaChartWidget)
    chart.resize(560, 420)
    chart.setOption(
        {
            "animation": False,
            "tooltip": {"trigger": "axis"},
            "axisPointer": {"type": "line", "link": "all"},
            "xAxis": {"type": "value"},
            "yAxis": [
                {"type": "category", "data": ["A", "B"]},
                {"type": "category", "data": ["A", "B"]},
            ],
            "series": [
                {"type": "bar", "data": [1, 2]},
                {"type": "bar", "yAxisIndex": 1, "data": [3, 4]},
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    coord = chart.primaryCoord()
    chart._tooltip_axis(coord.plot.center())
    linked = chart.tooltip._linked_axes
    assert linked
    # 横向类目轴：联动的是另一条 y 轴，不是 x 轴。
    assert {kind for kind, _index, _value in linked} == {"y"}


def test_axis_pointer_link_false_disables_group_tip(make):
    first = _axis_chart(make)
    second = _axis_chart(make)
    first.setGroup("axis-link")
    second.setGroup("axis-link")
    connectCharts("axis-link")
    try:
        first.setOption({"axisPointer": {"link": False}})
        first._broadcastGroup("axisTip", {"percent": 0.5})
        assert second.tooltip.active is False

        first.setOption({"axisPointer": {"link": True}})
        first._broadcastGroup("axisTip", {"percent": 0.5})
        assert second.tooltip.active is True
    finally:
        disconnectCharts("axis-link")


def test_tooltip_confine_flag(make):
    chart = _axis_chart(make)
    assert chart.tooltip.confine() is False
    assert chart.tooltip.enterable() is False
    chart.setOption({"tooltip": {"confine": True, "enterable": True}})
    assert chart.tooltip.confine() is True
    assert chart.tooltip.enterable() is True


def _paint_tooltip_box(chart):
    image = QImage(chart.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        chart._paint_content(painter, use_series_cache=False)
    finally:
        painter.end()
    return chart.tooltip._box


def test_tooltip_confine_keeps_box_inside(make):
    chart = _axis_chart(make)
    chart.tooltip.showAt(
        QPointF(chart.width() - 4, chart.height() - 4),
        [(None, "A", "1")],
    )
    box = _paint_tooltip_box(chart)
    assert box.right() > chart.width() or box.bottom() > chart.height()

    chart.setOption({"tooltip": {"confine": True}})
    chart.tooltip.showAt(
        QPointF(chart.width() - 4, chart.height() - 4),
        [(None, "A", "1")],
    )
    box = _paint_tooltip_box(chart)
    assert box.right() <= chart.width()
    assert box.bottom() <= chart.height()


def test_graph_edge_symbols_paint(make):
    chart = make(ElaChartWidget)
    chart.resize(500, 400)
    chart.setOption(
        {
            "animation": False,
            "series": [
                {
                    "type": "graph",
                    "data": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
                    "links": [
                        {"source": "A", "target": "B"},
                        {"source": "B", "target": "C"},
                    ],
                    "edgeSymbol": ["circle", "arrow"],
                    "edgeSymbolSize": [4, 8],
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    _paint(chart)
    assert chart.getOptionDict()["series"][0]["edgeSymbol"] == ["circle", "arrow"]


def test_progressive_draws_in_frames_and_export_is_full(make):
    chart = make(ElaChartWidget)
    chart.resize(520, 400)
    data = [[index, index % 90] for index in range(5000)]
    chart.setOption(
        {
            "animation": False,
            "progressive": 120,
            "progressiveThreshold": 100,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "data": data}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    renderer = chart.seriesRenderers[0]
    _paint(chart)
    assert renderer._progressive_partial is True
    assert chart._progressive_step == 1
    for _ in range(3):
        chart._advance_progressive()
        renderer = chart.seriesRenderers[0]
        _paint(chart)
    assert renderer._progressive_partial is True

    chart._exporter._render_image({})
    assert renderer._progressive_partial is False


def test_realtime_sort_reorders_categories(make):
    chart = make(ElaChartWidget)
    chart.resize(480, 360)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A", "B", "C"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "realtimeSort": True, "data": [10, 30, 20]}],
        }
    )
    option = chart.getOptionDict()
    assert option["xAxis"]["data"] == ["B", "C", "A"]
    assert option["series"][0]["data"] == [30, 20, 10]


def test_selected_map_initial_state(make):
    chart = make(ElaChartWidget)
    chart.resize(480, 360)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A", "B", "C"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "selectedMode": "multiple",
                    "selectedMap": {"0": True, "1": False, "2": True},
                    "data": [1, 2, 3],
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    assert chart.selectedIndices(chart.seriesRenderers[0]) == {0, 2}


def test_color_by_data_and_toolbox_data_view(make):
    chart = make(ElaChartWidget)
    chart.resize(500, 360)
    chart.setOption(
        {
            "animation": False,
            "toolbox": {"feature": ["dataView"]},
            "xAxis": {"type": "category", "data": ["A", "B", "C"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "colorBy": "data",
                    "data": [1, 2, 3],
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    renderer = chart.seriesRenderers[0]
    assert len({renderer.itemColor(i).name() for i in range(3)}) == 3
    toolbox = chart._component("toolbox")
    toolbox._show_data_view()
    dialog = getattr(toolbox, "_data_view", None)
    assert dialog is not None
    dialog.close()


def test_datazoom_brush_select_toggle(make):
    chart = make(ElaChartWidget)
    chart.resize(520, 380)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": [str(i) for i in range(20)]},
            "yAxis": {"type": "value"},
            "dataZoom": [
                {
                    "type": "slider",
                    "start": 20,
                    "end": 40,
                    "brushSelect": False,
                }
            ],
            "series": [{"type": "line", "data": list(range(20))}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    zoom = chart._component("dataZoom")
    assert zoom.brushSelect() is False
    before = (zoom.start, zoom.end)
    pos = QPointF(
        zoom._track.left() + zoom._track.width() * 0.85,
        zoom._track.center().y(),
    )
    assert zoom.onMousePress(pos) is False
    assert (zoom.start, zoom.end) == before

    handle = zoom._h_end.center()
    assert zoom.onMousePress(handle) is True
    zoom.onMouseMove(QPointF(handle.x() - 20, handle.y()))
    assert (zoom.start, zoom.end) != before


def test_progressive_mod_spreads_indices(make):
    chart = make(ElaChartWidget)
    chart.setOption(
        {
            "animation": False,
            "progressive": 10,
            "progressiveThreshold": 10,
            "progressiveChunkMode": "mod",
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{"type": "scatter", "data": [[i, i] for i in range(1000)]}],
        }
    )
    renderer = chart.seriesRenderers[0]
    indices = list(renderer.progressiveIndices(1000))
    assert 0 < len(indices) < 1000
    assert indices[0] == 0
    assert indices[1] > 1


def test_universal_transition_cross_fade(make):
    chart = make(ElaChartWidget)
    chart.resize(500, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A", "B"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [1, 2]}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    chart.setOption(
        {
            "universalTransition": {"duration": 200},
            "series": [{"type": "line", "data": [2, 1]}],
        }
    )
    assert chart._universal_prev is not None
    assert chart._universal_morph
    assert chart._universal_t == 0.0
    chart._universal_t = 0.5
    _paint(chart)
    chart._universal_timer.stop()
    chart._universal_prev = None
    chart._universal_morph = None
    chart._universal_t = 1.0
    _paint(chart)
