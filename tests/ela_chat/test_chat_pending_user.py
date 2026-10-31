"""待发送用户消息（插话 / 移到队列 / 删除）。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import ElaChatWidget


class TestPendingUser:
    def test_pending_steer_resolves_on_drain(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        steer_id = chat.steerMessage("插一句")
        assert steer_id
        pending = [
            message
            for message in chat.chatView().messages()
            if message.delivery == "steer"
        ]
        assert len(pending) == 1
        assert pending[0].status == "done"
        payload = chat.drainSteer()
        assert payload is not None
        remaining = [
            message
            for message in chat.chatView().messages()
            if message.id == pending[0].id
        ]
        assert remaining
        assert remaining[0].delivery == ""

    def test_pending_queue_moves_to_queue(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.steerMessage("排队去")
        pending = chat.chatView().messages()[-1]
        chat._on_pending_user_action(pending.id, "queue")
        assert chat.queueCount() == 1
        assert chat.chatView().message(pending.id) is None

    def test_pending_delete(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setGenerating(True)
        chat.steerMessage("删掉")
        pending = chat.chatView().messages()[-1]
        chat._on_pending_user_action(pending.id, "delete")
        assert chat.chatView().message(pending.id) is None
