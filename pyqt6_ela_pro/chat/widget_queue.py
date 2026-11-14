"""聊天排队消息方法组。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional
from uuid import uuid4


class _WidgetQueueMixin:
    @contextmanager
    def _autoSendPaused(self):  # noqa: N802 (与 Qt 命名一致)
        """临时关掉 ``autoSendQueue``（``clear`` / 换流期间）。
        宿主在 ``stopRequested`` 槽里会同步收尾，而 ``endAssistantMessage`` 末尾无条件
        续发排队消息 —— 不压住就会出现「队首抢在刚点的消息前面发出」或「清空前已把
        """
        autoSend = self._auto_send_queue
        self._auto_send_queue = False
        try:
            yield
        finally:
            self._auto_send_queue = autoSend

    def _snapshot_queue(self, steerId: Optional[str] = None) -> None:
        """记录一次队列快照（撤销栈上限 20）。

        ``steerId`` 只由 :meth:`steerQueued` 传入，撤销时据此移除它创建的那条
        插话；其余队列操作不需要回滚 ``_steer``。
        """
        self._queue_history.append(([dict(item) for item in self._queue], steerId))
        if len(self._queue_history) > 20:
            del self._queue_history[0]

    def canUndoQueue(self) -> bool:
        """是否有可撤销的队列操作。"""
        return bool(self._queue_history)

    def undoQueueChange(self) -> bool:
        """撤销上一次队列操作（添加 / 移除 / 编辑 / 排序 / 转为插话）。"""
        if not self._queue_history:
            return False
        queue, steerId = self._queue_history.pop()
        if steerId is not None:
            if not any(item.get("id") == steerId for item in self._steer):
                # 插话已被投递 / 清理：恢复队列会重复发送同一条指令。
                return False
            self._steer = [item for item in self._steer if item.get("id") != steerId]
            self.steerChanged.emit(self.steerMessages())
        self._queue = queue
        self._sync_queue()
        self.queueChanged.emit(self.queuedMessages())
        return True

    def moveQueued(self, queueId: str, toIndex: int) -> bool:
        """把排队消息移到指定下标。"""
        for index, item in enumerate(self._queue):
            if item["id"] != queueId:
                continue
            target = max(0, min(int(toIndex), len(self._queue) - 1))
            if target == index:
                return True
            self._snapshot_queue()
            entry = self._queue.pop(index)
            self._queue.insert(target, entry)
            self._sync_queue()
            return True
        return False

    def steerQueued(self, queueId: str) -> bool:
        """把排队消息转为插话（生成中且插话可用时）。"""
        if not self._generating or not self.steerEnabled():
            return False
        for index, item in enumerate(self._queue):
            if item["id"] != queueId:
                continue
            steerId = uuid4().hex[:12]
            self._snapshot_queue(steerId)
            self._queue.pop(index)
            self._steer.append(
                {
                    "id": steerId,
                    "text": item["text"],
                    "attachments": list(item.get("attachments") or []),
                    "messageId": item.get("messageId"),
                    "mentions": list(item.get("mentions") or []),
                }
            )
            self._sync_queue()
            self.steerChanged.emit(self.steerMessages())
            return True
        return False

    def setQueueEnabled(self, on: bool) -> None:
        """设置生成中提交是否进入排队（默认开启）。"""
        self._queue_enabled = bool(on)
        self._input.setQueueEnabled(self._queue_enabled)

    def queueEnabled(self) -> bool:
        """生成中提交是否进入排队。"""
        return self._queue_enabled

    def enqueueMessage(
        self,
        text: str,
        attachments=None,
        messageId: Optional[int] = None,
        *,
        mentions=None,
    ) -> Optional[str]:
        """把消息加入排队 dock；返回排队 id（空文本返回 ``None``）。

        ``messageId`` 为幂等键：同 id 重复入队只保留一条（消除双击 / 竞态）。
        """
        text = (text or "").strip()
        if not text:
            return None
        if messageId is not None:
            for item in self._queue:
                if item.get("messageId") == messageId:
                    return item["id"]
        self._snapshot_queue()
        queueId = uuid4().hex[:12]
        self._queue.append(
            {
                "id": queueId,
                "text": text,
                "attachments": list(attachments or []),
                "messageId": messageId,
                "mentions": list(mentions or []),
            }
        )
        self._sync_queue()
        return queueId

    def queuedMessages(self) -> list:
        """排队消息快照列表。"""
        return [dict(item) for item in self._queue]

    def queueCount(self) -> int:
        """排队消息条数。"""
        return len(self._queue)

    def dequeueMessage(self, queueId: str) -> bool:
        """移除指定排队消息。"""
        for index, item in enumerate(self._queue):
            if item["id"] == queueId:
                self._snapshot_queue()
                self._queue.pop(index)
                self._sync_queue()
                return True
        return False

    def sendQueuedNow(self, queueId: str) -> bool:
        """立即发送指定排队消息（出队并作为新消息提交）。

        只发被点的那一条，其余保持排队。
        """
        for index, item in enumerate(self._queue):
            if item["id"] != queueId:
                continue
            self._queue.pop(index)
            self._sync_queue()
            self.sendUserMessage(
                item["text"],
                item["attachments"],
                item.get("messageId"),
                mentions=item.get("mentions"),
            )
            return True
        return False

    def editQueuedMessage(self, queueId: str) -> bool:
        """把排队消息回填到输入框（出队）。"""
        for index, item in enumerate(self._queue):
            if item["id"] != queueId:
                continue
            self._snapshot_queue()
            self._queue.pop(index)
            self._sync_queue()
            self._input.setText(item["text"])
            if item["attachments"]:
                self._input.setAttachments(item["attachments"])
            self._input.setMentions(item.get("mentions"))
            self._input.textEdit().setFocus()
            return True
        return False

    def clearQueue(self) -> None:
        """清空排队消息。"""
        if not self._queue:
            return
        self._snapshot_queue()
        self._queue.clear()
        self._sync_queue()

    def _sync_queue(self) -> None:
        self._queue_dock.setMessages(self._queue)
        self._queue_dock.setWorking(bool(self._generating))
        self._queue_dock.setSteerEnabled(self.steerEnabled())
        self._queue_dock.setUndoAvailable(self.canUndoQueue())
        self.queueChanged.emit(self.queuedMessages())

    def sendNextQueued(self) -> bool:
        """发送队首排队消息（空闲且有排队时）；返回是否已发送。"""
        if self.isGenerating():
            return False
        queued = self.queuedMessages()
        if not queued:
            return False
        self.sendQueuedNow(queued[0]["id"])
        return True

    def setAutoSendQueue(self, on: bool = True) -> None:
        """设置回合结束后是否自动发送队首排队消息（默认开启）。"""
        self._auto_send_queue = bool(on)

    def autoSendQueue(self) -> bool:
        """回合结束后是否自动发送队首排队消息。"""
        return self._auto_send_queue
