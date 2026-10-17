"""队列 dock / 输入区 dock 与 ElaChatWidget 排队集成测试。"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel

from pyqt6_ela_pro.chat import ElaChatInputDock, ElaChatQueueDock, ElaChatWidget


class TestQueueDock:
    def test_messages_and_signals(self, qapp, make):
        dock = make(ElaChatQueueDock)
        dock.setMessages(
            [
                {"id": "q1", "text": "第一条", "attachments": []},
                {"id": "q2", "text": "第二条", "attachments": [{"name": "a"}]},
            ]
        )
        assert dock.count() == 2
        assert dock.isHidden() is False
        assert "2 条排队消息" in dock._title.text()
        assert "第一条" in dock._preview.text()

        sends = []
        edits = []
        removes = []
        dock.sendRequested.connect(sends.append)
        dock.editRequested.connect(edits.append)
        dock.removeRequested.connect(removes.append)
        row = dock._rows_layout.itemAt(1).widget()
        buttons = [
            row.layout().itemAt(index).widget() for index in range(row.layout().count())
        ]
        buttons[1].click()  # 立即发送
        buttons[2].click()  # 编辑
        buttons[3].click()  # 移除
        assert sends == ["q2"]
        assert edits == ["q2"]
        assert removes == ["q2"]

        dock.setMessages([])
        assert dock.count() == 0
        assert dock.isHidden()

    def test_expand_toggle(self, qapp, make):
        dock = make(ElaChatQueueDock)
        dock.setMessages([{"id": "q1", "text": "x"}])
        assert dock.isExpanded() is False
        dock.setExpanded(True)
        assert dock.isExpanded() is True
        assert dock._rows.isHidden() is False

    def test_row_label_uses_small_font(self, qapp, make):
        dock = make(ElaChatQueueDock)
        dock.setMessages([{"id": "q1", "text": "你好"}])
        row = dock._rows_layout.itemAt(0).widget()
        label = row.layout().itemAt(0).widget()
        assert label.text() == "你好"
        assert label.font().pixelSize() == 12


class TestInputDock:
    def test_replace_and_clear(self, qapp, make):
        dock = make(ElaChatInputDock)
        changed = []
        dock.changed.connect(changed.append)
        dock.setTitle("需要授权")
        dock.setWidget(QLabel("允许执行命令？"))
        assert dock.replacesInput() is True
        assert dock.isHidden() is False
        dock.clear()
        assert dock.replacesInput() is False
        assert dock.isHidden() is True
        assert changed == [True, False]


class TestWidgetQueue:
    def _generating_chat(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.resize(600, 400)
        chat.show()
        qapp.processEvents()
        chat.sendUserMessage("第一问")
        mid = chat.beginAssistantMessage()
        chat.chatView().appendText(mid, "回答中")
        qapp.processEvents()
        return chat

    def test_submit_while_generating_queues(self, qapp, make):
        chat = self._generating_chat(qapp, make)
        chat.chatInput().setText("第二问")
        chat.chatInput()._button.click()
        assert chat.queueCount() == 1
        assert chat.queuedMessages()[0]["text"] == "第二问"
        assert len(chat.chatView().messages()) == 2  # 未直接发送
        assert chat.queueDock().isHidden() is False

    def test_send_now_and_edit(self, qapp, make):
        chat = self._generating_chat(qapp, make)
        chat.chatInput().setText("第二问")
        chat.chatInput().submit()
        queueId = chat.queuedMessages()[0]["id"]

        chat.editQueuedMessage(queueId)
        assert chat.queueCount() == 0
        assert chat.chatInput().text() == "第二问"

        chat.chatInput().submit()
        queueId = chat.queuedMessages()[0]["id"]
        chat.sendQueuedNow(queueId)
        assert chat.queueCount() == 0
        assert len(chat.chatView().messages()) == 3

    def test_queue_disabled(self, qapp, make):
        chat = self._generating_chat(qapp, make)
        chat.setQueueEnabled(False)
        chat.chatInput().setText("第二问")
        chat.chatInput().submit()
        assert chat.queueCount() == 0
        assert len(chat.chatView().messages()) == 2

    def test_queue_changed_signal(self, qapp, make):
        chat = self._generating_chat(qapp, make)
        changes = []
        chat.queueChanged.connect(lambda items: changes.append(len(items)))
        chat.enqueueMessage("A")
        chat.enqueueMessage("B")
        chat.dequeueMessage(chat.queuedMessages()[0]["id"])
        chat.clearQueue()
        assert changes == [1, 2, 1, 0]

    def test_input_dock_disables_composer(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        chat.setDockWidget(QLabel("权限请求"))
        assert chat.chatInput().isEnabled() is False
        chat.clearDock()
        assert chat.chatInput().isEnabled() is True


class TestQueueDockRobustness:
    def test_set_messages_skips_non_dict_rows(self, qapp, make):
        dock = make(ElaChatQueueDock)
        dock.setMessages([None, "x", {"id": "q1", "text": "ok"}])
        assert dock.count() == 1
        assert "ok" in dock._preview.text()
