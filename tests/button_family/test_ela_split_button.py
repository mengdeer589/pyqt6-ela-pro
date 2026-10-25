"""``ElaSplitButton`` 测试：构造接线 / 文本图标 / 菜单 / 事件 / 外观 / 菜单生命周期。"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaIconType, ElaMenu

from pyqt6_ela_pro._theme import textDisabled
from pyqt6_ela_pro.ela_split_button import ElaSplitButton


@pytest.fixture
def btn(make):
    """默认构造的 split button。"""
    return make(ElaSplitButton)


class TestElaSplitButtonInit:
    def test_ctor_wiring(self, btn):
        """一次钉住构造期全部接线：内容初值 / 圆角 / 箭头宽度 / 高度 / 信号。"""
        assert btn._text == ""
        assert btn._icon == ElaIconType.IconName.None_
        assert btn.elaIcon() == ElaIconType.IconName.None_
        assert btn.borderRadius() == 3
        assert btn._dropdown_width == 30
        assert btn.menu() is None
        assert btn._is_left_hovered is False
        assert btn._is_right_hovered is False
        assert btn._is_left_pressed is False
        assert btn._is_right_pressed is False
        # 与按钮族一致（ElaPushButton V3.0 / ElaButton middle 都是 30）。
        assert btn.height() == 30
        assert btn.hasMouseTracking() is True
        assert callable(btn.clicked)

    def test_initialization_with_text_and_icon(self, make):
        icon = ElaIconType.IconName.FloppyDisk
        btn = make(ElaSplitButton, text="保存", icon=icon)
        assert btn.text() == "保存"
        assert btn.elaIcon() == icon


class TestElaSplitButtonContent:
    @pytest.mark.parametrize("text", ["保存", ""], ids=["non-empty", "empty"])
    def test_text_roundtrip(self, btn, text):
        btn.setText(text)
        assert btn.text() == text

    def test_icon_roundtrip(self, btn):
        btn.setElaIcon(ElaIconType.IconName.FloppyDisk)
        assert btn.elaIcon() == ElaIconType.IconName.FloppyDisk

    def test_border_radius_roundtrip(self, btn):
        btn.setBorderRadius(12)
        assert btn.borderRadius() == 12


class TestElaSplitButtonMenu:
    def test_menu_roundtrip(self, make):
        btn = make(ElaSplitButton)
        menu = make(ElaMenu, make(QWidget))

        btn.setMenu(menu)

        assert btn.menu() is menu


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


class TestElaSplitButtonAppearance:
    """透明底 + 无外框：基础态不画底，hover / press 才叠状态层；只有两半之间的分隔线。"""

    def test_state_layers(self, btn):
        assert btn._state_layer(pressed=False, hovered=False).alpha() == 0
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


class TestElaSplitButtonMenuLifetime:
    """F13 回归：菜单生命周期边界（宿主先删菜单 / 显式清空）。

    原实现 `if self._menu: self._menu.popup(pos)` 对已删除的 sip 包装器调方法
    抛 ``RuntimeError``，穿出 Qt 回调 = 0xC0000409 崩进程（子进程探针实测）。
    """

    @staticmethod
    def _click_arrow(widget, before_release=None) -> None:
        right_x = widget.width() - 5  # 右半（箭头区）
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(
                widget,
                QMouseEvent(
                    kind,
                    QPointF(QPoint(right_x, 5)),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )

    def test_arrow_click_with_deleted_menu_is_safe(self, make):
        btn = make(ElaSplitButton)
        btn.resize(160, 30)
        menu = make(ElaMenu, btn)
        btn.setMenu(menu)
        sip.delete(menu)
        assert sip.isdeleted(menu)

        self._click_arrow(btn)  # 守卫放行（不再 popup），不得崩

        assert btn._is_right_pressed is False

    def test_arrow_click_with_live_menu_still_pops_up(self, make):
        btn = make(ElaSplitButton)
        btn.resize(160, 30)
        menu = make(ElaMenu, btn)
        calls: list = []
        menu.popup = lambda *args: calls.append(args)  # type: ignore[method-assign]
        btn.setMenu(menu)

        self._click_arrow(btn)

        assert calls, "存活菜单必须照常弹出（守卫不能误伤）"

    def test_set_menu_none_clears_and_click_is_safe(self, make):
        btn = make(ElaSplitButton)
        btn.resize(160, 30)
        btn.setMenu(make(ElaMenu, btn))

        btn.setMenu(None)

        assert btn.menu() is None
        self._click_arrow(btn)  # 无菜单点击 = 空操作，不崩
