"""流式数据窗口回归。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import DataRing


def _chart(make) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(520, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "value", "min": 0, "max": 20},
            "yAxis": {"type": "value", "min": 0, "max": 20},
            "series": [
                {
                    "type": "line",
                    "name": "wave",
                    "id": "wave-id",
                    "data": [[0, 1], [1, 2]],
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def test_push_data_ring_and_window(make):
    chart = _chart(make)
    assert chart.pushData("wave", [2, 3], maxPoints=4)
    renderer = chart.seriesRenderers[0]
    assert isinstance(renderer.data(), DataRing)
    assert list(renderer.data()) == [[0, 1], [1, 2], [2, 3]]

    assert chart.pushData("wave-id", [[3, 4], [4, 5], [5, 6]], maxPoints=4)
    renderer = chart.seriesRenderers[0]
    assert len(renderer.data()) == 4
    assert list(renderer.data()) == [[2, 3], [3, 4], [4, 5], [5, 6]]
    assert chart.streamLength("wave") == 4


def test_set_data_window_and_unknown_series(make):
    chart = _chart(make)
    assert chart.setDataWindow(0, [[9, 9], [10, 10]], maxPoints=3)
    renderer = chart.seriesRenderers[0]
    assert list(renderer.data()) == [[9, 9], [10, 10]]
    assert chart.streamLength(0) == 2
    assert chart.pushData("missing", [1, 2]) is False
    assert chart.setDataWindow("missing", [1, 2]) is False


def test_push_data_updates_auto_axis_and_keeps_renderer(make):
    chart = make(ElaChartWidget)
    chart.resize(520, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{"name": "wave", "data": [[0, 1], [1, 2]]}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    renderer = chart.seriesRenderers[0]
    assert chart.pushData("wave", [[2, 10], [3, 20]], maxPoints=10)
    assert chart.seriesRenderers[0] is renderer
    assert chart.primaryCoord().x_axis.vmax == 3.0
    assert chart.primaryCoord().y_axis.vmax == 20.0


def test_push_keeps_data_zoom_window(make):
    chart = _chart(make)
    chart.setOption(
        {
            "dataZoom": [{"type": "inside", "start": 0, "end": 40}],
            "series": [{"name": "wave"}],
        }
    )
    zoom = chart._component("dataZoom")
    assert zoom is not None
    start, end = zoom.start, zoom.end
    assert chart.pushData("wave", [3, 4], maxPoints=8)
    zoom = chart._component("dataZoom")
    assert (zoom.start, zoom.end) == (start, end)
