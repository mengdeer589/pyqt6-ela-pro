"""ElaChatWidget 组装组件测试：完整回合、停止、头部与清空。"""

from __future__ import annotations

import os

from _qthelpers import wait_until as _wait_until
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage

import pyqt6_ela_pro.chat.widget as widget_mod
from pyqt6_ela_pro.chat import (
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatWidget,
)
from pyqt6_ela_pro.chat.blocks import _ImageAttachmentCard


class TestRoundTrip:
    def test_full_generation_flow(self, qapp, make):
        chat = make(ElaChatWidget)
        events = []
        chat.messageSubmitted.connect(lambda text: events.append(("submitted", text)))
        chat.generationStarted.connect(lambda mid: events.append(("started", mid)))
        chat.generationFinished.connect(
            lambda mid, status: events.append(("finished", mid, status))
        )

        user_id = chat.sendUserMessage("你好")
        assert user_id == 1
        assert chat.isGenerating() is True
        assert chat.chatInput().isGenerating() is True

        assistant_id = chat.beginAssistantMessage()
        assert assistant_id == 2
        chat.chatView().appendText(assistant_id, "你好")
        chat.chatView().appendText(assistant_id, "，世界")
        chat.endAssistantMessage()

        assert events == [
            ("submitted", "你好"),
            ("started", assistant_id),
            ("finished", assistant_id, ElaChatStatusType.Done),
        ]
        assert chat.isGenerating() is False
        messages = chat.chatView().messages()
        assert [(m.id, m.role, m.text, m.status) for m in messages] == [
            (1, ElaChatRoleType.User, "你好", ElaChatStatusType.Done),
            (2, ElaChatRoleType.Assistant, "你好，世界", ElaChatStatusType.Done),
        ]

    def test_send_empty_ignored(self, qapp, make):
        chat = make(ElaChatWidget)
        assert chat.sendUserMessage("   ") is None
        assert chat.chatView().messages() == []
        assert chat.isGenerating() is False

    def test_input_submit_drives_widget(self, qapp, make):
        chat = make(ElaChatWidget)
        submitted = []
        chat.messageSubmitted.connect(submitted.append)
        chat.chatInput().setText("来自输入框")
        chat.chatInput()._button.click()
        assert submitted == ["来自输入框"]
        assert chat.chatView().messages()[0].text == "来自输入框"

    def test_append_with_explicit_id(self, qapp, make):
        chat = make(ElaChatWidget)
        first = chat.beginAssistantMessage()
        chat.endAssistantMessage()
        second = chat.beginAssistantMessage()
        chat.chatView().appendText(first, "给第一条")
        chat.chatView().appendText(second, "给第二条")
        # 给已结束的第一条追加会当场落定；第二条仍在途，快照为空
        assert chat.chatView().message(first).text == "给第一条"
        assert chat.chatView().message(second).text == ""
        assert chat.chatView().bubble(second).text() == "给第二条"


class TestStop:
    def test_stop_marks_stopped(self, qapp, make):
        chat = make(ElaChatWidget)
        stops = []
        finished = []
        chat.stopRequested.connect(lambda: stops.append(1))
        chat.generationFinished.connect(lambda mid, status: finished.append(status))

        chat.sendUserMessage("问题")
        assistant_id = chat.beginAssistantMessage()
        chat.chatView().appendText(assistant_id, "部分回答")
        chat.stopGeneration()

        assert stops == [1]
        assert finished == [ElaChatStatusType.Stopped]
        assert chat.chatView().message(assistant_id).status == ElaChatStatusType.Stopped
        assert chat.chatView().message(assistant_id).text == "部分回答"
        assert chat.isGenerating() is False

    def test_stop_without_stream(self, qapp, make):
        chat = make(ElaChatWidget)
        stops = []
        chat.stopRequested.connect(lambda: stops.append(1))
        chat.setGenerating(True)
        chat.stopGeneration()
        assert stops == [1]
        assert chat.isGenerating() is False

    def test_stop_idle_noop(self, qapp, make):
        chat = make(ElaChatWidget)
        stops = []
        chat.stopRequested.connect(lambda: stops.append(1))
        chat.stopGeneration()
        assert stops == []

    def test_input_stop_button(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.sendUserMessage("问题")
        chat.beginAssistantMessage()
        chat.chatInput()._button.click()  # 生成中按钮为「停止」
        assert chat.isGenerating() is False
        assert chat.chatView().messages()[-1].status == ElaChatStatusType.Stopped


class TestClear:
    def test_clear_button(self, qapp, make):
        """输入区「清空上下文」的 widget 侧清空链路（弹框确认由 requestClear 负责）。"""
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        cleared = []
        chat.cleared.connect(lambda: cleared.append(1))
        chat.sendUserMessage("问题")
        chat.beginAssistantMessage()
        chat.clear()
        assert cleared == [1]
        assert chat.chatView().messages() == []
        assert chat.isGenerating() is False
        assert chat.chatView()._empty.isVisibleTo(chat.chatView())


class TestInputBarClearButton:
    """输入区工具栅的「清空上下文」按钮（扫帚图标）→ 弹框确认 → clear()。"""

    @staticmethod
    def _mock_confirm(monkeypatch, result: bool, calls: list):
        """把 ``ElaConfirmDialog.show`` 换成记录调用的桩（含锚点与位置）。"""

        class _Fake:
            @staticmethod
            def show(parent, title, message, position="bottom"):
                calls.append((parent, title, message, position))
                return result

        monkeypatch.setattr(widget_mod, "ElaConfirmDialog", _Fake)

    def test_button_exists_and_visible_by_default(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        button = chat.chatInput().clearButton()
        assert button is chat.chatInput().toolBar().toolButton("clear")
        assert chat.chatInput().clearVisible() is True
        chat.chatInput().setClearVisible(False)
        assert chat.chatInput().clearVisible() is False

    def test_click_confirm_clears_and_emits(self, qapp, monkeypatch, make):
        calls = []
        self._mock_confirm(monkeypatch, True, calls)
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        cleared = []
        requested = []
        chat.cleared.connect(lambda: cleared.append(1))
        chat.clearRequested.connect(lambda: requested.append(1))
        chat.addMessage(ElaChatRoleType.User, "你好")
        chat.addMessage(ElaChatRoleType.Assistant, "在")
        qapp.processEvents()

        chat.chatInput().clearButton().click()
        qapp.processEvents()

        # 弹了一次框：锚点是输入区（不能拿整块聊天组件当锚点 —— 它贴窗口底边，
        # 「下方」会算到屏幕外）、位置在锚点上方（输入区下方没有空间）
        assert len(calls) == 1
        assert calls[0][0] is chat.chatInput()
        assert calls[0][3] == "top"
        assert "清空" in calls[0][1]
        # 请求信号 + 清空信号都发了
        assert requested == [1]
        assert cleared == [1]
        assert chat.chatView().messages() == []

    def test_click_cancel_keeps_messages(self, qapp, monkeypatch, make):
        calls = []
        self._mock_confirm(monkeypatch, False, calls)
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        cleared = []
        chat.cleared.connect(lambda: cleared.append(1))
        chat.addMessage(ElaChatRoleType.User, "别删我")
        qapp.processEvents()

        chat.chatInput().clearButton().click()
        qapp.processEvents()

        assert len(calls) == 1
        assert cleared == []  # 取消 → 不清空
        assert len(chat.chatView().messages()) == 1

    def test_new_topic_signal_forwarded(self, qapp, make):
        """输入区「新建话题」→ 组件层同名信号（组件不做任何处理，宿主接管）。"""
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        requested = []
        chat.newTopicRequested.connect(lambda: requested.append(1))
        chat.addMessage(ElaChatRoleType.User, "旧话题的消息")

        chat.chatInput().newTopicButton().click()
        qapp.processEvents()

        assert requested == [1]
        # 组件不自己开话题：消息与草稿都原样留着
        assert len(chat.chatView().messages()) == 1
        qapp.processEvents()

    def test_empty_session_skips_confirm(self, qapp, monkeypatch, make):
        calls = []
        self._mock_confirm(monkeypatch, True, calls)
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        requested = []
        cleared = []
        chat.clearRequested.connect(lambda: requested.append(1))
        chat.cleared.connect(lambda: cleared.append(1))
        # 空会话点清空：直接返回 —— 不弹框，也不发 clearRequested（宿主拿它做
        # 「等待确认…」之类的提示 / 埋点，发了却什么都不弹，提示就永远挂着）
        chat.chatInput().clearButton().click()
        qapp.processEvents()
        assert calls == []
        assert requested == []
        assert cleared == []

    def test_queued_message_counts_as_content(self, qapp, monkeypatch, make):
        """视图为空、只有排队消息也算有内容：照常确认，确认后队列一并清掉。"""
        calls = []
        self._mock_confirm(monkeypatch, True, calls)
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        requested = []
        chat.clearRequested.connect(lambda: requested.append(1))
        chat.enqueueMessage("排队中的问题")
        qapp.processEvents()

        chat.chatInput().clearButton().click()
        qapp.processEvents()

        assert len(calls) == 1
        assert requested == [1]
        assert chat.queueCount() == 0


class TestWidgetDrop:
    """拖放到组件任意位置（消息区 / 头部最有用的两个）都落到输入区附件。"""

    @staticmethod
    def _file_mime(tmp_path):
        file_path = tmp_path / "拖到消息区.txt"
        file_path.write_text("x", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(file_path))])
        return file_path, mime

    def test_drop_on_message_view_reaches_input(self, qapp, tmp_path, make):
        chat = make(ElaChatWidget)
        chat.show()
        qapp.processEvents()
        file_path, mime = self._file_mime(tmp_path)
        dropped = []
        chat.filesAdded.connect(dropped.append)

        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        chat.dropEvent(event)
        qapp.processEvents()

        assert event.isAccepted()
        assert chat.chatInput().attachmentCount() == 1
        assert chat.chatInput().attachments()[0].name == "拖到消息区.txt"
        assert chat.chatView().count() == 0  # 只是加附件，不建消息
        assert dropped and os.path.normpath(dropped[0][0]) == os.path.normpath(
            str(file_path)
        )
        qapp.processEvents()

    def test_drag_enter_accepts_and_rejects(self, qapp, tmp_path, make):
        chat = make(ElaChatWidget)

        def enter(mime):
            event = QDragEnterEvent(
                QPoint(5, 5),
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            chat.dragEnterEvent(event)
            return event.isAccepted()

        _, file_mime = self._file_mime(tmp_path)
        text_mime = QMimeData()
        text_mime.setText("只是文字")

        assert enter(file_mime) is True
        assert enter(text_mime) is False
        qapp.processEvents()


class TestPassthrough:
    def test_suggestions(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.chatView().setSuggestions(["A", "B"])
        assert chat.chatView().suggestions() == ["A", "B"]
        clicked = []
        chat.suggestionClicked.connect(clicked.append)
        chat.chatView()._empty.suggestionClicked.emit("A")
        assert clicked == ["A"]

    def test_empty_title_and_subtitle(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.chatView().setEmptyTitle("有什么可以帮你？")
        chat.chatView().setEmptySubtitle("点击建议开始")
        assert chat.chatView().emptyTitle() == "有什么可以帮你？"
        assert chat.chatView().emptySubtitle() == "点击建议开始"

    def test_add_system_message(self, qapp, make):
        chat = make(ElaChatWidget)
        messageId = chat.addMessage(ElaChatRoleType.System, "会话已创建")
        assert chat.chatView().message(messageId).role == ElaChatRoleType.System

    def test_appearance_propagation(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.chatView().setAvatarVisible(False)
        chat.chatView().setUserBubbleMaxWidth(0.6)
        messageId = chat.addMessage(ElaChatRoleType.User, "hi")
        bubble = chat.chatView().bubble(messageId)
        assert bubble.avatarVisible() is False
        assert bubble.maxWidthRatio() == 0.6
        assert chat.chatView().avatarVisible() is False
        assert chat.chatView().userBubbleMaxWidth() == 0.6

    def test_scroll_to_bottom(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.resize(420, 260)
        chat.show()
        qapp.processEvents()
        for index in range(6):
            chat.addMessage(ElaChatRoleType.User, f"消息 {index} " + "内容" * 20)
        assert _wait_until(
            qapp,
            lambda: (
                chat.chatView()._scroll.verticalScrollBar().value()
                >= chat.chatView()._scroll.verticalScrollBar().maximum() - 6
            ),
        )
        chat.chatView().scrollToBottom()
        assert chat.chatView().stickToBottom() is True


class TestAttachmentsFlow:
    def test_send_with_attachments(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.chatInput().setAttachments(
            [{"name": "资料.pdf", "path": "C:/tmp/资料.pdf", "size": 1024}]
        )
        received = []
        chat.messageSubmittedFull.connect(
            lambda text, items: received.append((text, len(items)))
        )
        chat.chatInput().setText("看这份资料")
        chat.chatInput()._button.click()
        assert received == [("看这份资料", 1)]
        message = chat.chatView().messages()[0]
        assert len(message.attachments) == 1
        assert message.attachments[0].name == "资料.pdf"
        assert chat.chatInput().attachmentCount() == 0

    def test_attachments_changed_signal(self, qapp, make):
        chat = make(ElaChatWidget)
        changes = []
        chat.attachmentsChanged.connect(lambda items: changes.append(len(items)))
        chat.chatInput().addAttachment("a.txt", "C:/a.txt", 1)
        chat.chatInput().clearAttachments()
        assert changes == [1, 0]


class TestTitles:
    def test_names_applied_to_messages(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.setUserName("我")
        chat.setAssistantName("deepseek-v4")
        user_id = chat.sendUserMessage("你好")
        assistant_id = chat.beginAssistantMessage()
        chat.endAssistantMessage()
        assert chat.chatView().message(user_id).title == "我"
        assert chat.chatView().message(assistant_id).title == "deepseek-v4"
        assert chat.userName() == "我"
        assert chat.assistantName() == "deepseek-v4"

        chat.setUserName("管理员")
        assert chat.chatView().message(user_id).title == "管理员"
        assert chat.chatView().bubble(user_id).title() == "管理员"


class TestToolBarAndActions:
    def test_custom_tool_button(self, qapp, make):
        chat = make(ElaChatWidget)
        clicks = []
        chat.toolBar().addButton(
            text="模板", key="tpl", callback=lambda: clicks.append(1)
        )
        chat.toolBar().toolButton("tpl").click()
        assert clicks == [1]

    def test_action_passthrough(self, qapp, make):
        chat = make(ElaChatWidget)
        messageId = chat.addMessage(ElaChatRoleType.User, "hi")
        events = []
        chat.messageActionTriggered.connect(lambda mid, key: events.append((mid, key)))
        chat.actions(messageId).toolButton("undo").click()
        assert events == [(messageId, "undo")]
        assert chat.actions(999) is None

    def test_custom_message_action(self, qapp, make):
        chat = make(ElaChatWidget)
        messageId = chat.addMessage(ElaChatRoleType.Assistant, "hi")
        events = []
        chat.messageActionTriggered.connect(lambda mid, key: events.append((mid, key)))
        chat.actions(messageId).addCustomAction("favorite", tooltip="收藏")
        chat.actions(messageId).toolButton("favorite").click()
        assert events == [(messageId, "favorite")]


class TestReasoningAndTools:
    def test_reasoning_stream(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.sendUserMessage("问题")
        assistant_id = chat.beginAssistantMessage()
        chat.chatView().beginReasoning(assistant_id)
        chat.chatView().appendReasoning(assistant_id, "先分析")
        chat.chatView().appendReasoning(assistant_id, "再回答")
        chat.chatView().endReasoning(assistant_id, 500)
        snapshot = chat.chatView().message(assistant_id)
        assert snapshot.reasoning == "先分析再回答"
        assert snapshot.reasoning_ms == 500.0
        chat.endAssistantMessage()

    def test_tool_call_flow(self, qapp, make):
        chat = make(ElaChatWidget)
        assistant_id = chat.beginAssistantMessage()
        callId = chat.chatView().addToolCall(assistant_id, "search", '{"q": "x"}')
        assert callId
        chat.chatView().setToolCallResult(assistant_id, callId, "结果 1")
        snapshot = chat.chatView().message(assistant_id)
        assert len(snapshot.tool_calls) == 1
        assert snapshot.tool_calls[0].isDone
        assert snapshot.tool_calls[0].result == "结果 1"

    def test_stats_and_error(self, qapp, make):
        chat = make(ElaChatWidget)
        assistant_id = chat.beginAssistantMessage()
        stats = ElaChatStats(
            prompt_tokens=3, completion_tokens=4, total_tokens=7, tps=8.0
        )
        chat.chatView().setStepStats(assistant_id, stats)
        assert chat.chatView().message(assistant_id).stats is stats

        chat.setMessageError("网关错误", assistant_id)
        snapshot = chat.chatView().message(assistant_id)
        assert snapshot.error == "网关错误"
        assert snapshot.status == ElaChatStatusType.Error
        assert chat.isGenerating() is False
        # 流式引用已结束，后续 end 不会把错误状态覆盖为「完成」
        assert chat.endAssistantMessage() is None
        assert chat.chatView().message(assistant_id).status == ElaChatStatusType.Error


class TestMessageManagement:
    def test_remove_update_count_and_tool_calls(self, qapp, make):
        chat = make(ElaChatWidget)
        first = chat.addMessage(ElaChatRoleType.User, "a")
        chat.addMessage(ElaChatRoleType.Assistant, "b")
        assert chat.chatView().count() == 2
        assert chat.chatView().toolCalls(first) == []

        updates = []
        chat.messageUpdated.connect(updates.append)
        chat.chatView().updateMessage(first, "a2")
        assert chat.chatView().message(first).text == "a2"
        assert updates == [first]

        chat.removeMessage(first)
        assert chat.chatView().count() == 1
        assert chat.chatView().message(first) is None

    def test_remove_streaming_message_ends_generation(self, qapp, make):
        chat = make(ElaChatWidget)
        message_id = chat.beginAssistantMessage()
        assert chat.isGenerating() is True
        chat.removeMessage(message_id)
        assert chat.isGenerating() is False
        assert chat.chatView().count() == 0


class TestSessionMarker:
    """会话 id 只是「本 widget 属于哪个话题」的标记（多话题归宿主，见 session.py）。"""

    def test_current_session_signal(self, qapp, make):
        chat = make(ElaChatWidget)
        changes = []
        chat.sessionChanged.connect(changes.append)
        chat.setCurrentSessionId("s1")
        chat.setCurrentSessionId("s1")
        chat.setCurrentSessionId("s2")
        assert changes == ["s1", "s2"]
        assert chat.currentSessionId() == "s2"


class TestHostActions:
    def test_undo_message_removes_tail_and_restores_input(self, qapp, make):
        chat = make(ElaChatWidget)
        userId = chat.addMessage(ElaChatRoleType.User, "第一问")
        chat.addMessage(ElaChatRoleType.Assistant, "第一答")
        targetId = chat.addMessage(ElaChatRoleType.User, "第二问")
        chat.addMessage(ElaChatRoleType.Assistant, "第二答")

        target = chat.undoMessage(targetId)
        assert target is not None
        assert target.text == "第二问"
        assert [message.id for message in chat.chatView().messages()] == [userId, 2]
        assert chat.chatInput().text() == "第二问"
        assert chat.undoMessage(999) is None

    def test_undo_message_restores_attachments(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.chatInput().addAttachment("a.txt", "C:/tmp/a.txt", 10)
        chat.chatInput().setText("带附件的提问")
        assert chat.chatInput().submit() is True
        userId = chat.chatView().messages()[0].id

        assistant_id = chat.beginAssistantMessage()
        chat.chatView().appendText(assistant_id, "回答")
        chat.endAssistantMessage()

        assert chat.undoMessage(userId) is not None
        assert [item.name for item in chat.chatInput().attachments()] == ["a.txt"]
        assert chat.isGenerating() is False

    def test_undo_message_restores_pasted_image(self, qapp, make):
        """粘贴图片的**图像**要跟着附件回填（不是退化成文件 chip）。"""
        chat = make(ElaChatWidget)
        image = QImage(24, 24, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ff5500"))
        assert chat.chatInput()._on_image_pasted(image) is True
        chat.chatInput().setText("带图的问题")
        assert chat.chatInput().submit() is True
        userId = chat.chatView().messages()[0].id

        # 消息气泡按图片缩略卡渲染（图像随附件对象流转）
        bubble_cards = chat.chatView().bubble(userId).attachmentStrip()._cards
        assert isinstance(bubble_cards[0], _ImageAttachmentCard)

        assert chat.undoMessage(userId) is not None
        restored = chat.chatInput().attachments()
        assert len(restored) == 1
        assert restored[0].isImage
        assert restored[0].image is not None
        # 输入框回填成图片缩略卡；图像是运行时字段，不进序列化
        input_cards = chat.chatInput().attachmentStrip()._cards
        assert isinstance(input_cards[0], _ImageAttachmentCard)
        assert "image" not in restored[0].toDict()

    def test_undo_streaming_message_ends_generation(self, qapp, make):
        chat = make(ElaChatWidget)
        userId = chat.sendUserMessage("问")
        assistantId = chat.beginAssistantMessage()
        assert chat.isGenerating() is True
        assert chat.undoMessage(userId) is not None
        assert chat.isGenerating() is False
        assert chat.chatView().message(assistantId) is None

    def test_undo_last_user_message_skips_assistant_reply(self, qapp, make):
        """「撤回最后一条消息」撤回的是最后一条**用户**消息，不是助手回答。"""
        chat = make(ElaChatWidget)
        first_user = chat.addMessage(ElaChatRoleType.User, "第一条")
        first_assistant = chat.addMessage(ElaChatRoleType.Assistant, "第一条回答")
        last_user = chat.addMessage(ElaChatRoleType.User, "第二条")
        chat.addMessage(ElaChatRoleType.Assistant, "第二条回答")

        target = chat.undoLastUserMessage()
        assert target is not None
        assert target.id == last_user
        assert target.text == "第二条"
        assert chat.chatInput().text() == "第二条"
        assert [m.id for m in chat.chatView().messages()] == [
            first_user,
            first_assistant,
        ]

    def test_undo_last_user_message_without_user_is_noop(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.addMessage(ElaChatRoleType.Assistant, "只有回答")
        chat.addMessage(ElaChatRoleType.System, "系统消息")
        assert chat.undoLastUserMessage() is None
        assert chat.chatView().count() == 2

    def test_undo_message_rejects_assistant_target(self, qapp, make):
        """``undoMessage`` 只对用户消息生效：传助手消息不删任何东西。"""
        chat = make(ElaChatWidget)
        user_id = chat.addMessage(ElaChatRoleType.User, "问题")
        assistant_id = chat.addMessage(ElaChatRoleType.Assistant, "回答")
        assert chat.undoMessage(assistant_id) is None
        assert [m.id for m in chat.chatView().messages()] == [user_id, assistant_id]
        assert chat.chatInput().text() == ""

    def test_regenerate_from_returns_previous_user_message(self, qapp, make):
        chat = make(ElaChatWidget)
        userId = chat.addMessage(ElaChatRoleType.User, "原始提问")
        assistantId = chat.addMessage(ElaChatRoleType.Assistant, "旧回答")
        chat.addMessage(ElaChatRoleType.User, "后续提问")
        chat.addMessage(ElaChatRoleType.Assistant, "后续回答")

        userMessage = chat.regenerateFrom(assistantId)
        assert userMessage is not None
        assert userMessage.id == userId
        assert userMessage.text == "原始提问"
        assert [message.id for message in chat.chatView().messages()] == [userId]

    def test_regenerate_from_without_user_message_keeps_messages(self, qapp, make):
        chat = make(ElaChatWidget)
        assistantId = chat.addMessage(ElaChatRoleType.Assistant, "孤立回答")
        assert chat.regenerateFrom(assistantId) is None
        assert chat.chatView().count() == 1
        assert chat.chatView().message(assistantId) is not None

    def test_regenerate_streaming_message_ends_generation(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.sendUserMessage("问")
        assistantId = chat.beginAssistantMessage()
        assert chat.isGenerating() is True
        assert chat.regenerateFrom(assistantId) is not None
        assert chat.isGenerating() is False
        assert chat.chatView().message(assistantId) is None

    def test_auto_send_queue_default_and_toggle(self, qapp, make):
        chat = make(ElaChatWidget)
        assert chat.autoSendQueue() is True
        chat.setAutoSendQueue(False)
        assert chat.autoSendQueue() is False
        chat.setAutoSendQueue()
        assert chat.autoSendQueue() is True

    def test_end_assistant_message_auto_sends_queue(self, qapp, make):
        chat = make(ElaChatWidget)
        submitted = []
        chat.messageSubmitted.connect(lambda text: submitted.append(text))
        chat.sendUserMessage("第一问")
        assistantId = chat.beginAssistantMessage()
        chat.chatView().appendText(assistantId, "回答")
        chat.enqueueMessage("排队问题")

        chat.endAssistantMessage()
        assert submitted == ["第一问", "排队问题"]
        assert chat.queueCount() == 0
        assert chat.isGenerating() is True
        assert chat.chatView().message(assistantId).status == ElaChatStatusType.Done

    def test_end_assistant_message_respects_auto_send_off(self, qapp, make):
        chat = make(ElaChatWidget)
        submitted = []
        chat.messageSubmitted.connect(lambda text: submitted.append(text))
        chat.setAutoSendQueue(False)
        chat.sendUserMessage("第一问")
        chat.beginAssistantMessage()
        chat.enqueueMessage("排队问题")

        chat.endAssistantMessage()
        assert submitted == ["第一问"]
        assert chat.queueCount() == 1
        assert chat.isGenerating() is False

        assert chat.sendNextQueued() is True
        assert submitted == ["第一问", "排队问题"]

    def test_send_next_queued_requires_idle(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.beginAssistantMessage()
        chat.enqueueMessage("排队问题")
        assert chat.sendNextQueued() is False
        assert chat.queueCount() == 1
        chat.endAssistantMessage()

    def test_queue_changed_signal(self, qapp, make):
        chat = make(ElaChatWidget)
        snapshots = []
        chat.queueChanged.connect(snapshots.append)
        queueId = chat.enqueueMessage("排队问题")
        assert snapshots[-1][0]["id"] == queueId
        assert chat.dequeueMessage(queueId) is True
        assert snapshots[-1] == []


class TestConcurrentTurnSafety:
    """同一时刻只保留一个活跃流：立即发送 / 错误定向 / 双 begin 防护。"""

    def test_send_queued_now_ends_active_stream(self, qapp, make):
        chat = make(ElaChatWidget)
        first = chat.beginAssistantMessage()
        chat.chatView().appendText(first, "旧回答")
        chat.enqueueMessage("第二问")
        queueId = chat.queuedMessages()[0]["id"]
        submitted = []
        stopped = []
        chat.messageSubmitted.connect(submitted.append)
        chat.stopRequested.connect(lambda: stopped.append(1))

        chat.sendQueuedNow(queueId)

        assert stopped == [1]
        assert chat.chatView().message(first).status == ElaChatStatusType.Stopped
        assert chat.isGenerating() is True
        assert submitted == ["第二问"]

        # 新回合的分片不会再落到旧消息
        second = chat.beginAssistantMessage()
        chat.chatView().appendText(second, "新回答")
        assert chat.chatView().message(first).text == "旧回答"
        assert chat.chatView().message(second).text == ""
        assert chat.chatView().bubble(second).text() == "新回答"

    def test_send_queued_now_with_sync_host_finish_keeps_queue_order(self, qapp, make):
        chat = make(ElaChatWidget)
        submitted = []
        chat.messageSubmitted.connect(submitted.append)

        def on_stop():
            # 模拟宿主在 stopRequested 槽里同步收尾（binder.finish 语义）
            if chat.isGenerating():
                chat.endAssistantMessage(status=ElaChatStatusType.Stopped)

        chat.stopRequested.connect(on_stop)
        chat.beginAssistantMessage()
        chat.enqueueMessage("A")
        chat.enqueueMessage("B")
        first = chat.queuedMessages()[0]["id"]

        chat.sendQueuedNow(first)

        assert submitted == ["A"]
        assert chat.queueCount() == 1

    def test_error_on_other_message_keeps_generating(self, qapp, make):
        chat = make(ElaChatWidget)
        other = chat.addMessage(ElaChatRoleType.Assistant, "旧回答")
        streaming = chat.beginAssistantMessage()
        chat.chatView().appendText(streaming, "进行中")

        chat.chatView().setMessageError(other, "旧消息出错")
        assert chat.chatView().message(other).status == ElaChatStatusType.Error
        assert chat.isGenerating() is True
        assert chat._streaming_id == streaming

    def test_begin_assistant_message_ends_previous(self, qapp, make):
        chat = make(ElaChatWidget)
        first = chat.beginAssistantMessage()
        chat.chatView().appendText(first, "第一条")
        finished = []
        chat.generationFinished.connect(
            lambda mid, status: finished.append((mid, status))
        )

        second = chat.beginAssistantMessage()

        assert chat.chatView().message(first).status == ElaChatStatusType.Stopped
        assert finished == [(first, ElaChatStatusType.Stopped)]
        assert chat._streaming_id == second
        chat.chatView().appendText(second, "第二条")
        assert chat.chatView().message(second).text == ""
        assert chat.chatView().bubble(second).text() == "第二条"
        chat.endAssistantMessage(second)
        assert chat.chatView().message(second).text == "第二条"

    def test_clear_clears_queue_and_stops(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.beginAssistantMessage()
        chat.enqueueMessage("排队问题")
        stopped = []
        chat.stopRequested.connect(lambda: stopped.append(1))

        chat.clear()

        assert stopped == [1]
        assert chat.queueCount() == 0
        assert chat.chatView().messages() == []
        assert chat.isGenerating() is False

    def test_clear_with_sync_host_finish_does_not_resend_queue(self, qapp, make):
        chat = make(ElaChatWidget)
        submitted = []
        chat.messageSubmitted.connect(submitted.append)

        def on_stop():
            # 宿主的真实收尾路径：binder.finish -> endAssistantMessage(目标已结束)
            # -> 末尾排下一条排队消息。组件必须在这条链上把续发压住。
            chat.endAssistantMessage(status=ElaChatStatusType.Stopped)

        chat.stopRequested.connect(on_stop)
        chat.beginAssistantMessage()
        chat.enqueueMessage("排队问题")

        chat.clear()

        assert submitted == []
        assert chat.queueCount() == 0
        assert chat.isGenerating() is False

    def test_send_queued_now_keeps_other_queued_items(self, qapp, make):
        """点 B 的「立即发送」不该把队首 A 抢先发出去（顺序错乱 + A 被截断）。"""
        chat = make(ElaChatWidget)
        submitted = []
        chat.messageSubmitted.connect(submitted.append)
        chat.beginAssistantMessage()
        chat.enqueueMessage("A")
        chat.enqueueMessage("B")
        queued = {item["text"]: item["id"] for item in chat.queuedMessages()}

        def on_stop():
            chat.endAssistantMessage(status=ElaChatStatusType.Stopped)

        chat.stopRequested.connect(on_stop)
        chat.sendQueuedNow(queued["B"])

        assert submitted == ["B"], "只有被点的那条该发出去"
        assert [item["text"] for item in chat.queuedMessages()] == ["A"]

    def test_end_explicit_id_keeps_error_status(self, qapp, make):
        chat = make(ElaChatWidget)
        messageId = chat.beginAssistantMessage()
        chat.setMessageError("失败", messageId)

        chat.endAssistantMessage(messageId)

        assert chat.chatView().message(messageId).status == ElaChatStatusType.Error
