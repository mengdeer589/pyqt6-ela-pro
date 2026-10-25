"""堆叠折线：``stackStrategy`` 正负分桶（ECharts 默认 samesign）。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, series):
    chart = make(ElaChartWidget)
    chart.resize(420, 320)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "series": series,
        }
    )
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestStackStrategy:
    def test_samesign_keeps_negative_bucket_separate(self, qapp, make):
        chart = _chart(
            make,
            [
                {"type": "line", "name": "pos", "data": [5, 5], "stack": "t"},
                {"type": "line", "name": "neg", "data": [-5, -5], "stack": "t"},
            ],
        )
        pos, neg = chart.seriesRenderers
        assert pos._y_at(0) == 5
        # 默认 samesign：负值不从正值基线叠加
        assert neg._y_at(0) == -5
        assert neg._raw_value(0) == -5

    def test_negative_contributors_stack_together(self, qapp, make):
        chart = _chart(
            make,
            [
                {"type": "line", "name": "pos", "data": [5, 5], "stack": "t"},
                {"type": "line", "name": "n1", "data": [-5, -5], "stack": "t"},
                {"type": "line", "name": "n2", "data": [-2, -3], "stack": "t"},
            ],
        )
        n2 = chart.seriesRenderers[2]
        assert n2._y_at(0) == -7
        assert n2._raw_value(0) == -2

    def test_all_strategy_keeps_old_behaviour(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "pos",
                    "data": [5, 5],
                    "stack": "t",
                },
                {
                    "type": "line",
                    "name": "neg",
                    "data": [-5, -5],
                    "stack": "t",
                    "stackStrategy": "all",
                },
            ],
        )
        assert chart.seriesRenderers[1]._y_at(0) == 0

    def test_positive_strategy_ignores_negative_base(self, qapp, make):
        chart = _chart(
            make,
            [
                {"type": "line", "name": "pos", "data": [5, 5], "stack": "t"},
                {
                    "type": "line",
                    "name": "neg",
                    "data": [-5, -5],
                    "stack": "t",
                    "stackStrategy": "positive",
                },
            ],
        )
        assert chart.seriesRenderers[1]._y_at(0) == -5
