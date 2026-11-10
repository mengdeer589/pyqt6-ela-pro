"""子代理卡：父工具调用 + 嵌套子工具 + 结果。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaThemeType

from ..._internal import is_deleted
from ..._styles import ColorText
from ..._theme import ElaStatusRoleType, statusColor
from .._pricing import formatCost
from .._theme import muted_color, text_color
from ..message import ElaChatToolCall, ElaChatToolStatusType
from ..renderers import toolRenderer
from ._helpers import SUBAGENT_TOOLS, formatDuration, toolSubtitleParts
from .collapsible import _CollapsibleBlock
from .tool_cards import ToolCallCard


def _format_count(value) -> str:
    try:
        number = max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return "0"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}k"
    return str(number)


class SubagentCard(_CollapsibleBlock):
    """子代理父卡：头部显示任务 / 状态 / 统计，主体放子工具与最终结果。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        tool_call: Optional[ElaChatToolCall] = None,
        defaultOpen: bool = False,
    ) -> None:
        call = tool_call or ElaChatToolCall(id="", name="subagent")
        super().__init__(
            title=call.title or "子代理",
            opened=bool(defaultOpen),
            parent=parent,
            surface=False,
        )
        self.setCardMargins(0, 0, 0, 0)
        self._call = call
        self._message_id = 0
        self._child_cards: dict = {}
        self._subtitle_label = ColorText(self)
        self._subtitle_label.setWordWrap(False)
        self._subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
        self._stats_label = ColorText(self)
        self._stats_label.setWordWrap(False)
        self._stats_label.setTextFormat(Qt.TextFormat.PlainText)
        insert_at = self.headerLayout().count() - 1
        self.insertHeaderWidget(insert_at, self._subtitle_label)
        self.insertHeaderWidget(insert_at + 1, self._stats_label)
        self._children_container = QWidget(self)
        self._children_layout = QVBoxLayout(self._children_container)
        self._children_layout.setContentsMargins(0, 0, 0, 0)
        self._children_layout.setSpacing(2)
        self.bodyLayout().addWidget(self._children_container)
        self._result_caption = ColorText("结果", self)
        self._result_label = ColorText(self)
        self._result_label.setTextFormat(Qt.TextFormat.PlainText)
        self._result_label.setWordWrap(True)
        self._result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.bodyLayout().addWidget(self._result_caption)
        self.bodyLayout().addWidget(self._result_label)
        self._sync_header()
        self._sync_result()
        self._apply_theme()

    def setMessageId(self, messageId: int) -> None:
        """设置所属消息 id，并同步给所有子卡。"""
        self._message_id = int(messageId or 0)
        for card in self._child_cards.values():
            if not is_deleted(card):
                card.setMessageId(self._message_id)

    def addChild(
        self,
        call: ElaChatToolCall,
        *,
        defaultOpen: bool = False,
    ) -> _CollapsibleBlock:
        """追加一个子工具卡（body 仍按首次展开懒建；嵌套子代理仍是 SubagentCard）。"""
        key = (call.name or "").lower()
        if key in SUBAGENT_TOOLS and toolRenderer(call.name) is None:
            card = SubagentCard(
                parent=self._children_container,
                tool_call=call,
                defaultOpen=bool(defaultOpen),
            )
        else:
            card = ToolCallCard(
                parent=self._children_container,
                tool_call=call,
                defaultOpen=bool(defaultOpen),
            )
        card.setMessageId(self._message_id)
        self._children_layout.addWidget(card)
        self._child_cards[call.id] = card
        self._sync_stats()
        self._sync_header()
        return card

    def childCard(self, callId: str) -> Optional[_CollapsibleBlock]:
        """按 id 获取子工具卡（普通工具或嵌套子代理）。"""
        card = self._child_cards.get(str(callId or ""))
        return card if not is_deleted(card) else None

    def childCalls(self) -> list:
        """全部子工具调用快照。"""
        return [
            card.toolCall(callId)
            for callId, card in self._child_cards.items()
            if not is_deleted(card)
        ]

    def toolCall(self, callId: Optional[str] = None) -> ElaChatToolCall:
        """获取父调用或指定子调用快照。"""
        if callId:
            card = self.childCard(callId)
            if card is not None:
                return card.toolCall(callId)
        return self._call

    def setArguments(self, arguments: str) -> None:
        """更新父调用参数。"""
        self._call = self._call.withArguments(arguments)
        self._sync_header()

    def arguments(self) -> str:
        """获取父调用参数。"""
        return self._call.arguments

    def result(self) -> str:
        """获取父调用结果。"""
        return self._call.result

    def status(self) -> str:
        """获取父调用状态。"""
        return self._call.status

    def setStatus(self, status: str, durationMs: float = 0.0) -> None:
        """更新父调用状态。"""
        self._call = self._call.withStatus(status)
        if durationMs:
            self._call = self._call.withTiming(self._call.started_at, durationMs)
        self._sync_header()

    def setResult(
        self,
        result: str,
        ok: bool = True,
        durationMs: float = 0.0,
    ) -> None:
        """更新父调用结果。"""
        status = ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error
        self._call = self._call.withResult(result, status)
        if durationMs:
            self._call = self._call.withTiming(self._call.started_at, durationMs)
        self._sync_header()
        self._sync_result()
        if not ok:
            self.setOpened(True)

    def updateResult(
        self,
        callId: str,
        result: str,
        ok: bool = True,
        durationMs: float = 0.0,
    ) -> None:
        """结果更新入口（父调用或子调用都走这里）。"""
        card = self.childCard(callId)
        if card is not None:
            card.updateResult(callId, result, ok=ok, durationMs=durationMs)
            self._sync_stats()
            return
        self.setResult(result, ok=ok, durationMs=durationMs)

    def refreshStats(self) -> None:
        """刷新子工具数量 / 词元 / 成本摘要。"""
        self._sync_stats()

    def _sync_header(self) -> None:
        call = self._call
        running = call.status in (
            ElaChatToolStatusType.Pending,
            ElaChatToolStatusType.Running,
        )
        self.setTitle(call.title or "子代理")
        subtitle = ""
        try:
            _key, subtitle = toolSubtitleParts(call.arguments)
        except Exception:
            subtitle = ""
        subtitle = " ".join(str(subtitle or "").split())
        if len(subtitle) > 80:
            subtitle = subtitle[:79] + "…"
        self._subtitle_label.setText(subtitle)
        self._subtitle_label.setVisible(bool(subtitle))
        self._sync_stats()
        self.setBusy(running)
        self.setExpandable(True)

    def _sync_stats(self) -> None:
        metadata = self._call.metadata if isinstance(self._call.metadata, dict) else {}
        count = metadata.get("tool_calls", metadata.get("tools"))
        if not isinstance(count, (int, float)) or isinstance(count, bool):
            count = len(self._child_cards)
        tokens = metadata.get("tokens", metadata.get("total_tokens"))
        cost = metadata.get("cost_usd", metadata.get("cost"))
        parts = [f"{_format_count(count)} 个工具"]
        if isinstance(tokens, (int, float)) and not isinstance(tokens, bool):
            parts.append(f"{_format_count(tokens)} 词元")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            parts.append(formatCost(float(cost)))
        duration = formatDuration(self._call.duration_ms)
        if duration:
            parts.append(duration)
        self._stats_label.setText(
            " · ".join(parts) if self._child_cards or count else ""
        )
        self._stats_label.setVisible(bool(self._stats_label.text()))

    def _sync_result(self) -> None:
        text = self._call.result or ""
        self._result_caption.setVisible(bool(text))
        self._result_label.setText(text)
        self._result_label.setVisible(bool(text))

    def _apply_theme(self) -> None:
        super()._apply_theme()
        if not hasattr(self, "_subtitle_label"):
            return
        mode = self._theme_mode
        self._subtitle_label.setTextColor(muted_color(mode, 0.6))
        self._subtitle_label.setTextPixelSize(12)
        self._stats_label.setTextColor(muted_color(mode, 0.45))
        self._stats_label.setTextPixelSize(11)
        self._result_caption.setTextColor(muted_color(mode, 0.5))
        self._result_caption.setTextPixelSize(11)
        self._result_label.setTextColor(muted_color(mode, 0.75))
        self._result_label.setTextPixelSize(12)
        if self._call.status == ElaChatToolStatusType.Error:
            self._title_label.setTextColor(statusColor(mode, ElaStatusRoleType.Error))
        else:
            self._title_label.setTextColor(text_color(mode))
        self._title_label.setTextPixelSize(13)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        self._apply_child_theme()

    def _apply_child_theme(self) -> None:
        for card in self._child_cards.values():
            if not is_deleted(card):
                card._apply_theme()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()


__all__ = ["SubagentCard"]
