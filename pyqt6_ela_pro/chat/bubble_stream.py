"""气泡流式回合 / 状态机 / 底部行方法组。"""

from __future__ import annotations

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

        先进入「排队中」（等待模型首个输出，即 TTFT 阶段）；收到首个正文 /
        思考分片或工具调用后自动转「生成中」（见 :meth:`_mark_generation_started`）。
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
        """收尾仍在流式的分段（正文 / 思考 / 工具调用 / 工具分组）。

        供 :meth:`endStream` 与错误路径（:meth:`setError`）复用：结束当前
        正文段、关闭内联思考查看器的流式光标、结算所有未完成的工具调用，
        并把上下文工具分组卡从「正在探索」收为「已探索」。

        工具调用必须一并结算：回合结束后它们永远不会再收到结果，不结算就
        会留下永久转圈的忙碌环（对齐 opencode ``failUnsettledTools``）。

        未答复的**审批**同样要作废：回合都结束了，那次请求不可能再有回复，
        留着就是一张永远点不动的死卡（opencode 在这条路径上只删服务端
        记录、不发事件，客户端要靠重新 sync 才清得掉）。
        """
        self.endText()
        self.endReasoning()
        self._settle_open_tools(status)
        self._finish_tool_group()
        self.cancelPendingPermissions()

    def _settle_open_tools(self, status: str) -> None:
        """把仍处于 pending / running 的工具调用落到终态。

        错误回合落 ``Error``（确实没拿到结果），其余（用户停止 / 消息被替换）
        落 ``Aborted`` —— 区分二者是因为「被用户停止」不是失败。

        以 **part 数据**为准遍历而不是 ``_tool_cards``：上下文工具在分组开启时
        映射到 ``ContextToolGroupCard``（无单调用状态），而 part 始终是权威。
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
        # 通用清扫：回合结束后不允许残留 streaming 的 part。
        # 已结算的工具 part（Done/Error）与 stats part 自身仍带 Streaming，
        # 逐个 kind 处理很容易漏，这里统一兜底（对齐「无永转圈」不变量）。
        for part in self._parts:
            if part.status == ElaChatStatusType.Streaming:
                self._replace_part(part.id, part.withStatus(part_status))
                if part.kind == ElaChatPartKindType.Compaction:
                    # 压缩卡的状态只由 setCompactionStatus 驱动，不同步就会
                    # 永久停在「压缩中…」而 part 已经落定
                    widget = self._part_widgets.get(part.id)
                    if isinstance(widget, CompactionSeparator):
                        widget.setCompactionStatus(part_status)

    def isStreaming(self) -> bool:
        """是否正在流式生成。"""
        return self._status == ElaChatStatusType.Streaming

    def status(self) -> str:
        """获取消息状态（见 :class:`~pyqt6_ela_pro.chat.message.ElaChatStatusType`）。"""
        return self._status

    def setStatus(self, status: str) -> None:
        """设置消息状态（同步头部状态提示、底部行与用量徽标的显隐）。

        状态是**字符串枚举**（:class:`ElaChatStatusType`），非法值一律回落
        ``Done`` —— 直接写进去会让头部提示取不到文案、底部行按
        ``!= Streaming`` 放行，状态机被静默污染（``"Done"`` 这种大小写笔误
        很难在界面上一眼看出来）。``ElaChatStatusType.All`` 之外的展示态
        （如 ``Queued``）不进 ``_status``，只由头部按 ``Streaming`` 派生。
        """
        self._status = (
            status if status in ElaChatStatusType.All else ElaChatStatusType.Done
        )
        self._sync_header_status()
        self._sync_footer()
        if self._status != ElaChatStatusType.Streaming:
            # 流式期间徽标被收起（见 _apply_stats_mode），回合结束再按模式摆出来
            self._apply_stats_mode()

    def _sync_footer(self) -> None:
        """底部行（复制 / 重新生成 / 用量 / 耗时）只在回合有结果之后出现。

        生成中（含头部展示的「排队中」）整行不摆：回答还没写完，操作按钮与用量都
        是半截数据 —— 重新生成点了会丢掉用户已经看到的内容（``regenerateFrom`` 删该
        条及其后所有消息），复制到的也只是半句话；用量 / 耗时更是要等回合收尾才结算。
        回合结束（``Done`` / ``Stopped`` / ``Error``）后整行一起出现。
        """
        if self._footer is None:
            return
        self._footer.setVisible(
            not self._parts_deferred and self._status != ElaChatStatusType.Streaming
        )

    def _sync_header_status(self) -> None:
        """按状态与「是否已收到首个模型输出」刷新头部提示。

        ``Streaming`` 分两阶段展示：等待首个输出（TTFT）时显示
        ``Queued``（"排队中…"），收到正文 / 思考 / 工具调用后转
        ``Streaming``（"生成中…"）。``Queued`` 只是展示态，气泡与分段的
        ``_status`` 始终是 ``Streaming``（持久化 / journal 语义不变）。
        """
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
