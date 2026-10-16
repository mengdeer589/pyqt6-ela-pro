"""
步骤条组件，风格参考 ElaWidgetTools 的 ElaSteps。

支持设置步骤标题、前进/后退切换，水平 / 竖直两种排布。
步骤数由标题列表自动决定。

用法::

    steps = ElaSteps(parent=self)
    steps.step_titles = ["步骤一", "步骤二", "步骤三"]
    steps.setOrientation("vertical")
    steps.currentStepChanged.connect(lambda v: print(f"当前步骤: {v}"))
"""

from __future__ import annotations

from typing import Literal, Optional

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from .widget_base import ElaThemeWidget

ElaStepsOrientation = Literal["horizontal", "vertical"]

#: 水平排布几何：标题在圆下方一行
_H_HEIGHT = 70
_H_CIRCLE_Y = 8
_H_TITLE_Y = 42
_H_MARGIN = 50
_CIRCLE_D = 28

#: 竖直排布几何：圆列在左，标题在右、与圆垂直居中
_V_PAD = 14
_V_PITCH = 56
_V_LINE_X = 22
_V_TITLE_X = 48


class ElaSteps(ElaThemeWidget):
    """步骤条组件。"""

    currentStepChanged = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._current_step = 0
        self._step_titles: list[str] = []
        self._orientation: ElaStepsOrientation = "horizontal"

        self.setObjectName("ElaSteps")
        self._icon_font = QFont("ElaAwesome")
        self._sync_geometry()

    # ── Derived step count ───────────────────────────────

    @property
    def step_count(self) -> int:
        """由 ``step_titles`` 派生的当前步骤数（最少为 1）。"""
        return max(1, len(self._step_titles))

    # ── Public API ───────────────────────────────────────

    def setOrientation(self, orientation: ElaStepsOrientation) -> None:
        """切换排布方向（``"horizontal"`` / ``"vertical"``，非法值抛 ``ValueError``）。

        竖直模式高度随步骤数变化，切换时同步几何。
        """
        if orientation not in ("horizontal", "vertical"):
            raise ValueError(f"Invalid orientation: {orientation!r}")
        self._orientation = orientation
        self._sync_geometry()
        self.update()

    def orientation(self) -> str:
        return self._orientation

    def setCurrentStep(self, n: int) -> None:
        """值会被夹到 ``0`` ~ ``step_count - 1``，仅变化时发信号。"""
        old = self._current_step
        self._current_step = max(0, min(n, self.step_count - 1))
        if self._current_step != old:
            self.currentStepChanged.emit(self._current_step)
        self.update()

    def currentStep(self) -> int:
        return self._current_step

    @property
    def step_titles(self) -> list[str]:
        """标题列表（返回副本）。"""
        return list(self._step_titles)

    @step_titles.setter
    def step_titles(self, titles: list[str]) -> None:
        """步骤数由此决定；当前步骤超出新范围时自动修正。"""
        self._step_titles = list(titles)
        if self._current_step >= self.step_count:
            self._current_step = max(0, self.step_count - 1)
        self._sync_geometry()
        self.update()

    def next(self) -> None:
        """前进到下一步。已在最后一步时无效果。"""
        if self._current_step < self.step_count - 1:
            self._current_step += 1
            self.currentStepChanged.emit(self._current_step)
            self.update()

    def previous(self) -> None:
        """后退到上一步。已在第一步时无效果。"""
        if self._current_step > 0:
            self._current_step -= 1
            self.currentStepChanged.emit(self._current_step)
            self.update()

    # ── Internal ─────────────────────────────────────────

    def _sync_geometry(self) -> None:
        """按当前方向定固定高度（水平恒定 70；竖直随步骤数增长）。"""
        if self._orientation == "vertical":
            height = _V_PAD * 2 + _CIRCLE_D + (self.step_count - 1) * _V_PITCH
        else:
            height = _H_HEIGHT
        self.setFixedHeight(height)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── Paint ────────────────────────────────────────────

    def _theme_colors(self) -> tuple:
        mode = self._theme_mode
        return (
            eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PrimaryNormal),
            eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase),
            eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBorder),
            eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicDetailsText),
            eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText),
        )

    def _draw_step_circle(
        self, painter: QPainter, index: int, rect: QRectF, colors: tuple
    ) -> None:
        """绘制单个步骤圆（完成打勾 / 当前数字 / 待办数字）。"""
        primary, base, border, details_text, _ = colors
        if index < self._current_step:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(primary)
            painter.drawEllipse(rect)
            self._icon_font.setPixelSize(14)
            painter.setFont(self._icon_font)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, chr(0xEA6C))
            return

        number_font = self.font()
        number_font.setPixelSize(14)
        number_font.setBold(True)
        painter.setFont(number_font)
        if index == self._current_step:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(primary)
            painter.drawEllipse(rect)
            painter.setPen(Qt.GlobalColor.white)
        else:
            painter.setPen(QPen(border, 1))
            painter.setBrush(base)
            painter.drawEllipse(rect)
            painter.setPen(details_text)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(index + 1))

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        colors = self._theme_colors()
        title_font = self.font()
        title_font.setPixelSize(13)

        if self._orientation == "vertical":
            self._paint_vertical(painter, colors, title_font)
        else:
            self._paint_horizontal(painter, colors, title_font)

    def _paint_horizontal(
        self, painter: QPainter, colors: tuple, title_font: QFont
    ) -> None:
        primary, _, border, _, text_color = colors
        w = self.width()
        circle_r = _CIRCLE_D // 2
        line_center_y = _H_CIRCLE_Y + circle_r
        usable = w - _H_MARGIN * 2
        spacing = usable / (self.step_count - 1) if self.step_count > 1 else 0

        for i in range(self.step_count):
            cx = _H_MARGIN + i * spacing if self.step_count > 1 else w / 2.0

            # 连接线
            if i < self.step_count - 1:
                nx = _H_MARGIN + (i + 1) * spacing
                painter.setPen(QPen(primary if i < self._current_step else border, 2))
                painter.drawLine(
                    QPointF(cx + circle_r, line_center_y),
                    QPointF(nx - circle_r, line_center_y),
                )

            rect = QRectF(cx - circle_r, _H_CIRCLE_Y, _CIRCLE_D, _CIRCLE_D)
            self._draw_step_circle(painter, i, rect, colors)

            if i < len(self._step_titles):
                painter.setFont(title_font)
                painter.setPen(text_color)
                painter.drawText(
                    QRectF(cx - 60, _H_TITLE_Y, 120, 20),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    self._step_titles[i],
                )

    def _paint_vertical(
        self, painter: QPainter, colors: tuple, title_font: QFont
    ) -> None:
        primary, _, border, _, text_color = colors
        circle_r = _CIRCLE_D // 2
        title_fm = QFontMetrics(title_font)
        avail = max(0, self.width() - _V_TITLE_X - 12)

        for i in range(self.step_count):
            cy = _V_PAD + circle_r + i * _V_PITCH

            # 连接线
            if i < self.step_count - 1:
                ny = _V_PAD + circle_r + (i + 1) * _V_PITCH
                painter.setPen(QPen(primary if i < self._current_step else border, 2))
                painter.drawLine(
                    QPointF(_V_LINE_X, cy + circle_r),
                    QPointF(_V_LINE_X, ny - circle_r),
                )

            rect = QRectF(_V_LINE_X - circle_r, cy - circle_r, _CIRCLE_D, _CIRCLE_D)
            self._draw_step_circle(painter, i, rect, colors)

            if i < len(self._step_titles):
                text = title_fm.elidedText(
                    self._step_titles[i], Qt.TextElideMode.ElideRight, avail
                )
                painter.setFont(title_font)
                painter.setPen(text_color)
                painter.drawText(
                    QRectF(
                        _V_TITLE_X, cy - title_fm.height() / 2, avail, title_fm.height()
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    text,
                )
