"""聊天气泡的分段时间线数据层（parts / 快照 / 恢复 / 窗口化）。"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Optional
from uuid import uuid4

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from ..ela_button import ElaButton
from ..ela_markdown_viewer import ElaMarkdownViewer
from .blocks import CompactionSeparator, PermissionRecord, ReasoningBlock, ToolCallCard
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatRoleType,
    ElaChatStatusType,
)

#: 单条消息超过该步骤数时，物化只展开末尾若干步（历史超长回合）
STEP_MATERIALIZE_LIMIT = 24
#: 超长消息物化时保留的末尾步骤数（用户通常停在最新一步）
STEP_WINDOW_TAIL = 12


def estimate_parts_height(parts, width: int, stats_mode: str = "footer") -> int:
    """估算分段区高度（未物化消息的占位高度，物化后用实测值替换）。"""
    width = max(320, int(width or 0))
    chars_per_line = max(24, width // 8)
    stats_height = 24 if stats_mode == "steps" else 0
    total = 0
    last_step = 0
    for part in parts or ():
        step = max(1, int(getattr(part, "step", 1) or 1))
        if step != last_step:
            total += 28
            last_step = step
        kind = getattr(part, "kind", "")
        if kind == ElaChatPartKindType.Tool:
            total += 40
        elif kind == ElaChatPartKindType.Reasoning:
            total += 36
        elif kind == ElaChatPartKindType.Text:
            lines = max(
                1, math.ceil(len(getattr(part, "text", "") or "") / chars_per_line)
            )
            total += min(6000, 12 + lines * 22)
        elif kind == ElaChatPartKindType.Stats:
            total += stats_height
        elif kind == ElaChatPartKindType.Compaction:
            total += 64
        elif kind == ElaChatPartKindType.Permission:
            total += 96
        else:
            total += 40
    return max(40, total)


class ChatPartTimeline:
    """把气泡的时间线数据操作从 ``ElaChatBubble`` 中拆出来。"""

    def __init__(self, bubble) -> None:
        self._bubble = bubble

    def _find_part(self, partId: Optional[str]) -> Optional[ElaChatPart]:
        for part in self._bubble._parts:
            if part.id == partId:
                return part
        return None

    def _parts_of_kind(self, kind: str) -> list:
        """按类型筛选分段快照（:meth:`compactionParts` 等的公共实现）。"""
        return [part for part in self._bubble._parts if part.kind == kind]

    def _append_part(self, part: ElaChatPart, widget: Optional[QWidget]) -> None:
        self._bubble._parts.append(part)
        self._bubble._part_widgets[part.id] = widget
        # ``widget=None`` 是合法的：待答复的审批 part 只登记数据，等落定后再
        # 在原位补记录卡（见 beginPermission）。不判空就 ``addWidget(None)``，
        # Qt 会打 ``QLayout: Cannot add a null widget to QVBoxLayout/``。
        if widget is not None and self._bubble._parts_layout is not None:
            self._bubble._parts_layout.addWidget(widget)
        if part.kind != ElaChatPartKindType.Stats:
            self._bubble._move_step_stats_to_end(part.step)

    def _move_step_stats_to_end(self, step: int) -> None:
        """把指定步骤的步骤用量徽标移到该步骤内容的末尾。

        词元统计在该步 LLM 调用结束时即到达（早于工具执行），后续若同一步骤
        继续追加工具 / 正文，需要把徽标移到末尾，保持「步骤末尾」的语义。
        """
        target = None
        for item in reversed(self._bubble._parts):
            if item.kind == ElaChatPartKindType.Stats and item.step == step:
                target = item
                break
        if target is None:
            return
        widget = self._bubble._part_widgets.get(target.id)
        if widget is None or self._bubble._parts_layout is None:
            return
        if widget.parentWidget() is self._bubble._stats_host:
            # 已停靠底部行的整轮汇总徽标不参与「步骤末尾」重排：否则收尾后
            # 再来一次 beginText / 工具更新，就会把它从底部行拽回时间线。
            return
        self._bubble._parts_layout.removeWidget(widget)
        self._bubble._parts_layout.addWidget(widget)

    def _replace_part(self, partId: str, part: ElaChatPart) -> None:
        for index, item in enumerate(self._bubble._parts):
            if item.id == partId:
                self._bubble._parts[index] = part
                return

    def _remove_parts(self, kinds) -> None:
        """移除指定类型的分段与控件（``kinds`` 为类型集合）。"""
        removed = [part for part in self._bubble._parts if part.kind in kinds]
        self._bubble._parts = [
            part for part in self._bubble._parts if part.kind not in kinds
        ]
        if self._bubble._docked_stats is not None and self._bubble._docked_stats[0] in {
            part.id for part in removed
        }:
            self._bubble._docked_stats = None
        seen = set()
        for part in removed:
            self._bubble._discard_part_state(part.id)
            self._bubble._suspended_viewers.pop(part.id, None)
            widget = self._bubble._part_widgets.pop(part.id, None)
            if widget is None or id(widget) in seen:
                continue
            seen.add(id(widget))
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()

    def _drop_part(self, partId: str) -> None:
        """移除指定分段与控件。"""
        if self._bubble._find_part(partId) is None:
            return
        self._bubble._parts = [
            part for part in self._bubble._parts if part.id != partId
        ]
        if (
            self._bubble._docked_stats is not None
            and self._bubble._docked_stats[0] == partId
        ):
            self._bubble._docked_stats = None
        self._bubble._discard_part_state(partId)
        self._bubble._suspended_viewers.pop(partId, None)
        widget = self._bubble._part_widgets.pop(partId, None)
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()

    def _step_empty(self) -> bool:
        """当前步骤是否还没有任何分段。"""
        return not any(
            part.step == self._bubble._step_index for part in self._bubble._parts
        )

    def _last_text_part_id(self) -> Optional[str]:
        """最后一个正文段的 id（无则返回 ``None``）。"""
        for part in reversed(self._bubble._parts):
            if (
                part.kind == ElaChatPartKindType.Text
                and part.id in self._bubble._part_widgets
            ):
                return part.id
        return None

    def text(self) -> str:
        """获取消息文本（助手消息为全部分段正文的拼接）。

        **纯读取**：流式期间返回的是「落定文本 + 在途缓冲」的完整可见全文
        （与界面所见一致），但不会把缓冲写回 ``part.text``。要拿可序列化的
        落定值请读 :meth:`parts` 里各段的 ``text``，或消息快照的
        ``message.text``（回合结束后二者一致）。
        """
        if self._bubble._role == ElaChatRoleType.Assistant:
            return "".join(
                self._bubble.partText(part)
                for part in self._bubble._parts
                if part.kind == ElaChatPartKindType.Text
            )
        return self._bubble._label.text() if self._bubble._label is not None else ""

    def parts(self) -> tuple:
        """获取内容分段快照（按加入顺序，构成消息时间线）。

        **纯读取，无副作用**：流式在途分片只存在于缓冲中，读 ``parts()``
        不会把它们写回 ``part.text``。因此 ``part.text`` **只含已落定内容**，
        快照可直接用于持久化 / 序列化 / 与服务端对账，且**与读取时机无关**
        （读一次和读一百次结果相同）。

        「当前可见全文」（含在途分片）用 :meth:`partText`，或在气泡上用
        :meth:`text` / :meth:`reasoning`。

        .. note::
           落定发生在分段结束处：:meth:`endText` / :meth:`endReasoning` /
           :meth:`endStream` / :meth:`setError` 都会把缓冲并入 ``part.text``。
           所以**流式期间** ``part.text`` 为空、``message.text`` 也为空，
           回合结束后才是完整正文 —— 这是「part 自足可序列化」的代价，
           实时预览请走气泡 API 或信号。
        """
        return tuple(self._bubble._parts)

    def partText(self, part) -> str:
        """某个分段的当前可见全文 = 落定文本 + 在途缓冲。

        纯读取，不物化。渲染与实时预览读这里；要可序列化的落定值读
        ``part.text``（见 :meth:`parts` 的说明）。
        """
        base = part.text or ""
        chunks = self._bubble._text_buffers.get(part.id)
        if not chunks:
            return base
        return base + "".join(chunks)

    def setParts(self, parts) -> bool:
        """用一份分段快照重建整条时间线（**从存储恢复**用），返回是否成功。

        刻意**不**另写一套渲染逻辑，而是把每个分段按顺序**重放**到已经
        充分测试的增量 API 上（``beginText`` / ``appendText`` / ``endText``、
        ``beginReasoning`` / ``appendReasoning`` / ``endReasoning``、
        ``addToolCall`` / ``setToolCallResult``、``setStepStats``）。这样恢复
        出来的界面与实时流式出来的**逐像素一致**，且工具归组、内联思考行、
        步骤用量徽标这些横切逻辑自动保持正确 —— 复制一份实现必然随时间
        漂移。

        保留原 ``part.id``，使 ``messageId`` / ``partId`` 在重启后稳定。

        仅对**助手消息**有效（用户 / 系统消息请用 :meth:`setText`），且
        消息**不可处于流式状态**（否则返回 ``False``）。消息级字段
        （标题 / 时间 / 耗时 / 错误 / 附件）不在这里设置，由
        ``ElaChatView.addMessageFromDict`` 负责。
        """
        if self._bubble._role != ElaChatRoleType.Assistant:
            return False
        if self._bubble._status == ElaChatStatusType.Streaming:
            return False

        self._bubble._parts_deferred = False
        self._bubble._parts_windowed = False
        self._bubble._window_button = None
        self._bubble._deferred_placeholder = None
        self._bubble._reset_part_state()
        maxStep = 0
        self._bubble._begin_bulk_build()
        self._bubble._stats_batch = True
        try:
            for part in parts or ():
                if part is None:
                    continue
                maxStep = max(maxStep, int(getattr(part, "step", 1) or 1))
                # 每段先切到它所属步骤，_step_index 影响新建分段的 step 归属。
                # 切步必须与 beginStep 一样收口工具分组与当前面板 / 用量段，
                # 否则后续步骤的工具会并进上一步的面板（重放出的界面与实时不一致）。
                if int(getattr(part, "step", 1) or 1) != self._bubble._step_index:
                    self._bubble.endText()
                    self._bubble._finish_tool_group()
                    self._bubble.endReasoning()
                    self._bubble._current_stats_id = None
                    self._bubble._current_tool_panel = None
                    self._bubble._step_index = int(part.step or 1)
                self._bubble._restore_one_part(part)
        finally:
            self._bubble._stats_batch = False
            self._bubble._end_bulk_build()
        # 收尾：把最后一段的临时状态清干净，并落在最后一步
        # （工具分组也要收口，对齐 endStream，否则分组卡停在「正在探索」）
        self._bubble.endText()
        self._bubble.endReasoning()
        self._bubble._finish_tool_group()
        self._bubble._step_index = max(maxStep, 1)
        # 恢复出来的分段一律视为已结束（存储里不该有在途态）
        for part in self._bubble._parts:
            if part.status == ElaChatStatusType.Streaming:
                self._bubble._replace_part(
                    part.id, part.withStatus(ElaChatStatusType.Done)
                )
        self._bubble._apply_theme()
        self._bubble._apply_stats_mode()
        self._bubble._sync_stats_duration()
        # 延迟物化的消息在占位期间藏起了头部 / 底部；这里恢复。
        self._bubble._header.show()
        if self._bubble._footer is not None:
            self._bubble._sync_footer()
        self._bubble.updateGeometry()
        if self._bubble.layout() is not None:
            self._bubble.layout().activate()
        return True

    def setPartsDeferred(self, parts) -> bool:
        """只保存分段数据、不建控件（批量加载历史时的按需物化入口）。

        与 :meth:`setParts` 的区别：这里**不重放**增量 API，只把 parts 挂到
        气泡上并在分段区放一个等高占位。首屏 / 滚动到附近时由
        :meth:`materializeParts` 真正建卡。``parts()`` / ``messages()`` /
        导出读到的仍是完整数据。
        """
        if self._bubble._role != ElaChatRoleType.Assistant:
            return False
        if self._bubble._status == ElaChatStatusType.Streaming:
            return False
        self._bubble._reset_part_state()
        normalized = []
        for part in parts or ():
            if part is None:
                continue
            if part.status == ElaChatStatusType.Streaming:
                part = part.withStatus(ElaChatStatusType.Done)
            normalized.append(part)
        self._bubble._parts = normalized
        self._bubble._parts_deferred = True
        self._bubble._step_index = max(
            (max(1, int(getattr(part, "step", 1) or 1)) for part in normalized),
            default=1,
        )
        # 未物化的历史消息只显示占位高度，不摆头像 / 操作栏 / 「AI 生成」提示：
        # 一排空壳消息头比空白更像「坏了」。物化时再恢复。
        self._bubble._header.hide()
        if self._bubble._footer is not None:
            self._bubble._footer.hide()
        if self._bubble._parts_layout is not None:
            width = self._bubble.width()
            if width <= 0 and self._bubble._content is not None:
                width = self._bubble._content.width()
            placeholder = QWidget(
                self._bubble._parts_container or self._bubble._content or self
            )
            placeholder.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            placeholder.setFixedHeight(
                estimate_parts_height(normalized, width, self._bubble._stats_mode) + 90
            )
            self._bubble._parts_layout.addWidget(placeholder)
            self._bubble._deferred_placeholder = placeholder
        self._bubble.updateGeometry()
        if self._bubble.layout() is not None:
            self._bubble.layout().activate()
        return True

    def materializeParts(self) -> bool:
        """把延迟保存的分段真正建成控件；返回是否执行了物化。

        超过 :data:`STEP_MATERIALIZE_LIMIT` 步的超长消息只建末尾
        :data:`STEP_WINDOW_TAIL` 步，其余折叠成「展开全部」按钮；完整
        ``parts`` 数据仍保留，导出 / 搜索不受影响。
        """
        if not self._bubble._parts_deferred:
            return False
        parts = list(self._bubble._parts)
        self._bubble._parts_deferred = False
        self._bubble._deferred_placeholder = None
        groups = self._bubble._stepGroups(parts)
        if len(groups) > STEP_MATERIALIZE_LIMIT:
            return self._bubble._setPartsWindowed(parts, groups)
        return self._bubble.setParts(parts)

    def _setPartsWindowed(self, parts, groups) -> bool:
        window = [part for group in groups[-STEP_WINDOW_TAIL:] for part in group]
        if not window:
            return False
        if not self._bubble.setParts(window):
            return False
        # ``setParts`` 会把 ``_parts`` 覆盖成窗口分段；恢复完整时间线，
        # 让 parts() / 导出 / 工具快照读取看到的始终是全量数据。
        self._bubble._parts = list(parts)
        self._bubble._parts_windowed = True
        button = ElaButton(
            f"展开全部 {len(groups)} 个步骤（当前显示末尾 {STEP_WINDOW_TAIL} 步）",
            parent=self._bubble._parts_container or self._bubble._content or self,
        )
        button.clicked.connect(self._bubble.expandParts)
        if self._bubble._parts_layout is not None:
            self._bubble._parts_layout.insertWidget(0, button)
        self._bubble._window_button = button
        self._bubble._step_index = max(
            (max(1, int(getattr(part, "step", 1) or 1)) for part in parts),
            default=1,
        )
        self._bubble.updateGeometry()
        if self._bubble.layout() is not None:
            self._bubble.layout().activate()
        return True

    def expandParts(self) -> bool:
        """把超长消息折叠的步骤全部展开（用户显式操作）。"""
        if not self._bubble._parts_windowed:
            return False
        parts = list(self._bubble._parts)
        self._bubble._parts_windowed = False
        self._bubble._window_button = None
        return self._bubble.setParts(parts)

    def partsWindowed(self) -> bool:
        """是否只物化了超长消息的末尾若干步。"""
        return self._bubble._parts_windowed

    def partsDeferred(self) -> bool:
        """分段是否仍处于「只有数据、没有控件」状态。"""
        return self._bubble._parts_deferred

    def _ensure_parts_materialized(self) -> None:
        """写路径入口：延迟分段先物化，再做增量更新。"""
        if self._bubble._parts_deferred:
            self._bubble.materializeParts()

    def estimatedPartsHeight(self) -> int:
        """当前分段的估算高度（未物化占位用）。"""
        width = self._bubble.width()
        if width <= 0 and self._bubble._content is not None:
            width = self._bubble._content.width()
        return estimate_parts_height(
            self._bubble._parts, width, self._bubble._stats_mode
        )

    def _restore_one_part(self, part) -> None:
        """重放单个分段的恢复（内部由 :meth:`setParts` 驱动）。"""
        if not getattr(part, "id", ""):
            # 损坏数据可能缺 id：统一补一个，否则空 id 的分段会在
            # ``_part_widgets`` 里互相覆盖（Permission / Compaction / Text
            # 三条分支对空 id 的口径此前各不相同）。
            part = replace(part, id=uuid4().hex[:12])
        kind = getattr(part, "kind", "")
        if kind == ElaChatPartKindType.Text:
            self._bubble._restore_text_part(part.id, part.text or "")
        elif kind == ElaChatPartKindType.Reasoning:
            partId = self._bubble._ensure_reasoning_part(part.id or None)
            widget = self._bubble._part_widgets.get(partId)
            if isinstance(widget, ReasoningBlock):
                widget.setText(part.text or "")
                widget.finishSilently(part.duration_ms or None)
            elif isinstance(widget, ElaMarkdownViewer):
                if part.text:
                    self._bubble._write_viewer_text(partId, widget, part.text)
                if self._bubble._thinking_row is not None:
                    self._bubble._thinking_row.end()
            self._bubble._current_reasoning_id = None
            self._bubble._replace_part(partId, part.withStatus(ElaChatStatusType.Done))
        elif kind == ElaChatPartKindType.Tool:
            call = part.tool_call
            if call is None:
                return
            callId = self._bubble.addToolCall(
                call.name,
                call.arguments,
                toolCallId=call.id or None,
                tool_call=call,
            )
            if not callId:
                return
            current = self._bubble._find_part(callId)
            if current is not None and current.tool_call != call:
                self._bubble._replace_part(callId, current.withToolCall(call))
                card = self._bubble._tool_cards.get(callId)
                if isinstance(card, ToolCallCard):
                    card.setStatus(call.status)
                panel = self._bubble._panel_for_call(callId)
                if panel is not None:
                    if self._bubble._bulk_build:
                        self._bubble._bulk_panels.add(panel)
                    else:
                        self._bubble._sync_tool_panel(panel)
        elif kind == ElaChatPartKindType.Stats:
            if part.stats is not None:
                self._bubble.setStepStats(part.stats, part.id or None)
        elif kind == ElaChatPartKindType.Synthetic:
            self._bubble.addSteerNotice(part.text, part.id or None)
        elif kind == ElaChatPartKindType.Compaction:
            self._bubble._restore_compaction(part)
        elif kind == ElaChatPartKindType.Permission:
            request = part.permission
            if request is not None:
                self._bubble._restore_permission(part.id, request)

    def _restore_compaction(self, part) -> None:
        """重放压缩分段（恢复路径：直接建卡并灌摘要，不走流式接口）。"""
        widget = CompactionSeparator(
            self._bubble._parts_container or self._bubble._content or self
        )
        widget.setSummary(part.text or "")
        widget.setCompactionStatus(part.status)
        self._bubble._append_part(part, widget)

    def _restore_permission(self, partId: str, request: ElaChatPermission) -> None:
        """重放审批分段（恢复路径：建**记录卡** + 灌快照，不发任何交互信号）。

        恢复出来的审批**一律是只读记录**，即便载荷里的状态还是 ``pending``：

        - **不发** ``permissionRequested``：那一次请求早已随上一个进程消失，
          宿主此刻并没有在等这个回复；发信号会让宿主去「恢复一个不存在的挂起」；
        - **不放进 dock**：dock 是「现在要你动手」的位置，而历史里的一张待答卡
          摆在那里只会让人以为还能点。它照样显示（用户能看到「这里曾需要你
          确认」），但不参与宿主交互契约。
        """
        record = request
        if request.isPending:
            record = request.withStatus(ElaChatPermissionStatusType.Cancelled)
        widget = PermissionRecord(
            record, self._bubble._parts_container or self._bubble._content or self
        )
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Permission,
            status=ElaChatStatusType.Done,
            permission=record,
            step=self._bubble._step_index,
        )
        self._bubble._append_part(part, widget)
        self._bubble._permission_cards[partId] = widget

    def compactionParts(self) -> list:
        """获取全部压缩分段快照。"""
        return self._bubble._parts_of_kind(ElaChatPartKindType.Compaction)
