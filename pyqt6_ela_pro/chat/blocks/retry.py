"""自动重试卡（第 N 次重试 + 倒计时）。

与 ``ErrorCard`` 的区别：错误卡是**落定结果**（失败后由用户点重试），重试卡是
**在途状态**（后端正在按退避策略重试）。两者视觉同级、语义相反，所以卡面共用
一套材质但分成两个控件。

组件只显示 + 发信号，**不自己重发**：重试由宿主 / binder 驱动。
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaScrollPageArea,
    eTheme,
)

from ..._internal import _ThemeAwareMixin
from ..._styles import ColorText
from ..._theme import (
    ElaStatusRoleType,
    blend,
    statusColor,
    text as text_color,
    textMuted,
)
from ...ela_button import ElaButton


class ElaChatRetryCard(_ThemeAwareMixin, ElaScrollPageArea):
    """自动重试卡：错误摘要 + 第 N 次 + 倒计时 + 立即重试 / 取消。"""

    #: 用户点击「立即重试」
    retryRequested = pyqtSignal()
    #: 用户点击「取消」
    cancelRequested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._attempt = 0
        self._message = ""
        self._next_at = 0.0
        self._rail_color = QColor(0, 0, 0, 0)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.setBorderRadius(8)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 8, 10, 8)
        layout.setSpacing(8)

        self._rail = QWidget(self)
        self._rail.setFixedWidth(2)
        layout.addWidget(self._rail)

        self._icon = ElaIconButton(
            ElaIconType.IconName.TriangleExclamation, 14, 18, 18, self
        )
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        self._message_label = ColorText(self)
        self._message_label.setTextFormat(Qt.TextFormat.PlainText)
        self._message_label.setWordWrap(False)
        self._info_label = ColorText(self)
        self._info_label.setTextFormat(Qt.TextFormat.PlainText)
        self._info_label.setWordWrap(False)
        texts.addWidget(self._message_label)
        texts.addWidget(self._info_label)
        layout.addLayout(texts, 1)

        self._retry_button = ElaButton(
            "立即重试", variant="text", size="small", parent=self
        )
        self._retry_button.clicked.connect(self.retryRequested)
        self._cancel_button = ElaIconButton(
            ElaIconType.IconName.Xmark, 12, 18, 18, self
        )
        self._cancel_button.setBorderRadius(4)
        self._cancel_button.setToolTip("取消重试")
        self._cancel_button.clicked.connect(self.cancelRequested)
        layout.addWidget(self._retry_button, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(self._cancel_button, 0, Qt.AlignmentFlag.AlignBottom)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self.hide()
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def setRetry(self, attempt: int, message: str, nextAt: float) -> None:
        """设置重试状态（``nextAt`` 为 epoch 毫秒；``0`` 表示无倒计时）。"""
        self._attempt = max(1, int(attempt or 1))
        self._message = str(message or "")
        self._next_at = float(nextAt or 0.0)
        self._message_label.setToolTip(self._message)
        self._sync_text()
        self.show()
        if self._next_at > 0:
            self._timer.start()
        else:
            self._timer.stop()

    def clear(self) -> None:
        """清空并隐藏。"""
        self._timer.stop()
        self._attempt = 0
        self._message = ""
        self._next_at = 0.0
        self._message_label.clear()
        self._message_label.setToolTip("")
        self._info_label.clear()
        self.hide()

    def retryState(self) -> tuple:
        """获取 ``(attempt, message, nextAt)`` 快照。"""
        return (self._attempt, self._message, self._next_at)

    def isActive(self) -> bool:
        """是否正在显示重试状态。"""
        return self.isVisible() and self._attempt > 0

    # -- 内部 --------------------------------------------------------------

    def _remaining_seconds(self) -> int:
        if self._next_at <= 0:
            return 0
        return max(0, int(math.ceil((self._next_at - time.time() * 1000.0) / 1000.0)))

    def _sync_text(self) -> None:
        remaining = self._remaining_seconds()
        if remaining > 0:
            self._info_label.setText(f"第 {self._attempt} 次重试 · {remaining}s 后")
        else:
            self._info_label.setText(f"第 {self._attempt} 次重试 · 正在重试…")
        self._elide_message()

    def _elide_message(self) -> None:
        width = max(80, self.width() - 190)
        metrics = QFontMetrics(self._message_label.font())
        self._message_label.setText(
            metrics.elidedText(self._message, Qt.TextElideMode.ElideRight, width)
        )

    def _tick(self) -> None:
        if self._next_at > 0 and self._remaining_seconds() <= 0:
            self._next_at = 0.0
            self._timer.stop()
        self._sync_text()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._elide_message()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if self._next_at > 0 and not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self._timer.stop()
        super().hideEvent(event)

    # -- 主题 --------------------------------------------------------------

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        danger = statusColor(mode, ElaStatusRoleType.Error)
        self._rail_color = blend(text_color(mode), danger, 0.55)
        self._message_label.setTextColor(text_color(mode))
        self._message_label.setTextPixelSize(12)
        self._info_label.setTextColor(textMuted(mode))
        self._info_label.setTextPixelSize(11)
        self._icon.setLightIconColor(danger)
        self._icon.setDarkIconColor(danger)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().paintEvent(event)
        # 左侧语义竖条（与 ErrorCard 同一套语言）
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 6, 0, -6)
        painter.fillRect(rect.left(), rect.top(), 2, rect.height(), self._rail_color)

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


__all__ = ["ElaChatRetryCard"]
