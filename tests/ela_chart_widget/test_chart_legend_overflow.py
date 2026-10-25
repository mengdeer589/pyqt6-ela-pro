"""图例换行 / 分页：多系列不再溢出绘图区、分页按钮可用。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, count=12, **legend):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "legend": {"top": "top", **legend},
        "xAxis": {"type": "category", "data": ["a", "b"]},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "line",
                "name": f"series-with-long-name-{i}",
                "data": [i, i + 1],
            }
            for i in range(count)
        ],
    }
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestLegendOverflow:
    def test_entries_stay_inside_chart(self, qapp, make):
        chart = _chart(make)
        legend = chart.legend
        assert legend._paginate is True
        assert legend._page_count > 1
        for rect in legend._item_rects:
            assert rect.left() >= 0
            assert rect.right() <= chart.width()

    def test_page_navigation(self, qapp, make):
        chart = _chart(make)
        legend = chart.legend
        first = [name for name, _ in legend._page_items]
        next_rect = legend._page_rects[1]
        chart.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                next_rect.center(),
                QPointF(chart.mapToGlobal(next_rect.center().toPoint())),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert legend._page == 1
        assert [name for name, _ in legend._page_items] != first

    def test_scroll_type_uses_single_row(self, qapp, make):
        chart = _chart(make, count=6, type="scroll")
        legend = chart.legend
        assert legend._paginate is True
        assert legend._page_count >= 2
        tops = {round(rect.top(), 3) for rect in legend._item_rects}
        assert len(tops) == 1
