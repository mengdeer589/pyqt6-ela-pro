"""Tests for component band layout (dataZoom / timeline / visualMap stacking)."""

from __future__ import annotations

from PyQt6.QtGui import QColor

from pyqt6_ela_pro.charts import ElaChartWidget


def _make_chart(option):
    chart = ElaChartWidget()
    chart.resize(800, 400)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    return chart


def _component(chart, key: str):
    return next(c for c in chart.components if getattr(c, "optionKey", "") == key)


def _interact_option():
    return {
        "xAxis": {"type": "category", "data": [f"{i}月" for i in range(1, 13)]},
        "yAxis": {},
        "toolbox": {},
        "dataZoom": [{"type": "slider", "start": 20, "end": 80}],
        "timeline": {"data": ["2024", "2025", "2026"]},
        "options": [
            {"series": [{"type": "bar", "name": "2024", "data": [1] * 12}]},
            {"series": [{"type": "bar", "name": "2025", "data": [2] * 12}]},
            {"series": [{"type": "bar", "name": "2026", "data": [3] * 12}]},
        ],
        "series": [{"type": "bar", "name": "2024", "data": [1] * 12}],
    }


def _bar_option(**extra):
    option = {
        "xAxis": {"type": "category", "data": ["一", "二", "三"]},
        "yAxis": {},
        "series": [{"type": "bar", "name": "S", "data": [1, 2, 3]}],
    }
    option.update(extra)
    return option


class TestComponentBands:
    def test_data_zoom_above_timeline(self):
        chart = _make_chart(_interact_option())
        dz = _component(chart, "dataZoom")
        tl = _component(chart, "timeline")

        assert not dz._track.isNull()
        assert not tl._band.isNull()
        # 滑块在时间轴条带上方；把手 / 百分比区域不压住时间轴
        assert dz._track.bottom() < tl._band.top()
        assert dz._h_start.bottom() <= tl._band.top()
        # 播放按钮在时间轴条带内，条带不越出画布
        assert tl._play_rect.top() >= tl._band.top()
        assert tl._play_rect.bottom() <= tl._band.bottom()
        assert tl._band.bottom() <= chart.height()
        chart.deleteLater()

    def test_grid_above_all_bottom_bands(self):
        chart = _make_chart(_interact_option())
        dz = _component(chart, "dataZoom")
        tl = _component(chart, "timeline")
        coord = chart._coords[0]

        assert coord.plot.bottom() <= dz._track.top()
        assert coord.plot.bottom() <= tl._band.top()
        chart.deleteLater()

    def test_timeline_alone_sits_at_bottom(self):
        option = _bar_option(timeline={"data": ["A", "B"]})
        chart = _make_chart(option)
        tl = _component(chart, "timeline")
        assert tl._band.bottom() <= chart.height()
        assert tl._band.bottom() > chart.height() - tl.BAND_H - 10
        chart.deleteLater()

    def test_data_zoom_alone_sits_at_bottom(self):
        option = _bar_option(dataZoom=[{"type": "slider"}])
        chart = _make_chart(option)
        dz = _component(chart, "dataZoom")
        content_bottom = chart._content_rect().bottom()
        assert dz._track.bottom() < content_bottom
        assert dz._track.bottom() > content_bottom - dz.SLIDER_H - 30
        chart.deleteLater()

    def test_visual_map_and_data_zoom_do_not_overlap(self):
        option = _bar_option(
            dataZoom=[{"type": "slider"}],
            visualMap={
                "min": 0,
                "max": 10,
                "inRange": {"colors": ["#000000", "#ffffff"]},
            },
        )
        chart = _make_chart(option)
        dz = _component(chart, "dataZoom")
        vm = _component(chart, "visualMap")
        # 色带（竖直）在滑块条带上方
        assert vm._bar.bottom() <= dz._track.top() + 1
        chart.deleteLater()

    def test_horizontal_visual_map_above_data_zoom(self):
        option = _bar_option(
            dataZoom=[{"type": "slider"}],
            visualMap={"min": 0, "max": 10, "orient": "horizontal"},
        )
        chart = _make_chart(option)
        dz = _component(chart, "dataZoom")
        vm = _component(chart, "visualMap")
        assert not vm._bar.isNull()
        assert vm._bar.bottom() <= dz._track.top() + 1
        chart.deleteLater()

    def test_visual_map_color_unchanged(self):
        chart = _make_chart(_bar_option(visualMap={"min": 0, "max": 10}))
        vm = _component(chart, "visualMap")
        assert vm.mapColor(0) != vm.mapColor(10)
        assert QColor(vm.mapColor(0)).isValid()
        chart.deleteLater()
