"""
进度显示按钮组件。

继承自 ElaPushButton，支持显示进度条，进度由外部控制。
"""

from __future__ import annotations

from typing import Optional
import warnings

from PyQt6.QtCore import pyqtSignal, QPointF, QRect, QRectF, QSize
from PyQt6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QLinearGradient,
    QPainterPath,
    QPaintEvent,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import (
    eTheme,
    ElaThemeType,
    ElaPushButton,
    ElaIcon,
    ElaIconType,
)

from ._internal import _draw_button_content, _ThemeAwareMixin
from ._styles import coerceElaIcon
from .ela_button import _FACE_INSET


class ElaProgressButton(_ThemeAwareMixin, ElaPushButton):
    """进度显示按钮。

    继承自 ElaPushButton，支持显示进度条。
    进度由外部通过 setProgress() 控制。

    :param text: 按钮文本
    :param getProgressColor: 进度条颜色，为 None 时使用主题色
    :param parent: 父控件

    Example::

        button = ElaProgressButton(text="下载", parent=parent)
        button.setProgress(50)  # 显示50%进度
        button.setProgress(100)  # 完成
    """

    progressChanged = pyqtSignal(int)

    def __init__(
        self,
        text: str = "",
        getProgressColor: Optional[QColor] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setText(text)

        self._border_radius = 3
        self._icon_name: Optional[ElaIconType.IconName] = None
        self._icon_size = 16
        self._progress = 0.0
        self._custom_progress_color = getProgressColor is not None
        self._progress_color = (
            getProgressColor if self._custom_progress_color else QColor()
        )
        self._theme_mode = eTheme.getThemeMode()
        # 与上游 ElaPushButton V3.0（控件高 30）和 ElaButton middle 同高
        self.setFixedHeight(30)

        self._onThemeChanged(self._theme_mode)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        if not self._custom_progress_color:
            self._progress_color = eTheme.getThemeColor(
                mode, ElaThemeType.ThemeColor.PrimaryNormal
            )
        self.update()

    def setBorderRadius(self, radius: int) -> None:
        self._border_radius = radius
        self.update()

    def setElaIcon(self, icon, iconSize: int = 16) -> None:
        """设置 ElaAwesome 图标（``ElaIconType.IconName`` 或其整数值；``None`` 清除）。"""
        self._icon_name = None if icon is None else coerceElaIcon(icon)
        self._icon_size = iconSize
        self.setIconSize(QSize(iconSize, iconSize))
        self.update()

    def setProgressColor(self, color: QColor) -> None:
        self._custom_progress_color = True
        self._progress_color = color
        self.update()

    def progressColor(self) -> QColor:
        return self._progress_color

    def setProgress(self, percent: int) -> None:
        """设置进度百分比（0-100，越界会打警告并夹取）。"""
        if percent < 0 or percent > 100:
            warnings.warn(
                f"ElaProgressButton.setProgress({percent}) out of range [0, 100]，已夹取",
                RuntimeWarning,
                stacklevel=2,
            )
        percent = max(0, min(100, percent))
        self._progress = percent / 100.0
        self.progressChanged.emit(percent)
        self.update()

    def progress(self) -> int:
        return int(self._progress * 100)

    def resetProgress(self) -> None:
        """重置进度为0。"""
        self.setProgress(0)

    def _getCurrentBgColor(self) -> QColor:
        mode = self._theme_mode
        if not self.isEnabled():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicDisable)
        if self.isDown():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)
        if self.underMouse():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicHover)
        return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase)

    def _getCurrentTextColor(self) -> QColor:
        mode = self._theme_mode
        if not self.isEnabled():
            return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicTextDisable)
        return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)

    def _getBorderColor(self) -> QColor:
        return eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicBaseLine
        )

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        face_inset = _FACE_INSET
        rect = QRect(
            face_inset,
            face_inset,
            self.width() - 2 * face_inset,
            self.height() - 2 * face_inset,
        )

        bg_color = self._getCurrentBgColor()
        text_color = self._getCurrentTextColor()
        border_color = self._getBorderColor()

        # Background + border (same pattern as ElaThemeToolButton)
        painter.setPen(border_color)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, self._border_radius, self._border_radius)

        # Progress overlay
        if self._progress > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), self._border_radius, self._border_radius)
            painter.save()
            painter.setClipPath(path)

            if self._progress < 1.0:
                p = self._progress
                gradient = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.topRight()))
                gradient.setColorAt(0, self._progress_color)
                gradient.setColorAt(p, self._progress_color)
                gradient.setColorAt(min(p + 0.001, 1.0), QColor(0, 0, 0, 0))
                gradient.setColorAt(1, QColor(0, 0, 0, 0))
                painter.fillRect(rect, gradient)
            else:
                painter.fillRect(rect, self._progress_color)

            painter.restore()

        # Icon + text (same pattern as ElaThemeToolButton)
        def _icon_getter(icon_name, color):
            # 绘制链兜底：取图失败只丢图标，绝不让异常穿出 paintEvent
            try:
                return ElaIcon.getInstance().getElaIcon(
                    coerceElaIcon(icon_name), color
                )
            except Exception:
                return QIcon()

        _draw_button_content(
            painter,
            self.text(),
            self._icon_name,
            self._icon_size,
            face_inset,
            self.width(),
            self.height(),
            text_color,
            _icon_getter,
        )
