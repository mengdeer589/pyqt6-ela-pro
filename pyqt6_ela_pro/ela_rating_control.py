"""
星级评分组件，风格参考 ElaWidgetTools 的 ElaRatingControl。

支持鼠标悬停预览、点击评分、只读模式，支持半星评分。

用法::

    rating = ElaRatingControl(parent=self)
    rating.ratingChanged.connect(lambda v: print(f"评分: {v}"))
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal, QEvent
from PyQt6.QtGui import QPainter, QPaintEvent, QMouseEvent, QFont
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaIconType

from .widget_base import ElaThemeWidget


class ElaRatingControl(ElaThemeWidget):
    """星级评分组件，支持半星。"""

    ratingChanged = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._max_rating = 5
        self._rating: float = 0.0
        self._star_size = 24
        self._spacing = 4
        self._is_read_only = False
        self._hovered_star: float = -1.0

        self.setObjectName("ElaRatingControl")
        self.setMouseTracking(True)
        self.setFixedHeight(self._star_size + 4)
        self._icon_font = QFont("ElaAwesome")

    def setMaxRating(self, n: int) -> None:
        self._max_rating = n
        # 收紧上限时必须重新夹取，否则 rating() 会大于 maxRating()：
        # 值与界面（只画 n 颗星）不一致。
        clamped = max(0.0, min(float(self._max_rating), self._rating))
        if clamped != self._rating:
            self._rating = clamped
            self.ratingChanged.emit(self._rating)
        self.updateGeometry()
        self.update()

    def maxRating(self) -> int:
        return self._max_rating

    def setRating(self, n: float) -> None:
        """四舍五入到 0.5 的倍数；仅在值变化时发 ``ratingChanged``。"""
        n = max(0.0, min(float(self._max_rating), n))
        n = round(n * 2) / 2
        if self._rating == n:
            return
        self._rating = n
        self.ratingChanged.emit(n)
        self.update()

    def rating(self) -> float:
        return self._rating

    def setStarSize(self, size: int) -> None:
        self._star_size = size
        self.setFixedHeight(size + 4)
        self.updateGeometry()
        self.update()

    def starSize(self) -> int:
        return self._star_size

    def setSpacing(self, spacing: int) -> None:
        self._spacing = spacing
        self.updateGeometry()
        self.update()

    def spacing(self) -> int:
        return self._spacing

    def setReadOnly(self, ro: bool) -> None:
        """只读模式下不可交互。"""
        self._is_read_only = ro

    def isReadOnly(self) -> bool:
        return self._is_read_only

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    def _starAt(self, pos) -> float:
        """根据位置计算星级（1~max，支持 0.5 粒度）；不在星区时返回 -1。"""
        unit = self._star_size + self._spacing
        if unit <= 0 or pos.x() < 0:
            return -1.0
        star_idx = int(pos.x() // unit)
        if star_idx >= self._max_rating:
            return -1.0
        rel_x = pos.x() - star_idx * unit
        return star_idx + (0.5 if rel_x < unit / 2 else 1.0)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_read_only:
            super().mouseMoveEvent(event)
            return
        h = self._starAt(event.position().toPoint())
        if self._hovered_star != h:
            self._hovered_star = h
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._is_read_only and event.button() == Qt.MouseButton.LeftButton:
            star = self._starAt(event.position().toPoint())
            if star > 0:
                self.setRating(star)
        super().mousePressEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered_star = -1.0
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._icon_font.setPixelSize(self._star_size - 4)
        painter.setFont(self._icon_font)

        effective = self._rating
        if not self._is_read_only and self._hovered_star > 0:
            effective = self._hovered_star

        star_char = chr(ElaIconType.IconName.Star.value)
        primary = eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.PrimaryNormal
        )
        empty = eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicBorderDeep
        )

        for i in range(self._max_rating):
            x = i * (self._star_size + self._spacing)
            r = QRect(x, 2, self._star_size, self._star_size)

            if i < int(effective):
                painter.setPen(primary)
                painter.drawText(r, Qt.AlignmentFlag.AlignCenter, star_char)
            elif i == int(effective) and effective - i >= 0.5:
                painter.save()
                painter.setClipRect(QRect(x, 2, self._star_size // 2, self._star_size))
                painter.setPen(primary)
                painter.drawText(r, Qt.AlignmentFlag.AlignCenter, star_char)
                painter.restore()
                painter.save()
                painter.setClipRect(
                    QRect(
                        x + self._star_size // 2,
                        2,
                        self._star_size // 2,
                        self._star_size,
                    )
                )
                painter.setPen(empty)
                painter.drawText(r, Qt.AlignmentFlag.AlignCenter, star_char)
                painter.restore()
            else:
                painter.setPen(empty)
                painter.drawText(r, Qt.AlignmentFlag.AlignCenter, star_char)

    def sizeHint(self) -> QSize:
        w = self._max_rating * (self._star_size + self._spacing) - self._spacing
        return QSize(w, self._star_size + 4)
