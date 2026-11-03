"""
具名输入框组件。

带有标题标签的输入框组件，支持主题适配、焦点状态和错误状态显示。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QFontMetrics, QTextOption, QFont
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaLineEdit

from ._internal import _ThemeAwareMixin


class ElaTagLineEdit(_ThemeAwareMixin, ElaLineEdit):
    """具名输入框（标题画在左侧内边距，不是 ``placeholderText``）。

    :param parent: 父控件
    :param title: 标题文字；空串则不画
    """

    #: 标题文字与输入文字之间的可见间距
    _TITLE_GAP = 8
    #: 标题绘制区左右内边距（标题起点与输入文字落在同一条 13px 基线）
    _TITLE_PAD_LEFT = 10
    _TITLE_PAD_RIGHT = 10

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "",
    ) -> None:
        super().__init__(parent)

        self._title_text = title
        self._title_font_size = 13
        self._is_error = False

        # 固定高度 35px
        self.setFixedHeight(35)
        self._updateMargins()

        self._textChangedSlot = self._onTextChanged  # 断连要同一对象（lambda / partial 必须存引用）
        self.textChanged.connect(self._textChangedSlot)

        self._theme_mode = eTheme.getThemeMode()

    def setTitle(self, title: str) -> None:
        self._title_text = title
        self._updateMargins()
        self.update()

    def title(self) -> str:
        return self._title_text

    def setTitleFontSize(self, size: int) -> None:
        self._title_font_size = size
        self._updateMargins()
        self.update()

    def notifyInvalidInput(self) -> None:
        """触发错误状态样式。"""
        self._is_error = True
        self.update()

    def clearError(self) -> None:
        """清除错误状态样式。"""
        self._is_error = False
        self.update()

    def _updateMargins(self) -> None:
        if not self._title_text:
            # 无标题时不留标题宽度空位
            self.setTextMargins(0, 0, 10, 0)
            return
        self.setTextMargins(self._titleTextWidth() + self._TITLE_GAP, 0, 10, 0)

    def _titleFont(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(self._title_font_size)
        return font

    def _titleTextWidth(self) -> int:
        """标题按标题字号量宽，不用输入框字号。"""
        return QFontMetrics(self._titleFont()).horizontalAdvance(self._title_text)

    def _onTextChanged(self, _text: str) -> None:
        self.update()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    def _getTitleColor(self) -> QColor:
        current_theme = eTheme.getThemeMode()
        if self._is_error:
            return eTheme.getThemeColor(
                current_theme, ElaThemeType.ThemeColor.StatusDanger
            )
        return eTheme.getThemeColor(current_theme, ElaThemeType.ThemeColor.BasicText)

    def _getBorderColor(self) -> QColor:
        current_theme = eTheme.getThemeMode()
        if self._is_error:
            return eTheme.getThemeColor(
                current_theme, ElaThemeType.ThemeColor.StatusDanger
            )
        if self.hasFocus():
            return eTheme.getThemeColor(
                current_theme, ElaThemeType.ThemeColor.PrimaryNormal
            )
        return eTheme.getThemeColor(
            current_theme, ElaThemeType.ThemeColor.BasicBaseLine
        )

    def _drawTitle(self, painter: QPainter) -> None:
        if not self._title_text:
            return
        title_height = self.height()
        text_width = self._titleTextWidth()
        title_rect = QRect(
            3,
            0,
            self._TITLE_PAD_LEFT + text_width + self._TITLE_PAD_RIGHT,
            title_height,
        )

        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        option.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        painter.save()
        painter.setFont(self._titleFont())
        painter.setPen(self._getTitleColor())
        painter.drawText(
            QRectF(
                title_rect.adjusted(
                    self._TITLE_PAD_LEFT, 0, -self._TITLE_PAD_RIGHT, 0
                )
            ),
            self._title_text,
            option,
        )
        painter.restore()

    def _drawBorder(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._getBorderColor())

        br = self.getBorderRadius()
        error_rect = QRectF(br / 2, self.height() - 2.5, self.width() - br, 2.5)
        painter.drawRoundedRect(error_rect, 2, 2)

    def deleteLater(self) -> None:
        slot = getattr(self, '_textChangedSlot', None)
        if slot is not None:
            try:
                self.textChanged.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
            self._textChangedSlot = None  # 幂等：deleteLater 可能被调用两次
        self._theme_cleanup()
        super().deleteLater()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        if self._is_error:
            self._drawBorder(painter)
        self._drawTitle(painter)
