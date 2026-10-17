"""流式生命周期回归：错误 / 结束路径必须收尾查看器、工具分组与快照分段。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatReasoningStyleType,
    ElaChatBubble,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatView,
    ElaChatWidget,
)


class TestInlineReasoningStream:
    def test_end_reasoning_stops_inline_viewer(self, qapp, make):
        """内联思考结束后查看器必须退出流式（否则光标永久闪烁）。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        bubble.beginReasoning()
        bubble.appendReasoning("思考内容")
        viewer = bubble._part_widgets[bubble._current_reasoning_id]
        assert viewer.isStreaming() is True

        bubble.endReasoning(500)

        assert viewer.isStreaming() is False
        assert viewer._caret_timer.isActive() is False

    def test_end_stream_stops_inline_reasoning(self, qapp, make):
        """endStream 收尾仍处于流式的内联思考查看器。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        bubble.beginStream()
        bubble.beginReasoning()
        bubble.appendReasoning("第一段")
        viewer = bubble._part_widgets[bubble._current_reasoning_id]

        bubble.endStream()

        assert viewer.isStreaming() is False
        assert bubble.status() == ElaChatStatusType.Done


class TestErrorTearsDownStream:
    def test_error_stops_text_viewer(self, qapp, make):
        chat = make(ElaChatWidget)
        messageId = chat.beginAssistantMessage()
        chat.chatView().appendText(messageId, "部分回答")
        viewer = chat.chatView().bubble(messageId).markdownViewer()
        assert viewer.isStreaming() is True

        chat.chatView().setMessageError(messageId, "网关错误")

        assert viewer.isStreaming() is False
        assert viewer._caret_timer.isActive() is False
        message = chat.chatView().message(messageId)
        assert message.status == ElaChatStatusType.Error
        assert all(part.status == ElaChatStatusType.Done for part in message.parts)

    def test_error_stops_inline_reasoning_and_text(self, qapp, make):
        chat = make(ElaChatWidget)
        messageId = chat.beginAssistantMessage()
        view = chat.chatView()
        view.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        view.bubble(messageId).setReasoningStyle(ElaChatReasoningStyleType.Inline)
        chat.chatView().beginReasoning(messageId)
        chat.chatView().appendReasoning(messageId, "推理中")
        reasoning_viewer = view.bubble(messageId)._part_widgets[
            view.bubble(messageId)._current_reasoning_id
        ]
        chat.chatView().appendText(messageId, "正文开始")

        chat.chatView().setMessageError(messageId, "连接中断")

        assert reasoning_viewer.isStreaming() is False
        message = chat.chatView().message(messageId)
        assert message.status == ElaChatStatusType.Error
        assert all(part.status == ElaChatStatusType.Done for part in message.parts)

    def test_view_error_syncs_part_status(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(messageId, "part")

        view.setMessageError(messageId, "boom")

        message = view.message(messageId)
        assert message.error == "boom"
        assert all(part.status == ElaChatStatusType.Done for part in message.parts)


class TestToolGroupFinish:
    def test_context_only_turn_finishes_group(self, qapp, make):
        """仅上下文工具的回合在 endStream 时分组卡应收为「已探索」。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginStream()
        callId = bubble.addToolCall("read", '{"path": "a.py"}')
        bubble.setToolCallResult(callId, "内容")
        group = bubble._group_card
        assert group is not None
        assert group.title() == "正在探索"

        bubble.endStream()

        assert group.title() == "已探索"
        assert group.isBusy() is False


class TestSnapshotConsistency:
    def test_end_message_syncs_part_status(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        view.appendText(messageId, "hello")

        view.endMessage(messageId)

        parts = view.message(messageId).parts
        assert parts
        assert all(part.status == ElaChatStatusType.Done for part in parts)
        assert view.message(messageId).status == ElaChatStatusType.Done
