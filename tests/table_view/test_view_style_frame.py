"""视图样式的 ``CE_ShapedFrame`` 只画视图本体。

回归：``ElaTableViewStyle`` / ``ElaListViewStyle`` / ``ElaTreeViewStyle`` 通过
``setStyle`` 挂在视图上，**子控件会继承同一个 style**；``QLabel`` 等 ``QFrame``
子类在 ``QFrame::paintEvent`` 里也会调 ``CE_ShapedFrame``。不判 widget 类型就会把
「视口外框」（``PopupBorder`` + ``BasicBaseAlpha`` + 3px 圆角）画到
``setCellWidget`` / ``setItemWidget`` 放的子控件上 = 整格卡片。
"""

from __future__ import annotations

from collections import Counter

import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QLabel, QStyle, QStyleOptionFrame
from PyQt6ElaWidgetTools import (
    ElaListView,
    ElaTableView,
    ElaTreeView,
    ElaThemeType,
    eTheme,
)

from pyqt6_ela_pro import ElaDataTable


@pytest.fixture
def light_theme():
    previous = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
    yield
    eTheme.setThemeMode(previous)


def _painted_pixels(view, target, width: int = 100, height: int = 30) -> int:
    """用 ``view`` 的 style 给 ``target`` 画一次 ``CE_ShapedFrame``，数不透明像素。"""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    option = QStyleOptionFrame()
    option.rect = QRect(0, 0, width, height)
    view.style().drawControl(
        QStyle.ControlElement.CE_ShapedFrame, option, painter, target
    )
    painter.end()
    return sum(
        1
        for y in range(height)
        for x in range(width)
        if image.pixelColor(x, y).alpha() > 0
    )


@pytest.mark.parametrize(
    "view_cls",
    [ElaTableView, ElaListView, ElaTreeView],
    ids=["ElaTableView", "ElaListView", "ElaTreeView"],
)
def test_shaped_frame_skips_child_widgets(qapp, make, light_theme, view_cls):
    """视图本体仍画外框；QLabel 子控件（QFrame）不能再被画成卡片。"""
    view = make(view_cls)
    view.resize(200, 100)
    label = make(QLabel, "hello")
    label.setParent(view)
    label.resize(100, 30)

    assert _painted_pixels(view, view) > 0
    assert _painted_pixels(view, label) == 0


def _cell_pixel_names(table: ElaDataTable, row: int, col: int) -> list[str]:
    x = table.columnViewportPosition(col)
    y = table.rowViewportPosition(row)
    width = table.columnWidth(col)
    height = table.rowHeight(row)
    # 抓整张表：viewport().grab() 不含表格自己的底色，普通单元格会是透明黑。
    image = table.grab().toImage()
    offset = table.viewport().mapTo(table, QPoint(0, 0))
    names = []
    for yy in range(y + 4, min(y + height - 3, image.height() - offset.y())):
        for xx in range(x + 4, min(x + width - 3, image.width() - offset.x())):
            names.append(image.pixelColor(xx + offset.x(), yy + offset.y()).name())
    return names


def test_index_widget_cell_has_no_card(qapp, make, light_theme):
    """带 index widget 的单元格主色必须与普通单元格一致（不再叠卡片）。"""
    from _pixels import skip_if_no_pixels

    table = make(ElaDataTable)
    table.resize(420, 180)
    table.setTableData(
        [
            ["A", "B", "C", "D"],
            ["r0", "x", "y", ""],
            ["r1", "x", "y", ""],
        ]
    )
    table.show()
    qapp.processEvents()
    table.setCellWidget(0, 0, QLabel("hello", table))
    qapp.processEvents()

    widget_cell = _cell_pixel_names(table, 0, 0)
    plain_cell = _cell_pixel_names(table, 0, 1)
    skip_if_no_pixels(set(plain_cell), "单元格背景渲染")
    assert (
        Counter(widget_cell).most_common(1)[0][0]
        == Counter(plain_cell).most_common(1)[0][0]
    )
