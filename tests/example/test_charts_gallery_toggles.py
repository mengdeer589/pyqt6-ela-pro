"""系列画廊交互控件的状态回归。

**已修 bug**：日历热力的「GitHub 绿配色」打开再关掉，格子仍是绿的。根因是
``setOption`` 默认深合并 —— 关闭时提交的 ``visualMap`` 里**没有** ``inRange``，
合并会把上一次的 ``inRange.colors`` 原样留下；条件键消失的场景必须
``notMerge=True``（示例里由 ``_applyCalendarOption`` 统一重建）。

断言覆盖两条独立的消费路径：``visualMap`` 组件的色带，以及 heatmap 渲染器
按 option 直接算出的格子色 —— 只修其中一条时另一条仍会是绿的。
"""

from __future__ import annotations

from pyqt6_ela_pro.charts._utils import parse_color
from pyqt6_ela_pro.charts.interact.visualmap import VisualMapComponent
from pyqt6_ela_pro.example.charts_page import _GITHUB_GREENS, ChartsPage

_GITHUB = [parse_color(c).name() for c in _GITHUB_GREENS]


def _calendar(make):
    page = make(ChartsPage)
    page.resize(1100, 820)
    page._activate_workspace(1)  # 系列画廊
    chart = page._calendar_chart
    chart.anim.setProgress(1.0)
    return page, chart


def _palette(chart) -> list[str]:
    """``visualMap`` 组件当前生效的色带（十六进制名）。"""
    comp = next(c for c in chart.components if isinstance(c, VisualMapComponent))
    return [parse_color(c).name() for c in comp.colors()]


def _top_cell_color(chart) -> str:
    """最大值格子的实际渲染色（heatmap 渲染器自己的色带解析）。"""
    cells = [cell for cell in chart._series[0]._cells if not cell["empty"]]
    return max(cells, key=lambda cell: cell["value"])["color"].name()


def test_palette_toggle_round_trip(make):
    page, chart = _calendar(make)
    default_palette = _palette(chart)
    default_top = _top_cell_color(chart)
    assert default_palette != _GITHUB

    page._onCalendarPaletteToggled(True)
    assert _palette(chart) == _GITHUB
    assert _top_cell_color(chart) == _GITHUB[-1]

    page._onCalendarPaletteToggled(False)
    assert _palette(chart) == default_palette
    assert _top_cell_color(chart) == default_top
    assert "inRange" not in chart.getOption()["visualMap"]


def test_mode_switch_keeps_palette_state(make):
    page, chart = _calendar(make)
    default_palette = _palette(chart)

    page._onCalendarPaletteToggled(True)
    page._setCalendarMode("weekly")
    assert page._calendar_mode == "weekly"
    assert page._calendar_chips["weekly"].isChecked()
    assert _palette(chart) == _GITHUB
    assert _top_cell_color(chart) == _GITHUB[-1]

    page._onCalendarPaletteToggled(False)
    page._setCalendarMode("cumulative")
    assert _palette(chart) == default_palette
    assert "inRange" not in chart.getOption()["visualMap"]
