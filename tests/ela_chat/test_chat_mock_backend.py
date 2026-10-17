"""ElaChatMockBackend 模拟后端测试：事件契约、思考档位、取消与回复提供者。"""

from __future__ import annotations

from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import ElaChatMockBackend, ElaChatMockUsage


def _drain(qapp, worker, timeout_ms: int = 3000) -> bool:
    """跑事件循环直到回合结束（统一走 ``_qthelpers.wait_until``）。"""
    return _wait_until(qapp, lambda: not worker.isRunning(), timeout_ms=timeout_ms)


def _record(worker) -> list:
    events: list = []
    worker.llmStarted.connect(lambda: events.append(("llm",)))
    worker.chunkReceived.connect(
        lambda chunk: events.append(
            (
                "reasoning" if getattr(chunk, "reasoning_content", "") else "answer",
                getattr(chunk, "reasoning_content", "")
                or getattr(chunk, "answer_content", ""),
            )
        )
    )
    worker.toolStarted.connect(
        lambda toolCall: events.append(
            ("tool_start", toolCall["id"], toolCall["function"]["name"])
        )
    )
    worker.toolEnded.connect(
        lambda toolCall, result: events.append(("tool_end", toolCall["id"], result))
    )
    worker.statsReady.connect(
        lambda usage, ttft, tps: events.append(("stats", usage, ttft, tps))
    )
    worker.turnFinished.connect(lambda turn: events.append(("finished", turn)))
    return events


class TestEventContract:
    def test_full_turn_two_rounds(self, qapp):
        worker = ElaChatMockBackend(tickMs=0)
        events = _record(worker)
        turn = worker.ask("你好")
        assert turn is not None
        assert _drain(qapp, worker)

        kinds = [event[0] for event in events]
        assert kinds[0] == "llm"
        assert kinds.count("llm") == 2
        assert kinds.count("stats") == 2
        assert kinds.count("finished") == 1
        assert kinds[-1] == "finished"
        # 收尾信号带回的就是发起时那个回合 token
        assert [e[1] for e in events if e[0] == "finished"] == [turn]

        tool_starts = [e for e in events if e[0] == "tool_start"]
        tool_ends = [e for e in events if e[0] == "tool_end"]
        assert [e[1] for e in tool_starts] == ["mock-read", "mock-grep", "mock-patch"]
        assert [e[1] for e in tool_ends] == ["mock-read", "mock-grep", "mock-patch"]

        usage, ttft, tps = next(e[1:] for e in events if e[0] == "stats")
        assert isinstance(usage, ElaChatMockUsage)
        assert usage.prompt_tokens == 128
        assert usage.completion_tokens == 96
        assert usage.total_tokens == 128 + 96
        assert usage.prompt_cache_hit_tokens == 64
        assert ttft == 320.0
        assert tps == 42.0

        answer = "".join(e[1] for e in events if e[0] == "answer")
        assert "模拟回答" in answer
        assert worker.isRunning() is False
        worker.deleteLater()
        qapp.processEvents()

    def test_ready_emitted(self, qapp):
        worker = ElaChatMockBackend(tickMs=0)
        ready = []
        worker.ready.connect(lambda: ready.append(True))
        qapp.processEvents()
        assert ready == [True]
        worker.deleteLater()
        qapp.processEvents()

    def test_turn_attachments_are_kept_for_contract_parity(self, qapp):
        """模拟后端收下附件并留存（与真实 worker 契约同构，宿主接线不用分叉）。"""
        worker = ElaChatMockBackend(tickMs=0)
        attachment = {"name": "a.png", "path": "C:/a.png"}
        assert worker.ask("看图", attachments=[attachment]) is not None
        assert worker.turnAttachments() == [attachment]
        # 返回的是副本：改它不能污染内部状态
        worker.turnAttachments().append({"name": "注入"})
        assert worker.turnAttachments() == [attachment]

        assert worker.regenerate("再看", attachments=[attachment]) is not None
        assert worker.turnAttachments() == [attachment]

        worker.reset()
        assert worker.turnAttachments() == []
        worker.deleteLater()
        qapp.processEvents()

    def test_reasoning_before_answer_and_single_round_reasoning_block(self, qapp):
        worker = ElaChatMockBackend(tickMs=0)
        events = _record(worker)
        worker.ask("你好")
        _drain(qapp, worker)
        kinds = [event[0] for event in events]
        assert kinds.index("reasoning") < kinds.index("answer")
        # normal 档位只有第一轮有推理
        assert kinds.count("reasoning") > 1
        worker.deleteLater()
        qapp.processEvents()


class TestThinkLevel:
    def test_off_has_no_reasoning(self, qapp):
        worker = ElaChatMockBackend(tickMs=0, thinkLevel="off")
        events = _record(worker)
        worker.ask("你好")
        _drain(qapp, worker)
        assert not [e for e in events if e[0] == "reasoning"]
        worker.deleteLater()
        qapp.processEvents()

    def test_deep_has_second_round_reasoning(self, qapp):
        worker = ElaChatMockBackend(tickMs=0, thinkLevel="normal")
        worker.setThinkLevel("deep")
        assert worker.thinkLevel() == "deep"
        events = _record(worker)
        worker.ask("你好")
        _drain(qapp, worker)

        rounds: list = []
        for event in events:
            if event[0] == "llm":
                rounds.append([])
            elif event[0] == "reasoning" and rounds:
                rounds[-1].append(event[1])
        assert len(rounds) == 2
        assert rounds[0] and rounds[1]

    def test_invalid_level_falls_back_to_normal(self, qapp):
        worker = ElaChatMockBackend(tickMs=0)
        worker.setThinkLevel("bogus")
        assert worker.thinkLevel() == "normal"
        worker.deleteLater()
        qapp.processEvents()


class TestCommands:
    def test_reply_provider_and_reset(self, qapp):
        worker = ElaChatMockBackend(tickMs=0)
        worker.setReplyProvider(lambda question: f"自定义：{question}")
        events = _record(worker)
        worker.ask("问题")
        _drain(qapp, worker)
        answer = "".join(e[1] for e in events if e[0] == "answer")
        assert answer == "自定义：问题"

        worker.setReplyProvider(None)
        events.clear()
        worker.ask("问题")
        _drain(qapp, worker)
        answer = "".join(e[1] for e in events if e[0] == "answer")
        assert answer != "自定义：问题"
        worker.deleteLater()
        qapp.processEvents()

    def test_regenerate_equivalent_to_ask(self, qapp):
        worker = ElaChatMockBackend(tickMs=0)
        events = _record(worker)
        turn = worker.regenerate("再来一次")
        assert turn is not None
        assert _drain(qapp, worker)
        assert events[-1] == ("finished", turn)
        worker.deleteLater()
        qapp.processEvents()

    def test_cancel_ends_turn_without_chunks(self, qapp):
        worker = ElaChatMockBackend(tickMs=60)
        events = _record(worker)
        turn = worker.ask("你好")
        assert turn is not None
        worker.cancel()
        assert worker.isRunning() is False
        assert events == [("finished", turn)]
        # 事件已清空，后续 tick 不再产生内容
        _drain(qapp, worker)
        assert events == [("finished", turn)]
        worker.deleteLater()
        qapp.processEvents()

    def test_ask_while_running_cancels_previous(self, qapp):
        worker = ElaChatMockBackend(tickMs=200)
        finished = []
        worker.turnFinished.connect(finished.append)
        worker.ask("第一问")
        worker.ask("第二问")
        assert finished == [True]
        worker.cancel()
        worker.deleteLater()
        qapp.processEvents()

    def test_tick_ms_controls_interval(self, qapp):
        worker = ElaChatMockBackend(tickMs=25)
        assert worker.tickMs() == 25
        worker.setTickMs(0)
        assert worker.tickMs() == 0
        worker.deleteLater()
        qapp.processEvents()

    def test_shutdown_stops_timer(self, qapp):
        worker = ElaChatMockBackend(tickMs=0)
        worker.ask("你好")
        worker.shutdown()
        assert worker.isRunning() is False
        worker.deleteLater()
        qapp.processEvents()
