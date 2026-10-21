"""``ElaDataTable`` 单元格前景 / 背景色的渲染回归。

官方上游轮的 ``ElaTableViewStyle::CE_ItemViewItem`` 用固定主题色画文字、也不读
item 的 ``BackgroundRole`` —— ``setItemForeground`` / ``setItemBackground`` 设了
不显示。本地重建轮改为读 ``index.data(ForegroundRole / BackgroundRole)``；本文件
钉住这条路径（离屏平台不渲染文字像素时按 ``_pixels`` 探测跳过）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro import ElaDataTable

_MAGENTA = "#ff00ff"


@pytest.fixture
def light_theme():
    previous = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
    yield
    eTheme.setThemeMode(previous)


def _build(make, qapp):
    table = make(ElaDataTable)
    table.resize(420, 180)
    # 首行是表头、数据行从 0 起 —— 颜色设在第 1 行就必须有第二行数据
    table.setTableData(
        [
            ["A", "B", "C"],
            ["plain", "fg", "bg"],
            ["row2", "x", "y"],
        ]
    )
    table.show()
    qapp.processEvents()
    return table


def _cell_pixel_names(table, row, col):
    """单元格区域的像素颜色名列表（viewport 坐标，逐像素含重复）。"""
    x = table.columnViewportPosition(col)
    y = table.rowViewportPosition(row)
    width = table.columnWidth(col)
    height = table.rowHeight(row)
    image = table.viewport().grab().toImage()
    names = []
    for yy in range(y + 3, min(y + height - 2, image.height())):
        for xx in range(x + 3, min(x + width - 2, image.width())):
            names.append(image.pixelColor(xx, yy).name())
    return names


def _rgb(name):
    return int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16)


def _is_magenta(name):
    r, g, b = _rgb(name)
    return r > 140 and b > 140 and g < 130


def _is_dark(name):
    r, g, b = _rgb(name)
    return 0.299 * r + 0.587 * g + 0.114 * b < 110


class TestItemColors:
    def test_item_foreground_is_rendered(self, qapp, make, light_theme):
        from _pixels import skip_if_no_pixels

        table = _build(make, qapp)
        table.setItemForeground(1, 1, QColor(_MAGENTA))
        table.viewport().repaint()
        qapp.processEvents()

        names = _cell_pixel_names(table, 1, 1)
        skip_if_no_pixels(set(names), "单元格前景色渲染")
        assert any(_is_magenta(name) for name in names), (
            "单元格前景色没有画出来（样式没读 ForegroundRole？）"
        )

    def test_item_background_is_rendered(self, qapp, make, light_theme):
        table = _build(make, qapp)
        table.setItemBackground(1, 2, QColor("#ffff00"))
        table.viewport().repaint()
        qapp.processEvents()

        names = _cell_pixel_names(table, 1, 2)
        assert names, "单元格区域没有像素"
        assert max(set(names), key=names.count) == "#ffff00", (
            "单元格背景色没有画出来（样式没读 BackgroundRole？）"
        )

    def test_default_text_stays_readable(self, qapp, make, light_theme):
        """没设前景色的单元格仍用主题文字色（改动不得把默认路径弄坏）。"""
        from _pixels import skip_if_no_pixels

        table = _build(make, qapp)
        table.setItemForeground(1, 1, QColor(_MAGENTA))
        table.viewport().repaint()
        qapp.processEvents()

        names = _cell_pixel_names(table, 1, 0)
        skip_if_no_pixels(set(names), "默认单元格文字")
        assert any(_is_dark(name) for name in names), "默认单元格文字不可见"
        assert not any(_is_magenta(name) for name in names), (
            "前景色串到了其它单元格"
        )
