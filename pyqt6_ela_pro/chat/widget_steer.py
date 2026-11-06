"""聊天 steer 插话方法组。"""

from __future__ import annotations

from typing import Optional
from uuid import uuid4


class _WidgetSteerMixin:
    def steerMessage(
        self,
        text: str,
        attachments=None,
        messageId: Optional[str] = None,
    ) -> Optional[str]:
        """生成中**插话**：把新指令送进正在跑的这一轮，而不是排队等它跑完。

        投递由 binder 在 step 安全边界调 :meth:`drainSteer` 完成；组件不负责把文本
        送进后端。

        :returns: steer id（空文本返回 ``None``）
        """
        text = (text or "").strip()
        if not text:
            return None
        if messageId is not None:
            for item in self._steer:
                if item.get("messageId") == messageId:
                    return item["id"]
        self._snapshot_queue()
        pendingId = self._view.addPendingUserMessage(
            text,
            attachments,
            [],
            "steer",
        )
        steerId = uuid4().hex[:12]
        self._steer.append(
            {
                "id": steerId,
                "text": text,
                "attachments": list(attachments or []),
                "messageId": messageId,
                "pendingMessageId": pendingId,
            }
        )
        self.steerChanged.emit(self.steerMessages())
        return steerId

    def steerMessages(self) -> list:
        """待送插话快照列表。"""
        return [dict(item) for item in self._steer]

    def steerCount(self) -> int:
        """待送插话条数。"""
        return len(self._steer)

    def dequeueSteer(self, steerId: str) -> bool:
        """丢弃指定插话（用户改主意了）。"""
        for index, item in enumerate(self._steer):
            if item["id"] == steerId:
                self._snapshot_queue()
                pendingId = item.get("pendingMessageId")
                if pendingId is not None:
                    self._view.resolvePendingUserMessage(int(pendingId), sent=False)
                self._steer.pop(index)
                self.steerChanged.emit(self.steerMessages())
                return True
        return False

    def clearSteer(self) -> None:
        """清空待送插话。"""
        if not self._steer:
            return
        self._snapshot_queue()
        for item in list(self._steer):
            pendingId = item.get("pendingMessageId")
            if pendingId is not None:
                self._view.resolvePendingUserMessage(int(pendingId), sent=False)
        self._steer.clear()
        self.steerChanged.emit(self.steerMessages())

    def setSteerEnabled(self, on: bool) -> None:
        """是否在 step 边界自动投递插话（默认开）。

        关掉后插话只堆积，宿主得自己调 :meth:`drainSteer`。
        """
        self._steer_enabled = bool(on)

    def steerEnabled(self) -> bool:
        """是否在 step 边界自动投递插话。"""
        return self._steer_enabled

    def drainSteer(self) -> Optional[dict]:
        """取出并投递**一条**待送插话；没有则返回 ``None``。
        投递 = 在当前流式消息里留一行回执 + 发 :attr:`steerReady`；组件不发送后端
        请求。一次只投一条，避免把多句话一次性糊给模型。
        """
        if not self._steer:
            return None
        item = self._steer.pop(0)
        pendingId = item.get("pendingMessageId")
        if pendingId is not None:
            self._view.resolvePendingUserMessage(int(pendingId), sent=True)
        self.steerChanged.emit(self.steerMessages())
        messageId = self.streamingMessageId() or self._streaming_id
        if messageId is not None:
            self._view.addSteerNotice(messageId, item["text"])
        payload = dict(item)
        payload["messageId"] = messageId
        self.steerReady.emit(payload)
        return payload
