"""文字外观接口：图例 / 标题 / 提示框 / 轴标签 / 数据点标签。

回归两类问题：

1. ``*textStyle.fontWeight``（以及 ``series.label.fontWeight``）被接受，却
   从来没传给 ``chartFont`` —— 设了不生效、也不报错；
2. 顶层 ``textStyle`` 虽然有 ``ElaChartWidget.textStyle()`` 读取入口，却没有
   任何组件消费它 —— 用户按 ECharts 习惯写 ``{"textStyle": {"fontSize": 14}}``
   全图文字毫无变化。
"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts._tokens import T
from pyqt6_ela_pro.charts._utils import merged_text_style, text_weight


def _chart(make) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(640, 420)
    chart.setOption(
        {
            "animation": False,
            "legend": {"top": "top"},
            "title": {"text": "季度销量", "subtext": "单位：件"},
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "category", "data": ["A", "B"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "alpha",
                    "data": [1, 2],
                    "label": {"show": True},
                },
                {"type": "bar", "name": "beta", "data": [2, 1]},
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestFontWeightApplies:
    """每个 ``textStyle`` 都得真的把 fontWeight 交给 ``chartFont``。"""

    def test_legend_weight(self, make):
        chart = _chart(make)
        assert chart.legend._font().weight() == 400
        chart.setOption({"legend": {"textStyle": {"fontWeight": 700}}})
        assert chart.legend._font().weight() == 700

    def test_legend_weight_keyword(self, make):
        chart = _chart(make)
        chart.setOption({"legend": {"textStyle": {"fontWeight": "bold"}}})
        assert chart.legend._font().weight() == 700

    def test_series_label_weight(self, make):
        chart = _chart(make)
        chart.updateSeries({"label": {"fontWeight": 700}}, seriesIndex=0)
        renderer = chart.seriesRenderers[0]
        assert renderer.labelFontWeight() == 700
        assert renderer.labelFont().weight() == 700

    def test_tooltip_weight(self, make):
        chart = _chart(make)
        chart.setOption({"tooltip": {"textStyle": {"fontWeight": 700}}})
        assert chart.tooltip._font().weight() == 700
        assert chart.tooltip._font(1.0).weight() == 700

    def test_title_weight(self, make):
        chart = _chart(make)
        assert chart.title.titleFont().weight() == T("font.weight.semibold")
        chart.setOption({"title": {"textStyle": {"fontWeight": 700}}})
        assert chart.title.titleFont().weight() == 700

    def test_axis_label_weight(self, make):
        chart = _chart(make)
        chart.updateAxis("x", {"axisLabel": {"fontWeight": 700}})
        assert chart.coords[0].x_axes[0].labelFont().weight() == 700


class TestGlobalTextStyleFallback:
    """顶层 ``textStyle`` 是组件级未设置时的文字外观默认值。"""

    def test_legend_axis_and_series_label(self, make):
        chart = _chart(make)
        chart.setOption(
            {"textStyle": {"fontSize": 16, "fontWeight": 600, "color": "#123456"}}
        )

        legend = chart.legend
        assert legend._font().pixelSize() == 16
        assert legend._font().weight() == 600
        assert legend.textStyle()["color"] == "#123456"

        axis = chart.coords[0].x_axes[0]
        assert axis.labelFont().pixelSize() == 16
        assert axis.labelFont().weight() == 600
        assert axis.labelColor().name() == "#123456"

        renderer = chart.seriesRenderers[0]
        assert renderer.labelFontSize() == 16.0
        assert renderer.labelFontWeight() == 600
        assert renderer.labelColor().name() == "#123456"

    def test_title_and_tooltip(self, make):
        chart = _chart(make)
        chart.setOption({"textStyle": {"fontSize": 16, "fontWeight": 600}})
        assert chart.title.titleFont().pixelSize() == 16
        assert chart.title.titleFont().weight() == 600
        assert chart.title.subtitleFont().pixelSize() == 16
        assert chart.tooltip._font().pixelSize() == 16
        assert chart.tooltip._font().weight() == 600

    def test_title_band_height_follows_global_size(self, make):
        chart = _chart(make)
        chart.setOption({"textStyle": {"fontSize": 12}})
        small = chart.title.height()
        chart.setOption({"textStyle": {"fontSize": 28}})
        assert chart.title.height() > small

    def test_component_style_overrides_global(self, make):
        chart = _chart(make)
        chart.setOption(
            {"textStyle": {"fontSize": 16, "fontWeight": 600, "color": "#123456"}}
        )
        chart.setOption(
            {"legend": {"textStyle": {"fontSize": 10, "color": "#abcdef"}}}
        )
        legend = chart.legend
        assert legend._font().pixelSize() == 10
        # 只覆盖了字号 / 颜色，字重仍走全局
        assert legend._font().weight() == 600
        assert legend.textStyle()["color"] == "#abcdef"

    def test_global_style_never_enables_labels(self, make):
        """``textStyle`` 只合外观键：不能顺手把 ``show`` 漏给 label。"""
        chart = _chart(make)
        assert chart.seriesRenderers[1].labelShown() is False
        chart.setOption({"textStyle": {"show": True, "fontSize": 16}})
        assert chart.seriesRenderers[1].labelShown() is False


class TestTextWeightParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (400, 400),
            ("700", 700),
            (650, 650),
            ("bold", 700),
            ("Bold", 700),
            ("normal", 400),
            ("bolder", 700),
            ("lighter", 300),
            (None, None),
            ("heavy-ish", None),
            (float("inf"), None),
            (True, None),
        ],
        ids=[
            "int",
            "numeric-string",
            "arbitrary-int",
            "bold",
            "case-insensitive",
            "normal",
            "bolder",
            "lighter",
            "none",
            "garbage-string",
            "inf",
            "bool",
        ],
    )
    def test_text_weight(self, value, expected):
        assert text_weight(value) == expected

    def test_text_weight_default(self):
        assert text_weight("garbage", 400) == 400


class TestHierarchySeriesLabelFont:
    """饼图 / 树图 / 桑基等共用 ``_label_font``（标签样式来源各不相同）。"""

    def test_component_style(self, make):
        from pyqt6_ela_pro.charts.series_hierarchy._shared import _label_font

        chart = _chart(make)
        renderer = chart.seriesRenderers[0]
        font = _label_font(renderer, {"fontSize": 18, "fontWeight": "bold"})
        assert font.pixelSize() == 18
        assert font.weight() == 700

    def test_global_fallback(self, make):
        from pyqt6_ela_pro.charts.series_hierarchy._shared import _label_font

        chart = _chart(make)
        chart.setOption({"textStyle": {"fontSize": 15, "fontWeight": 600}})
        font = _label_font(chart.seriesRenderers[0], {})
        assert font.pixelSize() == 15
        assert font.weight() == 600


class TestFontFamily:
    """字体族：全图单族 API + 组件级覆盖（Win7 只允许单族）。"""

    def test_set_font_family_applies_everywhere(self, make):
        chart = _chart(make)
        chart.setFontFamily("Consolas")
        chart._layout_all(force=True)
        assert chart.fontFamily() == "Consolas"
        assert chart.legend._font().families() == ["Consolas"]
        assert chart.coords[0].x_axes[0].labelFont().families() == ["Consolas"]
        assert chart.coords[0].y_axes[0].nameFont().families() == ["Consolas"]
        assert chart.seriesRenderers[0].labelFont().families() == ["Consolas"]
        assert chart.title.titleFont().families() == ["Consolas"]
        assert chart.tooltip._font().families() == ["Consolas"]

    def test_multi_family_collapses_to_first(self, make):
        chart = _chart(make)
        chart.setFontFamily("Consolas, Arial, sans-serif")
        assert chart.fontFamily() == "Consolas"
        assert chart.legend._font().families() == ["Consolas"]

    def test_component_override(self, make):
        chart = _chart(make)
        chart.setFontFamily("Consolas")
        chart.setOption({"legend": {"textStyle": {"fontFamily": "Arial"}}})
        chart._layout_all(force=True)
        assert chart.legend._font().families() == ["Arial"]
        # 没覆盖的组件仍走全图字体
        assert chart.coords[0].x_axes[0].labelFont().families() == ["Consolas"]

    def test_global_text_style_font_family(self, make):
        chart = _chart(make)
        chart.setOption({"textStyle": {"fontFamily": "Courier New"}})
        chart._layout_all(force=True)
        assert chart.legend._font().families() == ["Courier New"]
        assert chart.seriesRenderers[0].labelFont().families() == ["Courier New"]

    def test_empty_component_family_falls_back(self, make):
        """``fontFamily: ""`` 视为未设置（继续用图表级字体，而不是回到默认）。"""
        chart = _chart(make)
        chart.setFontFamily("Consolas")
        chart.setOption({"legend": {"textStyle": {"fontFamily": ""}}})
        chart._layout_all(force=True)
        assert chart.legend._font().families() == ["Consolas"]

    def test_restore_default(self, make):
        chart = _chart(make)
        default = chart.legend._font().families()
        chart.setFontFamily("Consolas")
        chart.setFontFamily(None)
        chart._layout_all(force=True)
        assert chart.fontFamily() == ""
        assert chart.legend._font().families() == default

    def test_map_timeline_calendar(self, make):
        chart = make(ElaChartWidget)
        chart.resize(520, 380)
        chart.setOption(
            {
                "animation": False,
                "calendar": {"range": "2026"},
                "timeline": {"data": ["2024", "2025"]},
                "series": [{"type": "map", "name": "m", "label": {}, "data": []}],
            }
        )
        chart.setFontFamily("Consolas")
        chart._layout_all(force=True)
        map_renderer = next(
            r for r in chart.seriesRenderers if type(r).__name__ == "MapSeriesRenderer"
        )
        assert map_renderer.labelStyle()["fontFamily"] == "Consolas"
        assert (
            chart._component("timeline").labelStyle()["fontFamily"] == "Consolas"
        )
        calendar = next(c for c in chart.coords if type(c).__name__ == "CalendarCoord")
        assert calendar._label_style("day")["fontFamily"] == "Consolas"


class TestFontStyle:
    def test_legend_italic(self, make):
        chart = _chart(make)
        assert not chart.legend._font().italic()
        chart.setOption({"legend": {"textStyle": {"fontStyle": "italic"}}})
        assert chart.legend._font().italic()

    def test_global_oblique(self, make):
        chart = _chart(make)
        chart.setOption({"textStyle": {"fontStyle": "oblique"}})
        chart._layout_all(force=True)
        assert chart.title.titleFont().italic()
        assert chart.coords[0].x_axes[0].labelFont().italic()

    def test_normal_is_not_italic(self, make):
        chart = _chart(make)
        chart.setOption({"textStyle": {"fontStyle": "normal"}})
        assert not chart.title.titleFont().italic()


class TestTextItalic:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("italic", True),
            ("Oblique", True),
            (" normal ", False),
            ("", False),
            (None, False),
            (1, False),
        ],
        ids=["italic", "oblique-case", "normal", "empty", "none", "int"],
    )
    def test_text_italic(self, value, expected):
        from pyqt6_ela_pro.charts._utils import text_italic

        assert text_italic(value) is expected


class TestMergedTextStyle:
    def test_only_appearance_keys_survive(self):
        class _Chart:
            def textStyle(self):
                return {"fontSize": 14, "show": True, "formatter": "x", "color": "#111"}

        merged = merged_text_style(_Chart(), {"fontWeight": 700, "show": False})
        assert merged == {"fontSize": 14, "fontWeight": 700, "color": "#111"}

    def test_no_chart_is_safe(self):
        assert merged_text_style(None, {"fontSize": 12}) == {"fontSize": 12}
        assert merged_text_style(None, "garbage") == {}


class TestInvalidValuesAreIgnored:
    def test_invalid_legend_weight_keeps_default(self, make):
        chart = _chart(make)
        chart.setOption({"legend": {"textStyle": {"fontWeight": "heavy-ish"}}})
        assert chart.legend._font().weight() == 400

    def test_invalid_global_font_size_keeps_default(self, make):
        chart = _chart(make)
        chart.setOption({"textStyle": {"fontSize": "abc"}})
        assert chart.legend._font().pixelSize() == T("font.xs")
        assert chart.coords[0].x_axes[0].labelFont().pixelSize() == T("font.xs")
