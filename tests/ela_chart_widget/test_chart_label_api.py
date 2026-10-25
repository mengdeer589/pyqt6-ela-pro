"""轴标签 / 数据点标签的运行时 API（updateAxis / updateSeries / label 糖）。"""

from __future__ import annotations

from pyqt6_ela_pro.charts import ElaChartWidget


def _chart(make) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(
        {
            "animation": False,
            "xAxis": [
                {"type": "category", "data": ["A", "B", "C"]},
                {"type": "category", "data": ["Q1", "Q2", "Q3"], "position": "top"},
            ],
            "yAxis": [{"type": "value"}, {"type": "value", "position": "right"}],
            "series": [
                {"type": "line", "id": "s0", "name": "S0", "data": [1, 2, 3]},
                {
                    "type": "line",
                    "id": "s1",
                    "name": "S1",
                    "data": [3, 2, 1],
                    "xAxisIndex": 1,
                    "yAxisIndex": 1,
                },
            ],
        }
    )
    return chart


class TestAxisArrayMerge:
    def test_multi_axis_setoption_merges_by_index(self, make):
        chart = _chart(make)
        chart.setOption({"xAxis": [{"axisLabel": {"formatter": "{value}!"}}]})
        option = chart.getOption()
        assert len(option["xAxis"]) == 2
        assert option["xAxis"][0]["axisLabel"]["formatter"] == "{value}!"
        assert option["xAxis"][1]["data"] == ["Q1", "Q2", "Q3"]

    def test_update_axis_targets_one_axis(self, make):
        chart = _chart(make)
        assert chart.updateAxis("y", {"axisLabel": {"color": "#ff0000"}}, 1) is True
        option = chart.getOption()
        assert option["yAxis"][0].get("axisLabel") is None
        assert option["yAxis"][1]["axisLabel"]["color"] == "#ff0000"

    def test_update_axis_out_of_range_is_rejected(self, make):
        chart = _chart(make)
        assert chart.updateAxis("x", {"axisLabel": {"show": False}}, 5) is False
        assert len(chart.getOption()["xAxis"]) == 2

    def test_update_axis_dict_axis(self, make):
        chart = make(ElaChartWidget)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A"]},
                "yAxis": {},
                "series": [{"type": "line", "data": [1]}],
            }
        )
        assert chart.updateAxis("x", {"axisLabel": {"rotate": 30}}) is True
        option = chart.getOption()["xAxis"]
        assert option["axisLabel"]["rotate"] == 30
        assert option["data"] == ["A"]

    def test_dict_form_keeps_other_axes(self, make):
        """对象写法 = 只改第 0 条；**不能把多轴塌成单轴**（第二条会连 data 一起丢）。"""
        chart = _chart(make)
        chart.setOption({"xAxis": {"axisLabel": {"fontSize": 14}}})
        option = chart.getOption()
        assert isinstance(option["xAxis"], list)
        assert len(option["xAxis"]) == 2
        assert option["xAxis"][0]["axisLabel"]["fontSize"] == 14
        assert option["xAxis"][1]["data"] == ["Q1", "Q2", "Q3"]

    def test_dict_axis_keeps_dict_shape(self, make):
        """旧值是单对象时不能被悄悄升级成数组（``getOption`` 形状要稳定）。"""
        chart = make(ElaChartWidget)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A"]},
                "yAxis": {},
                "series": [{"type": "line", "data": [1]}],
            }
        )
        chart.setOption({"xAxis": {"axisLabel": {"fontSize": 13}}})
        option = chart.getOption()["xAxis"]
        assert isinstance(option, dict)
        assert option["data"] == ["A"]
        assert option["axisLabel"]["fontSize"] == 13

    def test_list_form_merges_into_dict_axis(self, make):
        chart = make(ElaChartWidget)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A"]},
                "yAxis": {},
                "series": [{"type": "line", "data": [1]}],
            }
        )
        chart.setOption(
            {"xAxis": [{"axisLabel": {"fontSize": 15}}, {"position": "top"}]}
        )
        option = chart.getOption()["xAxis"]
        assert isinstance(option, list)
        assert option[0]["axisLabel"]["fontSize"] == 15
        assert option[0]["data"] == ["A"]
        assert option[1]["position"] == "top"

    def test_update_axis_rejects_radar(self, make):
        """雷达没有「轴 option」：``series.indicator`` 不是坐标轴，别假装能改。"""
        chart = _chart(make)
        assert chart.updateAxis("radar", {"axisLabel": {"fontSize": 14}}) is False


class TestUpdateSeries:
    def test_by_index_name_id(self, make):
        chart = _chart(make)
        assert chart.updateSeries({"label": {"show": True}}, seriesIndex=1) is True
        option = chart.getOption()
        assert option["series"][0].get("label") is None
        assert option["series"][1]["label"]["show"] is True

        assert chart.updateSeries({"label": {"fontSize": 13}}, seriesName="S0") is True
        assert chart.getOption()["series"][0]["label"]["fontSize"] == 13

        assert chart.updateSeries({"label": {"color": "#00ff00"}}, seriesId="s0") is True
        assert chart.getOption()["series"][0]["label"]["color"] == "#00ff00"

    def test_missing_selector_returns_false(self, make):
        chart = _chart(make)
        assert chart.updateSeries({"label": {"show": True}}, seriesName="nope") is False
        assert chart.updateSeries({"label": {"show": True}}, seriesId="") is False


class TestAxisLabelFormatter:
    def test_callable_gets_tick_index(self, make):
        chart = _chart(make)
        assert (
            chart.setAxisLabelFormatter(
                "x", lambda value, index: f"{value}#{index}", 1
            )
            is True
        )
        axis = chart.coords[0].x_axes[1]
        assert axis.formatTickLabel("Q2", 1) == "Q2#1"

    def test_category_axis_uses_formatter(self, make):
        chart = _chart(make)
        assert chart.setCategoryLabels(["Jan", "Feb", "Mar"], 0) is True
        assert chart.setAxisLabelFormatter("x", "{value} 月", 0) is True
        chart._layout_all()
        coord = chart.coords[0]
        labels = [
            label
            for _x, _y, label, _idx in coord._axis_positions(coord.x_axes[0], False)
        ]
        assert labels == ["Jan 月", "Feb 月", "Mar 月"]

    def test_category_labels_keep_axis_options(self, make):
        chart = _chart(make)
        assert chart.setCategoryLabels(["一", "二", "三"], 0) is True
        option = chart.getOption()
        assert option["xAxis"][0]["data"] == ["一", "二", "三"]
        assert option["xAxis"][0]["type"] == "category"
        assert option["xAxis"][1]["data"] == ["Q1", "Q2", "Q3"]


class TestSeriesLabelText:
    def test_by_index_and_clear(self, make):
        chart = _chart(make)
        assert chart.setSeriesLabelText(seriesIndex=0, dataIndex=1, text="峰值") is True
        assert chart.seriesLabelTexts(seriesIndex=0) == {"1": "峰值"}
        assert chart.seriesRenderers[0].labelText(1, 2) == "峰值"

        assert chart.clearSeriesLabelTexts(seriesIndex=0) is True
        assert chart.seriesLabelTexts(seriesIndex=0) == {}

    def test_by_name_and_id(self, make):
        chart = _chart(make)
        assert chart.setSeriesLabelText(seriesName="S0", dataIndex=0, text="A") is True
        assert chart.setSeriesLabelText(seriesId="s0", dataIndex=1, text="B") is True
        assert chart.seriesLabelTexts(seriesId="s0") == {"0": "A", "1": "B"}
        assert chart.seriesLabelTexts(seriesId="") == {}

    def test_annotation_by_index(self, make):
        chart = make(ElaChartWidget)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A", "B"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "line",
                        "name": "S0",
                        "data": [1, 2],
                        "markPoint": {"data": [{"type": "max", "name": "峰值"}]},
                    }
                ],
            }
        )
        assert (
            chart.setAnnotationText(
                componentType="markPoint", seriesIndex=0, dataIndex=0, text="最高"
            )
            is True
        )
        component = chart._component("markPoint")
        assert component.opt["data"][0]["name"] == "最高"
