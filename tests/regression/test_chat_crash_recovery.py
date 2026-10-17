"""回归测试：崩溃恢复日志 :class:`ElaChatTurnJournal`。

解决的问题
----------
``parts`` 的落定语义保证 ``message.toDict()`` 任意时刻可落库，但**流式在途
分片只在气泡缓冲里** —— 回合中途进程死掉，那个回合收到的内容全丢。本日志把
回合记成**追加写事件流**，崩了能重放出全部内容。

关键不变量
----------
- **记录 == 重放**：``_push`` 记事件的同时应用它，所以正在记录的 journal 自己
  就是可用 journal（``message()`` 随时给「已收到的部分」），``replayInto()``
  不必先序列化再读回；
- **残行可容忍**：进程可能在写一半时被杀，``loadsLine()`` 对截断 / 非法 JSON
  返回 ``None`` 而不抛；
- **未知事件跳过**：旧版本读到新事件类型不崩；
- **不留永久转圈**：日志来自一个已不存在的进程，所以 ``fromLines()`` 默认把
  还在 streaming 的分段结算掉（未完成工具落 ``Aborted``，出错回合落 ``Error``）；
- 与实时流式**逐字段一致**（见 ``TestJournalMatchesLive``）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from pyqt6_ela_pro.chat import ElaChatWidget
from pyqt6_ela_pro.chat.journal import JOURNAL_VERSION, ElaChatTurnJournal
from pyqt6_ela_pro.chat.message import (
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolStatusType,
)


def _chat(qapp) -> ElaChatWidget:
    chat = ElaChatWidget()
    chat.resize(700, 500)
    chat.show()
    qapp.processEvents()
    return chat


# ------------------------------------------------------------------ 崩溃恢复
class TestCrashRecovery:
    def test_content_received_before_crash_survives(self, qapp):
        """崩在中途：已收到的正文与思考一个都不能丢。"""
        journal = ElaChatTurnJournal(messageId=5).begin(5)
        journal.reasoning("先看一下")
        journal.text("答")
        journal.text("案")
        # 崩了：没有 end()

        message = ElaChatTurnJournal.fromLines([journal.dumps()]).message()
        assert message.text == "答案"
        assert message.reasoning == "先看一下"

    def test_no_permanent_spinner_after_crash(self, qapp):
        """恢复出来的分段不能还带 streaming（界面会留永久闪烁的光标）。"""
        journal = ElaChatTurnJournal(messageId=5).begin(5)
        journal.reasoning("想").text("答")
        message = ElaChatTurnJournal.fromLines([journal.dumps()]).message()
        assert message.status != ElaChatStatusType.Streaming
        assert all(part.status != ElaChatStatusType.Streaming for part in message.parts), (
            f"残留 streaming: {[(p.kind, p.status) for p in message.parts]}"
        )

    def test_unfinished_tool_becomes_aborted(self, qapp):
        """未拿到结果的工具落 ``Aborted``（被停止 ≠ 失败）。"""
        journal = ElaChatTurnJournal(messageId=3).begin(3)
        journal.toolStart("c1", "read", "{}")
        journal.toolStart("c2", "bash", "ls")
        journal.toolEnd("c2", "输出", ok=True)
        journal.text("部分答案")

        message = ElaChatTurnJournal.fromLines([journal.dumps()]).message()
        byName = {call.name: call.status for call in message.tool_calls}
        assert byName["read"] == ElaChatToolStatusType.Aborted
        assert byName["bash"] == ElaChatToolStatusType.Done
        assert message.text == "部分答案"

    def test_error_crash_marks_tools_error(self, qapp):
        journal = ElaChatTurnJournal(messageId=3).begin(3)
        journal.toolStart("c1", "read")
        journal.text("半截")
        journal.end("error", error="断了")

        message = ElaChatTurnJournal.fromLines([journal.dumps()]).message()
        assert message.error == "断了"
        assert message.tool_calls[0].status == ElaChatToolStatusType.Error

    def test_settle_open_can_be_disabled(self, qapp):
        """忠实重放（不结算）供需要保留 streaming 语义的场景使用。"""
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.text("流式中")
        faithful = ElaChatTurnJournal.fromEvents(journal.events())
        assert faithful.message().parts[0].status == ElaChatStatusType.Streaming
        settled = ElaChatTurnJournal.fromLines([journal.dumps()])
        assert settled.message().parts[0].status == ElaChatStatusType.Done

    def test_mid_turn_message_is_usable_directly(self, qapp):
        """正在记录的 journal 自己就能给出「已收到的部分」（无需序列化往返）。"""
        journal = ElaChatTurnJournal(messageId=8).begin(8)
        journal.text("已经写完的部分")
        journal.text("，还在写")
        message = journal.message()
        assert message.id == 8
        assert message.text == "已经写完的部分，还在写"
        assert message.status == ElaChatStatusType.Streaming

    def test_multi_line_blob_accepted(self, qapp):
        """``fh.read()`` 的整段文本（含换行）也能直接喂进去。"""
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.text("整段内容")
        blob = journal.dumps() + "\n"
        assert "\n" in blob
        assert ElaChatTurnJournal.fromLines([blob]).message().text == "整段内容"

    def test_dumps_is_one_line_per_event(self, qapp):
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.reasoning("a").text("b").end("done")
        lines = journal.dumps().split("\n")
        assert len(lines) == len(journal.events())
        assert all(ElaChatTurnJournal.loadsLine(line) is not None for line in lines)
        assert str(JOURNAL_VERSION) in lines[0]

    def test_dumps_is_strict_json(self, qapp):
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.text("中文 & <标记>")
        for line in journal.dumps().split("\n"):
            assert json.loads(line)["v"] == JOURNAL_VERSION


# ------------------------------------------------------------------ 容错
class TestTolerance:
    @pytest.mark.parametrize(
        "junk",
        ["", "   ", "{", "null", "[]", "123", "not json", '{"e": }', '"\xe4\xb8'],
    )
    def test_loads_line_returns_none_for_junk(self, junk):
        assert ElaChatTurnJournal.loadsLine(junk) is None

    def test_loads_line_rejects_non_str(self):
        assert ElaChatTurnJournal.loadsLine(None) is None
        assert ElaChatTurnJournal.loadsLine(123) is None

    def test_truncated_line_recovers_the_rest(self, qapp):
        """最后一行被截断（写到一半被杀）不影响前面已写完的内容。"""
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.text("完整内容")
        blob = journal.dumps()
        truncated = blob[: len(blob) // 2]
        assert ElaChatTurnJournal.loadsLine(truncated) is None
        assert ElaChatTurnJournal.fromLines([blob]).message().text == "完整内容"

    def test_unknown_event_type_skipped(self, qapp):
        """旧版本读到新事件类型不崩。"""
        journal = ElaChatTurnJournal(messageId=2).begin(2)
        journal.text("老版本内容")
        lines = ['{"v":99,"e":"未来事件","x":1}'] + journal.dumps().split("\n")
        assert ElaChatTurnJournal.fromLines(lines).message().text == "老版本内容"

    def test_bad_field_types_do_not_break_replay(self, qapp):
        lines = [
            '{"v":1,"e":"b","id":"不是数字","role":"外星角色"}',
            '{"v":1,"e":"t","id":"j1","text":12345}',
            '{"v":1,"e":"st","data":"不是字典"}',
            '{"v":1,"e":"ts","id":null,"name":null}',
            '{"v":1,"e":"e","status":123}',
            "完全不是 JSON",
            "[]",
        ]
        message = ElaChatTurnJournal.fromLines(lines).message()
        assert message.id == 0
        assert message.role == ElaChatRoleType.Assistant
        assert message.status in ElaChatStatusType.All

    def test_empty_log_gives_empty_message(self, qapp):
        message = ElaChatTurnJournal.fromLines([]).message()
        assert message.parts == ()
        assert message.text == ""

    def test_nan_duration_neutralised(self, qapp):
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.reasoning("x")
        journal.endReasoning(float("nan"))
        journal.end("done")
        # NaN 不能进 JSON（否则整份日志写不出来）
        assert "NaN" not in journal.dumps()
        assert (
            ElaChatTurnJournal.fromLines([journal.dumps()]).message().reasoning_ms
            == 0.0
        )


# ------------------------------------------------------------------ 步骤
class TestSteps:
    def test_step_boundaries_recorded(self, qapp):
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.text("第一步")
        journal.beginStep()
        journal.reasoning("第二步思考")
        journal.endReasoning(300.0)
        journal.text("第二步答案")
        journal.end("done")

        message = ElaChatTurnJournal.fromLines([journal.dumps()]).message()
        assert [part.step for part in message.parts] == [1, 2, 2]
        assert message.stepCount == 2
        assert message.text == "第一步第二步答案"
        assert message.reasoning == "第二步思考"

    def test_repeated_begin_step_advances(self, qapp):
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        for index in range(3):
            journal.beginStep()
            journal.text(f"段{index}")
        message = journal.message()
        assert [part.step for part in message.parts] == [2, 3, 4]


# ------------------------------------------------------------------ 与实时一致
class TestJournalMatchesLive:
    def test_replay_equals_live_streaming_message(self, qapp):
        """同一轮分别喂给组件与 journal，重放结果必须与实时消息**逐字段一致**。"""
        chat = _chat(qapp)
        messageId = chat.beginAssistantMessage()
        journal = ElaChatTurnJournal(messageId=messageId).begin(messageId)

        chat.chatView().appendReasoning(messageId, "分析")
        journal.reasoning("分析")
        chat.chatView().endReasoning(messageId, 700.0)
        journal.endReasoning(700.0)
        chat.chatView().appendText(messageId, "**答案**")
        journal.text("**答案**")

        callId = chat.chatView().addToolCall(messageId, "read", "{}")
        journal.toolStart(callId, "read", "{}")
        chat.chatView().setToolCallResult(messageId, callId, "内容", ok=True)
        journal.toolEnd(callId, "内容", ok=True)

        failId = chat.chatView().addToolCall(messageId, "bash", "ls")
        journal.toolStart(failId, "bash", "ls")
        chat.chatView().setToolCallResult(messageId, failId, "boom", ok=False)
        journal.toolEnd(failId, "boom", ok=False)

        stats = ElaChatStats(prompt_tokens=5, total_tokens=20)
        chat.chatView().setStepStats(messageId, stats)
        journal.stats(stats)
        chat.chatView().setMessageDuration(messageId, 1500.0)
        journal.setDuration(1500.0)
        chat.endAssistantMessage(messageId)
        journal.end("done")
        qapp.processEvents()

        live = chat.chatView().message(messageId)
        recorded = ElaChatTurnJournal.fromLines([journal.dumps()]).message()

        def shape(message):
            return [
                (p.kind, p.status, p.text, p.duration_ms, p.step) for p in message.parts
            ]

        assert shape(recorded) == shape(live)
        assert recorded.text == live.text
        assert recorded.reasoning == live.reasoning
        assert recorded.reasoning_ms == live.reasoning_ms
        assert recorded.duration_ms == live.duration_ms
        assert recorded.stats == live.stats
        assert [(c.name, c.status, c.result) for c in recorded.tool_calls] == [
            (c.name, c.status, c.result) for c in live.tool_calls
        ]
        chat.deleteLater()
        qapp.processEvents()

    def test_part_ids_stable_across_replay(self, qapp):
        """分段 id 在事件里，重放后保持稳定（可与 UI 状态对齐）。"""
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.reasoning("r").text("t")
        first = [p.id for p in journal.message().parts]
        second = [
            p.id
            for p in ElaChatTurnJournal.fromLines([journal.dumps()]).message().parts
        ]
        assert first == second == ["j1", "j2"]


# ------------------------------------------------------------------ 接入
class TestReplayIntoView:
    def test_recovered_message_renders(self, qapp):
        journal = ElaChatTurnJournal(messageId=9).begin(9)
        journal.setTitle("模型X").setTimestamp("09:30").setCreatedAt(1700000000.0)
        journal.reasoning("想一想").endReasoning(500.0)
        journal.text("恢复出来的答案")
        journal.toolStart("c1", "grep", "{}").toolEnd("c1", "匹配 3 处", ok=True)
        journal.stats(ElaChatStats(total_tokens=99))
        journal.setDuration(2000.0)
        journal.end("done")

        chat = _chat(qapp)
        messageId = journal.replayInto(chat.chatView())
        qapp.processEvents()
        message = chat.chatView().message(messageId)

        assert messageId == 9
        assert message.text == "恢复出来的答案"
        assert message.reasoning == "想一想"
        assert message.reasoning_ms == 500.0
        assert message.title == "模型X"
        assert message.timestamp == "09:30"
        assert message.created_at == 1700000000.0
        assert message.duration_ms == 2000.0
        assert message.stats.total_tokens == 99
        assert [(c.name, c.status) for c in message.tool_calls] == [
            ("grep", ElaChatToolStatusType.Done)
        ]
        # 界面上的气泡也必须有内容（不只是数据层）
        bubble = chat.chatView().bubble(messageId)
        assert bubble.text() == "恢复出来的答案"
        assert bubble.reasoning() == "想一想"
        chat.deleteLater()
        qapp.processEvents()

    def test_crashed_turn_renders_without_spinner(self, qapp):
        """崩溃的回合恢复进界面后不能有 streaming 残留。"""
        journal = ElaChatTurnJournal(messageId=4).begin(4)
        journal.reasoning("想到一半").text("答到一半")

        chat = _chat(qapp)
        messageId = ElaChatTurnJournal.fromLines([journal.dumps()]).replayInto(
            chat.chatView()
        )
        qapp.processEvents()
        bubble = chat.chatView().bubble(messageId)
        assert bubble.text() == "答到一半"
        assert all(part.status != ElaChatStatusType.Streaming for part in bubble.parts())
        assert bubble.hasPendingText() is False
        chat.deleteLater()
        qapp.processEvents()

    def test_recovered_message_is_storable(self, qapp):
        """重放结果能直接当正常消息落库（读取端无需知道日志存在）。"""
        journal = ElaChatTurnJournal(messageId=6).begin(6)
        journal.text("日志内容")
        row = ElaChatTurnJournal.fromLines([journal.dumps()]).message().toDict()
        # 严格 JSON（可写成文件），且能原样读回
        assert json.loads(json.dumps(row, ensure_ascii=False, allow_nan=False)) == row

        chat = _chat(qapp)
        messageId = chat.chatView().addMessageFromDict(row)
        qapp.processEvents()
        assert chat.chatView().message(messageId).text == "日志内容"
        chat.deleteLater()
        qapp.processEvents()


class TestWorkerWiring:
    class _Worker:
        """最小 worker 桩（信号契约与 ElaChatAsyncWorker 同构）。"""

        def __init__(self):

            class Emitter(QObject):
                chunkReceived = pyqtSignal(object)
                toolStarted = pyqtSignal(dict)
                toolEnded = pyqtSignal(dict, str)
                statsReady = pyqtSignal(object, float, float)

            self._emitter = Emitter()

        def __getattr__(self, name):
            return getattr(self._emitter, name)

    def test_chunk_dispatch(self, qapp):
        worker = self._Worker()
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.connectWorker(worker)

        worker.chunkReceived.emit(
            SimpleNamespace(reasoning_content="想", answer_content="")
        )
        worker.chunkReceived.emit(
            SimpleNamespace(reasoning_content="", answer_content="答")
        )
        journal.end("done")

        message = journal.message()
        assert message.reasoning == "想"
        assert message.text == "答"
        assert message.reasoning_ms == 0.0

    def test_reasoning_settles_when_answer_starts(self, qapp):
        """正文一开始，思考段就真的结束了（与 binder 同一语义）。"""
        worker = self._Worker()
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.connectWorker(worker)
        worker.chunkReceived.emit(
            SimpleNamespace(reasoning_content="思考中", answer_content="")
        )
        assert journal.message().parts[0].status == ElaChatStatusType.Streaming
        worker.chunkReceived.emit(
            SimpleNamespace(reasoning_content="", answer_content="答案")
        )
        assert journal.message().parts[0].status == ElaChatStatusType.Done
        journal.end("done")

    def test_tool_dispatch(self, qapp):
        worker = self._Worker()
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.connectWorker(worker)
        worker.toolStarted.emit(
            {"id": "t1", "function": {"name": "read", "arguments": "{}"}}
        )
        worker.toolEnded.emit({"id": "t1"}, "文件内容")
        worker.toolStarted.emit({"id": "t2", "function": {"name": "bash"}})
        worker.toolEnded.emit({"id": "t2"}, "Error: 炸了")
        journal.end("done")

        calls = {c.name: (c.status, c.result) for c in journal.message().tool_calls}
        assert calls["read"] == (ElaChatToolStatusType.Done, "文件内容")
        # 'Error:' 前缀自动判失败（与 binder 同）
        assert calls["bash"] == (ElaChatToolStatusType.Error, "Error: 炸了")

    def test_junk_payloads_ignored(self, qapp):
        worker = self._Worker()
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.connectWorker(worker)
        # chunkReceived 是 object 信号，喂什么都进得来
        worker.chunkReceived.emit("不是对象")
        worker.chunkReceived.emit(None)
        worker.chunkReceived.emit(SimpleNamespace())
        # toolStarted / toolEnded 的信号签名是 dict，传非 dict 会被 Qt 拒掉，
        # 所以这里直接调槽函数验证「拿到非 dict 时忽略」
        journal._on_tool_started("不是 dict")
        journal._on_tool_started(None)
        journal._on_tool_ended(None, None)
        journal._on_tool_ended("不是 dict", "x")
        worker.statsReady.emit(None, 0.0, 0.0)
        journal.end("done")
        assert journal.message().parts == ()

    def test_stats_from_openai_usage(self, qapp):
        worker = self._Worker()
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.connectWorker(worker)
        usage = SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            prompt_cache_hit_tokens=3,
        )
        worker.statsReady.emit(usage, 120.0, 30.0)
        journal.end("done")
        stats = journal.message().stats
        assert stats.prompt_tokens == 11
        assert stats.completion_tokens == 7
        assert stats.total_tokens == 18
        assert stats.cache_read_tokens == 3
        assert stats.ttft_ms == 120.0
        assert stats.tps == 30.0

    def test_stats_from_elastats(self, qapp):
        worker = self._Worker()
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.connectWorker(worker)
        worker.statsReady.emit(ElaChatStats(prompt_tokens=5), 0.0, 0.0)
        journal.end("done")
        assert journal.message().stats.prompt_tokens == 5

    def test_disconnect_is_idempotent(self, qapp):
        worker = self._Worker()
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.connectWorker(worker)
        journal.disconnectWorker(worker)
        journal.disconnectWorker(worker)  # 再来一次不得抛
        worker.chunkReceived.emit(
            SimpleNamespace(reasoning_content="", answer_content="不该进来")
        )
        assert journal.message().text == ""


class TestPartKind:
    def test_only_known_kinds_produced(self, qapp):
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.reasoning("r").text("t")
        journal.toolStart("c", "n").toolEnd("c", "r")
        journal.stats(ElaChatStats())
        journal.end("done")
        kinds = {part.kind for part in journal.message().parts}
        assert kinds <= set(ElaChatPartKindType.All)
        assert ElaChatPartKindType.Reasoning in kinds
        assert ElaChatPartKindType.Text in kinds
        assert ElaChatPartKindType.Tool in kinds
        assert ElaChatPartKindType.Stats in kinds
