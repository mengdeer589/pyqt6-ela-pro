"""非 QWidget 目标适配器：item view / 菜单 / QTextDocument。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QHelpEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QTextBrowser,
)

import pyqt6_ela_pro.tooltip_targets as tooltip_targets_module
from _qthelpers import wait_until
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


class _FakeCursor:
    """测试用光标替身：只实现看门狗用到的 ``pos()``。"""

    pos_value = QPoint(0, 0)

    @classmethod
    def pos(cls) -> QPoint:
        return cls.pos_value


class TestAdapterWatchdog:
    """适配器看门狗：程序滚动 / 重排后光标下的提示变了要收起。"""

    @staticmethod
    def _view(make, monkeypatch, interval=120):
        monkeypatch.setattr(tooltip_targets_module, "TOOLTIP_WATCH_INTERVAL", interval)
        view = make(QListWidget)
        view.resize(240, 120)
        for i in range(40):
            item = QListWidgetItem(f"条目 {i}")
            item.setData(Qt.ItemDataRole.ToolTipRole, f"说明 {i}")
            view.addItem(item)
        adapter = install_item_view_tooltips(view)
        view.show()
        QApplication.processEvents()
        return view, adapter

    @staticmethod
    def _hover(adapter, view, monkeypatch):
        index = view.model().index(0, 0)
        pos = view.visualRect(index).center()
        monkeypatch.setattr(tooltip_targets_module, "QCursor", _FakeCursor)
        _FakeCursor.pos_value = view.viewport().mapToGlobal(pos)
        event = _help_event(view.viewport(), pos)
        assert adapter.eventFilter(view.viewport(), event) is True
        assert adapter.tooltip().isVisible()
        return pos

    def test_cursor_inside_same_item_keeps_tooltip(self, qapp, make, monkeypatch):
        view, adapter = self._view(make, monkeypatch)
        self._hover(adapter, view, monkeypatch)

        adapter._check_still_hovered()

        assert adapter.tooltip().isVisible()
        assert adapter._watch.isActive()

    def test_cursor_outside_target_hides_tooltip(self, qapp, make, monkeypatch):
        view, adapter = self._view(make, monkeypatch)
        self._hover(adapter, view, monkeypatch)
        _FakeCursor.pos_value = QPoint(-10000, -10000)

        adapter._check_still_hovered()

        assert adapter.tooltip().isVisible() is False
        assert adapter._watch.isActive() is False

    def test_programmatic_scroll_hides_tooltip(self, qapp, make, monkeypatch):
        view, adapter = self._view(make, monkeypatch)
        self._hover(adapter, view, monkeypatch)

        view.scrollToBottom()
        QApplication.processEvents()
        adapter._check_still_hovered()

        assert adapter.tooltip().isVisible() is False
        assert adapter._watch.isActive() is False

    def test_watchdog_timer_hides_after_scroll(self, qapp, make, monkeypatch):
        view, adapter = self._view(make, monkeypatch, interval=20)
        self._hover(adapter, view, monkeypatch)

        view.scrollToBottom()
        QApplication.processEvents()

        assert wait_until(
            qapp, lambda: not adapter.tooltip().isVisible(), timeout_ms=1000
        )

    def test_dispose_stops_watch(self, qapp, make, monkeypatch):
        view, adapter = self._view(make, monkeypatch)
        self._hover(adapter, view, monkeypatch)
        assert adapter._watch.isActive()

        adapter.dispose()

        assert adapter._watch.isActive() is False
