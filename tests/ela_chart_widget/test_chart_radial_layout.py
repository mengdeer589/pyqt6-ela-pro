"""径向图几何：radius 百分比按短边一半，外侧标签 / 维度名不互相重叠。"""

from __future__ import annotations

from pyqt6_ela_pro.charts import ElaChartWidget


def _pie(make, size, series: dict):
    chart = make(ElaChartWidget)
    chart.resize(*size)
    chart.setOption(
        {
            "animation": False,
            "series": [{"type": "pie", "name": "p", "data": [3, 2], **series}],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestPieRadius:
    def test_percent_is_relative_to_half_short_side(self, make):
        chart = _pie(
            make,
            (640, 420),
            {"radius": "68%", "label": {"show": False}},
        )
        renderer = chart.seriesRenderers[0]
        half = min(chart.width(), chart.height()) / 2
        assert renderer._r_out == half * 0.68

    def test_ring_keeps_inner_outer_ratio(self, make):
        chart = _pie(
            make,
            (640, 420),
            {"radius": ["42%", "68%"], "label": {"show": False}},
        )
        renderer = chart.seriesRenderers[0]
        half = min(chart.width(), chart.height()) / 2
        assert renderer._r_in == half * 0.42
        assert renderer._r_out == half * 0.68

    def test_outside_labels_do_not_eat_the_radius(self, make):
        # 画廊尺寸（547×232 减图例）下 68% 半径曾被固定 56px 边距压到 ~33px。
        chart = _pie(make, (547, 232), {"radius": ["16%", "72%"]})
        renderer = chart.seriesRenderers[0]
        half = min(chart._content_rect().width(), chart._content_rect().height()) / 2
        assert renderer._r_out >= half * 0.6


class TestRadarRadius:
    def _radar(self, make, series_extra: dict):
        chart = make(ElaChartWidget)
        chart.resize(640, 420)
        chart.setOption(
            {
                "animation": False,
                "series": [
                    {
                        "type": "radar",
                        "name": "r",
                        "indicator": [
                            {"name": "A", "max": 10},
                            {"name": "B", "max": 10},
                            {"name": "C", "max": 10},
                        ],
                        "data": [{"name": "s", "value": [5, 8, 6]}],
                        **series_extra,
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        return chart.seriesRenderers[0]

    def test_percent_is_relative_to_half_short_side(self, make):
        renderer = self._radar(make, {"radius": "70%", "axisName": {"show": False}})
        assert renderer._radius == min(640, 420) / 2 * 0.7

    def test_axis_names_keep_full_radius(self, make):
        # 曾被固定 34px 边距压成 49px（内容短边一半约 104px）。
        renderer = self._radar(make, {"radius": "70%"})
        assert renderer._radius == min(640, 420) / 2 * 0.7

    def test_default_is_echarts_75_percent(self, make):
        renderer = self._radar(make, {})
        assert renderer._radius == min(640, 420) / 2 * 0.75


class TestPieOutsideLabels:
    def test_labels_do_not_overlap(self, make):
        chart = make(ElaChartWidget)
        chart.resize(640, 420)
        chart.setOption(
            {
                "animation": False,
                "series": [
                    {
                        "type": "pie",
                        "name": "p",
                        "radius": ["10%", "60%"],
                        "data": [
                            {"name": f"项{i}", "value": 1 if i else 20}
                            for i in range(12)
                        ],
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        chart._render_to_painter()
        rects = [rect for _index, rect, _text in chart.seriesRenderers[0]._label_rects]
        assert len(rects) == 12
        for i, first in enumerate(rects):
            for second in rects[i + 1 :]:
                assert not first.intersects(second)
