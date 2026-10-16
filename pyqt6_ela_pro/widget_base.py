"""
主题感知基类组件。

提供一个 ``QWidget`` 子类，通过监听 ``eTheme.themeModeChanged`` 信号
自动适应应用程序的当前主题模式（亮色 / 暗色）。
"""

from __future__ import annotations

from typing import Optional, Literal

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QGridLayout
from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaMessageBar, ElaMessageBarType

from ._internal import _ThemeAwareMixin


class ElaThemeWidget(_ThemeAwareMixin, QWidget):
    """自动适应主题变化的 ``QWidget`` 基类。

    子类应调用 ``super().__init__(parent)`` 以确保主题连接被建立。

    :param parent: 父级 widget，为 ``None`` 时表示顶级窗口。

    Example::

        class MyPanel(ElaThemeWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ElaThemeWidget")
        self._theme_mode = eTheme.getThemeMode()
        self._update_bg_color(self._theme_mode)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._update_bg_color(mode)

    def _update_bg_color(self, mode: ElaThemeType.ThemeMode) -> None:
        """按主题模式更新 widget 的背景调色板。"""
        bg_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, bg_color)
        self.setPalette(palette)

    def createLayout(
        self,
        layoutType: Literal["h", "v", "g"] = "h",
        parent: QWidget | None = None,
    ) -> QHBoxLayout | QVBoxLayout | QGridLayout:
        """创建布局（``"h"`` / ``"v"`` / ``"g"``），边距与间距均为 0。"""
        if parent is None:
            parent = self
        if layoutType == "h":
            lay = QHBoxLayout(parent)
        elif layoutType == "g":
            lay = QGridLayout(parent)
        else:
            lay = QVBoxLayout(parent)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        return lay

    def alert(
        self,
        message: str,
        level: Literal["error", "warning", "information", "success"] = "information",
        title: str = "提示",
        duration: int = 3000,
        position: Literal[
            "Top",
            "Left",
            "Bottom",
            "Right",
            "TopRight",
            "TopLeft",
            "BottomRight",
            "BottomLeft",
        ] = "TopRight",
        parent: Optional[QWidget] = None,
    ) -> None:
        """显示提示消息条（``level`` 取 ``error`` / ``warning`` / ``information`` / ``success``，
        非法值抛 ``ValueError``）。
        """
        if level not in ("error", "warning", "information", "success"):
            raise ValueError(f"Invalid alert level: {level!r}")
        func = getattr(ElaMessageBar, level)
        position_policy = getattr(ElaMessageBarType.PositionPolicy, position)
        if parent is None:
            parent = self
        func(position_policy, title, message, duration, parent)
