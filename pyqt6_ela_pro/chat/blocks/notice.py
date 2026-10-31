"""时间线通知行（模型 / agent / 目录切换、中断、指令更新、重启）。

对齐 opencode 的 ``TimelineSeparator``：左右各一条 1px 细线、中间一行弱化
文本，高度固定 30px。它是**分隔**不是卡片 —— 通知回答的是「这一轮为什么
换了上下文」，不需要展开、不需要图标、不需要动作。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget
from PyQt6ElaWidgetTools import eTheme

from ..._internal import _ThemeAwareMixin
from ..._styles import ColorText
from ..._theme import border as border_color, textMuted

#: 通知行高度
NOTICE_HEIGHT = 30
#: 正文 / 副值字号
NOTICE_PIXEL_SIZE = 12


class _Line(QWidget):
    """1px 水平分隔线（主题色，随通知行一起换肤）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = QColor()
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setColor(self, color: QColor) -> None:
        """设置线色。"""
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._color)


class ElaChatNotice(_ThemeAwareMixin, QWidget):
    """时间线通知行（细线 + 居中弱化文本 + 可选副值）。"""

    def __init__(
        self,
        noticeType: str = "",
        text: str = "",
        detail: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._notice_type = str(noticeType or "")
        self.setFixedHeight(NOTICE_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._left_line = _Line(self)
        self._right_line = _Line(self)
        texts = QWidget(self)
        text_layout = QHBoxLayout(texts)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        self._text_label = ColorText(texts)
        self._text_label.setTextFormat(Qt.TextFormat.PlainText)
        self._text_label.setWordWrap(False)
        self._detail_label = ColorText(texts)
        self._detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_label.setWordWrap(False)
        self._sep_label = ColorText("·", texts)
        self._sep_label.setWordWrap(False)
        text_layout.addWidget(self._text_label)
        text_layout.addWidget(self._sep_label)
        text_layout.addWidget(self._detail_label)
        layout.addWidget(self._left_line, 1)
        layout.addWidget(texts, 0)
        layout.addWidget(self._right_line, 1)

        self.setNotice(noticeType, text, detail)
        self._apply_theme()

    # -- 内容 --------------------------------------------------------------

    def setNotice(self, noticeType: str, text: str, detail: str = "") -> None:
        """替换通知类型 / 主文案 / 副值。"""
        self._notice_type = str(noticeType or "")
        self._text_label.setText(str(text or ""))
        self._detail_label.setText(str(detail or ""))
        self._sep_label.setVisible(bool(text) and bool(detail))
        self._text_label.setVisible(bool(text))
        self._detail_label.setVisible(bool(detail))
        self.setVisible(bool(text or detail))

    def noticeType(self) -> str:
        """获取通知类型（``ElaChatNoticeType`` 取值）。"""
        return self._notice_type

    def text(self) -> str:
        """获取主文案。"""
        return self._text_label.text()

    def detail(self) -> str:
        """获取副值。"""
        return self._detail_label.text()

    # -- 主题 --------------------------------------------------------------

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        muted = textMuted(mode)
        line = border_color(mode)
        self._left_line.setColor(line)
        self._right_line.setColor(line)
        self._text_label.setTextColor(muted)
        self._text_label.setTextPixelSize(NOTICE_PIXEL_SIZE)
        self._detail_label.setTextColor(muted)
        self._detail_label.setTextPixelSize(NOTICE_PIXEL_SIZE)
        self._sep_label.setTextColor(muted)
        self._sep_label.setTextPixelSize(NOTICE_PIXEL_SIZE)

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


__all__ = ["ElaChatNotice", "NOTICE_HEIGHT", "NOTICE_PIXEL_SIZE"]
