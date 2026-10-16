"""异步聊天后端 worker 基类（``pyqt6_ela_pro.chat``）。

:class:`ElaChatAsyncWorker` 把「QThread + asyncio 事件循环 + 命令队列 + 取消 / 收尾」
这套宿主基础设施收进库内；信号契约与
:class:`~pyqt6_ela_pro.chat.mock.ElaChatMockBackend` 完全同构，可直接接到
:class:`~pyqt6_ela_pro.chat.binder.ElaChatStreamBinder`。

子类只需实现与后端相关的钩子（**在钩子内直接发信号**，如 ``self.llmStarted.emit()`` /
``self.toolStarted.emit(tool_call)`` / ``self.statsReady.emit(usage, ttft_ms, tps)``）：

- ``_setup()``（async）：初始化后端，完成时发 ``ready``、失败时发 ``failed``；
- ``_stream_turn(prompt, attachments)``：返回本回合的异步分片迭代器，产出对象由
  ``chunkReceived`` 发出；``attachments`` 是本条消息的附件列表（可空）；
- ``_rollback_turn(prompt, attachments)``（async，可选）：``regenerate()`` 前
  回滚历史（``attachments`` 与 ``_stream_turn`` 同源，用于拼出与历史一致的口径）；
- ``_after_turn()``（async，可选）：回合正常结束时收尾（如空正文诊断）；
- ``_reset_backend()``（async，可选）：``reset()`` 命令。

线程安全命令：``ask`` / ``regenerate``（返回**回合 token**，未就绪返回
``None``）/ ``reset`` / ``cancel`` / ``shutdown``。

**回合 token 是必需的，不是可选装饰**：``cancel()`` 只置标记、由轮询异步收尾，
旧回合的 ``turnFinished`` 可能晚几十毫秒到达，而那时宿主往往已经发了新提问。
``turnFinished`` 原样带回发起时的 token，宿主凭它认领收尾（``binder.finish``），
认不出的迟到信号直接丢弃 —— 否则新回合会被旧回合的收尾按「完成」掐掉，
分片全被丢弃，用户看到「消息发出去了、正文一个字没有」。

用法::

    class MyWorker(ElaChatAsyncWorker):
        async def _setup(self):
            self._client = await create_client()
            self.ready.emit()

        def _stream_turn(self, prompt, attachments):
            return self._client.stream(prompt, attachments)

    worker = MyWorker(parent)
    worker.start()                 # QThread.start()
    worker.ask("你好", attachments=[{"name": "a.png", "path": "C:/a.png"}])
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import AsyncIterator, Optional

from PyQt6.QtCore import QThread, QTimer, pyqtSignal

#: 取消标记轮询间隔（秒）
_CANCEL_POLL_INTERVAL = 0.05
#: shutdown 后看门狗的轮询间隔（毫秒）—— 只读 ``isFinished()``，不阻塞
_SHUTDOWN_POLL_MS = 25
#: shutdown 等待线程退出的最长时间（毫秒）；超时后 terminate 兜底
_SHUTDOWN_WAIT_MS = 4000
#: shutdown 超时后 terminate 兜底的等待时间（毫秒）
_TERMINATE_WAIT_MS = 1000
#: 极端情况下仍未退出、需要保活避免「运行中被销毁」的 worker
_LINGERING_WORKERS: list = []


def _worker_exited(worker) -> bool:
    """worker 是否已退出（包装器已销毁也按「退出」处理）。"""
    try:
        return bool(worker.isFinished())
    except RuntimeError:
        # 对应的 C++ 对象已销毁：没有任何保活意义
        return True


def _remember_lingering(worker) -> None:
    """保活一个「terminate 后仍未退出」的 worker；顺手剪掉已退出的条目。

    保活的目的只是「避免运行中的 ``QThread`` 被 GC 析构」，线程一旦退出就
    没有保活价值 —— 只增不减的列表在长生命周期宿主里会无界累积。
    """
    _LINGERING_WORKERS[:] = [
        item for item in _LINGERING_WORKERS if not _worker_exited(item)
    ]
    if not _worker_exited(worker):
        _LINGERING_WORKERS.append(worker)


class ElaChatAsyncWorker(QThread):
    """异步后端 worker 基类（``QThread`` + asyncio 事件循环 + 命令队列）。"""

    #: 后端初始化完成，可以提问
    ready = pyqtSignal()
    #: 后端初始化失败（携带人类可读原因）
    failed = pyqtSignal(str)
    #: 错误（类型、消息）
    errorOccurred = pyqtSignal(str, str)
    #: 回合结束但模型未返回正文（参数：finish_reason）
    emptyTurn = pyqtSignal(str)
    #: 新一轮 LLM 调用开始（用于划分步骤）
    llmStarted = pyqtSignal()
    #: 流式分片（对象由子类定义，如含 reasoning / answer 内容）
    chunkReceived = pyqtSignal(object)
    #: 工具调用开始（tool_call dict）
    toolStarted = pyqtSignal(dict)
    #: 工具调用结束（tool_call dict、结果文本）
    toolEnded = pyqtSignal(dict, str)
    #: 单次 LLM 用量（usage、首字耗时 ms、词元/秒）
    statsReady = pyqtSignal(object, float, float)
    #: 本回合结束（无论成功 / 失败 / 停止），载荷是 :meth:`ask` 返回的**回合 token**
    turnFinished = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue] = None
        self._cancel = threading.Event()
        self._closing = False
        self._token_lock = threading.Lock()
        #: 回合 token 自增源。token 是「这轮生杀」的凭据：``cancel()`` 是异步的
        #: （轮询命中才收尾），旧回合的 ``turnFinished`` 可能晚到几十毫秒，
        #: 宿主凭 token 就能认出迟到信号而不被它收掉新回合。
        self._turn_seq = 0
        self._watchdog: Optional[QTimer] = None
        self._watchdog_deadline = 0.0
        self._terminated = False
        #: 是否有一个回合正在跑（run() 的异常收尾据此决定要不要补发 turnFinished）
        self._turn_active = False
        #: 正在跑的回合 token（run() 的异常补发要带上它）
        self._active_turn = 0

    # -- 子类钩子 ----------------------------------------------------------

    async def _setup(self) -> None:
        """初始化后端（子类实现）；默认直接发 ``ready``。"""
        self.ready.emit()

    def _stream_turn(self, prompt: str, attachments: list) -> AsyncIterator:
        """返回本回合的异步分片迭代器（子类实现）。

        ``attachments`` 是本条消息的附件列表（``ElaChatAttachment`` 或等价
        dict；无附件时为空列表）。
        """
        raise NotImplementedError(f"{type(self).__name__} 未实现 _stream_turn")

    async def _rollback_turn(self, prompt: str, attachments: list) -> None:
        """``regenerate()`` 前回滚上一轮历史（子类可选实现）。

        ``attachments`` 与 :meth:`_stream_turn` 同源 —— 子类若把附件拼进提问
        （例如追加附件清单），回滚比较时也要用同一口径拼。
        """

    async def _after_turn(self) -> None:
        """回合正常结束时收尾，如空正文诊断（子类可选实现）。"""

    async def _reset_backend(self) -> None:
        """重置后端会话（子类可选实现）。"""

    # -- 线程主体 ----------------------------------------------------------

    def run(self) -> None:  # noqa: D102
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:
            message = f"worker 线程异常：{exc}"
            if self._queue is None:
                # 还在初始化阶段（命令循环都没进）：``failed`` 的语义就是
                # 「后端不可用」，宿主按初始化失败处理。
                self.failed.emit(message)
            else:
                # ready 之后的异常：不能再发 ``failed``（宿主可能只拿它做
                # 「初始化失败」提示），发结构化错误；若异常发生时有回合在跑，
                # 补一条 ``turnFinished``，否则宿主的流式回合永远收不掉。
                self.errorOccurred.emit("worker", message)
                if self._turn_active:
                    self._turn_active = False
                    self.turnFinished.emit(self._active_turn)
        finally:
            self._cleanup_loop()

    def _cleanup_loop(self) -> None:
        """退出前收尾：取消残留任务再关异步生成器。"""
        loop = self._loop
        if loop is None:
            return
        # **先把 ``_loop`` 置 None 再 close()**：反过来的话，「已 close 但仍非 None」
        # 这个中间态落在本函数的两条语句之间，而它是可达的（见 :meth:`_submit`）——
        # 别的线程此刻提交命令就会撞上 ``RuntimeError: Event loop is closed``。
        self._loop = None
        try:
            # 先取消残留任务：否则流式响应仍在跑，shutdown_asyncgens 会报
            # 「already running」
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()

    async def _serve(self) -> None:
        try:
            await self._setup()
        except Exception as exc:
            self.failed.emit(f"后端初始化失败：{exc}")
            return
        self._queue = asyncio.Queue()
        while True:
            command = await self._queue.get()
            if command is None:
                break
            # 新命令开始：清掉上一轮遗留的取消标记。**不能放在 ``_run_turn``
            # 里清** —— regenerate 的 ``_rollback_turn`` 可能耗时（HTTP / DB），
            # 期间用户按下的停止会被那一步清掉，整个回合照跑、停止键失效。
            self._cancel.clear()
            kind, payload, turn = command
            if kind == "ask":
                await self._run_turn(*payload, turn)
            elif kind == "regenerate":
                text, attachments = payload
                try:
                    await self._rollback_turn(text, attachments)
                except Exception as exc:
                    self.errorOccurred.emit("worker", f"{type(exc).__name__}: {exc}")
                await self._run_turn(text, attachments, turn)
            elif kind == "reset":
                try:
                    await self._reset_backend()
                except Exception as exc:
                    self.errorOccurred.emit("worker", f"{type(exc).__name__}: {exc}")

    async def _run_turn(self, prompt: str, attachments: list, turn: int) -> None:
        if self._cancel.is_set():
            # 回滚 / 排队期间用户按下了停止：这一轮直接作废，不再发起后端请求，
            # 但仍要发 ``turnFinished`` 把宿主的回合生命周期收掉。
            self._cancel.clear()
            self.turnFinished.emit(turn)
            return
        try:
            stream = self._stream_turn(prompt, attachments)
        except Exception as exc:
            # 同步抛异常（创建生成器 / 客户端时就失败）必须在本回合内收尾：
            # 否则异常冲出 _serve 循环，worker 线程直接退出，后续 ask 永久失败
            # 且不发 turnFinished。
            self.errorOccurred.emit("worker", f"{type(exc).__name__}: {exc}")
            self.turnFinished.emit(turn)
            return

        async def pump() -> None:
            async for chunk in stream:
                self.chunkReceived.emit(chunk)

        # 流式迭代独占一个 task：取消时注入 CancelledError 让生成器在自己的任务里
        # 收尾（直接 aclose 会与 SDK 内部的响应流任务冲突：already running）。
        self._turn_active = True
        self._active_turn = turn
        task = asyncio.ensure_future(pump())
        watcher = asyncio.ensure_future(self._watch_cancel(task))
        try:
            try:
                await task
            except asyncio.CancelledError:
                aclose = getattr(stream, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:
                        pass
                return
            if not (self._cancel.is_set() or self._closing):
                try:
                    await self._after_turn()
                except Exception as exc:
                    self.errorOccurred.emit("worker", f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            self.errorOccurred.emit("worker", f"{type(exc).__name__}: {exc}")
        finally:
            self._turn_active = False
            watcher.cancel()
            self.turnFinished.emit(turn)

    async def _watch_cancel(self, task: "asyncio.Future") -> None:
        """轮询取消 / 关闭标记；命中后取消流式 task。"""
        try:
            while not task.done():
                if self._cancel.is_set() or self._closing:
                    task.cancel()
                    return
                await asyncio.sleep(_CANCEL_POLL_INTERVAL)
        except asyncio.CancelledError:
            pass

    # -- 命令接口（线程安全） ----------------------------------------------

    def _next_turn_token(self) -> int:
        """分配一个回合 token（加锁：``ask`` 可能来自多个线程）。"""
        with self._token_lock:
            self._turn_seq += 1
            return self._turn_seq

    def ask(self, text: str, attachments=None) -> Optional[int]:
        """提交提问；worker 未就绪返回 ``None``。

        ``attachments`` 随提问一起交给 :meth:`_stream_turn`（附件对象 / dict
        列表，原样透传，不做序列化 —— 后端要什么格式由子类决定）。

        :returns: 回合 token（:attr:`turnFinished` 会原样带回，供宿主认领收尾）。
            **不要再当 bool 用** —— 真值即代表已受理。
        """
        turn = self._next_turn_token()
        submitted = self._submit(("ask", (text, list(attachments or ())), turn))
        return turn if submitted else None

    def regenerate(self, text: str, attachments=None) -> Optional[int]:
        """重新生成：先回滚历史再重跑；未就绪返回 ``None``。

        **必须带上原消息的附件** —— ``regenerateFrom`` 返回的提问快照里就有，
        不带等于模型看不见用户上传的文件。
        """
        turn = self._next_turn_token()
        submitted = self._submit(("regenerate", (text, list(attachments or ())), turn))
        return turn if submitted else None

    def reset(self) -> None:
        """重置后端会话。"""
        self._submit(("reset", None, 0))

    def cancel(self) -> None:
        """请求中止当前回合（保留已输出内容）。"""
        self._cancel.set()

    def _submit(self, command) -> bool:
        """投递命令。worker 未就绪 / 已关闭返回 ``False``（**不抛**）。

        契约是「未就绪时返回 ``False``」，所以这里对「事件循环已关闭」也必须走
        返回路径而不是让 ``RuntimeError`` 冒出去 —— ``ask()`` 是宿主从 GUI 线程直接
        调的，异常穿过 C++ 边界就是 0xC0000409 静默终止。

        :meth:`_cleanup_loop` 已经把「先置 ``None`` 后 ``close()``」的顺序固定下来，
        这里再兜一层底：万一 loop 在检查与投递之间被别的线程关掉（``terminate()``
        路径），也只是返回 ``False``。
        """
        loop = self._loop
        if loop is None or self._queue is None or self._closing:
            # 已请求关闭：不再受理命令（这之前只看了 loop/queue，shutdown 之后、
            # 线程收尾之前的那段窗口里 ask() 会假成功，命令永不执行）。
            return False
        put = self._queue.put(command)
        try:
            asyncio.run_coroutine_threadsafe(put, loop)
        except RuntimeError:
            # 协程已建出但没被调度 —— 必须显式关掉，否则 RuntimeWarning + 悬空
            put.close()
            return False
        return True

    #: shutdown 等待线程退出的最长时间（毫秒），超时后 terminate 兜底
    shutdownWaitMs = _SHUTDOWN_WAIT_MS

    def isShuttingDown(self) -> bool:
        """是否已请求关闭。"""
        return self._closing

    def shutdown(self) -> None:
        """请求停止 worker 并**立即返回**（不阻塞调用线程）。

        只做三件事：置关闭标记、请求中止当前回合、投递 ``None`` 哨兵让 ``_serve``
        循环退出。线程随后在**自己那条**消息里收尾，不占着 GUI 线程。

        **不要在这里阻塞。** 旧实现在这里 ``wait(4000)`` + ``terminate()`` 后再
        ``wait(1000)``，而后端初始化卡住时实测关窗冻结 4016 ms（``_setup`` 没跑完时
        ``_queue`` 还是 ``None``，哨兵投不出去，只能等满超时）。超时升级改由
        :meth:`_arm_watchdog` 的**非阻塞**轮询完成：到点就 ``terminate()``，再不退出
        就保活防「运行中被销毁」。

        确实需要「确保线程已退出」（例如紧接着销毁宿主窗口）时用
        :meth:`waitForShutdown`。
        """
        self._closing = True
        self.cancel()
        self._request_sentinel()
        self._arm_watchdog()

    def _request_sentinel(self) -> None:
        """投递 ``None`` 哨兵让 ``_serve`` 循环退出（投不出去也不抛）。

        ``shutdown()`` 走的是关窗路径，**任何**异常都会穿过 C++ 边界，所以这里
        连「队列对象状态异常」也要吞 —— 线程退不退出交给看门狗。
        """
        loop = self._loop
        queue = self._queue
        if loop is None or queue is None:
            return
        try:
            put = queue.put(None)
        except Exception:
            return
        try:
            asyncio.run_coroutine_threadsafe(put, loop)
        except RuntimeError:
            put.close()

    def waitForShutdown(self, timeoutMs: Optional[int] = None) -> bool:  # noqa: N802
        """阻塞等到线程退出（必要时 ``terminate()``）；返回是否已退出。

        :param timeoutMs: 总预算，默认 ``shutdownWaitMs``。**只有真的要确保线程停掉
            时才用**（例如紧接着销毁宿主窗口）；一般用 :meth:`shutdown` 就够。
        """
        budget = self.shutdownWaitMs if timeoutMs is None else int(timeoutMs)
        if not self.isRunning():
            self._stop_watchdog()
            return True
        if self.wait(budget):
            self._stop_watchdog()
            return True
        self.terminate()
        if self.wait(_TERMINATE_WAIT_MS):
            self._stop_watchdog()
            return True
        # 极端情况：宁可泄漏对象也不要在运行中被销毁
        _remember_lingering(self)
        self._stop_watchdog()
        return False

    def _arm_watchdog(self) -> None:
        """武装非阻塞看门狗：到点升级成 ``terminate()``，再不退出就保活。

        挂在 self 上的 ``QTimer``，靠 GUI 线程的事件循环推进 —— 与 worker 线程
        无关，所以后端卡死时它照样能把线程收掉。
        """
        if self._watchdog is None:
            self._watchdog = QTimer(self)
            self._watchdog.setInterval(_SHUTDOWN_POLL_MS)
            self._watchdog.timeout.connect(self._on_watchdog)
        # 重新武装时复位 terminate 标记：否则第二次 shutdown（例如宿主先
        # shutdown 一次、窗口关闭再触发一次）会因 `_terminated` 仍为 True
        # 而跳过升级，只保活不 terminate。
        self._terminated = False
        self._watchdog_deadline = (
            time.monotonic() * 1000.0 + self.shutdownWaitMs + _TERMINATE_WAIT_MS
        )
        self._watchdog.start()

    def _stop_watchdog(self) -> None:
        if self._watchdog is not None:
            self._watchdog.stop()

    def _on_watchdog(self) -> None:
        if self.isFinished() or not self.isRunning():
            self._stop_watchdog()
            return
        if time.monotonic() * 1000.0 < self._watchdog_deadline:
            return
        # 已超预算仍未退出：升级 —— 先 terminate，再不退出就保活
        if not self._terminated:
            self._terminated = True
            self.terminate()
            return
        self._stop_watchdog()
        _remember_lingering(self)


__all__ = ["ElaChatAsyncWorker"]
