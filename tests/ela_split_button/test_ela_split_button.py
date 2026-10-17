"""``ElaSplitButton`` 测试：初值 / 文本 / 图标 / 圆角 / 菜单 / 事件。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import ElaIconType, ElaMenu, ElaThemeType

from pyqt6_ela_pro._theme import textDisabled
from pyqt6_ela_pro.ela_split_button import ElaSplitButton


@pytest.fixture
def btn(make):
    """默认构造的 split button。"""
    return make(ElaSplitButton)


class TestElaSplitButtonInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_text", ""),
            ("_icon", ElaIconType.IconName.None_),
            ("_border_radius", 3),
            ("_dropdown_width", 30),
            ("_menu", None),
            ("_is_left_hovered", False),
            ("_is_right_hovered", False),
            ("_is_left_pressed", False),
            ("_is_right_pressed", False),
        ],
        ids=[
            "text",
            "icon",
            "border-radius",
            "dropdown-width",
            "menu",
            "left-hovered",
            "right-hovered",
            "left-pressed",
            "right-pressed",
        ],
    )
    def test_initialization_with_defaults(self, btn, attr, expected):
        assert getattr(btn, attr) == expected

    def test_initialization_with_text(self, make):
        assert make(ElaSplitButton, text="保存").text() == "保存"

    def test_initialization_with_icon(self, make):
        icon = ElaIconType.IconName.FloppyDisk
        assert make(ElaSplitButton, icon=icon).elaIcon() == icon

    def test_initialization_with_text_and_icon(self, make):
        icon = ElaIconType.IconName.FloppyDisk
        btn = make(ElaSplitButton, text="保存", icon=icon)
        assert btn.text() == "保存"
        assert btn.elaIcon() == icon

    def test_fixed_height(self, btn):
        """与按钮族一致（ElaPushButton V3.0 / ElaButton middle 都是 30）。"""
        assert btn.height() == 30

    def test_mouse_tracking_enabled(self, btn):
        assert btn.hasMouseTracking() is True

    def test_has_clicked_signal(self, btn):
        assert hasattr(btn, "clicked")
        assert callable(btn.clicked)


class TestElaSplitButtonText:
    @pytest.mark.parametrize("text", ["保存", ""], ids=["non-empty", "empty"])
    def test_set_text_roundtrip(self, btn, text):
        btn.setText(text)
        assert btn.text() == text


class TestElaSplitButtonIcon:
    def test_set_icon(self, btn):
        btn.setElaIcon(ElaIconType.IconName.FloppyDisk)
        assert btn.elaIcon() == ElaIconType.IconName.FloppyDisk

    def test_icon_default(self, btn):
        assert btn.elaIcon() == ElaIconType.IconName.None_


class TestElaSplitButtonBorderRadius:
    def test_border_radius_default(self, btn):
        assert btn.borderRadius() == 3

    def test_set_border_radius(self, btn):
        btn.setBorderRadius(12)
        assert btn.borderRadius() == 12


class TestElaSplitButtonMenu:
    def test_set_menu(self, make):
        btn = make(ElaSplitButton)
        parent = make(QWidget)
        menu = make(ElaMenu, parent)

        btn.setMenu(menu)

        assert btn.menu() is menu

    def test_menu_default_none(self, btn):
        assert btn.menu() is None


class TestElaSplitButtonLeaveEvent:
    @pytest.mark.parametrize(
        "attr",
        [
            "_is_left_hovered",
            "_is_right_hovered",
            "_is_left_pressed",
            "_is_right_pressed",
        ],
        ids=["left-hovered", "right-hovered", "left-pressed", "right-pressed"],
    )
    def test_leave_resets_state(self, btn, attr):
        setattr(btn, attr, True)

        btn.leaveEvent(QEvent(QEvent.Type.Leave))

        assert getattr(btn, attr) is False


class TestElaSplitButtonTheme:
    def test_on_theme_changed_updates_mode(self, btn):
        btn._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert btn._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaSplitButtonAppearance:
    """透明底 + 无外框：基础态不画底，hover / press 才叠状态层；只有两半之间的分隔线。"""

    def test_base_state_is_transparent(self, btn):
        assert btn._state_layer(pressed=False, hovered=False).alpha() == 0

    def test_hover_and_press_layers(self, btn):
        hover = btn._state_layer(pressed=False, hovered=True)
        press = btn._state_layer(pressed=True, hovered=True)
        assert hover.alpha() > 0
        assert press.alpha() > hover.alpha()

    def test_press_layer_without_hover(self, btn):
        """按下时鼠标可能已滑出半边，press 状态不依赖 hover 标记。"""
        assert btn._state_layer(pressed=True, hovered=False).alpha() > 0

    def test_divider_is_visible_and_dims_when_disabled(self, btn):
        """去掉外框后只剩两半之间的分隔线；禁用时跟着变淡。"""
        enabled_divider = btn._divider_color()
        assert enabled_divider.alpha() > 0

        btn.setEnabled(False)

        assert btn._divider_color().name() != enabled_divider.name()

    def test_disabled_suppresses_layer_and_grays_content(self, btn):
        btn._is_left_hovered = True
        btn._is_right_hovered = True

        btn.setEnabled(False)

        assert btn._state_layer(pressed=False, hovered=True).alpha() == 0
        assert btn._state_layer(pressed=True, hovered=True).alpha() == 0
        assert btn._content_color().name() == textDisabled(btn._theme_mode).name()

    def test_enabled_change_resets_halves(self, btn):
        btn._is_left_hovered = True
        btn._is_right_hovered = True
        btn._is_left_pressed = True
        btn._is_right_pressed = True

        btn.setEnabled(False)

        assert btn._is_left_hovered is False
        assert btn._is_right_hovered is False
        assert btn._is_left_pressed is False
        assert btn._is_right_pressed is False


class TestElaSplitButtonDeleteLater:
    def test_delete_later_cleans_up(self, btn):
        btn.deleteLater()
