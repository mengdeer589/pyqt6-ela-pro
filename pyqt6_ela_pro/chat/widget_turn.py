"""聊天回合生命周期与消息动作方法组。"""

from __future__ import annotations

from typing import Optional

from ..ela_confirm_dialog import ElaConfirmDialog
from .message import ElaChatMessage, ElaChatRoleType, ElaChatStatusType


class _WidgetTurnMixin:
    def sendUserMessage(
        self,
        text: str,
        attachments=None,
        messageId: Optional[int] = None,
        *,
        mentions=None,
        agent: str = "",
        model: str = "",
        modelVariant: str = "",
    ) -> Optional[int]:
        """添加用户消息并进入生成状态；返回消息 id（空文本返回 ``None``）。
        ``messageId`` 为幂等键：消息仍存在时直接返回既有 id，不重复建消息、不重复发
        ``messageSubmitted``。已有流式消息时先按 ``Stopped`` 收尾并发 ``stopRequested``，
        """
        text = (text or "").strip()
        if not text:
            return None
        if messageId is not None:
            existing = self._view.message(messageId)
            if existing is not None:
                return existing.id
        if self._streaming_id is not None:
            # 先就地收尾旧流再通知宿主：宿主可能在 stopRequested 槽里同步
            # 走完 binder.finish(turn)，其末尾会续发排队消息 —— 不压住就会把
            # 队首消息抢在新消息前面发出（顺序错乱，且队首回合立刻被截断）。
            self._endActiveStream(ElaChatStatusType.Stopped)
            with self._autoSendPaused():
                self.stopRequested.emit()
        if messageId is None:
            messageId = self._view.addMessage(ElaChatRoleType.User, text)
        else:
            # 外部 id 且尚不存在：用该 id 建消息（乐观 UI 先行渲染的路径）
            messageId = self._view.addMessage(
                ElaChatRoleType.User, text, messageId=messageId
            )
        if mentions:
            self._view.setMessageMentions(messageId, mentions)
        if agent or model or modelVariant:
            self._view.setMessageIdentity(messageId, agent, model, modelVariant)
        if self._user_title:
            self._view.setMessageTitle(messageId, self._user_title)
        if attachments:
            self._view.setMessageAttachments(messageId, attachments)
        self.setGenerating(True)
        self.messageSubmitted.emit(text)
        self.messageSubmittedFull.emit(text, list(attachments or []))
        return messageId

    def _on_input_submitted(self, text: str, attachments: list) -> None:
        mentions = self._input.mentionSpans()
        if self._generating and self._queue_enabled:
            self.enqueueMessage(text, attachments, mentions=mentions)
            return
        self.sendUserMessage(text, attachments, mentions=mentions)

    def _on_alternate_submitted(self, text: str, attachments: list) -> None:
        """``Ctrl+Enter``：生成中走插话，空闲时普通发送。"""
        if self._generating:
            self.steerMessage(text, attachments)
        else:
            self.sendUserMessage(text, attachments)

    def _on_pending_user_action(self, messageId: int, action: str) -> None:
        """待发送消息上的「移到队列 / 删除」。"""
        message = self._view.message(messageId)
        if message is None:
            return
        if action == "queue":
            self.enqueueMessage(
                message.text,
                message.attachments,
                mentions=message.mentions,
            )
            self._view.resolvePendingUserMessage(messageId, sent=False)
        elif action == "delete":
            self._view.resolvePendingUserMessage(messageId, sent=False)
        self.pendingUserActionRequested.emit(messageId, action)

    def _hasClearableContent(self) -> bool:
        """会话是否有东西可清（消息 / 排队消息 / 生成中）——「清空」的前提。"""
        return bool(self._view.count() or self._queue or self._generating)

    def _on_clear_requested(self) -> None:
        # 空会话直接返回：不弹框，也不发 clearRequested —— 宿主拿它做「等待确认」
        # 之类的提示 / 埋点，发了却什么都不弹，提示就永远挂在那儿
        if not self._hasClearableContent():
            return
        # 先发公共信号通知宿主，再走默认「弹框确认 → 清空」链路
        self.clearRequested.emit()
        self.requestClear()

    def requestClear(self) -> None:
        """「清空上下文」入口：先弹 :class:`ElaConfirmDialog` 确认再 :meth:`clear`。
        锚点是输入区（贴在窗口底部，锚整窗会把弹框算到屏幕外），``position="top"``
        摆在输入卡片上方。
        """
        if not self._hasClearableContent():
            return  # 已经是空会话，无需确认
        confirmed = ElaConfirmDialog.show(
            self._input,
            "清空上下文",
            "确定要清空当前对话吗？此操作不可撤销。",
            position="top",
        )
        if confirmed:
            self.clear()

    def clear(self) -> None:
        """清空整个会话：中止生成 -> 停流 -> 清队列 -> 清消息 -> 发 ``cleared``。
        顺序要紧：先 ``stopRequested`` 让宿主 cancel 后端，再停流，否则后端还会往
        已清空的消息里发分片。只清组件侧，后端会话归宿主（接 ``cleared`` 后自行
        """
        with self._autoSendPaused():
            if self._generating or self._streaming_id is not None:
                self.stopGeneration()
            self._streaming_id = None
            self.setGenerating(False)
            self.clearQueue()
            # 插话属于**被中止的那一轮**：留着会在新会话的下一个 step 边界
            # 被自动投递（旧指令静默重放给模型），必须一起清
            self.clearSteer()
            self._finished_generation.clear()
            # 会话没了，两个 dock 都要清（审批卡对应的消息已经不存在）
            self.clearDock()
            self.clearPermissionDock()
            self._view.clear()
        self.cleared.emit()

    def setMessageError(
        self, message: str, messageId: Optional[int] = None, errorType: str = ""
    ) -> None:
        """给消息设置错误文本与类型；若是当前流式消息则同时结束生成状态。
        ``generating`` 必须随之落下，否则状态栏一直停在「生成中」、``autoSendQueue``
        也排不出下一条。
        """
        target = self._streaming_id if messageId is None else messageId
        if target is None:
            return
        self._view.setMessageError(target, message, errorType)
        if message and target == self._streaming_id:
            self._finishErrorTurn(target, ElaChatStatusType.Error)

    def removeMessage(self, messageId: int) -> None:
        """移除指定消息；若是当前流式消息则先结束生成状态。"""
        if messageId == self._streaming_id:
            self._streaming_id = None
            self.setGenerating(False)
        # 删消息前必须先 abort 该消息里的未答复审批，否则 dock 上会留下一张
        # 指向已不存在消息的死卡（用户点了没有任何回音）。
        bubble = self._view.bubble(messageId)
        if bubble is not None:
            bubble.cancelPendingPermissions()
        self._finished_generation.discard(messageId)
        self._view.removeMessage(messageId)

    def beginAssistantMessage(
        self, *, agent: str = "", model: str = "", modelVariant: str = ""
    ) -> int:
        """开始一条助手流式消息；返回消息 id。
        防御：若已有消息在流式生成（宿主直接调用且未先结束），先把上一条按
        ``Stopped`` 收尾（不发 ``stopRequested``、不触发排队续发）。
        """
        if self._streaming_id is not None:
            self._endActiveStream(ElaChatStatusType.Stopped)
        messageId = self._view.beginMessage(
            ElaChatRoleType.Assistant,
            agent=agent,
            model=model,
            modelVariant=modelVariant,
        )
        if self._assistant_title:
            self._view.setMessageTitle(messageId, self._assistant_title)
        self._streaming_id = messageId
        self.setGenerating(True)
        self.generationStarted.emit(messageId)
        return messageId

    def stepCount(self, messageId: Optional[int] = None) -> int:
        """获取指定消息（默认最后一条）的步骤数。"""
        target = self._resolve_message_id(messageId)
        if target is None:
            return 0
        message = self._view.message(target)
        return message.stepCount if message is not None else 0

    def toolPanels(self, messageId: Optional[int] = None) -> list:
        """获取指定消息（默认最后一条）的各步骤工具面板。"""
        target = self._resolve_message_id(messageId)
        bubble = self._view.bubble(target) if target is not None else None
        return bubble.toolPanels() if bubble is not None else []

    def endAssistantMessage(
        self,
        messageId: Optional[int] = None,
        status: str = ElaChatStatusType.Done,
    ) -> Optional[int]:
        """结束助手消息（默认当前流式消息）；返回消息 id。
        先发 ``generationFinished``，若开启 ``autoSendQueue``（默认）再自动发送队首。
        **幂等**：已被 ``stopGeneration`` 收尾过的消息只补状态与排队续发，不重发信号。
        """
        target = self._streaming_id if messageId is None else messageId
        if target is None:
            self.setGenerating(False)
            if self._auto_send_queue:
                self.sendNextQueued()
            return None
        message = self._view.message(target)
        if (
            message is not None
            and message.status == ElaChatStatusType.Error
            and status == ElaChatStatusType.Done
        ):
            # 已出错的消息不被缺省的「完成」覆盖：按实际状态补发收尾信号
            return self._finishErrorTurn(target, ElaChatStatusType.Error)
        if message is not None and message.isStreaming:
            self._view.endMessage(target, status)
        if target == self._streaming_id:
            self._streaming_id = None
        self.setGenerating(False)
        self._emit_generation_finished(target, status)
        if self._auto_send_queue:
            self.sendNextQueued()
        return target

    def _emit_generation_finished(self, target: int, status: str) -> None:
        """发 ``generationFinished``（同一条消息只发一次，避免重复收尾）。"""
        if target in self._finished_generation:
            return
        self._finished_generation.add(target)
        self.generationFinished.emit(target, status)

    def _finishErrorTurn(self, target: int, status: str) -> int:
        """错误回合的收尾：落 generating、发 ``generationFinished``、排空队列。
        不发收尾信号并排空队列，``autoSendQueue`` 就发不出下一条、状态栏一直停在
        「生成中」。
        """
        if target == self._streaming_id:
            self._streaming_id = None
        self.setGenerating(False)
        self._emit_generation_finished(target, status)
        if self._auto_send_queue:
            self.sendNextQueued()
        return target

    def _endActiveStream(self, status: str) -> Optional[int]:
        """结束当前流式消息（不发 ``stopRequested``、不触发排队续发）。
        供 :meth:`sendUserMessage` / :meth:`beginAssistantMessage` 在开始新流前收尾
        旧流；返回被结束的消息 id（无流式消息返回 ``None``）。
        """
        target = self._streaming_id
        if target is None:
            return None
        self._streaming_id = None
        message = self._view.message(target)
        if message is not None and message.status == ElaChatStatusType.Error:
            # 错误来自 ``view.setMessageError``（widget 并不知道）：不能再用
            # 缺省的 ``Stopped`` 覆盖，收尾信号与文案都按实际状态走
            status = ElaChatStatusType.Error
        if message is None or message.isStreaming:
            self._view.endMessage(target, status)
        self.setGenerating(False)
        if self._steer:
            self.clearSteer()
        self._emit_generation_finished(target, status)
        return target

    def streamingMessageId(self) -> Optional[int]:
        """当前正在流式生成的消息 id；无则 ``None``。
        与 :meth:`isGenerating` 独立：``_generating`` 可能已 False 而流式消息尚未
        收尾，宿主需要据此判断是否还要收尾。
        """
        return self._streaming_id

    def _resolve_message_id(self, messageId: Optional[int]) -> Optional[int]:
        if messageId is not None:
            return messageId
        if self._streaming_id is not None:
            return self._streaming_id
        last = self._view.lastMessage()
        return last.id if last is not None else None

    def stopGeneration(self) -> None:
        """请求停止生成：就地收尾当前流式消息，再发 ``stopRequested``。"""
        if not self._generating and self._streaming_id is None:
            return
        # 先就地收尾旧流再通知宿主：stopRequested 的宿主槽往往会 cancel() +
        # finish()，finish() 之后会自动续发排队消息，此时 _streaming_id 已指向
        # **新**消息 —— 反过来会把刚发出的续发回合立刻置成 stopped。
        target = self._endActiveStream(ElaChatStatusType.Stopped)
        if target is None:
            self.setGenerating(False)
        self.stopRequested.emit()

    def setGenerating(self, on: bool) -> None:
        """设置生成状态（输入区按钮在发送/停止间切换）。"""
        self._generating = bool(on)
        self._input.setGenerating(self._generating)
        self._queue_dock.setWorking(self._generating)

    def isGenerating(self) -> bool:
        """是否正在生成。"""
        return self._generating

    def addMessage(self, role: str, text: str = "") -> int:
        """添加一条普通消息（用户 / 助手 / 系统）；返回消息 id。"""
        messageId = self._view.addMessage(role, text)
        if role == ElaChatRoleType.User and self._user_title:
            self._view.setMessageTitle(messageId, self._user_title)
        elif role == ElaChatRoleType.Assistant and self._assistant_title:
            self._view.setMessageTitle(messageId, self._assistant_title)
        return messageId

    def undoMessage(self, messageId: int) -> Optional[ElaChatMessage]:
        """撤回消息：删除该条及其后全部消息，并把原文 / 附件回填输入框。

        只对用户消息生效：目标不是用户消息或不存在时返回 ``None`` 且不做改动
        （否则会删掉 AI 回复、再把它的文本回填进输入框）。

        :returns: 被撤回的目标消息快照（不存在 / 非用户消息返回 ``None``）
        """
        target = self._view.message(messageId)
        if target is None or not target.isUser:
            return None
        if self._streaming_id is not None and self._streaming_id >= messageId:
            self._streaming_id = None
            self.setGenerating(False)
        self._view.removeMessagesFrom(messageId)
        self._finished_generation = {
            item for item in self._finished_generation if item < messageId
        }
        self._input.setText(target.text)
        self._input.setAttachments(target.attachments)
        return target

    def undoLastUserMessage(self) -> Optional[ElaChatMessage]:
        """撤回**最后一条用户消息**：删除该条及其后全部消息，回填输入框。

        自行从末尾往前找最近一条用户消息（跳过其后的助手回答），直接对
        ``messages()[-1]`` 调 :meth:`undoMessage` 会被拒绝。

        :returns: 被撤回的用户消息快照；没有用户消息时返回 ``None`` 且不做改动
        """
        target = None
        for message in self._view.messages():
            if message.isUser:
                target = message
        if target is None:
            return None
        return self.undoMessage(target.id)

    def regenerateFrom(self, messageId: int) -> Optional[ElaChatMessage]:
        """重新生成准备：删除该回答及其后消息，返回其之前的用户消息快照
        （宿主随后 ``beginAssistantMessage()`` 并重跑后端）；找不到前置用户消息时
        不删除任何消息并返回 ``None``。
        """
        userMessage = None
        for message in self._view.messages():
            if message.id >= messageId:
                break
            if message.isUser:
                userMessage = message
        if userMessage is None:
            return None
        if self._streaming_id is not None and self._streaming_id >= messageId:
            self._streaming_id = None
            self.setGenerating(False)
        self._view.removeMessagesFrom(messageId)
        self._finished_generation = {
            item for item in self._finished_generation if item < messageId
        }
        return userMessage

    def retryMessage(self, messageId: int) -> Optional[ElaChatMessage]:
        """重试准备：清掉该回答的错误（状态落成 ``Stopped``，保留失败记录与位置）。

        与 :meth:`regenerateFrom` 的区别是不删消息：宿主拿到提问快照后调
        ``beginAssistantMessage()`` 新建一条回答，失败的那条作为记录留在时间线上。

        :returns: 提问的用户消息快照；找不到前置用户消息时返回 ``None`` 且不做改动
        """
        userMessage = None
        for message in self._view.messages():
            if message.id >= messageId:
                break
            if message.isUser:
                userMessage = message
        if userMessage is None:
            return None
        if self._streaming_id == messageId:
            self._streaming_id = None
            self.setGenerating(False)
        self._view.clearMessageError(messageId)
        return userMessage
