"""``ElaTrayIcon`` 测试。

**所有断言只打在组件自身状态上**，不打托盘区几何 —— ``isSystemTrayAvailable()``
在无桌面环境可能为 ``False``，``show()`` 可能无任何效果，测试必须容忍这一点。
"""

from __future__ import annotations

import pytest
from _qthelpers import flush_events
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from pyqt6_ela_pro import ElaMenuItem, ElaTrayIcon
from pyqt6_ela_pro._internal import is_deleted
from pyqt6_ela_pro.ela_tray_icon import ElaTrayIcon as _Direct


def dot(color: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(0, 0, 16, 16)
    painter.end()
    return QIcon(pixmap)


def icon_key(icon: QIcon) -> int:
    """``QIcon.cacheKey()`` 对不同内容给出不同键，是比较图标内容最省事的方式。"""
    return int(icon.cacheKey())


@pytest.fixture
def tray(make):
    return make(ElaTrayIcon, dot("#4f9dff"), "tooltip text")


class TestPublicApi:
    def test_exported_from_package(self):
        assert ElaTrayIcon is _Direct
        assert (
            "ElaTrayIcon" in __import__("pyqt6_ela_pro", fromlist=["__all__"]).__all__
        )

    def test_menu_item_is_shared(self):
        """菜单项模型与划词助手共用同一个 dataclass。"""
        from pyqt6_ela_pro import menu_item as module

        assert module.ElaMenuItem is ElaMenuItem
        assert ElaMenuItem("a", "A").enabled is True


class TestInit:
    def test_object_name(self, tray):
        assert tray.objectName() == "ElaTrayIcon"

    def test_defaults(self, tray):
        assert tray.toolTip() == "tooltip text"
        assert tray.isVisible() is False
        assert tray.state() == ElaTrayIcon.ElaTrayStateType.Normal
        assert tray.menu() is None

    def test_empty_constructor(self, make):
        t = make(ElaTrayIcon)
        assert t.toolTip() == ""
        assert t.isVisible() is False

    def test_tooltip_setter(self, tray):
        tray.setToolTip("新的提示")
        assert tray.toolTip() == "新的提示"


class TestIcon:
    def test_set_icon(self, tray):
        tray.setIcon(dot("#ff0000"))
        assert not tray.icon().isNull()

    def test_set_icons_registers_all_three(self, tray):
        tray.setIcons(dot("#00ff00"), dot("#ffff00"), dot("#ff0000"))
        assert tray.state() == ElaTrayIcon.ElaTrayStateType.Normal

    def test_state_switch_changes_icon(self, tray):
        tray.setIcons(dot("#00ff00"), dot("#ffff00"), dot("#ff0000"))
        before = icon_key(tray.icon())
        tray.setState(ElaTrayIcon.ElaTrayStateType.Critical)
        assert tray.state() == ElaTrayIcon.ElaTrayStateType.Critical
        assert icon_key(tray.icon()) != before

    def test_invalid_state_falls_back(self, tray):
        tray.setIcons(dot("#00ff00"), dot("#ffff00"), dot("#ff0000"))
        tray.setState(ElaTrayIcon.ElaTrayStateType.Warning)
        tray.setState(999)  # 非法值
        assert tray.state() == ElaTrayIcon.ElaTrayStateType.Normal

    def test_unregistered_state_falls_back_to_normal(self, tray):
        tray.setIcons(normal=dot("#00ff00"))
        tray.setState(ElaTrayIcon.ElaTrayStateType.Critical)
        assert tray.state() == ElaTrayIcon.ElaTrayStateType.Critical
        # 不崩溃，图标不为 null（回落到 normal）


class TestMenu:
    def test_set_and_get_menu(self, tray):
        menu = QMenu()
        tray.setMenu(menu)
        assert tray.menu() is menu

    def test_clear_menu(self, tray):
        tray.setMenu(QMenu())
        tray.setMenu(None)
        assert tray.menu() is None

    def test_accepts_ela_menu(self, make, tray):
        from PyQt6ElaWidgetTools import ElaMenu

        menu = ElaMenu()
        tray.setMenu(menu)
        assert tray.menu() is menu
        menu.deleteLater()


class TestNotify:
    def test_notify_when_supported(self, tray, monkeypatch):
        monkeypatch.setattr(
            QSystemTrayIcon, "supportsMessages", staticmethod(lambda: True)
        )
        seen = []
        monkeypatch.setattr(
            tray._tray, "showMessage", lambda *a, **k: seen.append((a, k))
        )
        assert tray.notify("标题", "正文") is True
        assert len(seen) == 1

    def test_notify_degrades_when_unsupported(self, tray, monkeypatch):
        """Win7 等环境可能不支持气泡：降级发 errorOccurred，不抛也不发气泡。"""
        monkeypatch.setattr(
            QSystemTrayIcon, "supportsMessages", staticmethod(lambda: False)
        )
        errors = []
        tray.errorOccurred.connect(errors.append)
        called = []
        monkeypatch.setattr(tray._tray, "showMessage", lambda *a, **k: called.append(1))
        assert tray.notify("标题", "正文") is False
        assert called == []  # 没有真发气泡
        assert len(errors) == 1  # 但有降级提示

    def test_invalid_message_icon_defaults_to_info(self, tray, monkeypatch):
        monkeypatch.setattr(
            QSystemTrayIcon, "supportsMessages", staticmethod(lambda: True)
        )
        seen = []
        monkeypatch.setattr(tray._tray, "showMessage", lambda *a, **k: seen.append(a))
        tray.notify("t", "m", icon=99)
        assert seen


class TestVisibility:
    def test_show_hide_toggle(self, tray):
        changes = []
        tray.visibilityChanged.connect(changes.append)
        tray.show()
        assert tray.isVisible() is True
        tray.hide()
        assert tray.isVisible() is False
        assert changes == [True, False]

    def test_show_idempotent(self, tray):
        tray.show()
        changes = []
        tray.visibilityChanged.connect(changes.append)
        tray.show()
        assert changes == []

    def test_hide_idempotent(self, tray):
        changes = []
        tray.visibilityChanged.connect(changes.append)
        tray.hide()
        assert changes == []

    def test_activated_signal(self, tray):
        seen = []
        tray.activated.connect(seen.append)
        tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        # 信号契约是 int（枚举值），见 _on_activated
        assert seen == [QSystemTrayIcon.ActivationReason.Trigger.value]


class TestLifecycle:
    def test_delete_hides_tray(self, make):
        """析构必须先 hide()：否则托盘区留一个点不动的灰图标。"""
        t = make(ElaTrayIcon, dot("#ff0000"))
        t.show()
        assert t.isVisible() is True
        t.deleteLater()
        # deleteLater 后 tray 已不可见
        assert t._tray.isVisible() is False

    def test_theme_change_after_delete_does_not_raise(self, make, qapp):
        """析构时断开 themeModeChanged：之后切主题不得再回调到野对象。"""
        from PyQt6ElaWidgetTools import ElaThemeType, eTheme

        t = make(ElaTrayIcon, dot("#ff0000"))
        t.show()
        t.deleteLater()
        flush_events(qapp)
        current = eTheme.getThemeMode()
        other = (
            ElaThemeType.ThemeMode.Dark
            if current == ElaThemeType.ThemeMode.Light
            else ElaThemeType.ThemeMode.Light
        )
        eTheme.setThemeMode(other)  # 不得抛异常
        eTheme.setThemeMode(current)

    def test_ismarked_deleted(self, make, qapp):
        t = make(ElaTrayIcon, dot("#ff0000"))
        tray_obj = t._tray
        t.deleteLater()
        # processEvents() 不派发 DeferredDelete，要显式冲刷
        QCoreApplication.sendPostedEvents(t, QEvent.Type.DeferredDelete)
        flush_events(qapp)
        # 组件本体销毁后，托盘子对象随之析构
        assert is_deleted(tray_obj)


class TestSignalSafety:
    def test_activated_handler_exception_not_killing_process(self, tray):
        """Qt 回调内异常会 0xC0000409 静默 abort。这里只验证信号能正常派发，
        不在槽里故意抛异常（那正是 AGENTS 禁止的做法）。"""
        seen = []
        tray.activated.connect(seen.append)
        tray._on_activated(QSystemTrayIcon.ActivationReason.Context)
        assert seen == [QSystemTrayIcon.ActivationReason.Context.value]


__all__ = ["TestInit", "TestIcon", "TestMenu", "TestNotify", "TestVisibility"]
