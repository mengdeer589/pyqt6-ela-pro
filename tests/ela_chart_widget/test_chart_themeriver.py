"""themeRiver 标签走统一标签色策略：半透明流带用主题文字色。"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts._utils import parse_color, with_alpha


def test_theme_river_labels_use_theme_text(make):
    old_mode = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    try:
        chart = make(ElaChartWidget)
        chart.resize(640, 320)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "time", "show": False},
                "yAxis": {"type": "value", "show": False},
                "series": [
                    {
                        "type": "themeRiver",
                        "data": [
                            ["2015-11-08", 10, "游戏"],
                            ["2015-11-08", 8, "音乐"],
                            ["2015-11-08", 6, "旅游"],
                            ["2015-11-09", 12, "游戏"],
                            ["2015-11-09", 7, "音乐"],
                            ["2015-11-09", 9, "旅游"],
                        ],
                    }
                ],
            }
        )
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        renderer = chart.seriesRenderers[0]
        fill = with_alpha(parse_color(chart.palette()[0]), 150)
        actual = renderer.contrastLabelColor(fill, 0)
        expected = renderer.labelColorFor(0)
        assert actual.name() == expected.name()
        assert actual.name() != "#000000"
    finally:
        eTheme.setThemeMode(old_mode)
