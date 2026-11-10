"""非 QWidget 目标适配器：item view / 菜单 / QTextDocument。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QHelpEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QMenu, QTextBrowser

from pyqt6_ela_pro.tooltip_targets import (
    DOCUMENT_TOOLTIP_PROPERTY,
    action_tooltip_text,
    install_document_tooltips,
    install_item_view_tooltips,
    install_menu_tooltips,
    set_action_tooltip,
)


def _help_event(widget, pos: QPoint) -> QHelpEvent:
    return QHelpEvent(QEvent.Type.ToolTip, pos, widget.mapToGlobal(pos))


class TestItemViewToolTip:
    def test_item_role_shows_library_tooltip(self, qapp, make):
        view = make(QListWidget)
        item = QListWidgetItem("条目")
        item.setData(Qt.ItemDataRole.ToolTipRole, "条目说明")
        view.addItem(item)
        adapter = install_item_view_tooltips(view)
        view.resize(240, 120)
        view.show()
        qapp.processEvents()

        index = view.model().index(0, 0)
        pos = view.visualRect(index).center()
        event = _help_event(view.viewport(), pos)
        assert adapter.eventFilter(view.viewport(), event) is True
        assert adapter.tooltip()._text == "条目说明"

    def test_missing_item_text_hides_tooltip(self, qapp, make):
        view = make(QListWidget)
        view.addItem(QListWidgetItem("无提示"))
        adapter = install_item_view_tooltips(view)
        view.resize(240, 120)
        view.show()
        qapp.processEvents()

        index = view.model().index(0, 0)
        pos = view.visualRect(index).center()
        event = _help_event(view.viewport(), pos)
        assert adapter.eventFilter(view.viewport(), event) is True
        assert adapter.tooltip().isVisible() is False


class TestMenuToolTip:
    def test_action_property_shows_library_tooltip(self, qapp, make):
        menu = make(QMenu)
        action = menu.addAction("动作")
        set_action_tooltip(action, "菜单项说明")
        assert action_tooltip_text(action) == "菜单项说明"
        adapter = install_menu_tooltips(menu)
        menu.popup(QPoint(100, 100))
        qapp.processEvents()

        pos = menu.actionGeometry(action).center()
        event = _help_event(menu, pos)
        assert adapter.eventFilter(menu, event) is True
        assert adapter.tooltip()._text == "菜单项说明"
        menu.close()

    def test_plain_action_text_is_not_a_tooltip(self, qapp, make):
        menu = make(QMenu)
        action = menu.addAction("动作")
        assert action_tooltip_text(action) == ""


class TestDocumentToolTip:
    def test_format_property_shows_library_tooltip(self, qapp, make):
        browser = make(QTextBrowser)
        cursor = QTextCursor(browser.document())
        fmt = QTextCharFormat()
        fmt.setProperty(DOCUMENT_TOOLTIP_PROPERTY, "文档提示")
        cursor.setCharFormat(fmt)
        cursor.insertText("链接")
        adapter = install_document_tooltips(browser)
        browser.resize(260, 120)
        browser.show()
        qapp.processEvents()

        cursor.setPosition(0)
        pos = browser.cursorRect(cursor).center()
        event = _help_event(browser.viewport(), pos)
        assert adapter.eventFilter(browser.viewport(), event) is True
        assert adapter.tooltip()._text == "文档提示"

    def test_plain_text_hides_tooltip(self, qapp, make):
        browser = make(QTextBrowser)
        browser.setPlainText("普通文本")
        adapter = install_document_tooltips(browser)
        browser.resize(260, 120)
        browser.show()
        qapp.processEvents()

        cursor = QTextCursor(browser.document())
        cursor.setPosition(0)
        pos = browser.cursorRect(cursor).center()
        event = _help_event(browser.viewport(), pos)
        assert adapter.eventFilter(browser.viewport(), event) is True
        assert adapter.tooltip().isVisible() is False
