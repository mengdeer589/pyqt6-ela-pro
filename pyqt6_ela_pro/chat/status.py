"""聊天状态栏组件（``pyqt6_ela_pro.chat``）。

:class:`ElaChatStatusBar` 是一条宿主状态栏：左侧弱化信息（模型 / 服务地址
等），右侧状态文本（支持 ``info`` / ``busy`` / ``success`` / ``error``
四档语义配色），可选 ``busy`` 时在状态前显示 ``ElaProgressRing``。

用法::

    bar = ElaChatStatusBar(parent)
    bar.setInfo("Spark-X2.5-4B-FP8 @ 127.0.0.1:8000/v1")
    bar.setStatus("生成中…", level="busy")
    bar.setStatus("完成", level="success")
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaProgressRing, ElaThemeType

from .._styles import ColorText
from .._theme import ElaStatusRoleType, statusColor
from ..widget_base import ElaThemeWidget
from ._theme import accent_color, blend, muted_color, text_color

#: 状态语义档位
STATUS_LEVELS = ("info", "busy", "success", "error")


class ElaChatStatusBar(ElaThemeWidget):
    """聊天状态栏（左侧信息 + 右侧状态，语义配色）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._info_text = ""
        self._status_text = ""
        self._level = "info"
        self._busy = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 2, 12, 4)
        layout.setSpacing(6)

        self._ring = ElaProgressRing(self)
        self._ring.setFixedSize(14, 14)
        self._ring.setIsTransparent(True)
        self._ring.setBusyingWidth(2)
        self._ring.hide()

        self._info_label = ColorText(self)
        self._info_label.setWordWrap(False)
        self._status_label = ColorText(self)
        self._status_label.setWordWrap(False)
        # 信息 / 状态都是外部数据（模型名、服务地址、后端报错），按纯文本渲染
        self._info_label.setTextFormat(Qt.TextFormat.PlainText)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)

        layout.addWidget(self._ring)
        layout.addWidget(self._info_label)
        layout.addStretch(1)
        layout.addWidget(self._status_label)

        self._apply_theme()
        self._sync_visibility()

    # -- 内容 --------------------------------------------------------------

    def setInfo(self, text: str) -> None:
        """设置左侧信息文本（空则隐藏）。"""
        self._info_text = text or ""
        self._sync_visibility()

    def info(self) -> str:
        """获取左侧信息文本。"""
        return self._info_text

    def setStatus(self, text: str, level: str = "info") -> None:
        """设置右侧状态文本与语义档位（见 ``STATUS_LEVELS``）。"""
        self._status_text = text or ""
        self._level = level if level in STATUS_LEVELS else "info"
        self._apply_theme()
        self._sync_visibility()

    def status(self) -> str:
        """获取右侧状态文本。"""
        return self._status_text

    def level(self) -> str:
        """获取当前状态语义档位。"""
        return self._level

    def setBusy(self, on: bool) -> None:
        """显示 / 隐藏运行指示（``ElaProgressRing``）。"""
        self._busy = bool(on)
        if self._busy:
            self._ring.setIsBusying(True)
        self._sync_visibility()

    def isBusy(self) -> bool:
        """是否处于运行指示状态。"""
        return self._busy

    # -- 内部 --------------------------------------------------------------

    def _sync_visibility(self) -> None:
        self._info_label.setText(self._info_text)
        self._info_label.setVisible(bool(self._info_text))
        self._status_label.setText(self._status_text)
        self._status_label.setVisible(bool(self._status_text))
        self._ring.setVisible(self._busy)
        if not self._busy:
            self._ring.setIsBusying(False)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._info_label.setTextColor(muted_color(mode, 0.5))
        self._info_label.setTextPixelSize(12)
        if self._level == "busy":
            color = accent_color(mode)
        elif self._level == "success":
            color = blend(text_color(mode), statusColor(mode, ElaStatusRoleType.Success), 0.35)
        elif self._level == "error":
            color = blend(text_color(mode), statusColor(mode, ElaStatusRoleType.Error), 0.45)
        else:
            color = muted_color(mode, 0.65)
        self._status_label.setTextColor(color)
        self._status_label.setTextPixelSize(12)
