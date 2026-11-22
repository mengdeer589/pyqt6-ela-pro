"""半透明填充上的标签对比色：必须先压到画布底再选黑 / 白。

* **E9** 地图无数据区域用 ``color.bg.muted``（暗色白 alpha 15 / 亮色黑 alpha 9
  的叠色）。直接 ``text_on_color`` 只看原始 RGB —— 暗色下深灰底配黑字、
  亮色下浅灰底配白字，两头都看不清。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts._utils import flatten_on_canvas, text_on_fill


@pytest.fixture
def set_mode():
    previous = eTheme.getThemeMode()
    yield eTheme.setThemeMode
    eTheme.setThemeMode(previous)


def _map_chart(make):
    chart = make(ElaChartWidget)
    chart.resize(520, 380)
    chart.setOption(
        {
            "animation": False,
            "series": [
                {
                    "type": "map",
                    "map": "demo",
                    "data": [{"name": "华北", "value": 10}],
                }
            ],
        }
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


@pytest.mark.parametrize(
    "mode,fill,expected",
    [
        (ElaThemeType.ThemeMode.Dark, QColor(255, 255, 255, 15), "#ffffff"),
        (ElaThemeType.ThemeMode.Light, QColor(0, 0, 0, 9), "#000000"),
    ],
)
def test_translucent_fill_uses_canvas(set_mode, make, mode, fill, expected):
    set_mode(mode)
    chart = make(ElaChartWidget)
    assert text_on_fill(fill, chart).name() == expected


def test_flatten_uses_explicit_background(set_mode, make):
    set_mode(ElaThemeType.ThemeMode.Light)
    chart = make(ElaChartWidget)
    chart.setOption({"animation": False, "backgroundColor": "#000000"})
    assert flatten_on_canvas(QColor(255, 255, 255, 15), chart).name() == "#0f0f0f"


@pytest.mark.parametrize(
    "mode,expected",
    [
        (ElaThemeType.ThemeMode.Dark, "#ffffff"),
        (ElaThemeType.ThemeMode.Light, "#000000"),
    ],
)
def test_map_empty_region_is_readable(set_mode, make, mode, expected):
    set_mode(mode)
    chart = _map_chart(make)
    renderer = chart.seriesRenderers[0]
    values = renderer._value_map()
    fill = renderer._fill_color("西北", values, 0.0, 10.0, None)
    assert fill.alpha() == 255, "无数据区域仍是半透明，hover / 命中色会失真"
    assert text_on_fill(fill, chart).name() == expected
    assert fill.lighter(112).name() != fill.name(), "hover 提亮对纯白无效"
