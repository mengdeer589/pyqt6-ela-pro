"""ElaChatAsyncWorker 测试：回合顺序、串行、取消、回滚与关闭（假子类）。"""

from __future__ import annotations

import asyncio
import threading

from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import ElaChatAsyncWorker
from pyqt6_ela_pro.chat import worker as worker_module


class _FakeWorker(ElaChatAsyncWorker):
    """脚本化假后端：llm / chunk / sleep / tool 事件 + 钩子计数。"""

    def __init__(self, script=None, parent=None) -> None:
        super().__init__(parent)
        self.script = script or [("llm",), ("chunk", "a"), ("chunk", "b")]
        self.setup_count = 0
        self.rollback_args = []
        self.stream_args = []
        self.after_count = 0
        self.reset_count = 0
        self.active = 0
        self.max_active = 0

    async def _setup(self) -> None:
        self.setup_count += 1
        self.ready.emit()

    def _stream_turn(self, prompt, attachments):
        self.stream_args.append((prompt, list(attachments)))

        async def gen():
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                for item in self.script:
                    if item[0] == "llm":
                        self.llmStarted.emit()
                    elif item[0] == "tool_start":
                        self.toolStarted.emit(item[1])
                    elif item[0] == "tool_end":
                        self.toolEnded.emit(item[1], item[2])
                    elif item[0] == "sleep":
                        await asyncio.sleep(item[1])
                    else:
                        yield item[1]
                    await asyncio.sleep(0)
            finally:
                self.active -= 1

        return gen()

    async def _rollback_turn(self, prompt: str, attachments: list) -> None:
        self.rollback_args.append((prompt, list(attachments)))

    async def _after_turn(self) -> None:
        self.after_count += 1

    async def _reset_backend(self) -> None:
        self.reset_count += 1


def _started(qapp, worker):
    worker.start()
    # _queue 就绪才代表 _setup 完成、可以提交命令
    assert _wait_until(qapp, lambda: worker._queue is not None)
    return worker


def _dispose(qapp, worker):
    worker.shutdown()
    worker.deleteLater()
    qapp.processEvents()


class TestLifecycle:
    def test_turn_signal_order(self, qapp):
        worker = _FakeWorker()
        events = []
        worker.ready.connect(lambda: events.append("ready"))
        worker.llmStarted.connect(lambda: events.append("llm"))
        worker.chunkReceived.connect(lambda chunk: events.append(f"chunk:{chunk}"))
        worker.turnFinished.connect(
            lambda turn: events.append(f"finished:{turn}")
        )
        _started(qapp, worker)

        turn = worker.ask("你好")
        assert turn is not None
        assert _wait_until(qapp, lambda: any(e.startswith("finished") for e in events))
        assert events == [
            "ready",
            "llm",
            "chunk:a",
            "chunk:b",
            f"finished:{turn}",
        ]
        assert worker.after_count == 1
        _dispose(qapp, worker)

    def test_asks_are_serialized(self, qapp):
        worker = _FakeWorker(script=[("chunk", "x"), ("sleep", 0.05)])
        _started(qapp, worker)
        finished = []
        worker.turnFinished.connect(finished.append)
        first = worker.ask("一")
        second = worker.ask("二")
        assert first is not None and second is not None
        assert _wait_until(qapp, lambda: len(finished) == 2)
        assert finished == [first, second], "收尾必须按受理顺序、带回各自 token"
        assert worker.max_active == 1
        _dispose(qapp, worker)

    def test_tools_and_stats_pass_through(self, qapp):
        worker = _FakeWorker(
            script=[
                ("llm",),
                ("tool_start", {"id": "t1", "function": {"name": "read"}}),
                ("tool_end", {"id": "t1"}, "内容"),
            ]
        )
        events = []
        worker.toolStarted.connect(lambda tc: events.append(("start", tc["id"])))
        worker.toolEnded.connect(lambda tc, r: events.append(("end", tc["id"], r)))
        _started(qapp, worker)
        assert worker.ask("读文件") is not None
        assert _wait_until(qapp, lambda: len(events) == 2)
        assert events == [("start", "t1"), ("end", "t1", "内容")]
        _dispose(qapp, worker)


class TestCancel:
    def test_cancel_stops_stream_and_finishes_once(self, qapp):
        worker = _FakeWorker(script=[("chunk", "a"), ("sleep", 5.0), ("chunk", "b")])
        chunks = []
        finished = []
        worker.chunkReceived.connect(chunks.append)
        worker.turnFinished.connect(finished.append)
        _started(qapp, worker)

        turn = worker.ask("长回答")
        assert turn is not None
        assert _wait_until(qapp, lambda: chunks == ["a"])
        worker.cancel()
        assert _wait_until(qapp, lambda: bool(finished))
        assert chunks == ["a"]
        assert finished == [turn]
        qapp.processEvents()
        assert len(finished) == 1
        # 取消后还能继续下一轮
        worker.script = [("chunk", "next")]
        assert worker.ask("再来") is not None
        assert _wait_until(qapp, lambda: chunks[-1] == "next")
        _dispose(qapp, worker)


class TestCommands:
    def test_regenerate_rolls_back_first(self, qapp):
        worker = _FakeWorker(script=[("chunk", "x")])
        _started(qapp, worker)
        assert worker.regenerate("原问题") is not None
        assert _wait_until(qapp, lambda: worker.rollback_args == [("原问题", [])])
        assert _wait_until(qapp, lambda: worker.after_count == 1)
        _dispose(qapp, worker)

    def test_attachments_reach_stream_turn(self, qapp):
        """附件通道：ask / regenerate 的 attachments 都要到 ``_stream_turn``。"""
        worker = _FakeWorker(script=[("chunk", "x")])
        _started(qapp, worker)
        attachment = {"name": "a.png", "path": "C:/a.png"}

        assert worker.ask("看图", attachments=[attachment]) is not None
        assert _wait_until(qapp, lambda: worker.stream_args == [("看图", [attachment])])

        worker.script = [("chunk", "y")]
        assert worker.regenerate("看图", attachments=[attachment]) is not None
        assert _wait_until(
            qapp,
            lambda: worker.stream_args[-1:] == [("看图", [attachment])]
            and worker.rollback_args[-1:] == [("看图", [attachment])],
        )
        _dispose(qapp, worker)

    def test_reset_calls_backend(self, qapp):
        worker = _FakeWorker()
        _started(qapp, worker)
        worker.reset()
        assert _wait_until(qapp, lambda: worker.reset_count == 1)
        _dispose(qapp, worker)

    def test_ask_before_ready_returns_false(self, qapp):
        worker = _FakeWorker()
        assert worker.ask("你好") is None
        worker.deleteLater()
        qapp.processEvents()

    def test_setup_failure_emits_failed(self, qapp):
        class _BadWorker(_FakeWorker):
            async def _setup(self):
                raise RuntimeError("backend down")

        worker = _BadWorker()
        errors = []
        worker.failed.connect(errors.append)
        worker.start()
        assert _wait_until(qapp, lambda: bool(errors))
        assert "backend down" in errors[0]
        assert worker.ask("你好") is None
        _dispose(qapp, worker)

    def test_sync_stream_error_keeps_worker_alive(self, qapp):
        """_stream_turn 同步抛异常：收尾本回合且线程循环存活。"""

        class _SyncBadWorker(_FakeWorker):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.calls = 0

            def _stream_turn(self, prompt, attachments):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("sync boom")
                return super()._stream_turn(prompt, attachments)

        worker = _SyncBadWorker()
        errors = []
        finished = []
        worker.errorOccurred.connect(lambda kind, msg: errors.append((kind, msg)))
        worker.turnFinished.connect(finished.append)
        _started(qapp, worker)

        assert worker.ask("你好") is not None
        assert _wait_until(qapp, lambda: bool(finished))
        assert errors and "sync boom" in errors[0][1]
        assert worker.isRunning() is True

        chunks = []
        worker.chunkReceived.connect(chunks.append)
        worker.script = [("chunk", "next")]
        assert worker.ask("再来") is not None
        assert _wait_until(qapp, lambda: chunks == ["next"])
        _dispose(qapp, worker)


class TestShutdown:
    """``shutdown()`` 是**非阻塞**的：只发请求，线程在后台自己退。

    超时升级（``terminate`` → 保活）由看门狗轮询完成，不再阻塞调用线程 —— 旧实现
    在这里 ``wait(4000)``，后端初始化卡死时实测关窗冻结 4016 ms。
    """

    def test_shutdown_stops_thread_without_blocking(self, qapp):
        worker = _FakeWorker(script=[("sleep", 5.0), ("chunk", "late")])
        _started(qapp, worker)
        assert worker.ask("长任务") is not None
        assert _wait_until(qapp, lambda: worker.active == 1)

        worker.shutdown()
        assert worker.isShuttingDown() is True
        assert _wait_until(qapp, lambda: worker.isRunning() is False)

        worker.deleteLater()
        qapp.processEvents()

    def test_wait_for_shutdown_blocks_and_confirms_exit(self, qapp):
        """需要「确保线程已停」时走 ``waitForShutdown``。"""
        worker = _FakeWorker(script=[("sleep", 5.0), ("chunk", "late")])
        _started(qapp, worker)
        assert worker.ask("长任务") is not None
        assert _wait_until(qapp, lambda: worker.active == 1)
        worker.shutdown()
        assert worker.waitForShutdown() is True
        assert worker.isRunning() is False
        worker.deleteLater()
        qapp.processEvents()

    def test_shutdown_is_non_blocking_with_a_fake_loop(self, qapp, monkeypatch):
        """事件循环不可用时也不得抛（哨兵投不出去而已）。"""
        worker = _FakeWorker()
        worker._queue = object()
        worker._loop = object()  # 没有 run_coroutine_threadsafe 语义
        worker.shutdown()  # 不得抛
        assert worker.isShuttingDown() is True
        worker._stop_watchdog()
        worker.deleteLater()
        qapp.processEvents()

    def test_watchdog_terminates_a_stuck_thread(self, qapp, monkeypatch):
        """看门狗到点升级成 terminate，再不退出就保活（避免运行中被销毁）。"""
        worker = _FakeWorker()
        calls = []
        monkeypatch.setattr(worker, "isFinished", lambda: False)
        monkeypatch.setattr(worker, "isRunning", lambda: True)
        monkeypatch.setattr(worker, "terminate", lambda: calls.append(True))

        worker.shutdown()
        worker._watchdog_deadline = 0.0  # 预算已过
        worker._on_watchdog()  # 第一轮：升级 terminate
        assert calls == [True]

        worker._on_watchdog()  # 第二轮：terminate 过了还没退 -> 保活
        assert worker in worker_module._LINGERING_WORKERS
        worker_module._LINGERING_WORKERS.remove(worker)
        worker._stop_watchdog()
        worker.deleteLater()
        qapp.processEvents()

    def test_watchdog_stops_once_the_thread_is_finished(self, qapp):
        worker = _FakeWorker()
        _started(qapp, worker)
        worker.shutdown()
        assert _wait_until(qapp, lambda: worker.isFinished() is True)
        # 线程退出后由下一个看门狗 tick 停掉自己
        assert _wait_until(qapp, lambda: worker._watchdog.isActive() is False)
        worker.deleteLater()
        qapp.processEvents()


class TestTurnCancellationEdges:
    def test_cancel_during_rollback_skips_the_turn(self, qapp):
        """regenerate 回滚期间按下的停止必须生效：整轮不再发起后端请求。"""

        class _SlowRollback(_FakeWorker):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.rollback_started = threading.Event()

            async def _rollback_turn(self, prompt: str, attachments: list) -> None:
                self.rollback_started.set()
                await asyncio.sleep(0.4)

        worker = _SlowRollback(script=[("chunk", "x")])
        chunks = []
        finished = []
        worker.chunkReceived.connect(chunks.append)
        worker.turnFinished.connect(finished.append)
        _started(qapp, worker)

        assert worker.regenerate("原问题") is not None
        assert worker.rollback_started.wait(1.0)
        worker.cancel()

        assert _wait_until(qapp, lambda: bool(finished))
        assert chunks == [], "回滚期间的取消让这一轮根本没跑"
        assert worker.active == 0
        _dispose(qapp, worker)


class TestRunFailureClassification:
    def test_post_ready_crash_emits_error_not_failed(self, qapp):
        """ready 之后的线程异常发 ``errorOccurred``（不是初始化失败的 ``failed``）。"""

        class _Boom(_FakeWorker):
            async def _serve(self):
                await self._setup()
                self._queue = asyncio.Queue()
                raise RuntimeError("boom after ready")

        worker = _Boom()
        failed, errors = [], []
        worker.failed.connect(failed.append)
        worker.errorOccurred.connect(lambda kind, msg: errors.append((kind, msg)))
        worker.start()

        assert _wait_until(qapp, lambda: bool(errors))
        assert failed == []
        assert errors[0][0] == "worker"
        assert "boom after ready" in errors[0][1]
        assert _wait_until(qapp, lambda: worker.isFinished() is True)
        worker.deleteLater()
        qapp.processEvents()


class TestLingeringPruning:
    def test_running_worker_is_kept_and_finished_one_is_pruned(self, qapp):
        worker = _FakeWorker()
        _started(qapp, worker)
        worker_module._remember_lingering(worker)
        assert worker in worker_module._LINGERING_WORKERS

        worker.shutdown()
        assert _wait_until(qapp, lambda: worker.isFinished() is True)
        worker_module._remember_lingering(worker)
        assert worker not in worker_module._LINGERING_WORKERS, "退出后不再保活"
        worker.deleteLater()
        qapp.processEvents()

    def test_finished_worker_is_not_kept(self, qapp):
        worker = _FakeWorker()
        _started(qapp, worker)
        worker.shutdown()
        assert _wait_until(qapp, lambda: worker.isFinished() is True)
        worker_module._remember_lingering(worker)
        assert worker not in worker_module._LINGERING_WORKERS
        worker.deleteLater()
        qapp.processEvents()


class TestWatchdogRearm:
    def test_rearm_resets_terminate_flag(self, qapp):
        """第二次 shutdown 重新武装时，terminate 升级必须仍然可用。"""
        worker = _FakeWorker()
        worker._terminated = True
        worker._arm_watchdog()
        assert worker._terminated is False
        worker._stop_watchdog()
        worker.deleteLater()
        qapp.processEvents()
