"""消息流式 API / 审批 / 错误与字段更新方法组（从 ``ElaChatView`` 拆出）。"""

from __future__ import annotations


from typing import Optional


from .message import (
    ElaChatPermission,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
)


class _ViewStreamMixin:
    """方法组 mixin：状态由 ``ElaChatView.__init__`` 建立。"""

    def appendText(self, messageId: int, chunk: str) -> None:
        """向指定消息追加流式正文（助手消息为 Markdown）。"""
        bubble = self._require_bubble(messageId, "appendText")
        if bubble is None or not chunk:
            return
        bubble.appendText(chunk)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def beginText(self, messageId: int) -> Optional[str]:
        """开始指定消息的新正文段，返回分段 id（非助手消息返回 ``None``）。"""
        bubble = self._require_bubble(messageId, "beginText")
        if bubble is None:
            return None
        partId = bubble.beginText()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()
        return partId

    def endText(self, messageId: int) -> None:
        """结束指定消息的当前正文段（停止流式光标）。"""
        bubble = self._require_bubble(messageId, "endText")
        if bubble is None:
            return
        bubble.endText()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def updateMessage(self, messageId: int, text: str) -> None:
        """整体替换消息文本。"""
        bubble = self._require_bubble(messageId, "updateMessage")
        if bubble is None:
            return
        bubble.setText(text)
        if bubble.role() == ElaChatRoleType.Assistant:
            self._sync_parts(messageId)
        else:
            self._update_snapshot(messageId, lambda message: message.withText(text))
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def endMessage(self, messageId: int, status: str = ElaChatStatusType.Done) -> None:
        """结束指定消息的流式生成。"""
        bubble = self._require_bubble(messageId, "endMessage")
        if bubble is None:
            return
        bubble.endStream(status)

    def beginStep(self, messageId: int) -> Optional[int]:
        """开始指定助手消息的新步骤，返回步骤序号。

        仅推进步骤序号（分段未变），仍发出 ``messageUpdated`` 便于宿主
        统一观察消息变化。
        """
        bubble = self._require_bubble(messageId, "beginStep")
        if bubble is None:
            return None
        step = bubble.beginStep()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        return step

    def beginReasoning(self, messageId: int) -> None:
        """开始指定消息的思考阶段（展开「思考中」）。"""
        bubble = self._require_bubble(messageId, "beginReasoning")
        if bubble is None:
            return
        bubble.beginReasoning()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def appendReasoning(self, messageId: int, chunk: str) -> None:
        """向指定消息追加思考文本（流式）。"""
        bubble = self._require_bubble(messageId, "appendReasoning")
        if bubble is None or not chunk:
            return
        bubble.appendReasoning(chunk)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def endReasoning(self, messageId: int, durationMs: Optional[float] = None) -> None:
        """结束指定消息的思考阶段（显示耗时并收起）。"""
        bubble = self._require_bubble(messageId, "endReasoning")
        if bubble is None:
            return
        bubble.endReasoning(durationMs)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def setReasoning(
        self,
        messageId: int,
        text: str,
        durationMs: Optional[float] = None,
    ) -> None:
        """整体设置指定消息的思考内容。"""
        bubble = self._require_bubble(messageId, "setReasoning")
        if bubble is None:
            return
        bubble.setReasoning(text, durationMs)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def addToolCall(
        self,
        messageId: int,
        name: str,
        arguments: str = "",
        toolCallId: Optional[str] = None,
        *,
        metadata=None,
    ) -> Optional[str]:
        """为指定消息添加工具调用卡片，返回调用 id。

        ``metadata`` 是结构化附加数据（文件变更 / shell 状态 / 诊断等），
        会原样进入渲染器上下文与工具调用快照。
        """
        bubble = self._require_bubble(messageId, "addToolCall")
        if bubble is None:
            return None
        if metadata is not None:
            call = ElaChatToolCall(
                id=str(toolCallId or ""),
                name=str(name or ""),
                arguments=str(arguments or ""),
                status=ElaChatToolStatusType.Running,
                metadata=dict(metadata) if isinstance(metadata, dict) else {},
            )
            callId = bubble.addToolCall(
                name, arguments, toolCallId, tool_call=call
            )
        else:
            callId = bubble.addToolCall(name, arguments, toolCallId)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        self._follow_bottom()
        return callId

    def setToolCallResult(
        self,
        messageId: int,
        toolCallId: str,
        result: str,
        ok: bool = True,
    ) -> None:
        """更新指定工具调用的结果。"""
        bubble = self._require_bubble(messageId, "setToolCallResult")
        if bubble is None:
            return
        bubble.setToolCallResult(toolCallId, result, ok=ok)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def toolCalls(self, messageId: int) -> list:
        """获取指定消息的工具调用快照列表。"""
        self._require_int_id(messageId, "toolCalls")
        bubble = self._bubbles.get(messageId)
        return bubble.toolCalls() if bubble is not None else []

    def clearToolCalls(self, messageId: int) -> None:
        """清空指定消息的工具调用卡片。"""
        bubble = self._require_bubble(messageId, "clearToolCalls")
        if bubble is None:
            return
        bubble.clearToolCalls()
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def addSteerNotice(self, messageId: int, text: str) -> str:
        """在指定消息内追加一条插话回执，返回分段 id。

        插话（steer）= 生成中把新指令**送进正在跑的这一轮**，而不是排队等
        它跑完。回执留在同一条助手消息内（``↳ <text>``），不插用户气泡。
        """
        bubble = self._require_bubble(messageId, "addSteerNotice")
        if bubble is None:
            return ""
        partId = bubble.addSteerNotice(text)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        return partId

    def beginCompaction(
        self, messageId: int, reason: str = "auto", *, queued: bool = False
    ) -> str:
        """标记一次上下文压缩开始（``queued=True`` 表示已排队、尚未开跑），返回分段 id。

        **库不实现压缩算法**（摘要 / 收缩循环 / 词元估算都在 provider 侧），
        只在时间线上如实表达「这里发生过压缩」并接住摘要。

        ``reason`` 只进 journal 原始事件（诊断用），时间线卡片不展示它。
        """
        bubble = self._require_bubble(messageId, "beginCompaction")
        if bubble is None:
            return ""
        partId = bubble.beginCompaction(reason, queued=queued)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        return partId

    def appendCompactionSummary(self, messageId: int, partId: str, chunk: str) -> None:
        """追加压缩摘要（流式）。"""
        bubble = self._bubbles.get(messageId)
        if bubble is None or not partId or not chunk:
            return
        bubble.appendCompactionSummary(partId, chunk)
        self._dirty_syncs.add(messageId)
        self.messageUpdated.emit(messageId)

    def endCompaction(
        self,
        messageId: int,
        partId: str,
        status: str = ElaChatStatusType.Done,
        historyCount: int = 0,
        *,
        stats=None,
    ) -> None:
        """结束压缩并落定摘要（``stats`` 为压缩请求本身的用量）。"""
        bubble = self._require_bubble(messageId, "endCompaction")
        if bubble is None:
            return
        bubble.endCompaction(partId, status, historyCount, stats=stats)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def beginPermission(self, messageId: int, request) -> str:
        """在指定消息内插入一张工具审批卡，返回分段 id。

        **只画卡 + 发 ``permissionRequested``，绝不阻塞** —— 在 Qt 里挂起等
        用户点按钮会卡死事件循环。宿主拿到信号后自行挂起后端，用户点完卡片
        后组件发 ``permissionReplied``。「始终允许」的规则也归宿主持久化。

        :param request: :class:`~pyqt6_ela_pro.chat.message.ElaChatPermission`
            或等价的 ``dict``（会被 ``fromDict`` 转换）
        """
        bubble = self._require_bubble(messageId, "beginPermission")
        if bubble is None:
            return ""
        if isinstance(request, dict):
            request = ElaChatPermission.fromDict(request)
        if request is None:
            return ""
        partId = bubble.beginPermission(request)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)
        return partId

    def resolvePermission(
        self,
        messageId: int,
        requestId: str,
        reply: str,
        answer: str = "",
        feedback: str = "",
    ) -> bool:
        """以编程方式落定一次审批（对应卡片按钮）；找不到返回 ``False``。"""
        bubble = self._require_bubble(messageId, "resolvePermission")
        if bubble is None:
            return False
        ok = bubble.resolvePermission(requestId, reply, answer, feedback)
        if ok:
            self._sync_parts(messageId)
            self.messageUpdated.emit(messageId)
        return ok

    def pendingPermissions(self, messageId: int) -> list:
        """获取指定消息仍在等待用户回复的审批请求。"""
        self._require_int_id(messageId, "pendingPermissions")
        bubble = self._bubbles.get(messageId)
        return bubble.pendingPermissions() if bubble is not None else []

    def permissionCard(self, messageId: int, requestId: str):
        """取审批卡控件（宿主可改文案 / 挂事件；不存在返回 ``None``）。"""
        self._require_int_id(messageId, "permissionCard")
        bubble = self._bubbles.get(messageId)
        return bubble.permissionCard(requestId) if bubble is not None else None

    def permissionAnswers(self, messageId: int, requestId: str) -> dict:
        """取问答型审批的答案（``{key: [label, ...]}``；未答的 key 不在字典里）。

        批准型、或该请求不存在 / 已落定无答案时返回**空字典**。

        与 ``permissionReplied.answer`` 的区别：那条信号给的是**已编码**的 JSON 串
        （单选塌缩成标量），这里给的是**未塌缩**的原始分组形式 —— 宿主在
        「等用户答完、还没点提交」的中间态想知道当前进度时用它（用户答到一半
        可能切走、关窗口，这时候连信号都没发过）。

        **优先读 dock 上的交互卡**（等待期），落定后才退回时间线上的记录卡
        （那时记录卡已无交互态，答案只能从已落定的载荷里取）。
        """
        self._require_int_id(messageId, "permissionAnswers")
        card = self.interactivePermissionCard(messageId, requestId)
        if card is not None:
            return card.answers()
        permission = self._permission_of(messageId, requestId)
        if permission is None:
            return {}
        settled = permission.parsedAnswer()
        return {
            question.key: (list(value) if isinstance(value, list) else [value])
            for question in permission.questions
            if (value := settled.get(question.key)) is not None
        }

    def interactivePermissionCard(self, messageId: int, requestId: str):
        """取**仍在 dock 里等待用户操作**的交互卡（不在 dock 阶段返回 ``None``）。"""
        self._require_int_id(messageId, "interactivePermissionCard")
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            return None
        for partId, permission in bubble.pendingPermissionParts():
            if permission.request_id == requestId:
                return bubble.interactivePermissionCard(partId)
        return None

    def _permission_of(self, messageId: int, requestId: str):
        """按 ``requestId`` 取审批载荷快照（不存在返回 ``None``）。"""
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            return None
        for part in bubble.parts():
            if part.permission is not None and part.permission.request_id == requestId:
                return part.permission
        return None

    def setMessageAttachments(self, messageId: int, attachments) -> None:
        """整体替换指定消息的附件。"""
        bubble = self._require_bubble(messageId, "setMessageAttachments")
        if bubble is None:
            return
        bubble.setAttachments(attachments)
        self._update_snapshot(
            messageId, lambda m: m.withAttachments(bubble.attachments())
        )
        self.messageUpdated.emit(messageId)
        self._follow_bottom()

    def addMessageAttachment(
        self, messageId: int, name: str, path: str = "", size: int = 0
    ) -> None:
        """为指定消息追加一个附件。"""
        bubble = self._require_bubble(messageId, "addMessageAttachment")
        if bubble is None:
            return
        bubble.addAttachment(name, path, size)
        self._update_snapshot(
            messageId, lambda m: m.withAttachments(bubble.attachments())
        )
        self.messageUpdated.emit(messageId)

    def setStepStats(self, messageId: int, stats: Optional[ElaChatStats]) -> None:
        """设置指定消息当前步骤的用量统计（``None`` 移除徽标）。"""
        bubble = self._require_bubble(messageId, "setStepStats")
        if bubble is None:
            return
        bubble.setStepStats(stats)
        self._sync_parts(messageId)
        self.messageUpdated.emit(messageId)

    def setMessageDuration(self, messageId: int, durationMs: float) -> None:
        """设置指定消息的总耗时（显示在底部 meta 层，同时发出 ``messageUpdated``）。"""
        bubble = self._require_bubble(messageId, "setMessageDuration")
        if bubble is None:
            return
        bubble.setDuration(durationMs)
        self._update_snapshot(messageId, lambda m: m.withDuration(durationMs))
        self.messageUpdated.emit(messageId)

    def setMessageError(
        self, messageId: int, message: str, errorType: str = ""
    ) -> None:
        """设置指定消息的错误文本与类型。

        :param message: 面向用户的错误文本（空串清除错误）
        :param errorType: 错误类型（``"RateLimit"`` / ...）。**单独存字段而不是
            拼进 ``message``** —— 拼进去类型就丢了，错误卡无法判断该不该给
            「重试」按钮，宿主也拿不到结构化信息。
        """
        bubble = self._require_bubble(messageId, "setMessageError")
        if bubble is None:
            return
        bubble.setError(message, errorType)
        # setError 会收尾未完成分段（正文 / 思考 / 工具分组），同步快照
        self._sync_parts(messageId)
        self._update_snapshot(
            messageId, lambda m: m.withError(message, errorType=errorType)
        )
        if message:
            self._update_snapshot(
                messageId, lambda m: m.withStatus(ElaChatStatusType.Error)
            )
        self.messageUpdated.emit(messageId)

    def messageError(self, messageId: int) -> tuple:
        """获取指定消息的 ``(错误文本, 错误类型)``（无错误返回 ``("", "")``）。"""
        message = self.message(messageId)
        if message is None:
            return ("", "")
        return (message.error, message.error_type)

    def clearMessageError(self, messageId: int) -> None:
        """清除指定消息的错误（发出 ``messageUpdated``）。

        「重试」前必须先调它 —— 否则上一轮的错误卡会**留在界面上**，而新的
        流式内容正在同一条消息里生成，看起来像同时既有错误又在输出。

        消息状态为 ``Error`` 时一并落成 ``Stopped``（保留「失败的尝试」记录）：
        错误文案已清空却留着 ``Error`` 状态，导出 / 恢复出来的是「出错但没
        错误」的自相矛盾数据。
        """
        bubble = self._require_bubble(messageId, "clearMessageError")
        if bubble is None:
            return
        error, error_type = self.messageError(messageId)
        if not (error or error_type):
            return
        bubble.clearError()
        # 显式传空串清类型：withError 的 errorType=None 语义是「保持原值」
        self._update_snapshot(messageId, lambda m: m.withError("", errorType=""))
        message = self.message(messageId)
        if message is not None and message.status == ElaChatStatusType.Error:
            bubble.setStatus(ElaChatStatusType.Stopped)
            self._update_snapshot(
                messageId,
                lambda m: m.withStatus(ElaChatStatusType.Stopped),
            )
        self.messageUpdated.emit(messageId)

    def setMessageTitle(self, messageId: int, title: str) -> None:
        """设置指定消息的头部名称 / 模型名（发出 ``messageUpdated``）。"""
        bubble = self._require_bubble(messageId, "setMessageTitle")
        if bubble is None:
            return
        bubble.setTitle(title)
        self._update_snapshot(messageId, lambda m: m.withTitle(title))
        self.messageUpdated.emit(messageId)

    def setMessageTimestamp(self, messageId: int, timestamp: str) -> None:
        """设置指定消息的头部时间文本（发出 ``messageUpdated``）。"""
        bubble = self._require_bubble(messageId, "setMessageTimestamp")
        if bubble is None:
            return
        bubble.setTimestamp(timestamp)
        self._update_snapshot(messageId, lambda m: m.withTimestamp(timestamp))
        self.messageUpdated.emit(messageId)
