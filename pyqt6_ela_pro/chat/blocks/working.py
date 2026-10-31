"""运行态活动行（正在探索… / 正在运行命令…）：呼吸状态点 + 一行弱化文字。

它不是进度条 —— agent 的进度无法量化，只回答「现在在干什么」。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget
from PyQt6ElaWidgetTools import eTheme

from ..._internal import _ThemeAwareMixin
from ..._styles import ColorText
from ..._theme import accent as accent_color, textMuted
from .header import _StatusDot

#: 活动行高度
WORKING_ROW_HEIGHT = 28
#: 活动行字号
WORKING_ROW_PIXEL_SIZE = 12


class ElaChatWorkingRow(_ThemeAwareMixin, QWidget):
    """一行「正在做什么」：呼吸点 + 弱化文本（可空）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._text = ""
        self.setFixedHeight(WORKING_ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        self._dot = _StatusDot(self)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(False)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label, 1)
        self.hide()
        self._apply_theme()

    # -- 内容 --------------------------------------------------------------

    def setText(self, text: str) -> None:
        """设置活动文案（空串 = 隐藏）。"""
        self._text = str(text or "")
        self._label.setText(self._text)
        self._label.setToolTip(self._text)
        self.setVisible(bool(self._text))
        self._dot.setActive(bool(self._text))
        self._elide_text()

    def text(self) -> str:
        """获取活动文案。"""
        return self._text

    def _elide_text(self) -> None:
        if not self._text:
            return
        width = max(80, self.width() - 24)
        metrics = QFontMetrics(self._label.font())
        self._label.setText(
            metrics.elidedText(self._text, Qt.TextElideMode.ElideRight, width)
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._elide_text()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        self._dot.setActive(bool(self._text))

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._dot.setActive(False)
        super().hideEvent(event)

    # -- 主题 --------------------------------------------------------------

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._dot.setColor(accent_color(mode))
        self._label.setTextColor(textMuted(mode))
        self._label.setTextPixelSize(WORKING_ROW_PIXEL_SIZE)

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


__all__ = ["ElaChatWorkingRow", "WORKING_ROW_HEIGHT", "WORKING_ROW_PIXEL_SIZE"]
