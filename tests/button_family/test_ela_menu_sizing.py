"""ElaMenu 弹出时按 sizeHint 撑开（非主屏 / Win7 回归的本地不变量）。"""

from __future__ import annotations

from PyQt6.QtCore import QPoint

from PyQt6ElaWidgetTools import ElaMenu


def test_menu_expands_to_size_hint(make, qapp):
    menu = make(ElaMenu)
    for index in range(10):
        menu.addAction(f"item{index}")
    hint = menu.sizeHint()
    menu.popup(QPoint(100, 100))
    qapp.processEvents()
    assert menu.height() >= hint.height()
    assert menu.minimumSize().height() == menu.size().height()
    menu.close()


def test_menu_shrinks_after_actions_are_cleared(make, qapp):
    menu = make(ElaMenu)
    for index in range(20):
        menu.addAction(f"item{index}")
    menu.popup(QPoint(100, 100))
    qapp.processEvents()
    tall = menu.height()
    menu.close()

    menu.clear()
    for index in range(3):
        menu.addAction(f"item{index}")
    hint = menu.sizeHint()
    menu.popup(QPoint(100, 100))
    qapp.processEvents()
    assert menu.height() < tall
    assert menu.height() >= hint.height()
    menu.close()
