"""主题 × 系列矩阵：视口内绘制 / 点击 / 示例 option 回归。"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtTest import QTest

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import chartThemes
from pyqt6_ela_pro.example.charts_page import ChartsPage
from pyqt6_ela_pro.example.theme_matrix import (
    SERIES_ORDER,
    ThemeMatrixWidget,
    capabilities,
    sample_option,
)


def test_matrix_shape(make):
    matrix = make(ThemeMatrixWidget)
    matrix.resize(900, 600)
    assert matrix.themes() == chartThemes()
    assert matrix.seriesTypes() == list(SERIES_ORDER)
    assert len(matrix.seriesTypes()) == 23
    assert set(capabilities("line")) == {
        "label",
        "visualMap",
        "select",
        "legend",
        "polar",
    }


def test_matrix_paints_only_visible_rows(make, monkeypatch):
    matrix = make(ThemeMatrixWidget)
    matrix.resize(900, 1400)
    calls = []
    original = matrix._paint_row

    def track(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(matrix, "_paint_row", track)
    matrix.grab(QRect(0, 0, 900, 220))
    assert calls
    assert len(set(calls)) <= 6


def test_matrix_click_emits_cell(make):
    matrix = make(ThemeMatrixWidget)
    matrix.resize(900, 600)
    seen = []
    matrix.cellActivated.connect(lambda *args: seen.append(args))
    point = matrix._cell_rect(2, 3).center().toPoint()
    QTest.mouseClick(matrix, Qt.MouseButton.LeftButton, pos=point)
    assert seen == [(SERIES_ORDER[2], matrix.themes()[3])]


def test_every_series_sample_option_builds(make):
    for kind in SERIES_ORDER:
        chart = make(ElaChartWidget)
        chart.resize(480, 360)
        chart.setOption(sample_option(kind))
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        assert chart.seriesRenderers, kind
        assert len(chart.seriesRenderers[0].data()) > 0, kind


def test_theme_workspace_has_matrix_and_opens_example(make):
    page = make(ChartsPage)
    page.resize(1100, 820)
    page._activate_workspace(5)
    assert isinstance(page._theme_matrix, ThemeMatrixWidget)
    page._openThemeMatrixDemo("bar", "matlab")
    dialog = page._theme_matrix_dialog
    assert dialog is not None
    assert dialog.isVisible()
    dialog.close()
