"""多轴（双 Y / 顶部 X / 双 X）的几何与路由契约。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF

from pyqt6_ela_pro.charts import ElaChartWidget, GridCoord


def _chart(make, **overrides):
    chart = make(ElaChartWidget)
    chart.resize(640, 400)
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "a", "data": [1, 2, 3]}],
    }
    option.update(overrides)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    return chart


class TestMultiAxisLayout:
    def test_axis_arrays_create_positions(self, qapp, make):
        chart = _chart(
            make,
            xAxis=[
                {"type": "category", "data": ["a", "b", "c"]},
                {"type": "category", "data": ["a", "b", "c"]},
            ],
            yAxis=[{"type": "value"}, {"type": "value"}],
            series=[
                {"type": "line", "name": "a", "data": [1, 2, 3]},
                {
                    "type": "line",
                    "name": "b",
                    "yAxisIndex": 1,
                    "data": [100, 200, 300],
                },
            ],
        )
        coord = chart.primaryCoord()
        assert isinstance(coord, GridCoord)
        assert [axis.position for axis in coord.x_axes] == ["bottom", "top"]
        assert [axis.position for axis in coord.y_axes] == ["left", "right"]

    def test_secondary_y_range_is_independent(self, qapp, make):
        chart = _chart(
            make,
            yAxis=[{"type": "value"}, {"type": "value"}],
            series=[
                {"type": "line", "name": "a", "data": [1, 2, 3]},
                {
                    "type": "line",
                    "name": "b",
                    "yAxisIndex": 1,
                    "data": [100, 200, 300],
                },
            ],
        )
        coord = chart.primaryCoord()
        assert coord.y_axes[0].vmax == pytest.approx(3.0)
        assert coord.y_axes[1].vmax == pytest.approx(300.0)
        # 同一像素：主轴 2 与副轴 200 都落在绘图区 1/3 高度
        primary = chart.coordFor({"yAxisIndex": 0})
        secondary = chart.coordFor({"yAxisIndex": 1})
        assert primary.mapPoint(1, 2).y() == pytest.approx(
            secondary.mapPoint(1, 200).y()
        )

    def test_top_x_axis_routes_series(self, qapp, make):
        chart = _chart(
            make,
            xAxis=[
                {"type": "category", "data": ["a", "b", "c"]},
                {"type": "category", "data": ["x", "y", "z"]},
            ],
            series=[
                {"type": "line", "name": "bottom", "data": [1, 2, 3]},
                {
                    "type": "line",
                    "name": "top",
                    "xAxisIndex": 1,
                    "data": [4, 5, 6],
                },
            ],
        )
        coord = chart.primaryCoord()
        assert coord.x_axes[0].categories == ["a", "b", "c"]
        assert coord.x_axes[1].categories == ["x", "y", "z"]
        top = chart.coordFor({"xAxisIndex": 1})
        assert top.x_axis.categories == ["x", "y", "z"]
        assert top.mapPoint("y", 5).x() == pytest.approx(coord.mapPoint("b", 2).x())

    def test_top_and_right_margins_are_reserved(self, qapp, make):
        chart = _chart(
            make,
            xAxis=[
                {"type": "category", "data": ["a", "b", "c"]},
                {"type": "category", "data": ["a", "b", "c"]},
            ],
            yAxis=[{"type": "value"}, {"type": "value"}],
            series=[
                {"type": "line", "name": "a", "data": [1, 2, 3]},
                {
                    "type": "line",
                    "name": "b",
                    "yAxisIndex": 1,
                    "data": [100, 200, 300],
                },
            ],
        )
        coord = chart.primaryCoord()
        assert coord.m_right > 24.0
        assert coord.m_top >= 40.0

    def test_convert_to_pixel_honours_axis_index(self, qapp, make):
        chart = _chart(
            make,
            yAxis=[{"type": "value"}, {"type": "value"}],
            series=[
                {"type": "line", "name": "a", "data": [1, 2, 3]},
                {
                    "type": "line",
                    "name": "b",
                    "yAxisIndex": 1,
                    "data": [100, 200, 300],
                },
            ],
        )
        coord = chart.primaryCoord()
        point = chart.convertToPixel({"yAxisIndex": 1}, [1, 200])
        assert point is not None
        assert coord.plot.left() <= point[0] <= coord.plot.right()
        assert coord.plot.top() <= point[1] <= coord.plot.bottom()
        assert chart.convertFromPixel({"yAxisIndex": 1}, point) == pytest.approx(
            [1.0, 200.0], rel=1e-6
        )

    def test_datazoom_can_target_multiple_x_axes(self, qapp, make):
        chart = _chart(
            make,
            xAxis=[
                {"type": "category", "data": [str(i) for i in range(10)]},
                {
                    "type": "category",
                    "data": [f"t{i}" for i in range(10)],
                    "position": "top",
                },
            ],
            series=[
                {"type": "line", "name": "a", "data": list(range(10))},
                {
                    "type": "line",
                    "name": "b",
                    "xAxisIndex": 1,
                    "data": [i * 10 for i in range(10)],
                },
            ],
            dataZoom=[{"type": "inside", "xAxisIndex": [0, 1], "start": 20, "end": 80}],
        )
        coord = chart.primaryCoord()
        assert coord.x_axes[0].categories == ["2", "3", "4", "5", "6", "7"]
        assert coord.x_axes[1].categories == ["t2", "t3", "t4", "t5", "t6", "t7"]
        chart.dispatchAction({"type": "dataZoom", "start": 40, "end": 60})
        assert coord.x_axes[0].categories == ["4", "5"]
        assert coord.x_axes[1].categories == ["t4", "t5"]

    def test_axis_view_is_a_gridcoord(self, qapp, make):
        chart = _chart(make)
        view = chart.coordFor({"yAxisIndex": 0})
        assert isinstance(view, GridCoord)
        assert view.plot is chart.primaryCoord().plot
        assert isinstance(view.mapPoint(1, 2), QPointF)
