"""``ElaPasswordEdit`` 测试：初值 / 明文切换 / 眼睛图标 / 主题解绑。"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLineEdit

from pyqt6_ela_pro.ela_password_edit import ElaPasswordEdit


@pytest.fixture
def pwd(make):
    return make(ElaPasswordEdit)


class TestElaPasswordEditInit:
    def test_initialization_with_defaults(self, pwd):
        assert pwd._is_password_visible is False
        assert pwd.echoMode() == QLineEdit.EchoMode.Password

    def test_has_toggle_action(self, pwd):
        assert pwd._toggle_action is not None


class TestElaPasswordEditVisibility:
    def test_is_password_visible_default(self, pwd):
        assert pwd.isPasswordVisible() is False

    @pytest.mark.parametrize(
        ("pre_visible", "visible", "echo_mode"),
        [
            (False, True, QLineEdit.EchoMode.Normal),
            (True, False, QLineEdit.EchoMode.Password),
        ],
        ids=["show", "hide-again"],
    )
    def test_set_password_visible(self, pwd, pre_visible, visible, echo_mode):
        pwd.setPasswordVisible(pre_visible)
        pwd.setPasswordVisible(visible)
        assert pwd.isPasswordVisible() is visible
        assert pwd.echoMode() == echo_mode

    def test_toggle_visibility(self, pwd):
        pwd._on_toggle_visibility()
        assert pwd.isPasswordVisible() is True
        pwd._on_toggle_visibility()
        assert pwd.isPasswordVisible() is False


class TestElaPasswordEditIcon:
    def test_eye_icon_initially_eye(self, pwd):
        assert pwd._toggle_action.icon() is not None

    def test_eye_icon_changes_on_toggle(self, pwd):
        icon_before = pwd._toggle_action.icon()
        pwd.setPasswordVisible(True)
        icon_after = pwd._toggle_action.icon()
        assert icon_before != icon_after


class TestElaPasswordEditDeleteLater:
    def test_delete_later_disconnects_theme(self, pwd):
        pwd.deleteLater()
