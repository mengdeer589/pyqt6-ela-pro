"""``ElaDropDownButton`` 测试：初值 / 文本 / 图标 / 圆角 / 菜单 / 鼠标事件。"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, Qt, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaIconType, ElaMenu, ElaThemeType

from pyqt6_ela_pro._theme import textDisabled
from pyqt6_ela_pro.ela_dropdown_button import ElaDropDownButton


@pytest.fixture
def btn(make):
    """默认构造的下拉按钮。"""
    return make(ElaDropDownButton)


class TestElaDropDownButtonInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_text", ""),
            ("_icon", ElaIconType.IconName.None_),
            ("_border_radius", 6),
            ("_menu", None),
            ("_is_hover", False),
            ("_is_pressed", False),
        ],
        ids=["text", "icon", "border-radius", "menu", "hover", "pressed"],
    )
    def test_initialization_with_defaults(self, btn, attr, expected):
        assert getattr(btn, attr) == expected

    def test_initialization_with_text(self, make):
        assert make(ElaDropDownButton, text="操作").text() == "操作"

    def test_initialization_with_icon(self, make):
        assert make(ElaDropDownButton, icon=ElaIconType.IconName.Gear).elaIcon() == (
            ElaIconType.IconName.Gear
        )

    def test_initialization_with_text_and_icon(self, make):
        btn = make(ElaDropDownButton, text="操作", icon=ElaIconType.IconName.Gear)
        assert btn.text() == "操作"
        assert btn.elaIcon() == ElaIconType.IconName.Gear

    def test_fixed_height(self, btn):
        """与按钮族一致（ElaPushButton V3.0 / ElaButton middle 都是 30）。"""
        assert btn.height() == 30

    def test_mouse_tracking_enabled(self, btn):
        assert btn.hasMouseTracking() is True


class TestElaDropDownButtonText:
    @pytest.mark.parametrize("text", ["操作", ""], ids=["non-empty", "empty"])
    def test_set_text_roundtrip(self, btn, text):
        btn.setText(text)
        assert btn.text() == text


class TestElaDropDownButtonIcon:
    def test_set_icon(self, btn):
        btn.setElaIcon(ElaIconType.IconName.Gear)
        assert btn.elaIcon() == ElaIconType.IconName.Gear

    def test_icon_default(self, btn):
        assert btn.elaIcon() == ElaIconType.IconName.None_


class TestElaDropDownButtonBorderRadius:
    def test_border_radius_default(self, btn):
        assert btn.borderRadius() == 6

    def test_set_border_radius(self, btn):
        btn.setBorderRadius(12)
        assert btn.borderRadius() == 12


class TestElaDropDownButtonMenu:
    def test_set_menu(self, make):
        btn = make(ElaDropDownButton)
        parent = make(QWidget)
        menu = make(ElaMenu, parent)

        btn.setMenu(menu)

        assert btn.menu() is menu

    def test_menu_default_none(self, btn):
        assert btn.menu() is None


class TestElaDropDownButtonEvents:
    @pytest.mark.parametrize(
        "attr", ["_is_hover", "_is_pressed"], ids=["hover", "pressed"]
    )
    def test_leave_resets_state(self, btn, attr):
        setattr(btn, attr, True)

        btn.leaveEvent(QEvent(QEvent.Type.Leave))

        assert getattr(btn, attr) is False

    def test_mouse_press_sets_pressed(self, btn):
        btn.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(QPoint(10, 10)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert btn._is_pressed is True


class TestElaDropDownButtonTheme:
    def test_on_theme_changed_updates_mode(self, btn):
        btn._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert btn._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaDropDownButtonAppearance:
    """透明底 + 无外框：基础态不画底，hover / press 才叠状态层。"""

    def test_base_state_is_transparent(self, btn):
        assert btn._state_layer().alpha() == 0

    def test_hover_and_press_layers(self, btn):
        btn._is_hover = True
        hover = btn._state_layer()
        btn._is_pressed = True
        press = btn._state_layer()
        assert hover.alpha() > 0
        assert press.alpha() > hover.alpha()

    def test_no_border_is_painted(self, btn, monkeypatch):
        """无外框（用户明确要求去掉）：状态层只画底、不传 border。"""
        calls: list[dict] = []
        monkeypatch.setattr(
            "pyqt6_ela_pro.ela_dropdown_button.paintRoundedCard",
            lambda painter, rect, **kwargs: calls.append(kwargs),
        )

        btn.resize(120, 30)
        btn.grab()

        assert calls, "paintEvent 没有被触发"
        assert all("border" not in kwargs for kwargs in calls)

    def test_disabled_suppresses_layer_and_grays_content(self, btn):
        btn._is_hover = True

        btn.setEnabled(False)

        assert btn._state_layer().alpha() == 0
        assert btn._content_color().name() == textDisabled(btn._theme_mode).name()

    def test_enabled_change_resets_hover_state(self, btn):
        btn._is_hover = True
        btn._is_pressed = True

        btn.setEnabled(False)

        assert btn._is_hover is False
        assert btn._is_pressed is False


class TestElaDropDownButtonDeleteLater:
    def test_delete_later_cleans_up(self, btn):
        btn.deleteLater()


class TestElaDropDownButtonMenuLifetime:
    """F13 回归：菜单生命周期边界（宿主先删菜单 / 显式清空）。

    原实现 `if self._menu: popup(...)` 对**已删除的 sip 包装器**调方法抛
    ``RuntimeError``，穿出 Qt 回调 = 0xC0000409 崩进程（子进程探针实测）。
    """

    @staticmethod
    def _release_at(widget, x: int, y: int) -> None:
        QApplication.sendEvent(
            widget,
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(QPoint(x, y)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    def test_release_with_deleted_menu_is_safe(self, make):
        btn = make(ElaDropDownButton)
        btn.resize(120, 30)
        menu = make(ElaMenu, btn)
        btn.setMenu(menu)
        sip.delete(menu)
        assert sip.isdeleted(menu)

        self._release_at(btn, 5, 5)  # 守卫放行（不再 popup），不得崩

        assert btn._is_pressed is False

    def test_release_with_live_menu_still_pops_up(self, make):
        btn = make(ElaDropDownButton)
        btn.resize(120, 30)
        menu = make(ElaMenu, btn)
        calls: list = []
        menu.popup = lambda *args: calls.append(args)  # type: ignore[method-assign]
        btn.setMenu(menu)

        self._release_at(btn, 5, 5)

        assert calls, "存活菜单必须照常弹出（守卫不能误伤）"

    def test_set_menu_none_clears_and_release_is_safe(self, make):
        btn = make(ElaDropDownButton)
        btn.resize(120, 30)
        menu = make(ElaMenu, btn)
        btn.setMenu(menu)

        btn.setMenu(None)

        assert btn.menu() is None
        self._release_at(btn, 5, 5)  # 无菜单点击 = 空操作，不崩
