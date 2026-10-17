"""聊天组件性能冒烟测试。

**不钉墙钟**：断言一律钉「同一对象 / 同一结果」或行为契约（缓冲未物化、
宽度冻结、挂起生效…）。耗时阈值随机器与负载变化，只会带来 flake。
"""

from __future__ import annotations

from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import (
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatView,
    ElaChatWidget,
)


class TestChatPerformance:
    def test_many_messages_snapshot(self, qapp, make):
        """30 条消息：计数、顺序与快照拷贝契约。"""
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        for index in range(30):
            view.addMessage(ElaChatRoleType.User, f"第 {index} 条消息 " + "内容" * 10)
        assert view.count() == 30

        # 快照查询返回副本（防宿主改内部列表），内容与顺序正确
        first = view.messages()
        second = view.messages()
        assert first is not second
        assert len(first) == 30
        assert first[0].text.startswith("第 0 条消息")
        assert first[-1].text.startswith("第 29 条消息")

    def test_streaming_chunks_land_and_hug_content(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.resize(520, 360)
        chat.show()
        qapp.processEvents()
        chat.sendUserMessage("长回答")
        messageId = chat.beginAssistantMessage()
        for index in range(300):
            chat.chatView().appendText(messageId, f"分片 {index}，")
        chat.endAssistantMessage()
        assert chat.chatView().message(messageId).status == ElaChatStatusType.Done
        assert chat.chatView().message(messageId).text.count("分片") == 300

        # 嵌入模式高度贴合内容：不含文末空白，但不裁剪正文
        viewer = chat.chatView().bubble(messageId).markdownViewer()
        document = viewer.document()

        def _hugged_content():
            last = document.lastBlock()
            rect = document.documentLayout().blockBoundingRect(last)
            return (
                rect.height() > 0
                and viewer.height() >= rect.bottom()
                and viewer.height() <= document.size().height()
            )

        assert _wait_until(qapp, _hugged_content)

    def test_rich_messages_build_complete_snapshot(self, qapp, make):
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        stats = ElaChatStats(
            prompt_tokens=10, completion_tokens=20, total_tokens=30, tps=40.0
        )
        for index in range(12):
            messageId = view.addMessage(
                ElaChatRoleType.Assistant, f"第 {index} 条回答 " + "内容" * 8
            )
            view.setReasoning(messageId, f"推理 {index}", 500.0)
            callId = view.addToolCall(messageId, "read_file", '{"path": "a.txt"}')
            view.setToolCallResult(messageId, callId, "结果 " + str(index))
            view.setStepStats(messageId, stats)
        assert view.count() == 12
        snapshot = view.message(12)
        assert snapshot.reasoning == "推理 11"
        assert len(snapshot.tool_calls) == 1
        assert snapshot.stats is stats

    def test_long_stream_keeps_chunks_buffered(self, qapp, make):
        """长正文流：分片先入缓冲、回合结束才落定（旧实现是逐片 O(n²) 拼接）。"""
        chat = make(ElaChatWidget)
        message_id = chat.beginAssistantMessage()
        chunk = "这是一个稍长一些的分片内容用于放大字符串拼接开销"
        chunks = 4000
        for _ in range(chunks):
            chat.chatView().appendText(message_id, chunk)
        # 实时全文走气泡（纯读取，不物化 part.text）
        bubble = chat.chatView().bubble(message_id)
        assert bubble.text() == chunk * chunks
        # 快照在回合结束前是落定值（空），结束后才是完整正文
        assert chat.chatView().message(message_id).text == ""
        chat.endAssistantMessage(message_id)
        assert chat.chatView().message(message_id).text == chunk * chunks

    def test_long_inline_reasoning_heading_is_incremental(self, qapp, make):
        """长思考流（内联）：标题增量扫描，分片在回合结束前不落定。"""
        chat = make(ElaChatWidget)
        message_id = chat.beginAssistantMessage()
        bubble = chat.chatView().bubble(message_id)
        bubble.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        chat.chatView().beginReasoning(message_id)
        chunks = 3000
        chat.chatView().appendReasoning(message_id, "# 分析步骤\n")
        for _ in range(chunks):
            chat.chatView().appendReasoning(message_id, "推理分片内容")
        assert bubble.reasoning() == "# 分析步骤\n" + "推理分片内容" * chunks
        assert chat.chatView().message(message_id).reasoning == ""
        assert bubble.thinkingRow().heading() == "分析步骤"
        chat.endAssistantMessage(message_id)
        assert (
            chat.chatView().message(message_id).reasoning
            == "# 分析步骤\n" + "推理分片内容" * chunks
        )
        assert bubble.thinkingRow().heading() == "分析步骤"

    def test_resize_reflow_deferred_freezes_width(self, qapp, make):
        """延迟重排：开启时冻结内容宽度，释放后按新宽度一次性重排。"""
        view = make(ElaChatView)
        view.resize(480, 320)
        view.show()
        qapp.processEvents()
        md = "## 标题\n\n内容段落。" * 8
        for _ in range(60):
            view.addMessage(ElaChatRoleType.Assistant, md)
        qapp.processEvents()

        # 关闭延迟重排：resize 立即重排，不冻结
        view.setResizeReflowDeferred(False)
        view.resize(440, 320)
        qapp.processEvents()
        assert view._resize_frozen_width == 0
        assert view._resize_reflow_timer.isActive() is False

        # 开启：拖动期间冻结在起始宽度，停手后（delayMs 到点）释放
        view.setResizeReflowDeferred(True, minMessages=2, delayMs=200)
        view.resize(460, 320)
        qapp.processEvents()
        assert view._resize_frozen_width > 0
        assert view._resize_reflow_timer.isActive() is True
        assert _wait_until(qapp, lambda: view._resize_frozen_width == 0)
        # 释放后内容宽度拉回视口（ElaScrollBar 出现/消失会改变视口宽度）
        assert _wait_until(
            qapp, lambda: view._content.width() == view._scroll.viewport().width()
        )

    def test_suspension_bounds_live_viewers(self, qapp, make):
        """视口外挂起：大消息量下远离视口的查看器被替换为占位。"""
        view = make(ElaChatView)
        view.resize(360, 200)
        view.show()
        qapp.processEvents()
        view.setViewportSuspension(True, minMessages=2)
        ids = [
            view.addMessage(ElaChatRoleType.Assistant, "长内容 " * 60) for _ in range(10)
        ]
        bar = view._scroll.verticalScrollBar()
        assert _wait_until(qapp, lambda: bar.maximum() > 0)
        bar.setValue(0)
        assert _wait_until(
            qapp,
            lambda: sum(view.bubble(mid).viewersSuspended() for mid in ids) >= 1,
        )
        assert view.bubble(ids[-1]).viewersSuspended() is True
        assert view.bubble(ids[-1]).markdownViewer() is None
