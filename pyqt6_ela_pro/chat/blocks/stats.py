"""用量徽标。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


from dataclasses import replace
from typing import Optional

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaThemeType,
)

from ..._styles import ColorText
from ...tooltips import ElaToolTipPositionType, remove_tooltip, set_tooltip
from ...widget_base import ElaThemeWidget
from .._theme import (
    muted_color,
)
from ..message import (
    ElaChatStats,
)


class StatsBadge(ElaThemeWidget):
    """底部层用量行（单行 mono：``↑128 ↓96 · 总计 224 · 缓存 64`` + 悬停明细）。

    数值由气泡按展示模式注入：默认 ``"footer"`` 模式为整轮汇总
    （各步求和），``"steps"`` 模式为单个步骤的服务端原值。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._stats: Optional[ElaChatStats] = None
        self._message_duration_ms = 0.0
        self._tooltip_text = ""
        self._tooltip_bound_text = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addStretch(1)
        self._label = ColorText(self)
        self._label.setWordWrap(False)
        self._label.hide()
        layout.addWidget(self._label)
        self.hide()

    def setStats(self, stats: Optional[ElaChatStats]) -> None:
        """更新用量统计（``None`` 或全零则隐藏徽标）。"""
        self._setStats(stats, deferShow=False)

    def _setStats(
        self, stats: Optional[ElaChatStats], *, deferShow: bool = False
    ) -> None:
        """``setStats`` 的内部实现；历史批量回放时只填数据、不显示。"""
        self._stats = stats
        if stats is None or not (
            stats.total_tokens or stats.prompt_tokens or stats.completion_tokens
        ):
            self._apply_tooltip()
            self.hide()
            return
        parts = [
            f"↑{stats.prompt_tokens}",
            f"↓{stats.completion_tokens}",
            f"总计 {stats.total_tokens}",
        ]
        if stats.cache_read_tokens:
            parts.append(f"缓存读 {stats.cache_read_tokens}")
        if stats.cache_write_tokens:
            parts.append(f"缓存写 {stats.cache_write_tokens}")
        self._label.setText("  ·  ".join(parts))
        if deferShow:
            # 最终显隐由 _apply_stats_mode 决定：footer 模式只有最后一个可见，
            # 回放期把 500 个徽标都 show 出来纯属浪费（bug #17）。
            self._apply_theme()
            return
        self._label.show()
        self._apply_tooltip()
        self._apply_theme()
        self.show()

    def setMessageDuration(self, durationMs: float) -> None:
        """设置消息级端到端耗时（合并进悬浮提示，与首字延时相邻显示）。"""
        self._message_duration_ms = float(durationMs or 0.0)
        self._apply_tooltip()

    def _apply_tooltip(self) -> None:
        """刷新悬浮提示（库内 ``ElaToolTip``）：首字 / 端到端耗时 / 词元速率 / 缓存。"""
        stats = self._stats
        durationLabel = "耗时"
        if stats is not None and self._message_duration_ms:
            stats = replace(stats, duration_ms=self._message_duration_ms)
            durationLabel = "端到端"
        text = stats.tooltip(durationLabel) if stats is not None else ""
        if text == self._tooltip_text:
            return
        self._tooltip_text = text
        self._label.setToolTip(text)
        # 隐藏徽标不建 ElaToolTip：footer 模式下大部分步骤徽标永远不显示，
        # 每个都建一个提示框纯浪费（bug #17）。显示时 showEvent 补建。
        if self.isVisible():
            self._bind_tooltip()

    def _bind_tooltip(self) -> None:
        """按当前文本绑定 / 更新提示框（只在可见时调用）。"""
        text = self._tooltip_text
        if text:
            set_tooltip(self._label, text, ElaToolTipPositionType.Top)
        else:
            remove_tooltip(self._label)
        self._tooltip_bound_text = text

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if self._tooltip_bound_text != self._tooltip_text:
            self._bind_tooltip()

    def stats(self) -> Optional[ElaChatStats]:
        """获取当前用量统计。"""
        return self._stats

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        if self._stats is None:
            return
        self._label.setTextColor(muted_color(self._theme_mode, 0.7))
        self._label.setTextPixelSize(11)
