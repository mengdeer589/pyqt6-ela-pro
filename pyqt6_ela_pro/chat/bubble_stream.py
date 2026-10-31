"""气泡流式回合 / 状态机 / 底部行方法组。"""

from __future__ import annotations

from .._internal import is_deleted
from .bubble_shared import _STATUS_TEXTS


from ..ela_markdown_viewer import ElaMarkdownViewer
from .bubble_shared import _STREAMING_PLACEHOLDER

from .blocks import (
    CompactionSeparator,
)
from .message import (
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatToolStatusType,
)


class _BubbleStreamMixin:
    """方法组 mixin：状态由 ``ElaChatBubble.__init__`` 建立。"""

    def beginStream(self) -> None:
        """开始流式生成（仅助手消息；正文段在首次追加时按需创建）。

        先进入「排队中」（TTFT 阶段），收到首个输出后转「生成中」。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        self._status = ElaChatStatusType.Streaming
        self._stream_ended = False
        self._generation_started = False
        widget = self._part_widgets.get(self._current_text_id)
        if isinstance(widget, ElaMarkdownViewer):
            widget.setPlaceholderText(_STREAMING_PLACEHOLDER)
        self.setStatus(ElaChatStatusType.Streaming)

    def endStream(self, status: str = ElaChatStatusType.Done) -> None:
        """结束流式生成（仅助手消息）。"""
        if self._role != ElaChatRoleType.Assistant:
            return
        self._abortStream(status)
        self._stream_ended = True
        self._generation_started = True
        self._dock_step_stats_to_footer()
        self.setStatus(status)
        self.streamFinished.emit()

    def _abortStream(self, status: str = ElaChatStatusType.Stopped) -> None:
        """收尾仍在流式的分段（正文 / 思考 / 工具调用 / 工具分组 / 审批）。

        工具调用必须结算，否则留下永久转圈的忙碌环；未答复的审批同样作废。
        """
        self.endText()
        self.endReasoning()
        self._settle_open_tools(status)
        self._finish_tool_group()
        self.cancelPendingPermissions()

    def _settle_open_tools(self, status: str) -> None:
        """把仍处于 pending / running 的工具调用落到终态。

        错误回合落 ``Error``，其余（用户停止 / 消息被替换）落 ``Aborted``。
        以 part 数据为准遍历（分组卡没有单调用状态，part 始终是权威）。
        """
        settled = (
            ElaChatToolStatusType.Error
            if status == ElaChatStatusType.Error
            else ElaChatToolStatusType.Aborted
        )
        part_status = (
            ElaChatStatusType.Error
            if status == ElaChatStatusType.Error
            else ElaChatStatusType.Done
        )
        for part in self._parts:
            if part.kind != ElaChatPartKindType.Tool or part.tool_call is None:
                continue
            if part.tool_call.status in ElaChatToolStatusType.Settled:
                continue
            call = part.tool_call.withStatus(settled)
            self._replace_part(part.id, part.withStatus(part_status).withToolCall(call))
            card = self._tool_cards.get(part.id)
            if card is not None and hasattr(card, "setStatus"):
                card.setStatus(settled)
        for panel in self.toolPanels():
            self._sync_tool_panel(panel)
        # 通用清扫：回合结束后不允许残留 streaming 的 part
        for part in self._parts:
            if part.status == ElaChatStatusType.Streaming:
                self._replace_part(part.id, part.withStatus(part_status))
                if part.kind == ElaChatPartKindType.Compaction:
                    # 压缩卡状态只由 setCompactionStatus 驱动，不同步会停在「压缩中…」
                    widget = self._part_widgets.get(part.id)
                    if isinstance(widget, CompactionSeparator):
                        widget.setCompactionStatus(part_status)

    def isStreaming(self) -> bool:
        """是否正在流式生成。"""
        return self._status == ElaChatStatusType.Streaming

    def status(self) -> str:
        """获取消息状态（见 :class:`~pyqt6_ela_pro.chat.message.ElaChatStatusType`）。"""
        return self._status

    def setWaitingPlaceholderEnabled(self, on: bool) -> None:
        """设置等待首个 token（TTFT）期间是否显示骨架占位（默认开启）。"""
        self._waiting_placeholder_enabled = bool(on)
        self._sync_waiting_placeholder()

    def waitingPlaceholderEnabled(self) -> bool:
        """等待首个 token 期间是否显示骨架占位。"""
        return self._waiting_placeholder_enabled

    def _sync_waiting_placeholder(self) -> None:
        """按派生状态显隐等待骨架（骨架不是分段，``parts`` / 导出都看不到它）。"""
        wanted = (
            self._waiting_placeholder_enabled
            and self._role == ElaChatRoleType.Assistant
            and self._status == ElaChatStatusType.Streaming
            and not self._generation_started
            and not self._parts
        )
        shimmer = self._waiting_shimmer
        if not wanted:
            if shimmer is not None and not is_deleted(shimmer):
                shimmer.hide()
            return
        shimmer = self._ensure_waiting_shimmer()
        if shimmer is not None and shimmer.isHidden():
            shimmer.show()

    def setStatus(self, status: str) -> None:
        """设置消息状态（同步头部提示、底部行与用量徽标显隐）。

        非法值一律回落 ``Done``（直接写入会让状态机被静默污染）。``Queued``
        这类展示态不进 ``_status``，只由头部按 ``Streaming`` 派生。
        """
        self._status = (
            status if status in ElaChatStatusType.All else ElaChatStatusType.Done
        )
        self._meta.setInterrupted(self._status == ElaChatStatusType.Stopped)
        self._sync_header_status()
        self._sync_footer()
        if self._status != ElaChatStatusType.Streaming:
            # 流式期间徽标被收起（见 _apply_stats_mode），回合结束再按模式摆出来
            self._apply_stats_mode()
        self._sync_waiting_placeholder()

    def _sync_footer(self) -> None:
        """底部行（复制 / 重新生成 / 用量 / 耗时）只在回合结束（``!= Streaming``）后出现。"""
        if self._footer is None:
            return
        self._footer.setVisible(
            not self._parts_deferred and self._status != ElaChatStatusType.Streaming
        )

    def _sync_header_status(self) -> None:
        """按状态与「是否已收到首个输出」刷新头部提示。

        ``Streaming`` 分两阶段：等待首个输出（TTFT）显示 ``Queued``，收到输出后
        转 ``Streaming``；``Queued`` 只是展示态，不写入 ``_status``。
        """
        if getattr(self, "_pending_delivery", ""):
            suffix = " · 插话" if self._pending_delivery == "steer" else ""
            self._header.setStatusText(f"待发送{suffix}", ElaChatStatusType.Queued)
            return
        if self._status == ElaChatStatusType.Streaming and not self._generation_started:
            self._header.setStatusText(
                _STATUS_TEXTS[ElaChatStatusType.Queued], ElaChatStatusType.Queued
            )
            return
        self._header.setStatusText(_STATUS_TEXTS.get(self._status, ""), self._status)

    def _mark_generation_started(self) -> None:
        """收到首个模型输出：``排队中`` → ``生成中``（幂等，仅流式回合内生效）。"""
        if self._generation_started:
            return
        self._generation_started = True
        if self._status == ElaChatStatusType.Streaming:
            self._sync_header_status()
        self._sync_waiting_placeholder()
