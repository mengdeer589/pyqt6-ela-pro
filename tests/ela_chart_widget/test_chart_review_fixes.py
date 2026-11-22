"""2026-11 审查修复的回归（流式窗口 / 堆叠范围 / 布局缓存 / 多标题）。"""

from __future__ import annotations

import json

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts.axes._shared import _log_ticks
from pyqt6_ela_pro.charts.dataset import expandDataset
from pyqt6_ela_pro.charts.geo import registerMap, unregisterMap
from pyqt6_ela_pro.charts.models import ChartOption


def _ready(chart):
    chart.resize(520, 400)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def test_push_data_updates_after_ring_is_full(make):
    chart = _ready(make(ElaChartWidget))
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": [str(i) for i in range(5)]},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "data": [1, 2, 3, 4, 5]}],
        }
    )
    renderer = chart.seriesRenderers[0]
    assert chart.pushData(0, 999, maxPoints=5)
    assert renderer._y_at(4) == 999.0
    assert chart.primaryCoord().y_axis.vmax >= 999.0


def test_append_data_after_push_keeps_window(make):
    chart = _ready(make(ElaChartWidget))
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": [str(i) for i in range(9)]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [1, 2, 3]}],
        }
    )
    for value in (4, 5, 6):
        assert chart.pushData(0, value, maxPoints=10)
    assert chart.appendData({"seriesIndex": 0, "data": [7]})
    assert list(chart._option["series"][0]["data"]) == [1, 2, 3, 4, 5, 6, 7]


def test_streamed_option_dict_is_json_serializable(make):
    chart = _ready(make(ElaChartWidget))
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "data": [[0, 1], [1, 2]]}],
        }
    )
    assert chart.pushData(0, [2, 3], maxPoints=10)
    payload = chart.getOptionDict()
    json.dumps(payload)  # 不能出现 DataRing / ndarray


def test_horizontal_stacked_bar_extent_uses_total(make):
    chart = _ready(make(ElaChartWidget))
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "category", "data": ["A", "B"]},
            "series": [
                {"type": "bar", "stack": "t", "data": [3, 3]},
                {"type": "bar", "stack": "t", "data": [4, 4]},
            ],
        }
    )
    assert chart.primaryCoord().x_axis.vmax >= 7.0


def test_multiple_titles_reserve_union_in_any_order(make):
    for titles in (
        [{"text": "A", "top": 0}, {"text": "B", "top": 40}],
        [{"text": "B", "top": 40}, {"text": "A", "top": 0}],
    ):
        chart = _ready(make(ElaChartWidget))
        chart.setOption(
            {
                "animation": False,
                "title": titles,
                "xAxis": {},
                "yAxis": {},
                "series": [{"type": "line", "data": [1, 2]}],
            }
        )
        bands = [title.bandRect(chart.width(), chart.height()) for title in chart.titles]
        assert chart._content_rect().top() >= max(band.bottom() for band in bands)


def test_failed_series_layout_is_not_cached(make):
    chart = _ready(make(ElaChartWidget))
    chart.setWheelZoomEnabled(False)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {},
            "yAxis": {},
            "series": [{"type": "line", "data": [1, 2]}],
        }
    )
    chart._layout_all(force=True)

    def boom(_rect):
        raise RuntimeError("boom")

    chart.seriesRenderers[0].layout = boom
    chart._layout_key = None
    chart._layout_all(force=True)
    assert chart._layout_key is None


def test_dataset_aggregate_group_by_zero_and_average(make):
    option = ChartOption.from_dict(
        {
            "xAxis": {"type": "value"},
            "dataset": {
                "source": [[1, 1], [1, 3]],
                "transform": [
                    {"type": "aggregate", "config": {"groupBy": 0, "method": "average"}}
                ],
            },
            "series": [{"type": "line"}],
        }
    )
    out = expandDataset(option)
    assert out["series"][0]["data"] == [[1.0, 2.0]]


def test_register_raw_polygon_geometry():
    raw = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    }
    assert registerMap("review-raw-polygon", raw)
    assert unregisterMap("review-raw-polygon")


def test_log_ticks_use_even_decades_when_over_limit():
    ticks = _log_ticks(1.0, 100.0, 10.0, 2)
    assert ticks == [1.0, 10.0, 100.0]
