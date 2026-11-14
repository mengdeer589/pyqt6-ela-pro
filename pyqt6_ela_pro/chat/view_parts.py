"""聊天视图的轻量内部控件（内容容器 / 空态 / 回到底部 / 骨架占位）。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPalette
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import ElaIconType, ElaThemeType, eTheme

from .._internal import safe_connect
from .._styles import ColorText
from ..ela_button import ElaButton
from ..widget_base import ElaThemeWidget
from ._theme import muted_color, text_color

#: 「回到底部」浮动按钮尺寸（宽、高）与箭头字号
JUMP_BUTTON_WIDTH = 32
JUMP_BUTTON_HEIGHT = 28
JUMP_ICON_SIZE = 14


class ChatContent(ElaThemeWidget):
    """消息区内容容器。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self._min_height_cache: Optional[int] = None
        self._apply_theme()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def event(self, event) -> bool:  # noqa: N802 (Qt 命名)
        # 不清缓存会让 QScrollArea 按旧最小高度压缩子控件（卡片内部出滚动条）。
        if event.type() == QEvent.Type.LayoutRequest:
            self._min_height_cache = None
        return super().event(event)

    def minimumSizeHint(self):  # noqa: N802 (Qt 命名)
        """高度不小于内容布局的最小高度（避免滚动区把消息挤扁导致抖动）。"""
        hint = super().minimumSizeHint()
        if self.layout() is not None:
            if self._min_height_cache is None:
                self._min_height_cache = self.layout().minimumSize().height()
            hint.setHeight(self._min_height_cache)
        hint.setWidth(0)
        return hint

    def _apply_theme(self) -> None:
        color = eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicPress
        )
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, color)
        palette.setColor(QPalette.ColorRole.Base, color)
        self.setPalette(palette)
        self.update()


class NestedScrollGuard(QObject):
    """嵌套滚动区到达边界时吞掉滚轮事件，避免外层脱离贴底。"""

    def __init__(self, area: QAbstractScrollArea, parent=None) -> None:
        super().__init__(parent or area)
        self._area = area

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        if event.type() == QEvent.Type.Wheel:
            bar = self._area.verticalScrollBar()
            if bar is not None and bar.isVisible():
                delta = event.angleDelta().y()
                if delta < 0 and bar.value() >= bar.maximum():
                    return True
                if delta > 0 and bar.value() <= bar.minimum():
                    return True
        return super().eventFilter(obj, event)


class EmptyState(ElaThemeWidget):
    """空态：标题 + 副标题 + 建议按钮列表。"""

    suggestionClicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = "开始新的对话"
        self._subtitle = "输入问题，或从下面的建议开始。"
        self._suggestions: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 40, 16, 24)
        layout.setSpacing(8)
        layout.addStretch(1)

        self._title_label = ColorText(self)
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._subtitle_label = ColorText(self)
        self._subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle_label.setWordWrap(True)
        layout.addWidget(self._subtitle_label)

        self._suggestions_box = QVBoxLayout()
        self._suggestions_box.setContentsMargins(0, 12, 0, 0)
        self._suggestions_box.setSpacing(8)
        layout.addLayout(self._suggestions_box)
        layout.addStretch(2)

        self._apply_theme()

    def setTitle(self, text: str) -> None:
        """设置空态标题。"""
        self._title = text or ""
        self._title_label.setText(self._title)

    def title(self) -> str:
        """获取空态标题。"""
        return self._title

    def setSubtitle(self, text: str) -> None:
        """设置空态副标题。"""
        self._subtitle = text or ""
        self._subtitle_label.setText(self._subtitle)

    def subtitle(self) -> str:
        """获取空态副标题。"""
        return self._subtitle

    def setSuggestions(self, suggestions: Optional[list]) -> None:
        """设置建议按钮列表（点击发出 ``suggestionClicked``）。"""
        while self._suggestions_box.count():
            item = self._suggestions_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._suggestions = [str(s) for s in (suggestions or []) if str(s).strip()]
        for text in self._suggestions:
            button = ElaButton(text, variant="outlined", parent=self)
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            safe_connect(
                button,
                "clicked",
                lambda _checked=False, value=text: self.suggestionClicked.emit(value),
                "view_parts.suggestion",
                receiver=button,
            )
            self._suggestions_box.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._suggestions_box.setEnabled(bool(self._suggestions))

    def suggestions(self) -> list:
        """获取建议列表。"""
        return list(self._suggestions)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._title_label.setTextColor(text_color(mode))
        self._title_label.setTextPixelSize(19)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        self._subtitle_label.setTextColor(muted_color(mode, 0.5))
        self._subtitle_label.setTextPixelSize(13)


class JumpToBottomButton(ElaButton):
    """「回到底部」浮动按钮：ElaButton 实心强调色 + 箭头。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            "",
            ElaIconType.IconName.ArrowDown,
            JUMP_ICON_SIZE,
            variant="solid",
            color="primary",
            size="middle",
            parent=parent,
        )
        self.setFixedSize(JUMP_BUTTON_WIDTH, JUMP_BUTTON_HEIGHT)
        self.setBorderRadius(8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("回到底部")


class DeferredPlaceholder(QWidget):
    """未物化消息的轻量骨架（不建子控件，只画几条灰条）。"""

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            color = QColor(self.palette().color(QPalette.ColorRole.WindowText))
            color.setAlpha(26)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            left = 16.0
            width = max(40.0, self.width() - 32.0)
            bar_height = 10.0
            gap = 38.0
            fractions = (0.55, 0.85, 0.7, 0.4)
            top = 14.0 + max(
                0, int((event.rect().top() - 14) // (bar_height + gap))
            ) * (bar_height + gap)
            index = int((top - 14) // (bar_height + gap))
            bottom = min(float(self.height()), event.rect().bottom() + bar_height + gap)
            while top < bottom:
                painter.drawRoundedRect(
                    QRectF(
                        left,
                        top,
                        width * fractions[index % len(fractions)],
                        bar_height,
                    ),
                    4.0,
                    4.0,
                )
                index += 1
                top += bar_height + gap
        finally:
            painter.end()
