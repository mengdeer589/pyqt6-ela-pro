"""回归测试：发送幂等键（对齐 opencode 的 client-supplied prompt id）。

``sessions.prompt({ id? })`` 允许客户端自带消息 id：同 id 重复提交返回同一条
记录，不会产生第二条用户消息（opencode ``core/session/input.ts:41-81``）。
这消除「双击 / 回车+按钮竞态 / 网络超时后重试 / 乐观 UI 对账」整类 bug。

本组件的对应语义（经确认）：**消息仍在则幂等**。消息被 ``undoMessage``
移除后，同 id 可以重新发送 —— 那是有意的重发。
"""

from __future__ import annotations

from pyqt6_ela_pro.chat import ElaChatRoleType, ElaChatWidget


def _user_messages(chat: ElaChatWidget) -> list:
    return [m for m in chat.chatView().messages() if m.isUser]


class TestSendIdempotency:
    def test_same_id_twice_creates_one_message(self, qapp):
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        submitted = []
        chat.messageSubmitted.connect(submitted.append)

        first = chat.sendUserMessage("你好", messageId=1001)
        second = chat.sendUserMessage("你好", messageId=1001)

        assert first == 1001
        assert second == 1001
        assert len(_user_messages(chat)) == 1, "同 id 重复发送产生了第二条消息"
        assert len(submitted) == 1, f"messageSubmitted 发了 {len(submitted)} 次"
        chat.deleteLater()
        qapp.processEvents()

    def test_idempotent_retry_does_not_emit_twice(self, qapp):
        """模拟网络超时后的重试：后端只应被叫醒一次。"""
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        submitted = []
        chat.messageSubmitted.connect(submitted.append)

        mid = chat.sendUserMessage("question", messageId=2002)
        for _ in range(5):  # 指数退避重试
            chat.sendUserMessage("question", messageId=mid)
        assert len(submitted) == 1
        chat.deleteLater()
        qapp.processEvents()

    def test_different_ids_create_separate_messages(self, qapp):
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        chat.sendUserMessage("第一条", messageId=1)
        chat.stopGeneration()
        chat.sendUserMessage("第二条", messageId=2)
        assert len(_user_messages(chat)) == 2
        chat.deleteLater()
        qapp.processEvents()

    def test_explicit_id_used_for_new_message(self, qapp):
        """外部 id 尚不存在时，用该 id 建消息（乐观 UI 路径）。"""
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        mid = chat.sendUserMessage("乐观渲染", messageId=31337)
        assert mid == 31337
        assert chat.chatView().message(31337) is not None
        chat.deleteLater()
        qapp.processEvents()

    def test_resend_allowed_after_undo(self, qapp):
        """消息被撤销后，同 id 允许重发（那是有意的重发，不是重复）。"""
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        submitted = []
        chat.messageSubmitted.connect(submitted.append)

        mid = chat.sendUserMessage("撤销我", messageId=4141)
        assert chat.chatView().message(mid) is not None
        chat.undoMessage(mid)
        qapp.processEvents()
        assert chat.chatView().message(4141) is None

        again = chat.sendUserMessage("撤销我", messageId=mid)
        assert again == mid
        assert chat.chatView().message(mid) is not None
        assert len(submitted) == 2, "撤销后重发应正常发出第二次"
        chat.deleteLater()
        qapp.processEvents()

    def test_no_id_keeps_monotonic_allocation(self, qapp):
        """不传 id 时行为不变：内部单调计数器分配，顺序即创建顺序。"""
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        ids = [chat.sendUserMessage(f"m{i}") for i in range(5)]
        assert ids == sorted(ids), f"自动分配的 id 应单调递增：{ids}"
        assert len(set(ids)) == len(ids)
        chat.deleteLater()
        qapp.processEvents()

    def test_external_id_advances_internal_counter(self, qapp):
        """外部 id 较大时，内部计数器必须跟进，否则后续自动 id 会撞车。"""
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        chat.sendUserMessage("外部 id", messageId=9000)
        nxt = chat.sendUserMessage("自动 id")
        assert nxt > 9000, f"自动分配的 id 撞上了外部 id：{nxt}"
        chat.deleteLater()
        qapp.processEvents()


class TestQueueIdempotency:
    def test_same_message_id_enqueued_once(self, qapp):
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        a = chat.enqueueMessage("排队", messageId=555)
        b = chat.enqueueMessage("排队", messageId=555)
        assert a == b
        assert chat.queueCount() == 1, f"同 id 重复入队：count={chat.queueCount()}"
        chat.deleteLater()
        qapp.processEvents()

    def test_distinct_message_ids_queue_separately(self, qapp):
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        chat.enqueueMessage("第一条", messageId=1)
        chat.enqueueMessage("第二条", messageId=2)
        assert chat.queueCount() == 2
        chat.deleteLater()
        qapp.processEvents()

    def test_send_queued_now_passes_idempotency_key_through(self, qapp):
        """出队立即发送时必须带上 messageId，否则幂等链断掉。"""
        chat = ElaChatWidget()
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        submitted = []
        chat.messageSubmitted.connect(submitted.append)

        queueId = chat.enqueueMessage("马上发", messageId=777)
        assert chat.sendQueuedNow(queueId) is True
        qapp.processEvents()
        assert len(submitted) == 1
        assert chat.chatView().message(777) is not None
        chat.deleteLater()
        qapp.processEvents()
