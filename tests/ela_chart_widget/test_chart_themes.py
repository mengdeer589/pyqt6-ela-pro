"""图表配色主题：内置主题 / 实例切换 / 注册表 / 缓存失效 / 色带。

主题只提供**默认色**：option 里显式写的颜色始终优先。每个图表实例可以
独立切主题；``setDefaultChartTheme`` 只影响之后新建的图表（与 markdown
主题的语义一致）。
"""

from __future__ import annotations

import base64

import pytest
from PyQt6.QtGui import QImage
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro._colors import _contrast_ratio
from pyqt6_ela_pro.charts import (
    ECHARTS_PALETTE,
    ElaChartWidget,
    chartThemeSpec,
    chartThemes,
    chartToken,
    defaultChartTheme,
    defaultPalette,
    registerChartTheme,
    setDefaultChartTheme,
    unregisterChartTheme,
)
from pyqt6_ela_pro.charts._utils import parse_color
from pyqt6_ela_pro.charts.interact.visualmap import VisualMapComponent

BUILTINS = ("ela", "echarts", "matlab", "plotly", "ggplot2", "seaborn", "tableau")
PALETTES = {
    "ela": (ECHARTS_PALETTE, 9),
    "echarts": (ECHARTS_PALETTE, 9),
    "matlab": (["#0072bd", "#d95319", "#edb120", "#7e2f8e", "#77ac30"], 7),
    "plotly": (["#636efa", "#ef553b", "#00cc96", "#ab63fa", "#ffa15a"], 10),
    "ggplot2": (["#f8766d", "#d89000", "#a3a500", "#39b600", "#00ba38"], 10),
    "seaborn": (["#4c72b0", "#dd8452", "#55a868", "#c44e52", "#8172b3"], 10),
    "tableau": (["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f"], 10),
}

_BASE_OPTION = {
    "animation": False,
    "legend": {},
    "tooltip": {"trigger": "axis"},
    "xAxis": {"type": "category", "data": ["A", "B", "C"]},
    "yAxis": {"type": "value"},
    "series": [
        {"type": "bar", "name": "一", "data": [3, 5, 2]},
        {"type": "bar", "name": "二", "data": [2, 4, 6]},
        {"type": "line", "name": "三", "data": [1, 3, 5]},
    ],
}


@pytest.fixture(autouse=True)
def _restore_theme_state():
    previous = defaultChartTheme()
    yield
    setDefaultChartTheme(previous)
    for name in ("test-custom", "test-partial", "test-ramp"):
        unregisterChartTheme(name)


def _chart(make, theme=None):
    chart = make(ElaChartWidget)
    chart.resize(260, 180)
    if theme is not None:
        assert chart.setChartTheme(theme)
    return chart


def _variant() -> str:
    return "dark" if eTheme.getThemeMode() == ElaThemeType.ThemeMode.Dark else "light"


def _render(chart) -> QImage:
    image = QImage(
        max(1, chart.width()),
        max(1, chart.height()),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(0)
    chart.render(image)
    return image


def _data_image(url: str) -> QImage:
    assert url.startswith("data:image/png;base64,")
    image = QImage()
    assert image.loadFromData(base64.b64decode(url.split(",", 1)[1]), b"PNG")
    return image


class TestBuiltins:
    def test_names_and_default(self):
        assert chartThemes()[: len(BUILTINS)] == list(BUILTINS)
        assert defaultChartTheme() == "ela"

    @pytest.mark.parametrize("name", BUILTINS, ids=list(BUILTINS))
    def test_palette(self, name):
        first, count = PALETTES[name]
        palette = chartThemeSpec(name)["palette"]
        assert len(palette) == count
        assert palette[: len(first)] == first

    @pytest.mark.parametrize("name", BUILTINS, ids=list(BUILTINS))
    def test_all_colors_are_valid(self, name):
        spec = chartThemeSpec(name)
        assert all(parse_color(c).isValid() for c in spec["palette"])
        for variant in ("light", "dark"):
            for key, value in spec[variant].items():
                colors = value if key == "color.ramp" else [value]
                assert all(parse_color(c).isValid() for c in colors), (name, key)

    def test_default_theme_keeps_echarts_palette(self, make):
        chart = _chart(make)
        assert chart.chartTheme() == "ela"
        assert [color.name() for color in chart.palette()] == ECHARTS_PALETTE

    def test_default_palette_follows_default_theme(self):
        assert setDefaultChartTheme("matlab") is True
        assert defaultPalette()[0].name() == "#0072bd"

    @pytest.mark.parametrize("name", BUILTINS[1:], ids=list(BUILTINS[1:]))
    def test_text_contrast(self, name):
        spec = chartThemeSpec(name)
        for variant in ("light", "dark"):
            colors = spec[variant]
            background = colors.get("color.bg.base")
            primary = colors.get("color.text.primary")
            assert background and primary, f"{name}.{variant} 缺少底色 / 正文色"
            ratio = _contrast_ratio(parse_color(background), parse_color(primary))
            assert ratio >= 4.5, f"{name}.{variant} 正文对比度只有 {ratio:.2f}"

    @pytest.mark.parametrize("name", BUILTINS[1:], ids=list(BUILTINS[1:]))
    def test_builtin_renders(self, make, name):
        chart = _chart(make, name)
        chart.setOption(_BASE_OPTION)
        image = _render(chart)
        assert not image.isNull()


class TestInstanceTheme:
    def test_switch_palette_and_tokens(self, make):
        chart = _chart(make)
        assert chart.setChartTheme("matlab") is True
        assert chart.chartTheme() == "matlab"
        assert [color.name() for color in chart.palette()][:3] == [
            "#0072bd",
            "#d95319",
            "#edb120",
        ]
        colors = chartThemeSpec("matlab")[_variant()]
        assert chartToken("color.bg.base", chart).name() == colors["color.bg.base"]
        assert (
            chartToken("color.text.primary", chart).name()
            == colors["color.text.primary"]
        )

    def test_invalid_name_keeps_current(self, make):
        chart = _chart(make, "matlab")
        assert chart.setChartTheme("no-such-theme") is False
        assert chart.chartTheme() == "matlab"

    def test_reset_to_global_default(self, make):
        assert setDefaultChartTheme("plotly") is True
        chart = _chart(make)
        assert chart.chartTheme() == "plotly"
        assert chart.setChartTheme(None) is True
        assert chart.chartTheme() == "plotly"
        assert setDefaultChartTheme("ela") is True
        assert chart.setChartTheme("") is True
        assert chart.chartTheme() == "ela"

    def test_default_only_affects_new_charts(self, make):
        chart = _chart(make)
        assert setDefaultChartTheme("matlab") is True
        assert chart.chartTheme() == "ela"
        assert _chart(make).chartTheme() == "matlab"

    def test_option_color_still_wins(self, make):
        chart = _chart(make, "matlab")
        chart.setOption(
            {
                "color": ["#010203"],
                "series": [{"type": "bar", "data": [1, 2]}],
            },
            notMerge=True,
        )
        assert chart.palette()[0].name() == "#010203"

    def test_series_color_still_wins(self, make):
        chart = _chart(make, "matlab")
        chart.setOption(
            {"series": [{"type": "bar", "name": "S", "color": "#040506", "data": [1]}]},
            notMerge=True,
        )
        renderer = chart.seriesRenderers[0]
        assert chart.colorForSeries(renderer).name() == "#040506"

    def test_light_and_dark_variants(self, make):
        previous = eTheme.getThemeMode()
        try:
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
            chart = _chart(make, "matlab")
            assert chartToken("color.bg.base", chart).name() == "#ffffff"
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
            assert chartToken("color.bg.base", chart).name() == "#1e1e1e"
        finally:
            eTheme.setThemeMode(previous)

    def test_switch_invalidates_caches(self, make):
        chart = _chart(make)
        chart.setOption(_BASE_OPTION)
        _render(chart)
        assert chart._series_pixmap_key is not None
        chart.setChartTheme("matlab")
        assert chart._series_pixmap_key is None
        assert chart._palette_cache is None
        assert chart._layout_key is None
        _render(chart)
        assert chart._series_pixmap_key is not None
        assert "matlab" in repr(chart._series_pixmap_key)

    def test_export_background_follows_theme(self, make):
        chart = _chart(make, "matlab")
        image = _data_image(chart.getDataURL())
        expected = chartThemeSpec("matlab")[_variant()]["color.bg.base"]
        assert image.pixelColor(2, 2).name() == expected


class TestRegistry:
    def test_register_and_switch(self, make):
        registerChartTheme(
            "test-custom",
            palette=["#010203", "#040506"],
            light={
                "color.bg.base": "#fefefe",
                "color.text.primary": "#111111",
            },
            dark={
                "color.bg.base": "#101010",
                "color.text.primary": "#eeeeee",
            },
        )
        assert "test-custom" in chartThemes()
        chart = _chart(make, "test-custom")
        assert chart.palette()[0].name() == "#010203"
        colors = chartThemeSpec("test-custom")[_variant()]
        assert chartToken("color.bg.base", chart).name() == colors["color.bg.base"]

    def test_spec_is_a_deep_copy(self):
        registerChartTheme("test-custom", palette=["#010203"])
        spec = chartThemeSpec("test-custom")
        spec["palette"][0] = "#ffffff"
        spec["light"]["color.bg.base"] = "#000000"
        fresh = chartThemeSpec("test-custom")
        assert fresh["palette"][0] == "#010203"
        assert "color.bg.base" not in fresh["light"]

    def test_rgb_function_palette_is_parsed(self, make):
        registerChartTheme("test-custom", palette=["rgb(1, 2, 3)", "#040506"])
        chart = _chart(make, "test-custom")
        assert chart.palette()[0].name() == "#010203"
        assert chart.palette()[1].name() == "#040506"

    def test_partial_registration_merges(self):
        registerChartTheme("test-partial", light={"color.primary": "#123456"})
        registerChartTheme("test-partial", dark={"color.primary": "#654321"})
        spec = chartThemeSpec("test-partial")
        assert spec["light"]["color.primary"] == "#123456"
        assert spec["dark"]["color.primary"] == "#654321"
        assert spec["palette"] == ECHARTS_PALETTE

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"name": ""},
            {"name": "test-custom", "palette": []},
            {"name": "test-custom", "palette": ["not-a-color"]},
            {"name": "test-custom", "light": {"bogus.key": "#ffffff"}},
            {"name": "test-custom", "light": {"color.ramp": ["#ffffff"]}},
            {"name": "test-custom", "light": "not-a-dict"},
            {"name": "test-custom", "dark": {"color.ramp": "not-a-list"}},
        ],
        ids=[
            "empty-name",
            "empty-palette",
            "bad-color",
            "unknown-key",
            "short-ramp",
            "variant-not-dict",
            "ramp-not-list",
        ],
    )
    def test_invalid_registration(self, kwargs):
        with pytest.raises(ValueError):
            registerChartTheme(**kwargs)

    def test_unregister(self):
        registerChartTheme("test-custom", palette=["#010203"])
        assert unregisterChartTheme("test-custom") is True
        assert "test-custom" not in chartThemes()
        assert unregisterChartTheme("test-custom") is False
        assert unregisterChartTheme("ela") is False

    def test_unknown_theme_queries(self):
        assert chartThemeSpec("no-such-theme") is None
        assert setDefaultChartTheme("no-such-theme") is False

    def test_unregister_current_default_falls_back(self):
        registerChartTheme("test-custom", palette=["#010203"])
        assert setDefaultChartTheme("test-custom") is True
        assert unregisterChartTheme("test-custom") is True
        assert defaultChartTheme() == "ela"


class TestRamp:
    def test_theme_ramp_used_by_visual_map_and_heatmap(self, make):
        chart = _chart(make, "matlab")
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["A", "B"]},
                "yAxis": {"type": "category", "data": ["X", "Y"]},
                "visualMap": {"min": 0, "max": 10},
                "series": [
                    {
                        "type": "heatmap",
                        "data": [[0, 0, 0], [1, 1, 10]],
                    }
                ],
            }
        )
        expected = chartThemeSpec("matlab")[_variant()]["color.ramp"]
        component = next(
            c for c in chart.components if isinstance(c, VisualMapComponent)
        )
        assert [parse_color(c).name() for c in component.colors()] == expected
        cells = [cell for cell in chart.seriesRenderers[0]._cells if not cell["empty"]]
        top = max(cells, key=lambda cell: cell["value"])["color"].name()
        assert top == expected[-1]


class TestImageTheme:
    @staticmethod
    def _image_chart(make, **series):
        np = pytest.importorskip("numpy")
        chart = _chart(make)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "image",
                        "data": np.linspace(0, 1, 64).reshape(8, 8),
                        **series,
                    }
                ],
            },
            notMerge=True,
        )
        chart._layout_all(force=True)
        return chart

    def test_explicit_cmap_does_not_follow_theme(self, make):
        chart = self._image_chart(make, cmap="viridis")
        renderer = chart.seriesRenderers[0]
        before = [parse_color(c).name() for c in renderer._colors()]
        chart.setChartTheme("matlab")
        chart._layout_all(force=True)
        assert [parse_color(c).name() for c in renderer._colors()] == before
        colors = chartThemeSpec("matlab")[_variant()]
        assert chartToken("color.bg.base", chart).name() == colors["color.bg.base"]

    def test_implicit_colormap_follows_theme_ramp(self, make):
        chart = self._image_chart(make)
        renderer = chart.seriesRenderers[0]
        chart.setChartTheme("matlab")
        chart._layout_all(force=True)
        expected = chartThemeSpec("matlab")[_variant()]["color.ramp"]
        assert [parse_color(c).name() for c in renderer._colors()] == expected

