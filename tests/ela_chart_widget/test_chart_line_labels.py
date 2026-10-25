"""折线 / 散点数据标签：``label.position`` 落点、逐项颜色、重叠隐藏。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, series, *, width=420):
    chart = make(ElaChartWidget)
    chart.resize(width, 320)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": [str(i) for i in range(len(series[0]["data"]))]},
            "yAxis": {"type": "value"},
            "series": series,
        }
    )
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    chart.grab()
    return chart


class TestLineLabelPosition:
    def _rect_for(self, make, position):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [10, 20, 30],
                    "label": {"show": True, "position": position},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        point = renderer._points[1]
        index, rect, _text = next(r for r in renderer._label_rects if r[0] == 1)
        assert index == 1
        return point, rect

    def test_top_is_above_point(self, qapp, make):
        point, rect = self._rect_for(make, "top")
        assert rect.center().y() < point.y()

    def test_bottom_is_below_point(self, qapp, make):
        point, rect = self._rect_for(make, "bottom")
        assert rect.center().y() > point.y()

    def test_left_is_left_of_point(self, qapp, make):
        point, rect = self._rect_for(make, "left")
        assert rect.center().x() < point.x()

    def test_right_is_right_of_point(self, qapp, make):
        point, rect = self._rect_for(make, "right")
        assert rect.center().x() > point.x()

    def test_inside_crosses_point(self, qapp, make):
        point, rect = self._rect_for(make, "inside")
        assert rect.contains(QPointF(point.x(), point.y()))


class TestLineLabelStyle:
    def test_per_item_label_color(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [
                        {"value": 10, "label": {"color": "#ff0000"}},
                        20,
                    ],
                    "label": {"show": True},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.labelColorFor(0).name() == "#ff0000"
        assert renderer.labelColorFor(1).name() != "#ff0000"

    def test_hide_overlap_reduces_labels(self, qapp, make):
        data = [10 + (i % 2) for i in range(16)]
        series = [
            {
                "type": "line",
                "name": "A",
                "data": data,
                "label": {"show": True, "formatter": "value: {c} units"},
            }
        ]
        plain = _chart(make, series, width=360)
        hidden = _chart(
            make,
            [{**series[0], "labelLayout": {"hideOverlap": True}}],
            width=360,
        )
        assert len(plain.seriesRenderers[0]._label_rects) == len(data)
        assert len(hidden.seriesRenderers[0]._label_rects) < len(data)
