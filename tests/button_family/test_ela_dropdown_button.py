"""``ElaDropDownButton`` 测试：构造接线 / 文本图标 / 菜单 / 事件 / 外观 / 菜单生命周期。"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaIconType, ElaMenu

from pyqt6_ela_pro._theme import textDisabled
from pyqt6_ela_pro.ela_dropdown_button import ElaDropDownButton


@pytest.fixture
def btn(make):
    """默认构造的下拉按钮。"""
    return make(ElaDropDownButton)


class TestElaDropDownButtonInit:
    def test_ctor_wiring(self, btn):
        """一次钉住构造期全部接线：内容初值 / 圆角 / 高度 / 悬停追踪。"""
        assert btn._text == ""
        assert btn._icon == ElaIconType.IconName.None_
        assert btn.elaIcon() == ElaIconType.IconName.None_
        assert btn.borderRadius() == 6
        assert btn.menu() is None
        assert btn._is_hover is False
        assert btn._is_pressed is False
        # 与按钮族一致（ElaPushButton V3.0 / ElaButton middle 都是 30）。
        assert btn.height() == 30
        assert btn.hasMouseTracking() is True

    def test_initialization_with_text_and_icon(self, make):
        btn = make(ElaDropDownButton, text="操作", icon=ElaIconType.IconName.Gear)
        assert btn.text() == "操作"
        assert btn.elaIcon() == ElaIconType.IconName.Gear


class TestElaDropDownButtonContent:
    @pytest.mark.parametrize("text", ["操作", ""], ids=["non-empty", "empty"])
    def test_text_roundtrip(self, btn, text):
        btn.setText(text)
        assert btn.text() == text

    def test_icon_roundtrip(self, btn):
        btn.setElaIcon(ElaIconType.IconName.Gear)
        assert btn.elaIcon() == ElaIconType.IconName.Gear

    def test_border_radius_roundtrip(self, btn):
        btn.setBorderRadius(12)
        assert btn.borderRadius() == 12


class TestElaDropDownButtonMenu:
    def test_menu_roundtrip(self, make):
        btn = make(ElaDropDownButton)
        menu = make(ElaMenu, make(QWidget))

        btn.setMenu(menu)

        assert btn.menu() is menu


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


class TestElaDropDownButtonAppearance:
    """透明底 + 无外框：基础态不画底，hover / press 才叠状态层。"""

    def test_state_layers(self, btn):
        assert btn._state_layer().alpha() == 0
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
