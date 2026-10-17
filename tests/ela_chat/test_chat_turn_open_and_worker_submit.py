"""回合「是否开启」的判据与 worker 命令投递的失败路径。

两条曾经的缺陷：

1. :meth:`ElaChatStreamBinder.isOpen` 拿 ``_turn_start != 0.0`` 当判据 —— 那是**计时
   值**，而 ``clock`` 是可注入的。任何返回 ``0.0`` 的时钟（相对时钟的起点、测试用的
   假时钟）会让整回合被静默判成「未开启」：``reasoning`` / ``answer`` / ``toolStart``
   / ``stats`` / ``error`` 全部在第一行退出，**一个字都不落**，而 ``startTurn()``
   已经返回了回合 token。
2. :meth:`ElaChatAsyncWorker._submit` 的守卫只判 ``_loop is None``，而
   ``_cleanup_loop`` 是「先 ``close()`` 后置 ``None``」—— 中间那个「已 close 但仍非
   None」的可达状态会让 ``run_coroutine_threadsafe`` 抛 ``RuntimeError``，违背
   「未就绪时返回 ``None``」的契约（异常从 GUI 线程穿出去即 0xC0000409）。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from PyQt6.QtCore import QEventLoop, QTimer, Qt

from pyqt6_ela_pro.chat import ElaChatWidget
from pyqt6_ela_pro.chat.binder import ElaChatStreamBinder
from pyqt6_ela_pro.chat.worker import ElaChatAsyncWorker
from PyQt6 import sip


def _spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class _Worker(ElaChatAsyncWorker):
    async def _setup(self) -> None:
        self.ready.emit()

    def _stream_turn(self, prompt: str, attachments: list):
        async def gen():
            for i in range(3):
                yield {"answer_content": "x%d" % i}

        return gen()


class _HangingSetupWorker(ElaChatAsyncWorker):
    async def _setup(self) -> None:
        await asyncio.sleep(3600)

    def _stream_turn(self, prompt: str, attachments: list):  # pragma: no cover - 不会走到
        async def gen():
            yield {}

        return gen()


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15
    prompt_cache_hit_tokens = 0
    prompt_tokens_details = None


@pytest.fixture
def chat_widget(qapp, make):
    return make(ElaChatWidget)


@pytest.fixture
def _reap():
    """收尾所有本文件起的 worker。

    QThread 在运行中被析构就是 0xC0000409（无 traceback），所以每个用例结束前必须
    确保线程已停 —— 哪怕断言先失败了也一样。
    """
    started: list = []
    yield started
    for worker in started:
        try:
            if worker.isRunning():
                worker.shutdownWaitMs = min(
                    getattr(worker, "shutdownWaitMs", 4000), 500
                )
                worker.shutdown()
                worker.waitForShutdown(1500)
        except RuntimeError:
            pass


def _spawn(make, registry, cls=None, waitMs: int = 400):
    """起一个 worker 并登记到 ``registry``（供上面的 fixture 收尾）。"""
    worker = make(cls or _Worker)
    worker.shutdownWaitMs = waitMs
    registry.append(worker)
    worker.start()
    return worker


def _reap_worker(make, registry, worker):
    """登记并启动一个已由 ``make`` 造好的 worker。"""
    registry.append(worker)
    worker.start()
    return worker


class TestIsOpenDoesNotDependOnTheClock:
    """判据必须是显式标志，不是计时值。"""

    def test_zero_clock_still_records_everything(self, qapp, chat_widget):
        view = chat_widget.chatView()
        binder = ElaChatStreamBinder(chat_widget, clock=lambda: 0.0)
        messageId = chat_widget.beginAssistantMessage()
        turn = binder.beginTurn()

        assert binder.isOpen() is True, "返回 0.0 的时钟不得让回合变成「未开启」"

        binder.reasoning("思考")
        binder.answer("你好")
        binder.answer("世界")
        binder.toolStart("c1", "grep", "{}")
        binder.toolEnd("c1", "ok")
        binder.stats(_Usage())
        summary = binder.finish(turn)

        message = view.message(messageId)
        assert message.text == "你好世界"
        assert message.reasoning == "思考"
        assert len(message.tool_calls) == 1
        assert message.stats is not None and message.stats.prompt_tokens == 10
        assert summary.hadText is True

    def test_relative_clock_still_records(self, qapp, chat_widget):
        origin = time.monotonic()
        view = chat_widget.chatView()
        binder = ElaChatStreamBinder(
            chat_widget, clock=lambda: time.monotonic() - origin
        )
        messageId = chat_widget.beginAssistantMessage()
        turn = binder.beginTurn()
        binder.answer("相对时钟正文")
        binder.finish(turn)
        assert view.message(messageId).text == "相对时钟正文"

    def test_error_also_lands_with_a_zero_clock(self, qapp, chat_widget):
        view = chat_widget.chatView()
        binder = ElaChatStreamBinder(chat_widget, clock=lambda: 0.0)
        messageId = chat_widget.beginAssistantMessage()
        turn = binder.beginTurn()
        binder.error("RateLimit", "太频繁了")
        binder.finish(turn)
        # messageError 返回 (message, errorType)；errorType 原样保留（重试按钮靠它判断）
        assert view.messageError(messageId) == ("太频繁了", "RateLimit")

    def test_turn_closes_on_finish(self, qapp, chat_widget):
        binder = ElaChatStreamBinder(chat_widget)
        chat_widget.beginAssistantMessage()
        turn = binder.beginTurn()
        assert binder.isOpen() is True
        binder.finish(turn)
        assert binder.isOpen() is False

    def test_turn_without_a_target_is_not_open(self, qapp, chat_widget):
        binder = ElaChatStreamBinder(chat_widget)
        binder.beginTurn()  # 没有流式消息 -> 没有落点
        assert binder.isOpen() is False

    def test_finish_without_turn_is_safe(self, qapp, chat_widget):
        binder = ElaChatStreamBinder(chat_widget)
        assert binder.finish(binder.beginTurn()) is not None
        assert binder.isOpen() is False

    def test_finish_is_idempotent_on_duration(self, qapp, chat_widget):
        binder = ElaChatStreamBinder(chat_widget)
        chat_widget.beginAssistantMessage()
        turn = binder.beginTurn()
        first = binder.finish(turn)
        assert first.durationMs >= 0.0
        assert binder.finish(turn) is None, "同一 token 二次收尾属陈旧，必须丢弃"

    def test_abort_turn_returns_none_when_not_open(self, qapp, chat_widget):
        binder = ElaChatStreamBinder(chat_widget)
        assert binder.abortTurn() is None

    def test_abort_turn_closes_the_turn(self, qapp, chat_widget):
        binder = ElaChatStreamBinder(chat_widget)
        chat_widget.beginAssistantMessage()
        binder.beginTurn()
        summary = binder.abortTurn()
        assert summary is not None
        assert summary.status == "stopped"
        assert binder.isOpen() is False


class TestWorkerSubmitNeverRaises:
    """契约是「未就绪返回 ``None``」，不是抛异常。"""

    def test_ask_before_start_returns_none(self, qapp, make):
        worker = make(_Worker)
        assert worker.ask("hi") is None
        assert worker.regenerate("hi") is None

    def test_ask_after_shutdown_returns_none(self, qapp, make):
        worker = make(_Worker)
        worker.start()
        _spin(400)
        assert worker.ask("hi") is not None
        worker.shutdown()
        _spin(50)
        assert worker.ask("again") is None

    def test_closed_loop_returns_none_instead_of_raising(self, qapp, make):
        """回归：曾抛 ``RuntimeError: Event loop is closed``。"""
        worker = make(_Worker)
        closed = asyncio.new_event_loop()
        closed.close()
        worker._loop = closed  # 复刻 _cleanup_loop 的中间态
        worker._queue = asyncio.Queue()
        assert worker.ask("x") is None  # 不得抛
        assert worker.regenerate("x") is None

    def test_cleanup_clears_loop_before_closing(self, qapp, make):
        """``_loop`` 必须先置 ``None`` 再 ``close()``（顺序本身就是防线）。"""
        worker = make(_Worker)
        worker.start()
        _spin(400)
        assert worker._loop is not None
        worker.shutdown()
        _spin(100)
        assert worker._loop is None

    def test_setup_failure_leaves_commands_rejected(self, qapp, make):
        class Boom(_Worker):
            async def _setup(self):
                raise RuntimeError("boom")

        worker = make(Boom)
        failures = []
        worker.failed.connect(failures.append)
        worker.start()
        _spin(400)
        assert failures, "应发 failed"
        assert worker.ask("x") is None

    def test_shutdown_on_a_hanging_setup_is_non_blocking(
        self, qapp, make, _reap, monkeypatch
    ):
        """回归：``shutdown()`` 曾同步阻塞 4016 ms（后端初始化挂死时）。

        判据不是墙钟，而是「**绝不调用阻塞式 ``wait()``**」—— 它才是那 4 秒的
        来源，且这条契约与机器快慢无关。
        """
        worker = _spawn(make, _reap, _HangingSetupWorker, waitMs=300)
        _spin(300)

        waits = []
        monkeypatch.setattr(worker, "wait", lambda *a, **k: waits.append(True) or False)

        worker.shutdown()

        assert waits == [], "shutdown() 不得走阻塞等待"
        assert worker.isShuttingDown() is True

    def test_watchdog_terminates_a_stuck_thread_in_the_background(
        self, qapp, make, _reap
    ):
        worker = _spawn(make, _reap, _HangingSetupWorker, waitMs=300)
        _spin(300)
        worker.shutdown()
        assert worker.isRunning() is True, "刚 shutdown 时线程还没退"
        # 看门狗预算 = shutdownWaitMs(300) + _TERMINATE_WAIT_MS(1000)，到点才升级
        _spin(400)
        assert worker.isRunning() is True, "预算未到不该动它"
        _spin(1600)
        assert worker.isRunning() is False, "看门狗应已把它 terminate 掉"

    def test_normal_worker_exits_without_terminate(self, qapp, make, _reap):
        worker = _spawn(make, _reap)
        _spin(400)
        worker.shutdown()
        _spin(400)
        assert worker.isFinished() is True
        assert worker._watchdog.isActive() is False, "线程退出后看门狗应自行停止"

    def test_wait_for_shutdown_blocks_and_reports(self, qapp, make, _reap):
        """``waitForShutdown`` 保留给「紧接着销毁宿主窗口」的场景。"""
        worker = _spawn(make, _reap, _HangingSetupWorker, waitMs=300)
        _spin(300)
        worker.shutdown()
        assert worker.waitForShutdown() is True
        assert worker.isRunning() is False

    def test_shutdown_is_idempotent(self, qapp, make, _reap):
        worker = _spawn(make, _reap)
        _spin(400)
        worker.shutdown()
        worker.shutdown()
        _spin(300)
        assert worker.isRunning() is False


class TestBinderShutdownOnClose:
    """``shutdownOnClose`` 不得冻结关窗；需要确保退出时才传 timeoutMs。

    这里用**正常** worker：挂死后端要靠 ``terminate()`` 收尾，而「挂死 + 窗口销毁」
    的组合在测试进程里本身就不稳（已实测 0xC0000409）。挂死场景的看门狗升级由
    :class:`TestWorkerSubmitNeverRaises` 单独覆盖。
    """

    def _chat_and_worker(self, make, worker_cls=None):
        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        host = make(QWidget)
        host.setWindowFlags(Qt.WindowType.Window)
        layout = QVBoxLayout(host)
        chat = make(ElaChatWidget)
        layout.addWidget(chat)
        return host, chat, make(worker_cls or _Worker)

    def test_close_does_not_block(self, qapp, make, _reap, monkeypatch):
        host, chat, worker = self._chat_and_worker(make)
        binder = ElaChatStreamBinder(chat, worker=worker)
        binder.shutdownOnClose(host)
        worker = _reap_worker(make, _reap, worker)
        _spin(400)

        waits = []
        monkeypatch.setattr(worker, "wait", lambda *a, **k: waits.append(True) or False)

        host.close()  # 触发 Close 事件

        assert waits == [], "关窗不得走阻塞等待（关窗路径不得调用 wait）"
        assert worker.isShuttingDown() is True
        _spin(300)

    def test_destroyed_also_shuts_the_worker_down(self, qapp, make, _reap):
        host, chat, worker = self._chat_and_worker(make)
        binder = ElaChatStreamBinder(chat, worker=worker)
        binder.shutdownOnClose(host)
        worker = _reap_worker(make, _reap, worker)
        _spin(400)
        host.deleteLater()
        _spin(200)
        assert worker.isShuttingDown() is True

    def test_shutdown_worker_returns_true_without_a_worker(self, qapp, make):
        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        host = make(QWidget)
        chat = make(ElaChatWidget)
        QVBoxLayout(host).addWidget(chat)
        binder = ElaChatStreamBinder(chat)
        assert binder.shutdownWorker() is True

    def test_shutdown_worker_can_block_on_demand(self, qapp, make, _reap):
        host, chat, worker = self._chat_and_worker(make)
        binder = ElaChatStreamBinder(chat, worker=worker)
        worker = _reap_worker(make, _reap, worker)
        _spin(400)
        assert binder.shutdownWorker(timeoutMs=2000) is True
        assert worker.isRunning() is False

    def test_close_survives_an_already_deleted_worker(self, qapp, make):
        """回归：``destroyed`` 路径未包 try/except 时，后端先被析构会让关窗 0xC0000409。

        ``destroyed`` 是从 C++ 发射的 —— 包在 lambda 内部没用，必须在**连接前**包好。
        """

        host, chat, worker = self._chat_and_worker(make)
        binder = ElaChatStreamBinder(chat, worker=worker)
        binder.shutdownOnClose(host)
        worker.start()
        _spin(300)
        worker.shutdown()
        worker.waitForShutdown()
        sip.delete(worker)  # 宿主先销毁了后端

        host.close()  # 不得抛、不得 abort
        _spin(100)
        assert True


class TestWorkerStreamsAndFinishes:
    def test_chunks_arrive_and_turn_finishes(self, qapp, make):
        worker = make(_Worker)
        chunks, finished = [], []
        worker.chunkReceived.connect(chunks.append)
        worker.turnFinished.connect(finished.append)
        worker.start()
        _spin(400)
        assert worker.ask("hi") is not None
        _spin(600)
        worker.shutdown()
        _spin(100)
        assert chunks, "应收到分片"
        assert finished, "应发出 turnFinished"

    def test_cancel_stops_the_turn(self, qapp, make):
        class Slow(_Worker):
            def _stream_turn(self, prompt: str, attachments: list):
                async def gen():
                    for i in range(200):
                        yield {"answer_content": "y" * 50}
                        await asyncio.sleep(0.01)

                return gen()

        worker = make(Slow)
        finished = []
        worker.turnFinished.connect(finished.append)
        worker.start()
        _spin(400)
        worker.ask("hi")
        _spin(120)
        worker.cancel()
        _spin(400)
        assert finished, "取消后仍必须收尾"
        # 必须显式收尾：QThread 在运行中被析构就是 0xC0000409
        worker.shutdown()
        _spin(100)
        assert worker.isRunning() is False

    def test_stream_turn_raising_is_contained(self, qapp, make):
        class BadStream(_Worker):
            def _stream_turn(self, prompt: str, attachments: list):
                raise RuntimeError("创建流时就失败")

        worker = make(BadStream)
        errors, finished = [], []
        worker.errorOccurred.connect(lambda t, m: errors.append((t, m)))
        worker.turnFinished.connect(finished.append)
        worker.start()
        _spin(400)
        worker.ask("hi")
        _spin(300)
        worker.shutdown()
        _spin(100)
        assert errors, "同步抛异常应转成 errorOccurred"
        assert finished, "必须仍发 turnFinished，否则后续 ask 永久失败"
