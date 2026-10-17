"""ElaChatStreamBinder 映射器测试：步骤边界、思考复用、工具状态与摘要。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro.chat import (
    ElaChatMockBackend,
    ElaChatPartKindType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatStreamBinder,
    ElaChatWidget,
)


class _Clock:
    """可推进的假时钟（秒）。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0


class _FakeWorker(QObject):
    """最小后端（信号契约与 ElaChatMockBackend 同构）。"""

    llmStarted = pyqtSignal()
    chunkReceived = pyqtSignal(object)
    toolStarted = pyqtSignal(dict)
    toolEnded = pyqtSignal(dict, str)
    statsReady = pyqtSignal(object, float, float)
    emptyTurn = pyqtSignal(str)
    turnFinished = pyqtSignal(int)

    def __init__(self, ready: bool = True) -> None:
        super().__init__()
        self.ask_calls: list = []
        self.regenerate_calls: list = []
        self.ask_attachments: list = []
        self.regenerate_attachments: list = []
        self.shutdown_calls: list = []
        self.cancel_calls: list = []
        #: 每次受理返回的回合 token（与真实后端同构）
        self.turn_tokens: list = []
        self.ready = ready

    def _accept(self) -> Optional[int]:
        if not self.ready:
            return None
        self.turn_tokens.append(len(self.turn_tokens) + 1)
        return self.turn_tokens[-1]

    def ask(self, text: str, attachments=None) -> Optional[int]:
        self.ask_calls.append(text)
        self.ask_attachments.append(list(attachments or ()))
        return self._accept()

    def regenerate(self, text: str, attachments=None) -> Optional[int]:
        self.regenerate_calls.append(text)
        self.regenerate_attachments.append(list(attachments or ()))
        return self._accept()

    def cancel(self) -> None:
        self.cancel_calls.append(True)

    def shutdown(self) -> None:
        self.shutdown_calls.append(True)


def _begin(chat: ElaChatWidget, binder: ElaChatStreamBinder) -> tuple:
    """开一个新回合，返回 ``(消息 id, 回合 token)``。"""
    chat.sendUserMessage("问")
    messageId = chat.beginAssistantMessage()
    return messageId, binder.beginTurn()


class TestFullTurn:
    def test_parts_and_summary(self, qapp, make):
        clock = _Clock()
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, clock)
        messageId, turn = _begin(chat, binder)

        clock.advance(100)
        binder.beginRound()
        binder.reasoning("想")
        binder.reasoning("考")
        clock.advance(200)
        binder.answer("正文")
        binder.stats(
            SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                prompt_cache_hit_tokens=3,
            ),
            ttftMs=120,
            tps=42,
        )
        binder.toolStart("t1", "read", {"path": "a.txt"})
        binder.toolEnd("t1", "已读取")
        clock.advance(300)
        binder.beginRound()
        binder.toolStart("t2", "patch", '{"path": "b.md"}')
        binder.toolEnd("t2", "Error: 文件被占用")
        clock.advance(100)
        binder.stats(
            SimpleNamespace(
                prompt_tokens=20,
                completion_tokens=8,
                total_tokens=28,
                prompt_cache_hit_tokens=0,
                prompt_tokens_details=SimpleNamespace(cached_tokens=7),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=4),
                cache_creation_input_tokens=2,
            )
        )
        binder.answer("后半")
        clock.advance(300)
        summary = binder.finish(turn)

        assert binder.roundIndex() == 2
        assert binder.isOpen() is False
        assert summary.status == ElaChatStatusType.Done
        assert summary.hadText is True
        assert summary.isEmptyReply() is False
        assert summary.durationMs == pytest.approx(1000.0)

        message = chat.chatView().messages()[-1]
        assert message.status == ElaChatStatusType.Done
        assert message.stepCount == 2
        assert [part.kind for part in message.parts] == [
            ElaChatPartKindType.Reasoning,
            ElaChatPartKindType.Text,
            ElaChatPartKindType.Stats,
            ElaChatPartKindType.Tool,
            ElaChatPartKindType.Tool,
            ElaChatPartKindType.Stats,
            ElaChatPartKindType.Text,
        ]
        # 同一轮的推理分片复用同一思考段
        assert len(message.partsOfKind(ElaChatPartKindType.Reasoning)) == 1
        assert message.reasoning == "想考"
        assert message.reasoning_ms == pytest.approx(200.0)
        assert message.text == "正文后半"
        assert [(c.name, c.status) for c in message.tool_calls] == [
            ("read", ElaChatStatusType.Done),
            ("patch", ElaChatStatusType.Error),
        ]
        stats_parts = message.partsOfKind(ElaChatPartKindType.Stats)
        assert [
            (
                s.stats.prompt_tokens,
                s.stats.cache_read_tokens,
                s.stats.reasoning_tokens,
                s.stats.cache_write_tokens,
            )
            for s in stats_parts
        ] == [
            (10, 3, 0, 0),
            (20, 7, 4, 2),
        ]
        assert stats_parts[0].stats.ttft_ms == 120.0
        assert stats_parts[0].stats.tps == 42.0
        assert stats_parts[0].stats.duration_ms == pytest.approx(200.0)
        assert stats_parts[1].stats.duration_ms == pytest.approx(100.0)

        # 幂等：同一 token 重复收尾属于「陈旧收尾」，直接丢弃
        assert binder.finish(turn) is None
        assert chat.isGenerating() is False

    def test_stats_accepts_ela_chat_stats(self, qapp, make):
        clock = _Clock()
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, clock)
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.stats(ElaChatStats(prompt_tokens=3, completion_tokens=4), ttftMs=80)
        stats = (
            chat.chatView().messages()[-1].partsOfKind(ElaChatPartKindType.Stats)[0].stats
        )
        assert stats.prompt_tokens == 3
        assert stats.completion_tokens == 4
        assert stats.ttft_ms == pytest.approx(80.0)
        binder.finish(turn)

    def test_empty_stats_and_text_ignored(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.reasoning("")
        binder.answer("")
        binder.stats(None)
        binder.toolEnd("", "ignored")
        message = chat.chatView().messages()[-1]
        assert not message.parts
        binder.finish(turn)


class TestToolStatus:
    def test_error_prefix_infers_failure(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.toolStart("a", "grep")
        binder.toolEnd("a", "Error: 目录不存在")
        binder.toolStart("b", "read")
        binder.toolEnd("b", "内容")
        calls = chat.chatView().messages()[-1].tool_calls
        assert [(c.name, c.status) for c in calls] == [
            ("grep", ElaChatStatusType.Error),
            ("read", ElaChatStatusType.Done),
        ]

    def test_explicit_ok_overrides_prefix(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.toolStart("a", "shell")
        binder.toolEnd("a", "Error: not really", ok=True)
        calls = chat.chatView().messages()[-1].tool_calls
        assert calls[0].status == ElaChatStatusType.Done


class TestErrorsAndEmptyTurn:
    def test_error_closes_reasoning_and_marks_message(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.reasoning("思考中")
        binder.error("worker", "连接中断")
        message = chat.chatView().messages()[-1]
        # 类型单独存字段，不拼进文案（否则错误卡无法判断该不该给「重试」）
        assert message.error == "连接中断"
        assert message.error_type == "worker"
        assert chat.chatView().messageError(message.id) == ("连接中断", "worker")
        assert len(message.partsOfKind(ElaChatPartKindType.Reasoning)) == 1

    def test_empty_turn_summary(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.emptyTurn("length")
        summary = binder.finish(turn)
        assert summary.isEmptyReply() is True
        assert summary.hadText is False
        assert summary.finishReason == "length"
        assert chat.chatView().messages()[-1].text == ""


class TestWhitespaceChunks:
    """纯空白分片不算正文：不开正文段、不算 hadText，但空白本身保真。"""

    def test_whitespace_only_reply_is_empty(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.answer("\n\n")
        summary = binder.finish(turn)
        assert summary.hadText is False
        assert summary.isEmptyReply() is True
        message = chat.chatView().messages()[-1]
        assert message.text == ""
        assert message.partsOfKind(ElaChatPartKindType.Text) == []

    def test_leading_whitespace_merges_into_first_text_part(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.answer("\n\n")
        binder.answer("正文")
        binder.finish(turn)
        assert chat.chatView().messages()[-1].text == "\n\n正文"

    def test_mid_text_whitespace_is_preserved(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.answer("hello")
        binder.answer(" ")
        binder.answer("world")
        binder.finish(turn)
        assert chat.chatView().messages()[-1].text == "hello world"


class TestConvenienceDispatch:
    """便捷方法：分片对象 / OpenAI 风格 tool_call dict 直接可连信号。"""

    def test_stream_dispatches_reasoning_and_answer(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.stream(SimpleNamespace(reasoning_content="想", answer_content=""))
        binder.stream(SimpleNamespace(reasoning_content="", answer_content="正文"))
        binder.stream(SimpleNamespace(reasoning_content="再", answer_content="答"))
        # 正文一开始，binder 就结束了推理段 —— 推理是真的结束了，所以已落定；
        # 正文仍在途，快照里是空串，实时全文走气泡。
        bubble = chat.chatView().bubble(chat.streamingMessageId())
        assert bubble.text() == "正文答"
        assert bubble.reasoning() == "想再"
        message = chat.chatView().messages()[-1]
        assert message.reasoning == "想再"
        assert message.text == ""
        # 回合结束后快照才是完整内容
        binder.finish(turn)
        message = chat.chatView().messages()[-1]
        assert message.reasoning == "想再"
        assert message.text == "正文答"

    def test_stream_tolerates_missing_fields(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.stream(object())
        binder.stream(SimpleNamespace(reasoning_content=None, answer_content=None))
        assert chat.chatView().messages()[-1].text == ""
        binder.finish(turn)

    def test_tool_call_dict_dispatch(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.toolCallStarted(
            {
                "id": "t1",
                "function": {"name": "read", "arguments": '{"path": "a"}'},
            }
        )
        binder.toolCallEnded({"id": "t1"}, "内容")
        binder.toolCallStarted({})
        calls = chat.chatView().messages()[-1].tool_calls
        assert calls[0].name == "read"
        assert calls[0].isDone
        assert calls[1].name == "unknown"
        binder.finish(turn)

    def test_tool_call_ignores_non_dict(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.toolCallStarted(None)
        binder.toolCallEnded("not-a-dict", "结果")
        assert chat.chatView().messages()[-1].tool_calls == ()
        binder.finish(turn)


class TestWorkerBinding:
    """A/B：构造时绑定 worker 自动接线；startTurn 建消息并驱动后端。"""

    def test_ctor_worker_auto_wires_signals(self, qapp, make):
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        assert binder.worker() is worker

        turn = binder.startTurn("你好")
        assert turn is not None
        assert worker.ask_calls == ["你好"]
        assert chat.isGenerating() is True
        assert binder.isOpen() is True

        worker.llmStarted.emit()
        worker.chunkReceived.emit(
            SimpleNamespace(reasoning_content="想", answer_content="")
        )
        worker.chunkReceived.emit(
            SimpleNamespace(reasoning_content="", answer_content="答")
        )
        worker.toolStarted.emit({"id": "t1", "function": {"name": "read"}})
        worker.toolEnded.emit({"id": "t1"}, "内容")
        worker.statsReady.emit(ElaChatStats(prompt_tokens=1), 12.0, 8.0)

        message = chat.chatView().messages()[-1]
        # 工具 / 用量是结构化数据，回合未结束就已确定
        assert [(c.name, c.status) for c in message.tool_calls] == [
            ("read", ElaChatStatusType.Done)
        ]
        assert message.partsOfKind(ElaChatPartKindType.Stats)
        # 推理段在正文开始时已结束 -> 落定；正文仍在途 -> 快照为空
        assert message.reasoning == "想"
        assert message.text == ""
        binder.finish(turn)
        message = chat.chatView().messages()[-1]
        assert message.text == "答"
        assert message.reasoning == "想"

    def test_connect_worker_after_construction(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat)
        worker = _FakeWorker()
        binder.connectWorker(worker)
        assert binder.worker() is worker
        assert binder.startTurn("问") is not None

    def test_start_turn_regenerate_uses_regenerate(self, qapp, make):
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        assert binder.startTurn("原问题", regenerate=True) is not None
        assert worker.regenerate_calls == ["原问题"]
        assert worker.ask_calls == []

    def test_start_turn_forwards_attachments(self, qapp, make):
        """附件必须原样送到后端 —— 重新生成丢附件就是这条没接上。

        ``regenerateFrom`` 返回的提问快照里带着附件，宿主把
        ``message.attachments`` 传进 ``startTurn(attachments=...)`` 即可。
        """
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        attachment = {"name": "a.png", "path": "C:/a.png"}

        assert binder.startTurn("看图", attachments=[attachment]) is not None
        assert worker.ask_attachments == [[attachment]]

        assert (
            binder.startTurn("看图", attachments=[attachment], regenerate=True) is not None
        )
        assert worker.regenerate_attachments == [[attachment]]

    def test_start_turn_not_ready_creates_no_message(self, qapp, make):
        chat = make(ElaChatWidget)
        worker = _FakeWorker(ready=False)
        binder = ElaChatStreamBinder(chat, worker=worker)
        assert binder.startTurn("你好") is None
        assert chat.chatView().count() == 0
        assert chat.isGenerating() is False
        assert binder.isOpen() is False

    def test_start_turn_without_worker_returns_false(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat)
        assert binder.startTurn("你好") is None
        assert chat.chatView().count() == 0

    def test_empty_turn_auto_wired_into_summary(self, qapp, make):
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        turn = binder.startTurn("你好")
        assert turn is not None
        worker.emptyTurn.emit("length")
        summary = binder.finish(turn)
        assert summary.finishReason == "length"
        assert summary.isEmptyReply() is True

    def test_connect_same_worker_is_idempotent(self, qapp, make):
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        binder.connectWorker(worker)  # 重复绑定不得重复连接信号

        turn = binder.startTurn("问")
        assert turn is not None
        worker.llmStarted.emit()
        assert binder.roundIndex() == 1
        worker.chunkReceived.emit(
            SimpleNamespace(reasoning_content="", answer_content="答")
        )
        assert chat.chatView().messages()[-1].text == ""
        binder.finish(turn)
        assert chat.chatView().messages()[-1].text == "答"

    def test_rebind_disconnects_old_worker(self, qapp, make):
        chat = make(ElaChatWidget)
        first = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=first)
        second = _FakeWorker()
        binder.connectWorker(second)

        assert binder.worker() is second
        turn = binder.startTurn("问")
        assert turn is not None
        first.llmStarted.emit()
        first.chunkReceived.emit(
            SimpleNamespace(reasoning_content="", answer_content="旧")
        )
        assert binder.roundIndex() == 0
        assert chat.chatView().messages()[-1].text == ""

        second.llmStarted.emit()
        second.chunkReceived.emit(
            SimpleNamespace(reasoning_content="", answer_content="新")
        )
        assert binder.roundIndex() == 1
        assert chat.chatView().messages()[-1].text == ""
        binder.finish(turn)
        # 旧 worker 的分片始终没进消息，只有 "新"
        assert chat.chatView().messages()[-1].text == "新"


class TestLateEvents:
    """回合外（beginTurn 前 / finish 后）的迟到事件一律忽略。"""

    def test_events_after_finish_are_ignored(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.answer("正常")
        binder.finish(turn)

        binder.beginRound()
        binder.reasoning("迟到思考")
        binder.answer("迟到正文")
        binder.toolStart("t1", "read", '{"path": "a"}')
        binder.toolEnd("t1", "结果")
        binder.toolCallStarted({"id": "t2", "function": {"name": "grep"}})
        binder.toolCallEnded({"id": "t2"}, "结果")
        binder.stats(ElaChatStats(total_tokens=99), 10.0, 5.0)
        binder.error("late", "迟到错误")
        binder.emptyTurn("late")

        message = chat.chatView().messages()[-1]
        assert message.text == "正常"
        assert message.reasoning == ""
        assert message.tool_calls == ()
        assert message.stats is None
        assert message.error == ""
        assert binder.roundIndex() == 1
        # 同一 token 的第二次收尾是「陈旧收尾」：直接丢弃，不产生新摘要
        assert binder.finish(turn) is None

    def test_new_turn_still_works_after_late_events(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.answer("第一轮")
        binder.finish(turn)

        binder.answer("旧回合迟到分片")  # 忽略
        message_id, turn = _begin(chat, binder)
        assert binder.isOpen() is True
        binder.beginRound()
        binder.answer("第二轮")
        binder.stats(ElaChatStats(total_tokens=7))
        summary = binder.finish(turn)

        message = chat.chatView().message(message_id)
        assert summary.status == ElaChatStatusType.Done
        assert message.text == "第二轮"
        assert message.stats.total_tokens == 7


class TestStop:
    def test_finish_after_stop_keeps_status(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.reasoning("想")
        binder.answer("半句")
        chat.stopGeneration()
        summary = binder.finish(turn, ElaChatStatusType.Stopped)
        assert summary.status == ElaChatStatusType.Stopped
        message = chat.chatView().messages()[-1]
        assert message.status == ElaChatStatusType.Stopped
        assert message.text == "半句"
        assert chat.isGenerating() is False

    def test_cancel_closes_reasoning(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.reasoning("想")
        binder.cancel()
        assert chat.chatView().messages()[-1].reasoning_ms >= 0.0
        binder.finish(turn)

    def test_finish_defaults_to_stopped_after_cancel(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.beginRound()
        binder.reasoning("想")
        binder.answer("半句")
        binder.cancel()  # 宿主停止：无需再维护自己的 stopped 标志
        summary = binder.finish(turn)
        assert summary.status == ElaChatStatusType.Stopped
        assert chat.chatView().messages()[-1].status == ElaChatStatusType.Stopped
        assert chat.isGenerating() is False

    def test_begin_turn_resets_cancel_flag(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.cancel()
        assert binder.finish(turn).status == ElaChatStatusType.Stopped
        messageId, turn = _begin(chat, binder)  # 新回合
        assert binder.finish(turn).status == ElaChatStatusType.Done

    def test_explicit_status_overrides_cancel(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.cancel()
        assert binder.finish(turn, ElaChatStatusType.Done).status == ElaChatStatusType.Done

    # -- abortTurn（多话题：删除 / 关闭话题时立刻作废回合） ------------------

    def test_abort_turn_closes_turn_and_ignores_late_events(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat, _Clock())
        messageId, turn = _begin(chat, binder)
        binder.answer("写一半")
        messageId = chat.streamingMessageId()

        summary = binder.abortTurn()

        assert summary is not None and summary.status == ElaChatStatusType.Stopped
        assert binder.isOpen() is False
        assert chat.isGenerating() is False
        assert chat.chatView().message(messageId).status == ElaChatStatusType.Stopped
        before = chat.chatView().message(messageId).text
        # 作废之后迟到的事件一律无落点（多话题下同 id 恢复消息不会被污染）
        binder.stream("迟到的分片")
        binder.toolCallStarted(
            SimpleNamespace(id="late", name="read_file", arguments="{}")
        )
        assert chat.chatView().message(messageId).text == before
        assert chat.chatView().message(messageId).parts[-1].kind != ElaChatPartKindType.Tool

    def test_abort_turn_outside_turn_is_noop(self, qapp, make):
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        assert binder.abortTurn() is None  # 回合外：安全空操作
        assert worker.cancel_calls == []  # 也没有多停一次后端
        assert chat.isGenerating() is False
        assert chat.chatView().messages() == []

    def test_abort_turn_cancels_backend_by_default(self, qapp, make):
        """作废这一轮时默认把后端也停掉 —— 否则白烧 token。"""
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        assert binder.startTurn("边跑边删") is not None

        summary = binder.abortTurn()

        assert summary is not None and summary.status == ElaChatStatusType.Stopped
        assert worker.cancel_calls == [True]
        assert binder.isOpen() is False

    def test_abort_turn_can_leave_backend_running(self, qapp, make):
        """``cancelBackend=False``：只闭组件侧回合（后端中止归宿主的场景）。"""
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        assert binder.startTurn("后端留着") is not None

        summary = binder.abortTurn(cancelBackend=False)

        assert summary is not None and summary.status == ElaChatStatusType.Stopped
        assert worker.cancel_calls == []
        assert binder.isOpen() is False
        assert chat.isGenerating() is False

    def test_abort_turn_does_not_auto_send_queue(self, qapp, make):
        """作废不顺手起新一轮：排队消息留着，宿主的 autoSendQueue 设置原样还原。"""
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        assert chat.autoSendQueue() is True
        chat.sendUserMessage("第一轮")
        assert binder.startTurn("第一轮") is not None
        chat.enqueueMessage("排队中的第二条")

        binder.abortTurn()

        assert chat.queueCount() == 1  # 没被发出去
        assert chat.autoSendQueue() is True  # 宿主的设置没被改坏
        assert chat.isGenerating() is False
        # 消息照旧留着（作废的是「这一轮」，不是历史）
        assert len(chat.chatView().messages()) == 2

    def test_abort_turn_survives_reentrant_finish_from_backend(self, qapp, make):
        """后端 ``cancel()`` 同步发 ``turnFinished``、宿主接 ``binder.finish``：重入必须幂等。

        先收尾再停后端，重入那次 ``finish()`` 才不会把回合按 ``Done`` 结束
        （也不能因此续发排队消息）。
        """

        chat = make(ElaChatWidget)
        mock = ElaChatMockBackend(tickMs=0)
        binder = ElaChatStreamBinder(chat, worker=mock)
        mock.turnFinished.connect(binder.finish)  # 与示例 / llm_test 同款接线
        assert binder.startTurn("提问") is not None
        chat.enqueueMessage("排队中的第二条")

        summary = binder.abortTurn()

        assert summary is not None and summary.status == ElaChatStatusType.Stopped
        assert chat.chatView().messages()[-1].status == ElaChatStatusType.Stopped
        assert chat.queueCount() == 1
        assert binder.isOpen() is False
        mock.shutdown()


class TestShutdownOnClose:
    """窗口关闭 / 销毁时自动收尾后端（宿主免写 closeEvent）。"""

    def _window_with_binder(self, make, worker):
        window = make(QWidget)
        chat = make(ElaChatWidget, window)
        binder = ElaChatStreamBinder(chat, worker=worker)
        binder.shutdownOnClose(window)
        return window, chat

    def test_close_shuts_down_worker(self, qapp, make):
        worker = _FakeWorker()
        window, _chat = self._window_with_binder(make, worker)
        window.close()
        qapp.processEvents()
        assert worker.shutdown_calls == [True]

    def test_destroy_shuts_down_worker(self, qapp, make):
        worker = _FakeWorker()
        window, _chat = self._window_with_binder(make, worker)
        sip.delete(window)
        qapp.processEvents()
        assert worker.shutdown_calls == [True]

    def test_close_without_worker_is_noop(self, qapp, make):
        window = make(QWidget)
        chat = make(ElaChatWidget, window)
        binder = ElaChatStreamBinder(chat)
        binder.shutdownOnClose(window)
        window.close()
        qapp.processEvents()

    def test_worker_without_shutdown_is_safe(self, qapp, make):
        window = make(QWidget)
        chat = make(ElaChatWidget, window)
        binder = ElaChatStreamBinder(chat)
        binder._worker = object()  # 后端无 shutdown 方法
        binder.shutdownOnClose(window)
        window.close()
        qapp.processEvents()


class TestTurnBoundaryRobustness:
    """回合边界的重入与畸形输入（回归空回答 / 0xC0000409）。"""

    def test_finish_without_target_is_safe(self, qapp, make):
        """``beginTurn`` 后没有落点：finish 不能把 ``None`` 喂进 setMessageDuration。"""
        chat = make(ElaChatWidget)
        clock = _Clock(now=10.0)
        binder = ElaChatStreamBinder(chat, clock=clock)
        turn = binder.beginTurn()
        clock.advance(500)
        summary = binder.finish(turn)
        assert summary.durationMs > 0
        assert binder.isOpen() is False

    def test_finish_auto_send_keeps_new_turn_alive(self, qapp, make):
        """finish() 里的排队续发会同步开新回合，不能把新回合的落点抹掉。"""
        chat = make(ElaChatWidget)
        worker = _FakeWorker()
        binder = ElaChatStreamBinder(chat, worker=worker)
        chat.messageSubmitted.connect(lambda text: binder.startTurn(text))
        chat.enqueueMessage("第二个问题")
        first = binder.startTurn("第一个问题")
        assert first is not None
        binder.beginRound()
        binder.answer("答一")
        binder.finish(first)

        # 排队消息已自动发出：新回合必须仍然开着且有落点
        assert worker.ask_calls == ["第一个问题", "第二个问题"]
        assert binder.isOpen() is True
        assert chat.streamingMessageId() is not None
        # 新回合的分片不再被 isOpen() 闸门静默丢弃
        binder.beginRound()
        binder.answer("答二")
        binder.finish(worker.turn_tokens[-1])
        messages = chat.chatView().messages()
        assert messages[-1].text == "答二"
        assert messages[-1].status == ElaChatStatusType.Done

    def test_stats_with_non_finite_tokens_is_tolerated(self, qapp, make):
        """后端 usage 带 inf / nan 时按 0 计，而不是在槽里抛异常。"""
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat)
        mid = chat.beginAssistantMessage()
        binder.beginTurn()
        binder.stats(
            SimpleNamespace(
                prompt_tokens=float("inf"),
                completion_tokens=float("nan"),
                total_tokens=float("inf"),
            )
        )
        stats = chat.chatView().message(mid).stats
        assert stats is not None
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0
        assert stats.total_tokens == 0

    def test_malformed_tool_call_is_ignored(self, qapp, make):
        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat)
        mid = chat.beginAssistantMessage()
        binder.beginTurn()
        binder.toolCallStarted({"id": "c1", "function": "read"})
        assert chat.chatView().toolCalls(mid) == []
