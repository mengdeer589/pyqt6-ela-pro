"""Tests for calendar heatmap (calendar coordinate + heatmap series)."""

from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts.axes import CalendarCoord
from pyqt6_ela_pro.charts.series_cartesian import HeatmapSeriesRenderer


def _calendar_data(year: int = 2026, skip_mod: int = 0):
    """全年数据：每 ``skip_mod`` 天跳过一天（模拟无数据）。"""
    data = []
    day = date(year, 1, 1)
    index = 0
    while day <= date(year, 12, 31):
        if not (skip_mod and index % skip_mod == 0):
            data.append(
                {
                    "value": [day.isoformat(), index % 24],
                    "tooltip": {"formatter": f"{index % 24 + 500}万 tokens · 3 轮消息"},
                }
            )
        day += timedelta(days=1)
        index += 1
    return data


def _calendar_option(year: int = 2026, skip_mod: int = 0, **calendar):
    cal = {"range": year, "cellSize": "auto"}
    cal.update(calendar)
    series = {
        "type": "heatmap",
        "coordinateSystem": "calendar",
        "name": "Token",
        "data": _calendar_data(year, skip_mod),
    }
    item_style = cal.pop("seriesItemStyle", None)
    if item_style is not None:
        series["itemStyle"] = item_style
    return {
        "tooltip": {"trigger": "item"},
        "calendar": cal,
        "visualMap": {"min": 0, "max": 23},
        "series": [series],
    }


def _make_chart(option):
    chart = ElaChartWidget()
    chart.resize(900, 240)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    return chart


def _coord(**calendar) -> CalendarCoord:
    coord = CalendarCoord(option={"calendar": {"range": 2026, **calendar}})
    coord.layout(QRectF(0, 0, 900, 200))
    return coord


class TestCalendarCoord:
    def test_default_sunday_first(self):
        coord = _coord()
        # 行号 = (weekday + 1) % 7（周日 = 0）
        for day in (date(2026, 1, 1), date(2026, 6, 15), date(2026, 12, 31)):
            assert coord._row_of(day) == (day.weekday() + 1) % 7
        # 首列第一行是 start 所在周之前的周日
        first = coord._first_column_start()
        assert first.weekday() == 6 and first <= coord.start
        assert (coord.start - first).days < 7

    def test_monday_first_option(self):
        coord = _coord(dayLabel={"firstDay": 1})
        assert coord._row_of(date(2026, 1, 1)) == date(2026, 1, 1).weekday()
        assert coord._first_column_start().weekday() == 0

    def test_cell_rect_and_date_roundtrip(self):
        coord = _coord()
        day = date(2026, 5, 20)
        rect = coord.cellRect(day)
        assert not rect.isNull()
        assert coord.dateAt(rect.center()) == day
        assert coord.mapPoint(day) == rect.center()

    def test_out_of_range_dates(self):
        coord = _coord()
        assert coord.cellRect(date(2025, 12, 31)).isNull()
        assert coord.cellRect(date(2027, 1, 1)).isNull()
        assert coord.cellRect("not-a-date").isNull()

    def test_cross_year_range(self):
        coord = CalendarCoord(
            option={
                "calendar": {
                    "range": ["2025-12-15", "2026-01-15"],
                }
            }
        )
        coord.layout(QRectF(0, 0, 900, 200))
        days = list(coord.iterDates())
        assert len(days) == (date(2026, 1, 15) - date(2025, 12, 15)).days + 1
        assert not coord.cellRect(date(2025, 12, 16)).isNull()
        assert coord.cellRect(date(2025, 12, 14)).isNull()

    def test_auto_and_fixed_cell_size(self):
        auto = _coord()
        fixed = _coord(cellSize=10)
        assert auto.cellSize() > 0
        assert fixed.cellSize() == 10.0

    def test_label_options(self):
        coord = _coord(
            dayLabel={"show": False, "firstDay": "monday"},
            monthLabel={"show": False},
        )
        assert coord.show_week_labels is False
        assert coord.show_month_labels is False
        assert coord._row_of(date(2026, 1, 1)) == date(2026, 1, 1).weekday()

    def test_vertical_orient_transposes(self):
        h = _coord()
        v = _coord(orient="vertical")
        rect = h.cellRect(date(2026, 5, 20))
        rect_v = v.cellRect(date(2026, 5, 20))
        assert not rect_v.isNull()
        # 转置后单格尺寸一致、日期反查仍正确
        assert abs(rect.width() - rect_v.width()) < 1e-6
        assert v.dateAt(rect_v.center()) == date(2026, 5, 20)


class TestCalendarHeatmapRenderer:
    def test_cells_cover_whole_range(self):
        chart = _make_chart(_calendar_option())
        renderer = chart._series[0]
        assert isinstance(renderer, HeatmapSeriesRenderer)
        assert renderer._calendar is True
        assert len(renderer._cells) == 365
        chart.deleteLater()

    def test_empty_days_have_base_color(self):
        chart = _make_chart(_calendar_option(skip_mod=3))
        renderer = chart._series[0]
        empty = [cell for cell in renderer._cells if cell["empty"]]
        filled = [cell for cell in renderer._cells if not cell["empty"]]
        assert empty and filled
        assert empty[0]["tooltipFormatter"] is None
        assert empty[0]["color"].isValid()
        chart.deleteLater()

    def test_empty_color_custom_and_disabled(self):
        custom = _make_chart(
            _calendar_option(skip_mod=3, itemStyle={"color": "#123456"})
        )
        cell = next(c for c in custom._series[0]._cells if c["empty"])
        assert cell["color"].name() == "#123456"
        custom.deleteLater()

        none = _make_chart(_calendar_option(skip_mod=3, itemStyle={"color": "none"}))
        cell = next(c for c in none._series[0]._cells if c["empty"])
        assert cell["color"] is None
        none.deleteLater()

    def test_gap_and_radius_options(self):
        chart = _make_chart(
            _calendar_option(seriesItemStyle={"borderWidth": 2, "borderRadius": 4})
        )
        renderer = chart._series[0]
        assert renderer._cell_gap == 2.0
        assert renderer._cell_radius == 4.0
        chart.deleteLater()

    def test_hit_test_returns_title_and_tooltip_formatter(self):
        chart = _make_chart(_calendar_option(skip_mod=3))
        renderer = chart._series[0]
        filled = next(cell for cell in renderer._cells if not cell["empty"])
        hit = renderer.hitTest(filled["rect"].center())
        assert hit["title"] == filled["label"]
        assert hit["tooltipFormatter"] == filled["tooltipFormatter"]
        assert hit["value"] is not None

        empty = next(cell for cell in renderer._cells if cell["empty"])
        hit_empty = renderer.hitTest(empty["rect"].center())
        assert hit_empty["value"] is None
        assert hit_empty["tooltipFormatter"] is None
        chart.deleteLater()

    def test_visual_map_colors_endpoints(self):
        option = _calendar_option()
        option["visualMap"] = {
            "min": 0,
            "max": 23,
            "inRange": {"colors": ["#000000", "#ffffff"]},
        }
        chart = _make_chart(option)
        renderer = chart._series[0]
        by_value = {
            cell["value"]: cell for cell in renderer._cells if not cell["empty"]
        }
        assert by_value[0.0]["color"].name() == "#000000"
        assert by_value[23.0]["color"].name() == "#ffffff"
        chart.deleteLater()

    def test_render_non_empty(self):
        chart = _make_chart(_calendar_option(skip_mod=3))
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()

    def test_grid_avoids_vertical_visual_map(self):
        chart = _make_chart(_calendar_option())
        coord = chart._coords[0]
        bar = next(
            comp
            for comp in chart.components
            if getattr(comp, "optionKey", "") == "visualMap"
        )._bar
        grid_right = coord._origin.x() + coord.weeks() * coord.cellSize()
        assert grid_right <= bar.left()
        chart.deleteLater()


class TestTooltipLines:
    @staticmethod
    def _chart(opt=None):
        chart = ElaChartWidget()
        chart.setOption(opt or {"tooltip": {"trigger": "item"}})
        return chart

    def test_default_title_formats_iso_date(self):
        chart = self._chart()
        lines = chart.tooltip.buildLines(
            {"name": "2026-09-02", "title": "2026-09-02", "value": 557},
            QColor("#2563eb"),
            "Token",
        )
        assert lines[0] == (None, "", "2026年9月2日")
        assert lines[1][0].name() == "#2563eb"
        assert "557" in lines[1][2]
        chart.deleteLater()

    def test_data_tooltip_formatter_used(self):
        chart = self._chart()
        lines = chart.tooltip.buildLines(
            {
                "name": "2026-09-02",
                "title": "2026-09-02",
                "value": 557,
                "tooltipFormatter": "557万 tokens · 4轮消息",
            },
            QColor("#2563eb"),
            "Token",
        )
        assert lines[1][2] == "557万 tokens · 4轮消息"
        chart.deleteLater()

    def test_formatter_callable_returns_pair(self):
        chart = self._chart(
            {"tooltip": {"trigger": "item", "formatter": lambda p: ["标题", "内容"]}}
        )
        lines = chart.tooltip.buildLines(
            {"name": "a", "value": 1}, QColor("#000000"), "S"
        )
        assert lines[0] == (None, "", "标题")
        assert lines[1][2] == "内容"
        chart.deleteLater()

    def test_formatter_template(self):
        chart = self._chart({"tooltip": {"trigger": "item", "formatter": "{b}={c}"}})
        lines = chart.tooltip.buildLines(
            {"name": "一月", "value": 12}, QColor("#000000"), "S"
        )
        assert lines[0][2] == "一月=12"
        chart.deleteLater()

    def test_formatter_exception_falls_back_to_default(self):
        def broken(_params):
            raise RuntimeError("boom")

        chart = self._chart({"tooltip": {"trigger": "item", "formatter": broken}})
        lines = chart.tooltip.buildLines(
            {"name": "a", "value": 3}, QColor("#000000"), "S"
        )
        assert lines[0][1:] == ("a", "3")
        chart.deleteLater()

    def test_value_formatter(self):
        chart = self._chart(
            {
                "tooltip": {
                    "trigger": "item",
                    "valueFormatter": lambda v: f"{v} 件",
                }
            }
        )
        lines = chart.tooltip.buildLines(
            {"name": "x", "value": 5}, QColor("#000000"), "S"
        )
        assert lines[0][2] == "5 件"
        chart.deleteLater()

    def test_value_formatter_template(self):
        chart = self._chart(
            {"tooltip": {"trigger": "item", "valueFormatter": "{value} 万"}}
        )
        lines = chart.tooltip.buildLines(
            {"name": "x", "value": 7}, QColor("#000000"), "S"
        )
        assert lines[0][2] == "7 万"
        chart.deleteLater()

    def test_without_title_keeps_plain_line(self):
        chart = self._chart()
        lines = chart.tooltip.buildLines(
            {"name": "一月", "value": 5}, QColor("#000000"), "S"
        )
        assert len(lines) == 1
        assert lines[0][1:] == ("一月", "5")
        chart.deleteLater()
