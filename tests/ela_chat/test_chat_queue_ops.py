"""队列排序 / 插话 / 撤销。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import ElaChatWidget


class TestQueueOps:
    def test_move_and_undo(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.enqueueMessage("a")
        chat.enqueueMessage("b")
        c = chat.enqueueMessage("c")
        assert chat.moveQueued(c, 0)
        assert [item["text"] for item in chat.queuedMessages()] == ["c", "a", "b"]
        assert chat.canUndoQueue()
        assert chat.undoQueueChange()
        assert [item["text"] for item in chat.queuedMessages()] == ["a", "b", "c"]

    def test_steer_queued(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.enqueueMessage("a")
        assert not chat.steerQueued(chat.queuedMessages()[0]["id"])
        chat.setGenerating(True)
        assert chat.steerQueued(chat.queuedMessages()[0]["id"])
        assert chat.queueCount() == 0
        assert chat.steerCount() == 1
        assert chat.undoQueueChange()
        assert chat.queueCount() == 1
        assert chat.steerCount() == 0

    def test_dock_working_label(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.enqueueMessage("a")
        chat.queueDock().setExpanded(True)
        chat.setGenerating(True)
        assert chat.queueDock().working()
        chat.setGenerating(False)
        assert not chat.queueDock().working()
