"""消息增删改 / 恢复 / 导出 / 气泡构建方法组（从 ``ElaChatView`` 拆出）。"""

from __future__ import annotations

from dataclasses import replace


import time
from collections import Counter
from datetime import datetime
from typing import Optional


from .bubble import ElaChatBubble
from .message import (
    ElaChatMessage,
    ElaChatPartKindType,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatToolStatusType,
    _as_int,
)
from .session import SESSION_SCHEMA_VERSION, ElaChatSessionInfo


def _with_created_at(message: ElaChatMessage, createdAt: float) -> ElaChatMessage:
    """替换快照的创建时间（恢复历史消息时保留原时间戳）。"""
    return replace(message, created_at=float(createdAt))


def _with_identity(
    message: ElaChatMessage, identity=None, mentions=None, delivery=""
) -> ElaChatMessage:
    """把可选的 agent / 模型 / mention / 投递方式写到新快照上。"""
    if identity is not None:
        message = message.withIdentity(*identity)
    if mentions:
        message = message.withMentions(mentions)
    if delivery:
        message = message.withDelivery(delivery)
    return message


def _settle_restored(message: ElaChatMessage) -> ElaChatMessage:
    """恢复出来的消息一律落定：消息状态与未完成工具都不留在途态。

    存储里可能留下生成中导出的 ``streaming`` / ``pending`` 记录，恢复后不再
    有事件收尾；与 ``journal.settleOpen`` 同口径。
    """
    failed = message.status == ElaChatStatusType.Error or bool(message.error)
    target = (
        ElaChatStatusType.Stopped
        if message.status == ElaChatStatusType.Streaming
        else message.status
    )
    parts = []
    changed = False
    for part in message.parts:
        call = part.tool_call
        if call is not None and call.status in (
            ElaChatToolStatusType.Pending,
            ElaChatToolStatusType.Running,
        ):
            call = call.withStatus(
                ElaChatToolStatusType.Error if failed else ElaChatToolStatusType.Aborted
            )
            part = part.withToolCall(call)
            changed = True
        if part.status == ElaChatStatusType.Streaming:
            part = part.withStatus(ElaChatStatusType.Done)
            changed = True
        parts.append(part)
    if changed:
        message = message.withParts(parts)
    if target != message.status:
        message = message.withStatus(target)
    return message


class _ViewMessagesMixin:
    """方法组 mixin：状态由 ``ElaChatView.__init__`` 建立。"""

    def addMessage(
        self, role: str, text: str = "", messageId: Optional[int] = None
    ) -> int:
        """添加一条消息，返回消息 id。

        ``messageId`` 可由调用方指定（乐观 UI 先行渲染）；**该 id 已被占用时
        抛 :class:`ValueError`**（静默重号会让旧气泡既留在界面上又不在索引里）。
        """
        if messageId is not None and messageId in self._bubbles:
            raise ValueError(
                f"addMessage: 消息 id {messageId} 已被占用，请换一个 id 或改用既有消息"
            )
        return self._create_message(role, text, streaming=False, messageId=messageId)

    def beginMessage(
        self,
        role: str = ElaChatRoleType.Assistant,
        *,
        agent: str = "",
        model: str = "",
        modelVariant: str = "",
    ) -> int:
        """开始一条流式消息（通常为助手），返回消息 id。"""
        return self._create_message(
            role,
            "",
            streaming=True,
            identity=(agent, model, modelVariant),
        )

    def addMessageFromDict(self, data, messageId: Optional[int] = None) -> int:
        """从 :meth:`ElaChatMessage.toDict` 的输出恢复一条消息，返回消息 id。

        会重建完整分段时间线（思考 / 正文 / 工具 / 步骤用量）与消息级字段。
        ``messageId`` 为 ``None`` 时沿用 ``data`` 里的 ``id``；id 已占用抛
        :class:`ValueError`（不静默重号）。

        :raises ValueError: id 已被占用，或助手消息的分段无法重建
        """
        message = _settle_restored(ElaChatMessage.fromDict(data))
        if messageId is None and message.id > 0:
            messageId = message.id
        if messageId is not None:
            if messageId in self._bubbles:
                raise ValueError(
                    f"addMessageFromDict: 消息 id {messageId} 已被占用，"
                    "请显式传入 messageId 或改用 restoreMessages"
                )
            if messageId >= self._next_id:
                self._next_id = messageId + 1
        if message.role == ElaChatRoleType.Assistant and message.parts:
            messageId = self._create_message(
                message.role,
                "",
                streaming=False,
                messageId=messageId,
                emitAdded=False,
                snapshot=message,
            )
            if not self._bubbles[messageId].setParts(message.parts):
                raise ValueError("addMessageFromDict: 助手消息分段重建失败")
            self._apply_message_fields(messageId, message)
            self._sync_parts(messageId)
            self.messageAdded.emit(messageId, message.role)
            self._follow_bottom()
            return messageId
        # 用户 / 系统消息（或无分段的老数据）：走普通纯文本路径
        messageId = self._create_message(
            message.role,
            message.text,
            streaming=False,
            messageId=messageId,
            emitAdded=False,
            snapshot=message,
        )
        self._apply_message_fields(messageId, message)
        self.messageAdded.emit(messageId, message.role)
        return messageId

    def _validate_preserve_ids(self, rows, against_existing: bool = True) -> None:
        """校验 ``preserveIds=True`` 的整批 id（重复 / 与现有消息撞号即抛）。

        **只读校验**：调用方必须在写入前调用，否则坏 bundle 会先把当前会话清掉
        才抛异常。``against_existing=False`` 只查批内重复（``importSession`` 随后
        就 ``clear()``，与现有消息撞号无害）。
        """
        stored = [_as_int(data.get("id")) for data in rows if isinstance(data, dict)]
        stored = [messageId for messageId in stored if messageId > 0]
        counts = Counter(stored)
        bad = {messageId for messageId, count in counts.items() if count > 1}
        if against_existing:
            existing = {message.id for message in self._messages}
            bad |= {messageId for messageId in counts if messageId in existing}
        bad = sorted(bad)
        if bad:
            raise ValueError(
                f"restoreMessages: id {bad} 在本批或现有消息中重复 / 已被占用"
                "（preserveIds=True 时请先去重或 clear，或改用默认重分配）"
            )

    def restoreMessages(self, items, preserveIds: bool = False) -> list:
        """批量恢复消息（存储模块的读回入口），返回恢复后的消息 id 列表。

        按给定顺序追加；``preserveIds=False``（默认）时 id 一律重新分配。
        ``preserveIds=True`` 保留存储 id，本批重号或与现有消息撞号抛
        :class:`ValueError`，且**先校验后写入**（不留半恢复状态）。

        整体包在 :meth:`beginBatch` / :meth:`endBatch` 之间，大批量走渐进渲染。
        """
        rows = list(items or ())
        if preserveIds:
            self._validate_preserve_ids(rows)
        # 大批量恢复：连气泡壳一起延迟（只留等高占位）
        shell_virtual = (
            self._virtual_shells_enabled and len(rows) >= self._virtual_shells_min
        )
        virtual_list = (
            shell_virtual
            and self._virtual_list_enabled
            and len(rows) >= self._virtual_list_min
        )
        if virtual_list:
            self._virtual_list_mode = True
        # 壳虚拟化（80~200 条）启用「滚远收回占位」；spacer 模式自己管理回收。
        self._shell_recycling = bool(shell_virtual and not virtual_list)
        restored = []
        self.beginBatch()
        try:
            for data in rows:
                message = _settle_restored(ElaChatMessage.fromDict(data))
                messageId = message.id if preserveIds and message.id > 0 else None
                messageId = self._create_message(
                    message.role,
                    "" if message.parts else message.text,
                    streaming=False,
                    messageId=messageId,
                    hasParts=bool(message.parts),
                    emitAdded=False,
                    snapshot=message,
                    deferShell=shell_virtual,
                )
                if shell_virtual:
                    # 壳还没建：快照本身就带全部字段 / 分段，直接发信号
                    self.messageAdded.emit(messageId, message.role)
                    restored.append(messageId)
                    continue
                if message.role == ElaChatRoleType.Assistant and message.parts:
                    if self._batch_depth > 0 and self._virtual_parts_enabled:
                        self._bubbles[messageId].setPartsDeferred(message.parts)
                        self._sync_parts(messageId)
                    else:
                        if not self._bubbles[messageId].setParts(message.parts):
                            continue
                        # 快照当场结算，只有 Markdown 渲染延迟：否则读路径
                        # （messages() / exportSession）会拿到空消息，导出静默丢内容。
                        self._sync_parts(messageId)
                self._apply_message_fields(messageId, message)
                self.messageAdded.emit(messageId, message.role)
                restored.append(messageId)
        finally:
            self.endBatch()
        return restored

    def _apply_message_fields(self, messageId: int, message) -> None:
        """把消息级字段（标题 / 时间 / 耗时 / 错误 / 附件 / 创建时间）恢复到气泡与快照。

        必须走 view 级方法：``bubble.setDuration()`` 之类只改控件不改快照。
        """
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            return
        if message.title:
            self.setMessageTitle(messageId, message.title)
        if message.agent or message.model or message.model_variant:
            bubble.setIdentity(message.agent, message.model, message.model_variant)
        if message.mentions:
            bubble.setMentions(message.mentions)
        if message.timestamp:
            self.setMessageTimestamp(messageId, message.timestamp)
        if message.duration_ms:
            self.setMessageDuration(messageId, message.duration_ms)
        if message.error:
            self.setMessageError(messageId, message.error, message.error_type)
        if message.attachments:
            bubble.setAttachments(message.attachments)
            self._update_snapshot(
                messageId,
                lambda m, items=message.attachments: m.withAttachments(items),
            )
        if message.created_at:
            self._update_snapshot(
                messageId, lambda m, at=message.created_at: _with_created_at(m, at)
            )
        # 消息级状态也要还原：只信 parts 的派生字段会把「被停止」「出错」的历史
        # 消息显示成 Done。有错误文案时不覆盖 —— ``setMessageError`` 已置 Error。
        if message.status and not message.error:
            status = message.status
            if status == ElaChatStatusType.Streaming:
                # 生成中导出 / 崩在途的消息：状态与分段一起落定（同 journal.settleOpen）。
                status = ElaChatStatusType.Stopped
            # 状态未变时跳过：setStatus 会重复跑 _apply_stats_mode。
            if bubble.status() != status:
                bubble.setStatus(status)
                self._update_snapshot(
                    messageId, lambda m, value=status: m.withStatus(value)
                )

    def exportSession(self, session=None, extra=None) -> dict:
        """导出整会话快照（消息时间线 + 会话元数据 + 视图外观选项）。

        ``messages`` 是 ``ElaChatMessage.toDict()`` 列表（权威数据是 ``parts``）；
        ``extra`` 原样带回。输出可直接 ``json.dumps`` 落库；读回见 :meth:`importSession`。
        """
        if isinstance(session, ElaChatSessionInfo):
            info = session
        elif isinstance(session, dict):
            info = ElaChatSessionInfo.fromDict(session)
        elif session is None:
            info = ElaChatSessionInfo(id="")
        else:
            raise TypeError(
                "exportSession: session 必须是 ElaChatSessionInfo / dict / None"
            )
        if extra is not None and not isinstance(extra, dict):
            raise TypeError("exportSession: extra 必须是 dict 或 None")
        messages = self.messages()
        return {
            "schema": SESSION_SCHEMA_VERSION,
            "session": info.withMessageCount(len(messages)).toDict(),
            "view": {
                "reasoning_style": self._reasoning_style,
                "stats_mode": self._stats_mode,
                "tool_grouping": self._tool_grouping,
                "avatar_visible": self._avatar_visible,
                "user_bubble_ratio": self._user_bubble_ratio,
                "content_max_width": self._content_max_width,
                "timeline_detail": self.timelineDetail().toDict(),
                "disclosure": {
                    str(key): bool(value) for key, value in self._disclosure.items()
                },
            },
            "messages": [message.toDict() for message in messages],
            "extra": extra,
        }

    def importSession(self, bundle, clear: bool = True) -> int:
        """从 :meth:`exportSession` 的 bundle 恢复整会话，返回恢复的消息条数。

        - ``clear=True``（默认）：先校验（批内 id 重复即抛）再清空，保留消息 id；
          ``clear=False``：追加并重新分配 id。与当前消息撞号不算冲突。
        - 视图外观选项在写入消息**之前**应用（思考形态决定分段控件建卡形态）。
        - 非 dict / ``messages`` 非列表抛 :class:`ValueError`，非字典行跳过。
        - 会话元数据留在 bundle 里由宿主读取；输入草稿与排队队列不在 bundle 内。
        """
        if not isinstance(bundle, dict):
            raise ValueError("importSession: bundle 必须是 dict")
        rows = bundle.get("messages", [])
        if not isinstance(rows, list):
            raise ValueError("importSession: bundle['messages'] 必须是列表")
        rows = [row for row in rows if isinstance(row, dict)]
        if clear:
            # 先校验后清空：坏 bundle（批内重复 id）不能把当前会话清掉再抛。
            self._validate_preserve_ids(rows, against_existing=False)
        if clear:
            # 先清空再应用视图选项：``clear()`` 会重置披露状态。
            self.clear()
        self._apply_session_view(bundle.get("view"))
        return len(self.restoreMessages(rows, preserveIds=clear))

    def _apply_session_view(self, options) -> None:
        """按 bundle 的 ``view`` 段恢复外观选项（缺失 / 非法字段不动）。"""
        if not isinstance(options, dict):
            return
        if options.get("reasoning_style") in ElaChatReasoningStyleType.All:
            self.setReasoningStyle(options["reasoning_style"])
        if options.get("stats_mode") in ("footer", "steps", "none"):
            self.setStatsMode(options["stats_mode"])
        grouping = options.get("tool_grouping")
        if isinstance(grouping, bool):
            self.setToolGrouping(grouping)
        visible = options.get("avatar_visible")
        if isinstance(visible, bool):
            self.setAvatarVisible(visible)
        ratio = options.get("user_bubble_ratio")
        if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
            self.setUserBubbleMaxWidth(float(ratio))
        width = options.get("content_max_width")
        if isinstance(width, int) and not isinstance(width, bool):
            self.setContentMaxWidth(width)
        detail = options.get("timeline_detail")
        if isinstance(detail, dict):
            self.setTimelineDetail(detail)
        disclosure = options.get("disclosure")
        if isinstance(disclosure, dict):
            self._disclosure.clear()
            for key, value in disclosure.items():
                if isinstance(key, str) and isinstance(value, bool):
                    self._disclosure[key] = value
            for bubble in list(self._bubbles.values()):
                if bubble is not None:
                    bubble._disclosure = self._disclosure
                    bubble.applyTimelineDetail()

    def _create_message(
        self,
        role: str,
        text: str,
        streaming: bool,
        messageId: Optional[int] = None,
        *,
        hasParts: bool = False,
        emitAdded: bool = True,
        snapshot: Optional[ElaChatMessage] = None,
        deferShell: bool = False,
        identity=None,
        mentions=None,
        delivery: str = "",
    ) -> int:
        if role not in ElaChatRoleType.All:
            role = ElaChatRoleType.Assistant
        if messageId is None:
            messageId = self._next_id
            self._next_id += 1
        else:
            if isinstance(messageId, bool) or not isinstance(messageId, int):
                raise TypeError(
                    f"messageId 必须是 int，收到 {messageId!r}"
                    f"（{type(messageId).__name__}）"
                )
            if messageId in self._bubbles or messageId in self._shell_placeholders:
                raise ValueError(f"消息 id {messageId} 已被占用")
            if messageId >= self._next_id:
                # 外部 id 必须单调推进内部计数器，否则后续自动分配的 id 会撞车
                self._next_id = messageId + 1
        if snapshot is not None:
            role = snapshot.role
            text = "" if snapshot.parts else snapshot.text
            hasParts = bool(snapshot.parts)
            if snapshot.id != messageId:
                snapshot = snapshot.withId(messageId)
        # 判据是「有没有正文可渲染」，不是「text 是不是空串」：带 parts 的历史
        # 消息正文在 parts 里、text 是空串，只看 text 会让批量加载走同步渲染。
        deferred = (
            self._batch_depth > 0
            and role == ElaChatRoleType.Assistant
            and bool(text or hasParts)
            and not streaming
        )
        if (
            deferShell
            and self._batch_depth > 0
            and self._virtual_shells_enabled
            and not streaming
        ):
            # 大批量恢复：只落数据 + 等高占位，滚到附近才建 bubble
            message = snapshot or _with_identity(
                ElaChatMessage(
                    id=messageId,
                    role=role,
                    text=text,
                    status=ElaChatStatusType.Done,
                    created_at=time.time(),
                ),
                identity,
                mentions,
                delivery,
            )
            self._remember_message(message)
            self._empty.setVisible(False)
            if self._virtual_list_mode:
                # 超长历史：不建任何占位，只记录等高数据，由 spacer 列表按视口物化
                self._virtual_heights[message.id] = self._estimate_shell_height(message)
                self._virtual_prefix_dirty = True
                if emitAdded:
                    self.messageAdded.emit(messageId, role)
                return messageId
            self._add_shell_placeholder(message)
            self._render_queue.append(messageId)
            if emitAdded:
                self.messageAdded.emit(messageId, role)
            return messageId

        bubble = self._build_bubble(
            messageId,
            role,
            text,
            streaming,
            deferred,
            identity=(
                (snapshot.agent, snapshot.model, snapshot.model_variant)
                if snapshot is not None
                else identity
            ),
            mentions=(snapshot.mentions if snapshot is not None else mentions),
        )
        self._empty.setVisible(False)
        if snapshot is not None:
            self._remember_message(snapshot)
        else:
            status = (
                ElaChatStatusType.Streaming if streaming else ElaChatStatusType.Done
            )
            self._remember_message(
                _with_identity(
                    ElaChatMessage(
                        id=messageId,
                        role=role,
                        text=text,
                        status=status,
                        created_at=time.time(),
                        timestamp=bubble.timestamp(),
                    ),
                    identity,
                    mentions,
                    delivery,
                )
            )
        if self._virtual_list_mode and messageId not in self._virtual_bubble_ids:
            # 登记进 spacer 列表，否则 bottom spacer 会把它的高度再算一遍。
            self._virtual_bubble_ids.append(messageId)
            self._virtual_prefix_dirty = True
            if not self._virtual_window_timer.isActive():
                self._virtual_window_timer.start(0)
        if deferred:
            # 批量加载：先建骨架，Markdown 由渲染队列按时间片补齐
            bubble.setRenderDeferred(True)
            bubble.setText(text)
            self._render_queue.append(messageId)
        else:
            self._sync_parts(messageId)
        if emitAdded:
            # 恢复路径传 ``emitAdded=False``：字段 / 分段全部还原完之后再发一次，
            # 否则宿主在信号回调里读到的是半成品。
            self.messageAdded.emit(messageId, role)
        self._follow_bottom()
        return messageId

    def _build_bubble(
        self,
        messageId: int,
        role: str,
        text: str,
        streaming: bool,
        deferred: bool,
        insert_index: Optional[int] = None,
        identity=None,
        mentions=None,
    ) -> ElaChatBubble:
        """建气泡并完成全部宿主信号接线（壳虚拟化物化时复用）。"""
        bubble = ElaChatBubble(role, "" if deferred else text, self._content)
        if identity is not None:
            bubble.setIdentity(*identity)
        if mentions:
            bubble.setMentions(mentions)
        bubble.setAvatarVisible(self._avatar_visible)
        bubble.setAvatarShape(self._avatar_shape)
        if role == ElaChatRoleType.User and self._user_avatar is not None:
            bubble.setAvatarImage(self._user_avatar)
        elif role == ElaChatRoleType.Assistant and self._assistant_avatar is not None:
            bubble.setAvatarImage(self._assistant_avatar)
        bubble.setMaxWidthRatio(self._user_bubble_ratio)
        bubble.setContentMaxWidth(self._content_max_width)
        bubble.setMessageId(messageId)
        bubble.setTimestamp(datetime.now().strftime("%H:%M:%S"))
        bubble.setReasoningStyle(self._reasoning_style)
        bubble.setToolGrouping(self._tool_grouping)
        bubble.setStatsMode(self._stats_mode)
        bubble.setToolDefaultOpen(self._tool_default_open)
        bubble._disclosure = self._disclosure
        bubble.setTimelineDetail(self._timeline_detail)
        if self._retry.get(messageId) is not None:
            bubble.setRetry(*self._retry[messageId])
        bubble.setDisclaimer(self._disclaimer_text)
        bubble.setDisclaimerVisible(self._disclaimer_visible)
        bubble.setCopyNotificationEnabled(self._copy_notification_enabled)
        bubble.setWaitingPlaceholderEnabled(self._waiting_placeholder_enabled)
        has_previous = bool(self._messages) and not (
            len(self._messages) == 1 and self._messages[0].id == messageId
        )
        if role == ElaChatRoleType.User and has_previous:
            # turn 间隔：用户消息前额外留白（对齐 opencode 的 24px 节奏）
            bubble.setTopSpacing(10)
        for area in bubble.nestedScrollAreas():
            self._guard_message_viewer(messageId, area)
        bubble.viewerCreated.connect(
            lambda widget, mid=messageId: self._guard_message_viewer(mid, widget)
        )
        if streaming:
            bubble.beginStream()
        bubble.streamFinished.connect(
            lambda _=None, mid=messageId: self._on_bubble_stream_finished(mid)
        )
        bubble.copyRequested.connect(
            lambda mid=messageId: self._on_bubble_action(mid, "copy")
        )
        bubble.undoRequested.connect(
            lambda mid=messageId: self._on_bubble_action(mid, "undo")
        )
        bubble.regenerateRequested.connect(
            lambda mid=messageId: self._on_bubble_action(mid, "regenerate")
        )
        bubble.retryRequested.connect(
            lambda mid=messageId: self.retryRequested.emit(mid)
        )
        bubble.retryCancelled.connect(
            lambda mid=messageId: self.retryCancelled.emit(mid)
        )
        bubble.permissionRequested.connect(
            lambda requestId, mid=messageId: self.permissionRequested.emit(
                mid, str(requestId)
            )
        )
        bubble.permissionReplied.connect(
            lambda requestId, reply, answer, feedback, mid=messageId: (
                self.permissionReplied.emit(
                    mid, str(requestId), str(reply), str(answer), str(feedback)
                )
            )
        )
        bubble.permissionDockRequested.connect(
            lambda card, partId, mid=messageId: self.permissionDockRequested.emit(
                mid, str(partId), card
            )
        )
        bubble.permissionSettled.connect(
            lambda partId, mid=messageId: self.permissionSettled.emit(mid, str(partId))
        )
        bubble.actionTriggered.connect(
            lambda key, mid=messageId: self._on_bubble_action(mid, str(key))
        )
        bubble.attachmentClicked.connect(
            lambda path, mid=messageId: self.attachmentClicked.emit(mid, str(path))
        )
        bubble.toolToggled.connect(self._on_tool_toggled)
        self._bubbles[messageId] = bubble
        if insert_index is None:
            # spacer 虚拟列表里新气泡必须插在 bottom spacer 之前，否则会落到占位下方。
            if self._virtual_list_mode and self._virtual_bottom_spacer is not None:
                insert_index = self._content_layout.indexOf(self._virtual_bottom_spacer)
            if insert_index is None or insert_index < 0:
                insert_index = self._content_layout.count() - 1
        insert_index = max(0, min(int(insert_index), self._content_layout.count() - 1))
        self._content_layout.insertWidget(insert_index, bubble)
        self._position_activity_row()
        bubble.show()
        return bubble

    def _height_meta(self, message: ElaChatMessage) -> tuple:
        """轻量高度统计（缓存）：避免每次估算 / resize 都遍历全部 parts。"""
        cached = self._height_meta_cache.get(message.id)
        if cached is not None:
            return cached
        steps = 0
        tool = reasoning = text_parts = text_chars = 0
        stats = compaction = permission = other = 0
        for part in message.parts:
            step = max(1, int(getattr(part, "step", 1) or 1))
            if step > steps:
                steps = step
            kind = getattr(part, "kind", "")
            if kind == ElaChatPartKindType.Tool:
                tool += 1
            elif kind == ElaChatPartKindType.Reasoning:
                reasoning += 1
            elif kind == ElaChatPartKindType.Text:
                text_parts += 1
                text_chars += len(getattr(part, "text", "") or "")
            elif kind == ElaChatPartKindType.Stats:
                stats += 1
            elif kind == ElaChatPartKindType.Compaction:
                compaction += 1
            elif kind == ElaChatPartKindType.Permission:
                permission += 1
            else:
                other += 1
        if not message.parts and message.text:
            text_parts = 1
            text_chars = len(message.text)
        meta = (
            steps,
            tool,
            reasoning,
            text_parts,
            text_chars,
            stats,
            compaction,
            permission,
            other,
        )
        self._height_meta_cache[message.id] = meta
        return meta

    def _estimate_shell_height(self, message: ElaChatMessage) -> int:
        """未建壳消息的占位高度（分段统计缓存 + O(1) 估算）。"""
        width = self._content.width()
        if width <= 0:
            width = max(320, self.width() - 100)
        (
            steps,
            tool,
            reasoning,
            text_parts,
            text_chars,
            stats,
            compaction,
            permission,
            other,
        ) = self._height_meta(message)
        chars_per_line = max(24, width // 8)
        lines = (text_chars + chars_per_line - 1) // chars_per_line if text_chars else 0
        stats_height = 24 if self._stats_mode == "steps" else 0
        total = (
            steps * 28
            + tool * 40
            + reasoning * 36
            + text_parts * 12
            + lines * 22
            + stats * stats_height
            + compaction * 64
            + permission * 96
            + other * 40
        )
        return max(40, total + 110)

    def removeMessage(self, messageId: int) -> None:
        """移除指定消息（非 int id 抛 ``TypeError``；严格模式下不存在抛 ``KeyError``）。"""
        # 删消息前必须先作废未答复审批：交互卡在 dock 上，气泡删了卡还活着，
        # 用户点一下就会走进已销毁对象（0xC0000409）。
        self._require_int_id(messageId, "removeMessage")
        bubble = self._bubbles.get(messageId)
        virtual_exists = self._virtual_list_mode and messageId in self._message_index
        if (
            bubble is None
            and messageId not in self._shell_placeholders
            and not virtual_exists
        ):
            if self._strict_ids:
                raise KeyError(f"removeMessage：消息 id {messageId!r} 不存在")
            return
        if bubble is not None:
            bubble.cancelPendingPermissions()
        if not self._detach_message(messageId):
            return
        self._store.remove(messageId)
        self._virtual_prefix_dirty = True
        self._virtual_order_dirty = True
        if not self._messages:
            self._empty.setVisible(True)
        self.messageRemoved.emit(messageId)
        self._update_jump_button()

    def removeMessagesFrom(self, messageId: int) -> list:
        """批量移除 id >= ``messageId`` 的全部消息（撤回 / 重新生成用）。

        单趟过滤消息列表，避免逐条删除的 O(n²) 重建；每条仍发 ``messageRemoved``。

        :returns: 被移除的消息 id 列表（按原顺序）
        """
        self._require_int_id(messageId, "removeMessagesFrom")
        removed = [m.id for m in self._messages if m.id >= messageId]
        if not removed:
            return []
        removed_set = set(removed)
        # 两趟：先作废全部待答复审批，再摘气泡。取消会同步发 ``permissionSettled``
        # 触发 dock promote，边取消边摘会让 promote 拿到马上要删的卡。
        for mid in removed:
            bubble = self._bubbles.get(mid)
            if bubble is not None:
                bubble.cancelPendingPermissions()
        for mid in removed:
            self._detach_message(mid)
        self._store.remove_ids(removed_set)
        self._virtual_prefix_dirty = True
        self._virtual_order_dirty = True
        if not self._messages:
            self._empty.setVisible(True)
        self._update_jump_button()
        for mid in removed:
            self.messageRemoved.emit(mid)
        return removed

    def clear(self) -> None:
        """清空全部消息（恢复空态）。"""
        # 同 removeMessagesFrom：先作废全部待答复审批（两趟），避免 promote
        # 拿到马上要被销毁的气泡里的交互卡。
        bubbles = list(self._bubbles.values())
        for bubble in bubbles:
            bubble.cancelPendingPermissions()
        for bubble in bubbles:
            bubble.hide()
            bubble.setParent(None)
            bubble.deleteLater()
        for placeholder in self._shell_placeholders.values():
            self._content_layout.removeWidget(placeholder)
            placeholder.hide()
            placeholder.setParent(None)
            placeholder.deleteLater()
        self._shell_placeholders.clear()
        self._shell_recycling = False
        if self._virtual_top_spacer is not None:
            self._content_layout.removeWidget(self._virtual_top_spacer)
            self._virtual_top_spacer.hide()
            self._virtual_top_spacer.setParent(None)
            self._virtual_top_spacer.deleteLater()
            self._virtual_top_spacer = None
        if self._virtual_bottom_spacer is not None:
            self._content_layout.removeWidget(self._virtual_bottom_spacer)
            self._virtual_bottom_spacer.hide()
            self._virtual_bottom_spacer.setParent(None)
            self._virtual_bottom_spacer.deleteLater()
            self._virtual_bottom_spacer = None
        self._virtual_list_mode = False
        self._virtual_window_timer.stop()
        self._virtual_heights.clear()
        self._virtual_bubble_ids.clear()
        self._bubbles.clear()
        self._store.clear()
        self._virtual_order.clear()
        self._virtual_prefix.clear()
        self._virtual_prefix_dirty = True
        self._virtual_order_dirty = True
        self._render_queue.clear()
        self._render_timer.stop()
        # 渐进渲染被打断时必须自己收尾：``beginBatch`` 关掉了视口刷新，而恢复
        # 只在 ``_finish_batch_render`` 里；这里清空队列后再没人走到那里，视口
        # 就永久不再重绘。``_batch_depth > 0`` 时 ``endBatch`` 会兜住。
        if self._batch_depth <= 0 and not self._scroll.viewport().updatesEnabled():
            self._scroll.viewport().setUpdatesEnabled(True)
            self._scroll.viewport().update()
            self._content_layout.activate()
        self._suspended_ids.clear()
        self._suspension_timer.stop()
        self._lazy_ids.clear()
        self._lazy_timer.stop()
        self._loading_older = False
        self._pending_anchor = None
        self._batch_eager_rendered = 0
        for guards in self._guards_by_message.values():
            for guard in guards:
                try:
                    self._scroll_guards.remove(guard)
                except ValueError:
                    pass
        self._guards_by_message.clear()
        self._disclosure.clear()
        self._retry.clear()
        self._activity_text = ""
        self.clearSearch()
        if getattr(self, "_activity_row", None) is not None:
            self._activity_row.setText("")
            self._activity_row.hide()
        self._empty.setVisible(True)
        self._update_jump_button()

    def _detach_message(self, messageId: int) -> bool:
        """摘除单条消息的气泡 / 占位与相关引用；返回消息是否存在。"""
        placeholder = self._shell_placeholders.pop(messageId, None)
        bubble = self._bubbles.pop(messageId, None)
        virtual_exists = self._virtual_list_mode and messageId in self._message_index
        if bubble is None and placeholder is None and not virtual_exists:
            return False
        if placeholder is not None:
            self._content_layout.removeWidget(placeholder)
            placeholder.hide()
            placeholder.setParent(None)
            placeholder.deleteLater()
        if bubble is not None:
            self._content_layout.removeWidget(bubble)
            bubble.hide()
            bubble.setParent(None)
            bubble.deleteLater()
        if self._virtual_list_mode:
            if messageId in self._virtual_bubble_ids:
                self._virtual_bubble_ids.remove(messageId)
            self._virtual_heights.pop(messageId, None)
            self._virtual_prefix_dirty = True
            if not self._virtual_window_timer.isActive():
                self._virtual_window_timer.start(0)
        message = self._store.message(messageId)
        if message is not None:
            for part in message.parts:
                self._disclosure.pop(part.id, None)
        self._retry.pop(messageId, None)
        self._dirty_syncs.discard(messageId)
        self._suspended_ids.discard(messageId)
        if messageId in self._lazy_ids:
            self._lazy_ids.remove(messageId)
        try:
            self._render_queue.remove(messageId)
        except ValueError:
            pass
        for guard in self._guards_by_message.pop(messageId, ()):
            try:
                self._scroll_guards.remove(guard)
            except ValueError:
                pass
        return True

    def _remember_message(self, message: ElaChatMessage) -> None:
        """追加快照并维护 id 索引 / 高度缓存失效。"""
        self._store.add(message)
        self._virtual_prefix_dirty = True
        self._virtual_order_dirty = True

    def _reindex_messages(self) -> None:
        """重建 id → 下标 / 快照索引（列表结构变化后调用）。"""
        self._store.reindex()

    def _update_snapshot(self, messageId: int, updater) -> None:
        if not self._store.update(messageId, updater):
            return
        self._virtual_prefix_dirty = True

    def _sync_parts(self, messageId: int) -> None:
        """标记助手消息的分段快照待同步（读取时统一结算）。

        ``withParts`` 重算推迟到读快照前，宿主不读时零开销。快照里的 ``text``
        只含已落定内容，流式期间读为空串（实时预览读 ``bubble(id).text()``）。
        无 parts、派生字段只在消息级的旧格式消息不参与同步（会被抹掉）。
        """
        bubble = self._bubbles.get(messageId)
        if bubble is None or bubble.role() != ElaChatRoleType.Assistant:
            return
        if self._is_legacy_derived(self._store.message(messageId)):
            return
        self._dirty_syncs.add(messageId)

    @staticmethod
    def _is_legacy_derived(message) -> bool:
        """是否「无 parts、派生字段只存在消息级」的旧格式助手消息。"""
        return bool(
            message is not None
            and not message.parts
            and (
                message.stats is not None
                or message.tool_calls
                or message.reasoning
                or message.reasoning_ms
            )
        )

    def _flush_pending_syncs(self) -> None:
        """结算全部待同步的分段快照（单趟遍历，避免 O(脏条数 × 总条数)）。"""
        if not self._dirty_syncs:
            return
        dirty = self._store.take_dirty()
        for index, message in enumerate(self._messages):
            if message.id not in dirty:
                continue
            bubble = self._bubbles.get(message.id)
            if bubble is None or bubble.role() != ElaChatRoleType.Assistant:
                continue
            if self._is_legacy_derived(message):
                continue
            updated = message.withParts(bubble.parts())
            self._store.replace_at(index, updated)
            self._virtual_prefix_dirty = True

    def _on_bubble_stream_finished(self, messageId: int) -> None:
        bubble = self._bubbles.get(messageId)
        status = bubble.status() if bubble is not None else ElaChatStatusType.Done
        # endStream 会同步结束正文段，需一并同步到快照，否则 parts 里仍残留 streaming。
        self._sync_parts(messageId)
        self._update_snapshot(messageId, lambda m: m.withStatus(status))
        self.messageStreamFinished.emit(messageId, status)
        self._follow_bottom()

    def _on_bubble_action(self, messageId: int, action: str) -> None:
        self.messageActionTriggered.emit(messageId, action)
        if action == "copy":
            self.copyRequested.emit(messageId)
        elif action == "undo":
            self.undoRequested.emit(messageId)
        elif action == "regenerate":
            self.regenerateRequested.emit(messageId)
        elif action == "pending_queue":
            self.pendingUserActionRequested.emit(messageId, "queue")
        elif action == "pending_delete":
            self.pendingUserActionRequested.emit(messageId, "delete")
