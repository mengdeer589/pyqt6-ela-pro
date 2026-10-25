"""dataZoom 状态跨 setOption 保留 + getOption 返回交互后的实时状态。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaChartWidget

_BASE = {
    "animation": False,
    "xAxis": {"type": "category", "data": [str(i) for i in range(50)]},
    "yAxis": {"type": "value"},
    "dataZoom": [{"type": "inside", "start": 0, "end": 100}],
    "series": [{"type": "line", "name": "A", "data": list(range(50))}],
}


def _chart(make, **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {**_BASE, **patch}
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestZoomState:
    def test_set_option_keeps_user_window(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 60})
        assert (chart._component("dataZoom").start, chart._component("dataZoom").end) == (
            20.0,
            60.0,
        )
        chart.setOption({"series": [{"data": list(range(50))}]})
        zoom = chart._component("dataZoom")
        assert (zoom.start, zoom.end) == (20.0, 60.0)

    def test_append_data_keeps_user_window(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "dataZoom", "start": 10, "end": 40})
        chart.appendData({"seriesName": "A", "data": [50]})
        zoom = chart._component("dataZoom")
        assert (zoom.start, zoom.end) == (10.0, 40.0)

    def test_explicit_data_zoom_change_wins(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 60})
        chart.setOption(
            {"dataZoom": [{"type": "inside", "start": 5, "end": 25}]}
        )
        zoom = chart._component("dataZoom")
        assert (zoom.start, zoom.end) == (5.0, 25.0)

    def test_not_merge_resets_window(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 60})
        chart.setOption(dict(_BASE), notMerge=True)
        zoom = chart._component("dataZoom")
        assert (zoom.start, zoom.end) == (0.0, 100.0)


class TestGetOptionLiveState:
    def test_get_option_reads_current_window(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 60})
        entry = chart.getOption()["dataZoom"][0]
        assert (entry["start"], entry["end"]) == (20.0, 60.0)

    def test_get_option_reads_legend_selection(self, qapp, make):
        chart = _chart(make, legend={"show": True})
        chart.dispatchAction({"type": "legendUnSelect", "name": "A"})
        selected = chart.getOption()["legend"]["selected"]
        assert selected["A"] is False

    def test_internal_option_is_not_mutated(self, qapp, make):
        chart = _chart(make)
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 60})
        assert chart._option["dataZoom"][0]["start"] == 0
