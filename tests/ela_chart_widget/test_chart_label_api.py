"""轴标签 / 数据点标签的运行时 API（updateAxis / updateSeries / label 糖）。"""

from __future__ import annotations

import pytest

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


class TestAxisLabelAlignment:
    """默认对齐：x 水平居中于刻度；y 垂直居中于刻度线、水平贴轴。"""

    def test_default_style(self, make):
        chart = _chart(make)
        x_style = chart.axisLabelStyle("x", 0)
        assert x_style["align"] == "center"
        assert x_style["verticalAlign"] == "top"
        assert x_style["margin"] == 5
        y_style = chart.axisLabelStyle("y", 0)
        assert y_style["align"] == "right"
        assert y_style["verticalAlign"] == "middle"
        assert y_style["margin"] == 6

    def test_secondary_axes_follow_their_side(self, make):
        chart = _chart(make)
        assert chart.axisLabelStyle("x", 1)["verticalAlign"] == "bottom"
        assert chart.axisLabelStyle("y", 1)["align"] == "left"

    def test_unknown_axis_returns_empty(self, make):
        chart = _chart(make)
        assert chart.axisLabelStyle("radar") == {}
        assert chart.axisLabelStyle("x", 9) == {}

    @staticmethod
    def _red_bounds(image, y_min, y_max):
        xs, ys = [], []
        for y in range(max(0, int(y_min)), min(image.height(), int(y_max))):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.red() > 180 and color.green() < 90 and color.blue() < 90:
                    xs.append(x)
                    ys.append(y)
        return xs, ys

    def test_x_label_is_horizontally_centered_on_tick(self, make, qapp):
        chart = make(ElaChartWidget)
        chart.resize(600, 400)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {
                    "type": "category",
                    "data": ["MMMM"],
                    "axisLabel": {"color": "#ff0000", "fontSize": 16},
                },
                "yAxis": {},
                "series": [{"type": "line", "data": [1]}],
            }
        )
        chart.show()
        qapp.processEvents()
        chart._layout_all(force=True)
        coord = chart.coords[0]
        axis = coord.x_axes[0]
        tick_x = coord._axis_positions(axis, False)[0][0]
        line_y = coord._axis_line_pos(axis, False)
        xs, _ys = self._red_bounds(chart.grab().toImage(), line_y + 1, line_y + 40)
        if not xs:
            pytest.skip("当前 Qt 平台不渲染文字像素（offscreen）")
        assert abs((min(xs) + max(xs)) / 2 - tick_x) <= 3.0

    def test_y_label_is_vertically_centered_on_tick(self, make, qapp):
        chart = make(ElaChartWidget)
        chart.resize(600, 400)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A"]},
                "yAxis": {
                    "type": "value",
                    "min": 0,
                    "max": 100,
                    "splitNumber": 2,
                    "axisLabel": {
                        "color": "#ff0000",
                        "interval": lambda index, _value: index == 0,
                    },
                },
                "series": [{"type": "line", "data": [50]}],
            }
        )
        chart.show()
        qapp.processEvents()
        chart._layout_all(force=True)
        coord = chart.coords[0]
        axis = coord.y_axes[0]
        tick_y = coord._axis_positions(axis, True)[0][1]
        _xs, ys = self._red_bounds(chart.grab().toImage(), 0, chart.height())
        if not ys:
            pytest.skip("当前 Qt 平台不渲染文字像素（offscreen）")
        assert abs((min(ys) + max(ys)) / 2 - tick_y) <= 3.0


class TestAxisLabelStyleApi:
    def test_writes_only_selected_axis(self, make):
        chart = _chart(make)
        assert (
            chart.setAxisLabelStyle(
                "x",
                fontSize=13,
                bold=True,
                color="#112233",
                align="left",
                margin=9,
            )
            is True
        )
        raw = chart.getOption()["xAxis"][0]["axisLabel"]
        assert raw == {
            "fontSize": 13,
            "fontWeight": 700,
            "color": "#112233",
            "align": "left",
            "margin": 9,
        }
        assert chart.getOption()["xAxis"][1].get("axisLabel") is None
        style = chart.axisLabelStyle("x", 0)
        assert style["fontSize"] == 13
        assert style["fontWeight"] == 700
        assert style["color"] == "#112233"
        assert style["align"] == "left"
        assert style["margin"] == 9

    def test_both_axes_with_axis_index(self, make):
        chart = _chart(make)
        assert chart.setAxisLabelStyle("both", fontSize=10, axisIndex=1) is True
        assert chart.getOption()["xAxis"][1]["axisLabel"]["fontSize"] == 10
        assert chart.getOption()["yAxis"][1]["axisLabel"]["fontSize"] == 10
        assert chart.getOption()["xAxis"][0].get("axisLabel") is None

    def test_bold_false_and_font_style_reach_model(self, make):
        chart = _chart(make)
        assert (
            chart.setAxisLabelStyle(
                "x", bold=False, fontStyle="italic", fontFamily="Consolas"
            )
            is True
        )
        chart._layout_all(force=True)
        font = chart.coords[0].x_axes[0].labelFont()
        assert font.weight() == 400
        assert font.italic()
        assert font.families() == ["Consolas"]

    def test_auto_restores_default_alignment(self, make):
        chart = _chart(make)
        assert chart.setAxisLabelStyle("y", align="center") is True
        assert chart.axisLabelStyle("y", 0)["align"] == "center"
        assert chart.setAxisLabelStyle("y", align="auto", verticalAlign="auto") is True
        style = chart.axisLabelStyle("y", 0)
        assert style["align"] == "right"
        assert style["verticalAlign"] == "middle"

    def test_invalid_input_returns_false_without_writing(self, make):
        chart = _chart(make)
        assert chart.setAxisLabelStyle("radar", fontSize=12) is False
        assert chart.setAxisLabelStyle("x", fontSize=-1) is False
        assert chart.setAxisLabelStyle("x", fontSize="abc") is False
        assert chart.setAxisLabelStyle("x", fontWeight="heavy-ish") is False
        assert chart.setAxisLabelStyle("x", color="not-a-color") is False
        assert chart.setAxisLabelStyle("x", align="middle") is False
        assert chart.setAxisLabelStyle("x", verticalAlign="center") is False
        assert chart.setAxisLabelStyle("x", rotate=float("inf")) is False
        assert chart.setAxisLabelStyle("x", margin=-2) is False
        assert chart.setAxisLabelStyle("x") is False
        assert chart.setAxisLabelStyle("x", fontSize=12, axisIndex=9) is False
        assert chart.getOption()["xAxis"][0].get("axisLabel") is None

    def test_both_is_atomic_when_one_axis_is_missing(self, make):
        chart = make(ElaChartWidget)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A"]},
                "series": [{"type": "pie", "data": [1]}],
            }
        )
        assert chart.setAxisLabelStyle("both", fontSize=12) is False
        assert chart.getOption()["xAxis"].get("axisLabel") is None

    def test_bold_wins_over_font_weight(self, make):
        chart = _chart(make)
        assert chart.setAxisLabelStyle("x", fontWeight=600, bold=True) is True
        assert chart.getOption()["xAxis"][0]["axisLabel"]["fontWeight"] == 700


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
