"""会话内搜索（命中快照 + 搜索条控件）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaLineEdit,
    eTheme,
)

from .._internal import _ThemeAwareMixin
from .._styles import ColorText
from .._theme import text as text_color, textMuted

#: 搜索条高度
SEARCH_BAR_HEIGHT = 30
#: 命中上限
SEARCH_HIT_LIMIT = 500
#: 输入防抖
SEARCH_DEBOUNCE_MS = 150


@dataclass(frozen=True)
class ElaChatSearchHit:
    """一个搜索命中。"""

    #: 消息 id
    message_id: int
    #: 分段 id（用户消息为空串）
    part_id: str
    #: 该分段内的第几个匹配（从 0 开始）
    occurrence: int
    #: 命中片段（用于预览 / 测试）
    snippet: str = ""
    #: 是否为用户消息
    user: bool = False


class ElaChatSearchBar(_ThemeAwareMixin, QWidget):
    """会话内搜索条：输入 + 计数 + 上一个 / 下一个 / 关闭。"""

    #: 查询变化（参数：查询文本）
    queryChanged = pyqtSignal(str)
    #: 请求下一个 / 上一个
    nextRequested = pyqtSignal()
    prevRequested = pyqtSignal()
    #: 请求关闭
    closed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._count = 0
        self._index = -1
        self.setFixedHeight(SEARCH_BAR_HEIGHT + 4)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        self._edit = ElaLineEdit(self)
        self._edit.setPlaceholderText("在对话中查找…")
        self._edit.setIsClearButtonEnable(True)
        self._edit.setFixedHeight(SEARCH_BAR_HEIGHT)
        self._edit.textChanged.connect(self._on_text_changed)
        self._edit.returnPressed.connect(self.nextRequested.emit)
        self._count_label = ColorText(self)
        self._count_label.setTextFormat(Qt.TextFormat.PlainText)
        self._prev = ElaIconButton(ElaIconType.IconName.ChevronUp, 12, 20, 20, self)
        self._next = ElaIconButton(ElaIconType.IconName.ChevronDown, 12, 20, 20, self)
        self._close = ElaIconButton(ElaIconType.IconName.Xmark, 12, 20, 20, self)
        for button in (self._prev, self._next, self._close):
            button.setBorderRadius(4)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._prev.setToolTip("上一个")
        self._next.setToolTip("下一个")
        self._close.setToolTip("关闭")
        self._prev.clicked.connect(self.prevRequested)
        self._next.clicked.connect(self.nextRequested)
        self._close.clicked.connect(self.closeBar)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._count_label)
        layout.addWidget(self._prev)
        layout.addWidget(self._next)
        layout.addWidget(self._close)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self._emit_query)
        self.hide()
        self._apply_theme()

    # -- 内容 --------------------------------------------------------------

    def query(self) -> str:
        """当前查询文本。"""
        return self._edit.text()

    def setQuery(self, text: str) -> None:
        """设置查询文本（不自动发信号）。"""
        self._edit.blockSignals(True)
        self._edit.setText(str(text or ""))
        self._edit.blockSignals(False)

    def setState(self, count: int, index: int) -> None:
        """更新命中数量与当前下标（从 0 开始，``-1`` 表示无）。"""
        self._count = max(0, int(count))
        self._index = int(index)
        if self._count <= 0:
            self._count_label.setText("无结果" if self._edit.text() else "")
        else:
            self._count_label.setText(f"{self._index + 1}/{self._count}")
        self._prev.setEnabled(self._count > 0)
        self._next.setEnabled(self._count > 0)

    def closeBar(self) -> None:
        """隐藏并清空。"""
        self._timer.stop()
        self._edit.clear()
        self.hide()
        self.closed.emit()

    def focusEditor(self) -> None:
        """聚焦输入框并全选。"""
        self._edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._edit.selectAll()

    # -- 事件 --------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.closeBar()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_text_changed(self, _text: str) -> None:
        self._timer.start()

    def _emit_query(self) -> None:
        self.queryChanged.emit(self._edit.text())

    # -- 主题 --------------------------------------------------------------

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._count_label.setTextColor(textMuted(mode))
        self._count_label.setTextPixelSize(11)
        palette = self._edit.palette()
        palette.setColor(QPalette.ColorRole.Text, text_color(mode))
        palette.setColor(QPalette.ColorRole.PlaceholderText, textMuted(mode))
        self._edit.setPalette(palette)
        for button in (self._prev, self._next, self._close):
            button.setLightIconColor(textMuted(mode))
            button.setDarkIconColor(textMuted(mode))

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


__all__ = [
    "ElaChatSearchBar",
    "ElaChatSearchHit",
    "SEARCH_DEBOUNCE_MS",
    "SEARCH_HIT_LIMIT",
]
