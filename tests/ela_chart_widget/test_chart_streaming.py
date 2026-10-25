"""appendData：原地增量（不重建渲染器）、保留缩放窗口、轴范围更新。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaChartWidget


def _chart(make):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "dataZoom": [{"type": "inside", "start": 0, "end": 100}],
            "series": [{"type": "line", "name": "A", "data": [[i, i] for i in range(50)]}],
        }
    )
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestAppendData:
    def test_keeps_renderer_identity(self, qapp, make):
        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        assert chart.appendData({"seriesName": "A", "data": [[50, 50]]}) is True
        assert chart.seriesRenderers[0] is renderer
        assert len(renderer.data()) == 51

    def test_keeps_zoom_window(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 60})
        chart.appendData({"seriesName": "A", "data": [[50, 50]]})
        zoom = chart._component("dataZoom")
        assert (zoom.start, zoom.end) == (20.0, 60.0)

    def test_updates_value_axis_extent(self, qapp, make):
        chart = _chart(make)
        old_max = chart.primaryCoord().y_axis.vmax
        chart.appendData({"seriesName": "A", "data": [[60, 500]]})
        assert chart.primaryCoord().y_axis.vmax > old_max

    def test_append_multiple_points(self, qapp, make):
        chart = _chart(make)
        chart.appendData({"seriesName": "A", "data": [[50, 50], [51, 51]]})
        assert len(chart.seriesRenderers[0].data()) == 52
