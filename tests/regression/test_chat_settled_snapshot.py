"""回归测试：**完整反转**后的落定语义（``part`` 自足可序列化）。

契约（``ElaChatBubble.parts`` 纯读取）：

- ``part.text`` **只含已落定内容**。流式在途分片只在缓冲里，``parts()`` /
  ``text()`` / ``reasoning()`` 全是纯读取，绝不写回。
- 落定发生在分段结束处：``endText()`` / ``endReasoning()`` /
  ``endStream()`` / ``setError()`` 都会把缓冲并入 ``part.text``。
- 因此消息快照 ``message.text`` 在**流式期间为空**，回合结束才是完整正文。

好处：任意时刻的 ``parts()`` 都能直接序列化落库，读一次与读一百次相同。
代价：流式期间的实时预览要走气泡 API（``bubble.text()`` / ``partText()``）
或 ``messageUpdated`` 信号，不再从快照读。

对齐 opencode 的 ``part_text_accum_delta`` 分层：accum 存在途增量、
``part.text`` 存落定值，二者由 ``readPartText`` 合成。这里
``partText()`` 就是那个合成函数。
"""

from __future__ import annotations

import json

from pyqt6_ela_pro.chat import ElaChatPartKindType, ElaChatWidget


def _texts(parts) -> list:
    return [p.text for p in parts if p.kind == ElaChatPartKindType.Text]


def _reasons(parts) -> list:
    return [p.text for p in parts if p.kind == ElaChatPartKindType.Reasoning]


def _chat(qapp) -> ElaChatWidget:
    chat = ElaChatWidget()
    chat.resize(600, 400)
    chat.show()
    qapp.processEvents()
    return chat


class TestPartsIsPure:
    def test_parts_does_not_absorb_buffer(self, qapp):
        """``parts()`` 是纯读取：连续调用不改变缓冲，也不改变 ``part.text``。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.appendText(messageId, "hello world")

        bubble = view.bubble(messageId)
        assert bubble.hasPendingText() is True

        first = bubble.parts()
        second = bubble.parts()
        assert first == second, "parts() 非幂等"
        assert bubble.hasPendingText() is True, "parts() 把在途分片物化进了 part.text"
        assert all(t == "" for t in _texts(first)), (
            f"落定快照里不应含在途内容：{_texts(first)!r}"
        )
        chat.deleteLater()
        qapp.processEvents()

    def test_reads_are_stable_under_repetition(self, qapp):
        """连续读 20 次，快照必须逐字节相同（落库时机无关）。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        for ch in "abcdefgh":
            view.appendText(messageId, ch)

        bubble = view.bubble(messageId)
        baseline = [(p.id, p.kind, p.status, p.text) for p in bubble.parts()]
        for _ in range(20):
            assert [
                (p.id, p.kind, p.status, p.text) for p in bubble.parts()
            ] == baseline

        # 混入其它读 API 也不能改变它
        bubble.text()
        bubble.reasoning()
        assert [(p.id, p.kind, p.status, p.text) for p in bubble.parts()] == baseline
        chat.deleteLater()
        qapp.processEvents()

    def test_part_text_is_live_and_pure(self, qapp):
        """``partText()`` = 落定 + 在途，是界面所见；且同样不写回。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.appendText(messageId, "hello world")

        bubble = view.bubble(messageId)
        text_parts = [p for p in bubble.parts() if p.kind == ElaChatPartKindType.Text]
        assert text_parts
        assert bubble.partText(text_parts[0]) == "hello world"
        assert text_parts[0].text == "", "partText() 物化了 part.text"
        assert bubble.text() == "hello world"
        assert bubble.parts()[0].text == "", "text() 物化了 part.text"
        chat.deleteLater()
        qapp.processEvents()


class TestSettleOnSegmentEnd:
    def test_end_text_settles(self, qapp):
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.appendText(messageId, "part one")
        view.endText(messageId)
        qapp.processEvents()

        bubble = view.bubble(messageId)
        assert _texts(bubble.parts()) == ["part one"]
        assert bubble.hasPendingText() is False
        chat.deleteLater()
        qapp.processEvents()

    def test_end_stream_settles_everything(self, qapp):
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.beginReasoning(messageId)
        view.appendReasoning(messageId, "thinking")
        view.appendText(messageId, "final answer")
        view.endMessage(messageId)
        qapp.processEvents()

        bubble = view.bubble(messageId)
        assert bubble.hasPendingText() is False
        assert _reasons(bubble.parts()) == ["thinking"]
        assert _texts(bubble.parts()) == ["final answer"]
        chat.deleteLater()
        qapp.processEvents()

    def test_error_path_settles(self, qapp):
        """错误收尾也必须落定，否则崩溃恢复会丢掉已收到的内容。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.appendText(messageId, "partial")
        view.setMessageError(messageId, "boom")
        qapp.processEvents()

        bubble = view.bubble(messageId)
        assert bubble.hasPendingText() is False, "错误路径没有落定缓冲"
        assert _texts(bubble.parts()) == ["partial"]
        chat.deleteLater()
        qapp.processEvents()

    def test_settled_snapshot_is_json_ready(self, qapp):
        """落定快照可以直接 JSON 化（存储模块的基本要求）。"""

        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.appendText(messageId, "serialize **me**")
        view.endMessage(messageId)
        qapp.processEvents()

        bubble = view.bubble(messageId)
        payload = [
            {"id": p.id, "kind": p.kind, "status": p.status, "text": p.text}
            for p in bubble.parts()
        ]
        assert json.loads(json.dumps(payload, ensure_ascii=False))[0]["text"] == (
            "serialize **me**"
        )
        chat.deleteLater()
        qapp.processEvents()


class TestNoStrandedBuffer:
    """「在途」只存在于流式回合内 —— 非流式追加必须当场落定。

    反转 ``parts()`` 为纯读后暴露出来的真 bug：``appendText()`` 曾经无条件
    走缓冲，往**已结束**的消息追加时没有 ``endText()`` 来结算，缓冲永远滞留，
    文本对界面可见、对存储完全不可见。
    """

    def test_append_to_finished_message_settles_immediately(self, qapp):
        chat = _chat(qapp)
        first = chat.beginAssistantMessage()
        chat.endAssistantMessage(first)
        qapp.processEvents()
        # 第二条消息开着不收尾，模拟「前一条已结束后仍有在途回合」的迟到追加
        chat.beginAssistantMessage()

        chat.chatView().appendText(first, "给第一条")
        qapp.processEvents()
        assert view_text(chat, first) == "给第一条", (
            "往已结束的消息追加，文本滞留在缓冲里，对存储不可见"
        )
        bubble = view_bubble(chat, first)
        assert bubble.hasPendingText() is False
        chat.deleteLater()
        qapp.processEvents()

    def test_append_reasoning_to_finished_message_settles(self, qapp):
        chat = _chat(qapp)
        messageId = chat.beginAssistantMessage()
        chat.endAssistantMessage(messageId)
        qapp.processEvents()

        view = chat.chatView()
        view.appendReasoning(messageId, "事后补的思考")
        qapp.processEvents()
        assert chat.chatView().message(messageId).reasoning == "事后补的思考"
        assert view_bubble(chat, messageId).hasPendingText() is False
        chat.deleteLater()
        qapp.processEvents()

    def test_streaming_still_buffers(self, qapp):
        """对照组：流式回合内仍然走缓冲，不当场落定。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.appendText(messageId, "in flight")
        assert view_bubble(chat, messageId).hasPendingText() is True
        assert view_text(chat, messageId) == ""
        view.endMessage(messageId)
        assert view_bubble(chat, messageId).hasPendingText() is False
        assert view_text(chat, messageId) == "in flight"
        chat.deleteLater()
        qapp.processEvents()


class TestMessageSnapshotIsSettledOnly:
    def test_message_text_empty_during_stream(self, qapp):
        """流式期间快照 ``text`` 为空 —— 这是完整反转的既定代价。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        view.appendText(messageId, "live preview text")
        qapp.processEvents()
        assert view.message(messageId).text == ""
        # 实时预览走气泡
        assert view.bubble(messageId).text() == "live preview text"
        chat.deleteLater()
        qapp.processEvents()

    def test_message_text_complete_after_stream(self, qapp):
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        for ch in "final answer":
            view.appendText(messageId, ch)
        assert view.message(messageId).text == ""
        view.endMessage(messageId)
        qapp.processEvents()
        assert view.message(messageId).text == "final answer"
        chat.deleteLater()
        qapp.processEvents()

    def test_user_message_text_always_direct(self, qapp):
        """用户消息没有分段，``text`` 直接存字段，任何时候都可读。"""
        chat = _chat(qapp)
        messageId = chat.sendUserMessage("hello there")
        qapp.processEvents()
        assert view_text(chat, messageId) == "hello there"
        chat.deleteLater()
        qapp.processEvents()

    def test_loaded_assistant_message_has_text(self, qapp):
        """从存储恢复的助手消息（无流式过程）文本必须完整。"""
        chat = _chat(qapp)
        messageId = chat.addMessage("assistant", "restored **content**")
        qapp.processEvents()
        assert view_text(chat, messageId) == "restored **content**"
        chat.deleteLater()
        qapp.processEvents()

    def test_settled_snapshot_and_parts_converge(self, qapp):
        """回合结束后，快照与 ``parts()`` 必须给出同一个答案。"""
        chat = _chat(qapp)
        view = chat.chatView()
        messageId = chat.beginAssistantMessage()
        for ch in "final answer":
            view.appendText(messageId, ch)
        view.endMessage(messageId)
        qapp.processEvents()

        bubble = view.bubble(messageId)
        parts_text = "".join(_texts(bubble.parts()))
        assert parts_text == view.message(messageId).text
        assert parts_text == bubble.text()
        chat.deleteLater()
        qapp.processEvents()


def view_text(chat: ElaChatWidget, messageId: int) -> str:
    return chat.chatView().message(messageId).text


def view_bubble(chat: ElaChatWidget, messageId: int):
    return chat.chatView().bubble(messageId)
