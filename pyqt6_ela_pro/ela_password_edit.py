"""
密码输入框组件，风格参考 ElaWidgetTools 的 ElaPasswordBox。

继承自 ElaLineEdit，支持密码可见切换。

用法::

    from pyqt6_ela_pro import ElaPasswordEdit

    pwd = ElaPasswordEdit(parent=self)
    pwd.setPlaceholderText("请输入密码")
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QLineEdit, QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaLineEdit, ElaIcon, ElaIconType

from ._internal import connect_theme_signal, disconnect_theme


class ElaPasswordEdit(ElaLineEdit):
    """密码输入框。

    带密码可见切换按钮，继承 ElaLineEdit 提供的主题自适应和焦点动画。

    :param parent: 父控件
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._is_password_visible = False
        self.setEchoMode(QLineEdit.EchoMode.Password)

        self._toggle_action = QAction(self)
        self.addAction(self._toggle_action, QLineEdit.ActionPosition.TrailingPosition)
        self._toggle_action.triggered.connect(self._on_toggle_visibility)

        self._update_eye_icon()
        connect_theme_signal(self, self._update_eye_icon)

    def deleteLater(self) -> None:
        """断开主题信号并清理资源。"""
        disconnect_theme(self)
        super().deleteLater()

    def setPasswordVisible(self, visible: bool) -> None:
        """设置密码是否明文可见。"""
        self._is_password_visible = visible
        self.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self._update_eye_icon()

    def isPasswordVisible(self) -> bool:
        """密码当前是否明文可见。"""
        return self._is_password_visible

    def _on_toggle_visibility(self, _checked: bool = False) -> None:
        self.setPasswordVisible(not self._is_password_visible)

    def _update_eye_icon(self, _mode=None) -> None:
        icon_name = (
            ElaIconType.IconName.EyeSlash
            if self._is_password_visible
            else ElaIconType.IconName.Eye
        )
        color = eTheme.getThemeColor(
            eTheme.getThemeMode(), ElaThemeType.ThemeColor.BasicText
        )
        icon = ElaIcon.getInstance().getElaIcon(icon_name, color)
        self._toggle_action.setIcon(icon)
