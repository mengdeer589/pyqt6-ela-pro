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
    """具名输入框。

    带有标题标签的输入框，标题显示在输入框**左侧**（占位式内边距，
    不是 ``placeholderText`` —— 输入后标题仍然留着）。
    支持主题适配，包含空闲、聚焦、错误三种状态。

    :param parent: 父控件
    :param title: 标题文字（默认空串 —— 没设标题的输入框不该在框里喊 "Untitled"）

    **参数顺序跟全库一致：``parent`` 在前。** 曾经写成
    ``(title="Untitled", parent=None)`` —— 全库唯一的例外，后果是
    ``ElaTagLineEdit(self)`` 会把父控件当成标题传给
    ``QFontMetrics.horizontalAdvance()`` 抛 ``TypeError``；而
    ``ElaTagLineEdit("用户名")`` 更糟：**不报错**，造出一个没有父控件的
    顶层窗口（控件会在桌面上飘着，析构时机也不对）。

    Example::

        edit = ElaTagLineEdit(parent=parent, title="用户名")
        edit.setText("admin")
        edit.notifyInvalidInput()   # 错误态；clearError() 撤销
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "",
    ) -> None:
        super().__init__(parent)

        self._title_text = title
        self._title_font_size = 13
        self._is_error = False

        # 与上游 ElaLineEdit（35）同高
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
        metrics = QFontMetrics(self.font())
        title_width = metrics.horizontalAdvance(self._title_text) + 20
        self.setTextMargins(title_width + 3, 0, 10, 0)

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
        metrics = QFontMetrics(self.font())
        title_width = metrics.horizontalAdvance(self._title_text) + 20
        title_height = self.height()

        title_rect = QRect(3, 0, title_width, title_height)

        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        option.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        title_font = QFont(self.font())
        title_font.setPixelSize(self._title_font_size)

        painter.save()
        painter.setFont(title_font)
        painter.setPen(self._getTitleColor())
        painter.drawText(
            QRectF(title_rect.adjusted(10, 0, -10, 0)), self._title_text, option
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
