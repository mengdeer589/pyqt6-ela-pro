"""``example/tray_host.py`` 的 ``ElaTrayHost`` 测试（应用级宿主骨架）。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro import ElaMenuItem
from pyqt6_ela_pro.example.tray_host import (
    QUIT_ID,
    SEPARATOR,
    TOGGLE_WINDOW_ID,
    ElaTrayHost,
)


@pytest.fixture
def window(make):
    w = make(QWidget)
    w.setWindowFlags(Qt.WindowType.Window)
    w.resize(300, 200)
    return w


@pytest.fixture
def host(make, window):
    return make(ElaTrayHost, window, None, "host tooltip")


def action_by_id(menu, action_id):  # noqa: ANN001, ANN201
    for action in menu.actions():
        if action.data() == action_id:
            return action
    return None


def trigger(menu, action_id):  # noqa: ANN001
    for action in menu.actions():
        if action.data() == action_id:
            action.trigger()
            return True
    return False


def find_by_text(menu, text):  # noqa: ANN001
    for action in menu.actions():
        if action.text() == text:
            return action
    return None


class TestInit:
    def test_defaults(self, host, window):
        assert host.trayIcon() is not None
        assert host.items() == []
        assert host.isWindowVisible() is False

    def test_tooltip_forwarded(self, host):
        assert host.trayIcon().toolTip() == "host tooltip"

    def test_menu_created(self, host):
        assert host.trayIcon().menu() is not None


class TestItems:
    def test_set_items_builds_menu(self, host):
        host.setItems(
            [
                ElaMenuItem(TOGGLE_WINDOW_ID, "隐藏主窗口", None),
                SEPARATOR,
                ElaMenuItem(QUIT_ID, "退出", None),
            ]
        )
        menu = host.trayIcon().menu()
        labels = [a.text() for a in menu.actions()]
        assert "隐藏主窗口" in labels
        assert "退出" in labels
        assert any(a.isSeparator() for a in menu.actions())

    def test_disabled_item_hidden(self, host):
        host.setItems([ElaMenuItem("x", "隐藏我", None, enabled=False)])
        assert find_by_text(host.trayIcon().menu(), "隐藏我") is None

    def test_items_snapshot_is_copy(self, host):
        items = [ElaMenuItem("a", "A", None)]
        host.setItems(items)
        snapshot = host.items()
        snapshot.append(ElaMenuItem("b", "B", None))
        assert len(host.items()) == 1

    def test_update_item_rewrites_label(self, host):
        host.setItems([ElaMenuItem("a", "旧文案", None)])
        host.updateItem("a", label="新文案")
        assert find_by_text(host.trayIcon().menu(), "新文案") is not None
        assert find_by_text(host.trayIcon().menu(), "旧文案") is None

    def test_update_unknown_id_is_noop(self, host):
        host.setItems([ElaMenuItem("a", "A", None)])
        host.updateItem("zzz", label="X")
        assert find_by_text(host.trayIcon().menu(), "A") is not None

    def test_no_checkable_actions(self, host):
        """ElaMenu 的图标列与勾选框互斥：本菜单不许出现 checkable 项，
        否则所有项的 ElaIconType 图标都会消失。"""
        host.setItems(
            [
                ElaMenuItem(TOGGLE_WINDOW_ID, "隐藏主窗口", None),
                ElaMenuItem("s", "开关", None),
                ElaMenuItem(QUIT_ID, "退出", None),
            ]
        )
        for action in host.trayIcon().menu().actions():
            assert not action.isCheckable(), action.text()


class TestToggleWindow:
    def test_toggle_emits_signal(self, host, window):
        seen = []
        host.windowVisibilityRequested.connect(seen.append)
        host.toggleWindow()
        assert seen == [True]

    def test_toggle_flips_based_on_window_state(self, host, window):
        seen = []
        host.windowVisibilityRequested.connect(seen.append)
        window.show()
        host.toggleWindow()
        assert seen == [False]

    def test_toggle_syncs_menu_label(self, host, window):
        """显隐状态回写菜单文案（不用勾选框表达状态）。"""
        host.setItems([ElaMenuItem(TOGGLE_WINDOW_ID, "隐藏主窗口", None)])
        host.requestWindowVisibility(False)
        assert find_by_text(host.trayIcon().menu(), "显示主窗口") is not None
        host.requestWindowVisibility(True)
        assert find_by_text(host.trayIcon().menu(), "隐藏主窗口") is not None

    def test_request_emits_explicit_value(self, host):
        seen = []
        host.windowVisibilityRequested.connect(seen.append)
        host.requestWindowVisibility(True)
        host.requestWindowVisibility(False)
        assert seen == [True, False]

    def test_is_window_visible(self, host, window):
        assert host.isWindowVisible() is False
        window.show()
        assert host.isWindowVisible() is True


class TestActions:
    def test_toggle_item_triggers_toggle(self, host, window):
        host.setItems([ElaMenuItem(TOGGLE_WINDOW_ID, "隐藏主窗口", None)])
        seen = []
        host.windowVisibilityRequested.connect(seen.append)
        trigger(host.trayIcon().menu(), TOGGLE_WINDOW_ID)
        assert seen == [True]

    def test_quit_item_emits_quit_requested(self, host):
        host.setItems([ElaMenuItem(QUIT_ID, "退出", None)])
        seen = []
        host.quitRequested.connect(lambda: seen.append(True))
        trigger(host.trayIcon().menu(), QUIT_ID)
        assert seen == [True]

    def test_custom_item_emits_action_triggered(self, host):
        host.setItems([ElaMenuItem("custom", "自定义", None)])
        seen = []
        host.actionTriggered.connect(seen.append)
        trigger(host.trayIcon().menu(), "custom")
        assert seen == ["custom"]

    def test_quit_method_emits_signal(self, host):
        seen = []
        host.quitRequested.connect(lambda: seen.append(True))
        host.quit()
        assert seen == [True]


class TestTrayToggle:
    def test_show_hide(self, host):
        host.show()
        assert host.trayIcon().isVisible() is True
        host.hide()
        assert host.trayIcon().isVisible() is False

    def test_single_click_triggers_toggle(self, host, window):
        from PyQt6.QtWidgets import QSystemTrayIcon

        seen = []
        host.windowVisibilityRequested.connect(seen.append)
        host._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        assert seen == [True]

    def test_double_click_does_not_toggle(self, host):
        from PyQt6.QtWidgets import QSystemTrayIcon

        seen = []
        host.windowVisibilityRequested.connect(seen.append)
        host._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert seen == []


class TestItemActions:
    def test_data_carries_action_id(self, host):
        """菜单项 id 写进 QAction.data()，便于测试与调试定位。"""
        host.setItems([ElaMenuItem("myid", "文字", None)])
        assert action_by_id(host.trayIcon().menu(), "myid") is not None


__all__ = ["TestItems", "TestToggleWindow", "TestActions"]
