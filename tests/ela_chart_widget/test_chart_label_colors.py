"""标签颜色统一策略：半透明填充跟随主题文字，实色填充按黑 / 白对比。"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts._utils import parse_color, text_on_fill


def _bar_chart(make, color):
    chart = make(ElaChartWidget)
    chart.resize(600, 300)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b"]},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "data": [10, 8],
                    "itemStyle": {"color": color},
                    "label": {"show": True, "position": "inside"},
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def test_translucent_fill_uses_theme_label_color(make):
    old_mode = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    try:
        chart = _bar_chart(make, "rgba(0, 213, 224, 0.59)")
        renderer = chart.seriesRenderers[0]
        fill = parse_color("rgba(0, 213, 224, 0.59)")
        expected = renderer.labelColorFor(0)
        actual = renderer.contrastLabelColor(fill, 0)
        assert actual.name() == expected.name()
        assert actual.name() != "#000000"
    finally:
        eTheme.setThemeMode(old_mode)


def test_opaque_fill_keeps_black_white_contrast(make):
    old_mode = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    try:
        chart = _bar_chart(make, "#fce100")
        renderer = chart.seriesRenderers[0]
        fill = parse_color("#fce100")
        expected = text_on_fill(fill, chart)
        actual = renderer.contrastLabelColor(fill, 0)
        assert actual.name() == expected.name()
        assert actual.name() == "#000000"
    finally:
        eTheme.setThemeMode(old_mode)
