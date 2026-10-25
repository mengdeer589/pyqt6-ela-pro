"""markLine 任意坐标 / markPoint 符号 / markArea coord / toolbox magicType。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, series, **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {"type": "value"},
        "series": series,
    }
    option.update(patch)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    chart.grab()
    return chart


class TestMarkLines:
    def test_coord_pair_makes_arbitrary_line(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 5, 9],
                    "markLine": {
                        "data": [
                            {"coord": [[0, 1], [2, 9]], "name": "斜线"},
                        ]
                    },
                }
            ],
        )
        comp = next(c for c in chart.components if c.optionKey == "markLine")
        line = comp._lines[0]
        assert line["orient"] == "arbitrary"
        assert line["p1"] is not None and line["p2"] is not None
        assert line["text"] == "斜线"

    def test_line_style_per_item(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 5, 9],
                    "markLine": {
                        "data": [
                            {
                                "type": "average",
                                "lineStyle": {"color": "#ff0000", "type": "solid"},
                            }
                        ]
                    },
                }
            ],
        )
        comp = next(c for c in chart.components if c.optionKey == "markLine")
        line = comp._lines[0]
        pen = comp._line_pen(line, comp._color())
        assert pen.color().name() == "#ff0000"


class TestMarkPoints:
    def test_symbol_and_size(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 9, 3],
                    "markPoint": {
                        "symbol": "triangle",
                        "symbolSize": 16,
                        "data": [{"type": "max"}],
                    },
                }
            ],
        )
        comp = next(c for c in chart.components if c.optionKey == "markPoint")
        mark = comp._marks[0]
        assert mark["symbol"] == "triangle"
        assert mark["symbolSize"] == 16


class TestMarkArea:
    def test_coord_pair(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 5, 9],
                    "markArea": {
                        "data": [[{"coord": [0, 1]}, {"coord": [2, 5]}]]
                    },
                }
            ],
        )
        comp = next(c for c in chart.components if c.optionKey == "markArea")
        assert comp._areas
        assert comp._areas[0].width() > 0
        assert comp._areas[0].height() > 0


class TestMagicType:
    def test_cycles_line_bar_stack(self, qapp, make):
        chart = _chart(
            make,
            [{"type": "line", "name": "A", "data": [1, 5, 9]}],
            toolbox={"feature": ["magicType"]},
        )
        assert chart.toggleMagicType() is True
        assert chart.getOption()["series"][0]["type"] == "bar"
        assert chart.toggleMagicType() is True
        assert chart.getOption()["series"][0].get("stack") == "magic"
        assert chart.toggleMagicType() is True
        assert chart.getOption()["series"][0]["type"] == "line"
        assert "stack" not in chart.getOption()["series"][0]
