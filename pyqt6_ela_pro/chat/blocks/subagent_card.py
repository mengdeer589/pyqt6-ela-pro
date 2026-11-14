"""子代理卡：父工具调用 + 嵌套子工具 + 结果。"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaThemeType

from ..._internal import is_deleted, safe_connect
from ..._styles import ColorText
from ..._theme import ElaStatusRoleType, statusColor
from ...ela_button import ElaButton
from .._pricing import formatCost
from .._theme import muted_color, text_color
from ..message import ElaChatToolCall, ElaChatToolStatusType
from ..renderers import toolRenderer
from ._helpers import SUBAGENT_TOOLS, formatDuration, toolSubtitleParts
from .collapsible import _CollapsibleBlock
from .tool_cards import ToolCallCard

#: 单次展开时创建的子工具卡数量（Win7 老机器上控制单帧成本）
_CHILD_PAGE_SIZE = 16


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
    """子代理父卡：头部显示任务 / 状态 / 统计，主体按需物化子工具。"""

    #: 子工具卡展开 / 收起（用于冒泡到消息的 ``toolToggled``）
    childToggled = pyqtSignal()

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
        self._child_order: list = []
        self._pending_children: dict = {}
        self._more_button = None
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(0)
        safe_connect(
            self._stats_timer,
            "timeout",
            self._sync_stats,
            "subagent.stats",
            receiver=self,
        )
        self._page_timer = QTimer(self)
        self._page_timer.setInterval(0)
        safe_connect(
            self._page_timer,
            "timeout",
            self._load_next_page,
            "subagent.page",
            receiver=self,
        )
        safe_connect(
            self,
            "toggled",
            self._on_open_changed,
            "subagent.open",
            receiver=self,
        )
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
    ) -> Optional[_CollapsibleBlock]:
        """登记子工具；父卡收起时不建控件，展开后按页物化。"""
        call_id = str(call.id or "")
        if not call_id:
            call_id = f"child-{len(self._child_order)}"
            call = replace(call, id=call_id)
        if call_id in self._child_cards or call_id in self._pending_children:
            return self._child_cards.get(call_id)
        self._child_order.append(call_id)
        self._pending_children[call_id] = (call, bool(defaultOpen))
        if self.isOpened():
            self._materialize_page()
        self._schedule_stats()
        return self._child_cards.get(call_id)

    def childCard(self, callId: str) -> Optional[_CollapsibleBlock]:
        """按 id 获取子工具卡；未物化的子调用会按需建卡（API 兼容入口）。"""
        key = str(callId or "")
        card = self._child_cards.get(key)
        if card is not None and not is_deleted(card):
            return card
        return self._materialize_child(key)

    def childCalls(self) -> list:
        """全部子工具调用快照（按登记顺序，包含尚未物化的子调用）。"""
        result = []
        for call_id in self._child_order:
            card = self._child_cards.get(call_id)
            if card is not None and not is_deleted(card):
                call = card.toolCall(call_id)
                if call is not None:
                    result.append(call)
            else:
                item = self._pending_children.get(call_id)
                if item is not None:
                    result.append(item[0])
        return result

    def toolCall(self, callId: Optional[str] = None) -> ElaChatToolCall:
        """获取父调用或指定子调用快照（不会因查询而物化子卡）。"""
        key = str(callId or "")
        if key:
            card = self._child_cards.get(key)
            if card is not None and not is_deleted(card):
                call = card.toolCall(key)
                if call is not None:
                    return call
            item = self._pending_children.get(key)
            if item is not None:
                return item[0]
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
        """结果更新入口（父调用或子调用都走这里；不物化未展开的子卡）。"""
        key = str(callId or "")
        card = self._child_cards.get(key)
        if card is not None and not is_deleted(card):
            card.updateResult(key, result, ok=ok, durationMs=durationMs)
            self._schedule_stats()
            return
        pending = self._pending_children.get(key)
        if pending is not None:
            call, default_open = pending
            status = ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error
            call = call.withResult(result, status).withTiming(
                call.started_at, durationMs
            )
            self._pending_children[key] = (call, default_open)
            self._schedule_stats()
            return
        self.setResult(result, ok=ok, durationMs=durationMs)

    def refreshStats(self) -> None:
        """刷新子工具数量 / 词元 / 成本摘要。"""
        self._schedule_stats()

    def setOpenedSilently(self, opened: bool) -> None:
        """恢复展开态时也补齐第一批子卡（不触发祖先布局链）。"""
        super().setOpenedSilently(opened)
        if opened:
            self._materialize_page()

    def _on_open_changed(self, checked: bool) -> None:
        if checked:
            self._materialize_page()
        else:
            self._page_timer.stop()

    def _materialize_page(self) -> None:
        """按页物化未展开的子工具，避免一个事件循环建出几百个卡。"""
        if not self.isOpened():
            return
        created = 0
        for call_id in self._child_order:
            if call_id in self._child_cards:
                continue
            if call_id not in self._pending_children:
                continue
            self._materialize_child(call_id)
            created += 1
            if created >= _CHILD_PAGE_SIZE:
                break
        self._sync_more_button()
        self._sync_stats()

    def _materialize_child(self, callId: str) -> Optional[_CollapsibleBlock]:
        key = str(callId or "")
        card = self._child_cards.get(key)
        if card is not None and not is_deleted(card):
            return card
        item = self._pending_children.pop(key, None)
        if item is None:
            return None
        call, default_open = item
        name = (call.name or "").lower()
        if name in SUBAGENT_TOOLS and toolRenderer(call.name) is None:
            card = SubagentCard(
                parent=self._children_container,
                tool_call=call,
                defaultOpen=default_open,
            )
            safe_connect(
                card,
                "childToggled",
                self.childToggled.emit,
                "subagent.nested_child_toggle",
                receiver=card,
            )
        else:
            card = ToolCallCard(
                parent=self._children_container,
                tool_call=call,
                defaultOpen=default_open,
            )
        card.setMessageId(self._message_id)
        index = (
            self._children_layout.indexOf(self._more_button)
            if self._more_button is not None
            else -1
        )
        if index < 0:
            self._children_layout.addWidget(card)
        else:
            self._children_layout.insertWidget(index, card)
        self._child_cards[key] = card
        safe_connect(
            card,
            "toggled",
            self._on_child_toggled,
            "subagent.child_toggle",
            receiver=card,
        )
        self._sync_more_button()
        return card

    def _on_child_toggled(self, _checked: bool = False) -> None:
        self.childToggled.emit()

    def _sync_more_button(self) -> None:
        remaining = len(self._pending_children)
        if remaining <= 0:
            self._page_timer.stop()
        if not self.isOpened() or remaining <= 0:
            if self._more_button is not None:
                self._more_button.hide()
            return
        if self._more_button is None:
            self._more_button = ElaButton(
                "显示更多",
                variant="text",
                size="small",
                parent=self._children_container,
            )
            safe_connect(
                self._more_button,
                "clicked",
                self._start_loading_all,
                "subagent.more",
                receiver=self._more_button,
            )
            self._children_layout.addWidget(self._more_button)
        loading = self._page_timer.isActive()
        self._more_button.setEnabled(not loading)
        self._more_button.setText(
            f"加载中… 剩余 {remaining} 个工具"
            if loading
            else f"显示其余 {remaining} 个工具"
        )
        self._more_button.show()

    def _start_loading_all(self) -> None:
        """把剩余子工具按 16 个一页交给事件循环，避免单帧建满全部控件。"""
        if self._pending_children and not self._page_timer.isActive():
            self._page_timer.start()
            self._sync_more_button()

    def _load_next_page(self) -> None:
        if not self.isOpened() or not self._pending_children:
            self._page_timer.stop()
            self._sync_more_button()
            self._sync_stats()
            return
        self._materialize_page()
        if not self._pending_children:
            self._page_timer.stop()
            self._sync_more_button()
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

    def _schedule_stats(self) -> None:
        if not self._stats_timer.isActive():
            self._stats_timer.start()

    def _sync_stats(self) -> None:
        if self._stats_timer.isActive():
            self._stats_timer.stop()
        metadata = self._call.metadata if isinstance(self._call.metadata, dict) else {}
        count = metadata.get("tool_calls", metadata.get("tools"))
        if not isinstance(count, (int, float)) or isinstance(count, bool):
            count = len(self._child_order)
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
