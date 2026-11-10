"""时间线密度 / 通知 / 重试 / 活动行（``ElaChatView`` 方法组）。"""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from .._internal import is_deleted
from .blocks import ElaChatWorkingRow
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPlan,
    ElaChatRoleType,
    ElaChatStatusType,
)
from .timeline_detail import (
    DEFAULT_TIMELINE_DETAIL,
    ElaChatTimelineDetail,
    coerceTimelineDetail,
)


class _ViewTimelineMixin:
    """方法组 mixin：状态由 ``ElaChatView.__init__`` 建立。"""

    def setTimelineDetail(self, detail) -> None:
        """设置时间线密度（hidden / collapsed / expanded），立即作用到已建气泡。"""
        self._timeline_detail = coerceTimelineDetail(detail)
        for bubble in list(self._bubbles.values()):
            if bubble is not None:
                bubble.setTimelineDetail(self._timeline_detail)

    def timelineDetail(self) -> ElaChatTimelineDetail:
        """获取当前时间线密度（未设置返回默认值）。"""
        return self._timeline_detail or DEFAULT_TIMELINE_DETAIL

    def setPartExpanded(self, partId: str, opened: bool) -> None:
        """设置某个分段的展开状态（覆盖密度默认值；未物化消息也会记住）。"""
        key = str(partId or "")
        if not key:
            return
        self._disclosure[key] = bool(opened)
        for bubble in list(self._bubbles.values()):
            if bubble is None:
                continue
            if bubble._find_part(key) is not None:
                bubble._apply_part_visibility(key)
                break

    def partExpanded(self, partId: str) -> Optional[bool]:
        """读取分段的披露状态（未设置返回 ``None``）。"""
        return self._disclosure.get(str(partId or ""))

    def addNotice(
        self,
        messageId: int,
        noticeType: str,
        text: str = "",
        detail: str = "",
    ) -> str:
        """在指定消息的时间线上追加一条通知，返回分段 id。"""
        partId = uuid4().hex[:12]
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            bubble.addNotice(noticeType, text, detail, partId)
            self._sync_parts(messageId)
            return partId
        message = self._store.message(messageId)
        if message is None:
            raise ValueError(f"addNotice: 消息 {messageId} 不存在")
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Notice,
            text=text or "",
            status=ElaChatStatusType.Done,
            notice_type=noticeType or "",
            detail=detail or "",
        )
        self._update_snapshot(messageId, lambda m: m.withParts((*m.parts, part)))
        return partId

    def setPlan(
        self,
        messageId: int,
        plan,
        *,
        partId: Optional[str] = None,
    ) -> str:
        """插入 / 更新一条计划卡，返回分段 id。

        ``partId`` 为空时复用该消息最后一张计划卡；计划内容随消息持久化。
        """
        value = ElaChatPlan.coerce(plan)
        if value is None:
            return ""
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            value_id = bubble.setPlan(value, partId)
            if value_id:
                self._sync_parts(messageId)
                self.messageUpdated.emit(messageId)
            return value_id
        message = self._store.message(messageId)
        if message is None:
            raise ValueError(f"setPlan: 消息 {messageId} 不存在")
        if message.role != ElaChatRoleType.Assistant:
            return ""
        target = partId
        if target is None:
            for part in reversed(message.parts):
                if part.kind == ElaChatPartKindType.Plan:
                    target = part.id
                    break
        target = target or uuid4().hex[:12]
        existing = next((part for part in message.parts if part.id == target), None)
        if existing is not None and existing.kind == ElaChatPartKindType.Plan:
            updated = existing.withPlan(value)
            self._update_snapshot(
                messageId,
                lambda m, item=updated: m.withParts(
                    tuple(item if p.id == item.id else p for p in m.parts)
                ),
            )
            return target
        part = ElaChatPart(
            id=target,
            kind=ElaChatPartKindType.Plan,
            status=ElaChatStatusType.Done,
            plan=value,
            step=max(1, int(message.stepCount() or 1)),
        )
        self._update_snapshot(
            messageId, lambda m, item=part: m.withParts((*m.parts, item))
        )
        return target

    def plan(self, messageId: int) -> Optional[ElaChatPlan]:
        """获取指定消息最后一张计划卡的快照。"""
        part = self.planPart(messageId)
        return part.plan if part is not None else None

    def planPart(self, messageId: int) -> Optional[ElaChatPart]:
        """获取指定消息最后一个计划分段。"""
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            part = bubble.planPart()
            if part is not None:
                return part
        message = self.message(messageId)
        if message is None:
            return None
        for part in reversed(message.parts):
            if part.kind == ElaChatPartKindType.Plan:
                return part
        return None

    def clearPlan(self, messageId: int) -> None:
        """移除指定消息的全部计划卡。"""
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            bubble.clearPlan()
            self._sync_parts(messageId)
            self.messageUpdated.emit(messageId)
            return
        self._update_snapshot(
            messageId,
            lambda m: m.withParts(
                tuple(part for part in m.parts if part.kind != ElaChatPartKindType.Plan)
            ),
        )

    def setRetry(
        self,
        messageId: int,
        attempt: int,
        message: str,
        nextAt: float = 0.0,
    ) -> None:
        """设置某条消息的自动重试态（``nextAt`` 为 epoch 毫秒，0 = 无倒计时）。"""
        self._retry[messageId] = (
            max(1, int(attempt or 1)),
            str(message or ""),
            float(nextAt or 0.0),
        )
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            bubble.setRetry(*self._retry[messageId])

    def clearRetry(self, messageId: int) -> None:
        """清除某条消息的自动重试态。"""
        self._retry.pop(messageId, None)
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            bubble.clearRetry()

    def retryState(self, messageId: int) -> Optional[tuple]:
        """获取 ``(attempt, message, nextAt)`` 或 ``None``。"""
        return self._retry.get(messageId)

    def setActivity(self, text: str) -> None:
        """设置时间线底部的运行态文案（空串隐藏）。"""
        self._activity_text = str(text or "")
        row = self._ensure_activity_row()
        row.setText(self._activity_text)
        self._position_activity_row()

    def activity(self) -> str:
        """获取当前运行态文案。"""
        return self._activity_text

    def _ensure_activity_row(self) -> ElaChatWorkingRow:
        row = getattr(self, "_activity_row", None)
        if row is None or is_deleted(row):
            row = ElaChatWorkingRow(self._content)
            self._activity_row = row
        return row

    def _activity_insert_index(self) -> int:
        if self._virtual_list_mode and self._virtual_bottom_spacer is not None:
            index = self._content_layout.indexOf(self._virtual_bottom_spacer)
            if index >= 0:
                return index
        return max(0, self._content_layout.count() - 1)

    def _position_activity_row(self) -> None:
        row = getattr(self, "_activity_row", None)
        if row is None:
            return
        self._content_layout.removeWidget(row)
        self._content_layout.insertWidget(self._activity_insert_index(), row)
        row.setVisible(bool(self._activity_text))
        if self._activity_text:
            row.show()

    def addPendingUserMessage(
        self,
        text: str,
        attachments=None,
        mentions=None,
        delivery: str = "steer",
    ) -> int:
        """添加一条「待发送」用户消息（时间线立即显示），返回消息 id。"""
        messageId = self.addMessage(ElaChatRoleType.User, text)
        if attachments:
            self.setMessageAttachments(messageId, attachments)
        if mentions:
            self.setMessageMentions(messageId, mentions)
        if delivery:
            self._update_snapshot(messageId, lambda m: m.withDelivery(delivery))
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            bubble.setPendingDelivery(delivery)
        return messageId

    def resolvePendingUserMessage(self, messageId: int, sent: bool = True) -> bool:
        """结算待发送消息：``sent=True`` 转为普通消息，``False`` 删除。"""
        bubble = self._bubbles.get(messageId)
        if bubble is None:
            return False
        if sent:
            bubble.setPendingDelivery("")
            self._update_snapshot(messageId, lambda m: m.withDelivery(""))
            return True
        self.removeMessage(messageId)
        return True

    def setMessageIdentity(
        self,
        messageId: int,
        agent: str = "",
        model: str = "",
        modelVariant: str = "",
    ) -> None:
        """设置消息的 agent / 模型 / 变体（空串清除）。"""
        self._update_snapshot(
            messageId,
            lambda m: m.withIdentity(agent, model, modelVariant),
        )
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            bubble.setIdentity(agent, model, modelVariant)

    def setMessageMentions(self, messageId: int, mentions) -> None:
        """设置用户消息文本里的 @ 引用区间。"""
        self._update_snapshot(messageId, lambda m: m.withMentions(mentions))
        bubble = self._bubbles.get(messageId)
        if bubble is not None:
            bubble.setMentions(mentions)
