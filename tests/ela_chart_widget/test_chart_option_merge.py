"""``setOption`` 的组件数组合并语义（不需要 numpy）。

ECharts 的组件数组（``visualMap`` / 多轴）在合并模式下**按位置合并**：
「只改第 1 个」不能把第 2 个删掉。整体替换是静默数据丢失 —— 用户看到的
只是「第二个色带 / 第二条轴不见了」。
"""

from __future__ import annotations

from pyqt6_ela_pro.charts import ElaChartWidget


def _make(make, option=None) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(480, 360)
    chart.setOption(
        option
        or {
            "animation": False,
            "xAxis": {"type": "category", "data": ["A", "B"]},
            "yAxis": {"type": "value"},
            "series": [
                {"type": "line", "name": "alpha", "data": [1, 2]},
                {"type": "line", "name": "beta", "data": [2, 1]},
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestVisualMapArrayMerge:
    def test_update_first_keeps_others(self, make):
        chart = _make(make)
        chart.setOption(
            {
                "visualMap": [
                    {"min": 0, "max": 10},
                    {"seriesIndex": 1, "min": 0, "max": 5},
                ]
            }
        )
        assert len(chart.getOption()["visualMap"]) == 2

        chart.setOption({"visualMap": [{"max": 20}]})
        option = chart.getOption()["visualMap"]
        assert len(option) == 2, "只改第 1 个却把第 2 个丢掉了"
        assert option[0]["max"] == 20
        assert option[1]["seriesIndex"] == 1
        assert option[1]["max"] == 5

        maps = [c for c in chart.components if c.optionKey == "visualMap"]
        assert len(maps) == 2

    def test_append_new_entry(self, make):
        chart = _make(make)
        chart.setOption({"visualMap": [{"min": 0, "max": 10}]})
        chart.setOption({"visualMap": [{}, {"seriesIndex": 1, "min": 1, "max": 2}]})
        option = chart.getOption()["visualMap"]
        assert len(option) == 2
        assert option[0]["max"] == 10
        assert option[1]["seriesIndex"] == 1
