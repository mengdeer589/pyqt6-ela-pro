"""流式事件 → 聊天组件映射器：把分轮流式事件翻译成 :class:`ElaChatWidget` 的分步 API。

回合边界：``beginTurn`` 之前 / ``finish`` 之后到达的分片、工具、用量与错误一律忽略。
回合 token：``startTurn`` 返回后端的回合 token，``finish`` 必须带上同一个 ——
迟到的 ``turnFinished``（后端 ``cancel()`` 异步）会被丢弃并返回 ``None``。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QObject

from . import _json
from ._usage import stats_from_usage
from .message import ElaChatStatusType, _as_float
from .widget import ElaChatWidget

logger = logging.getLogger(__name__)


def _guarded(callback: Callable) -> Callable:
    """把回调包成「抛异常也不会穿过 C++ 边界」的形状（支持带参信号）。

    Qt 回调里未捕获的异常直接 0xC0000409 静默终止，且槽异常不会传回 ``emit()``；
    唯一防线是在连接时就把槽包起来。
    """

    def _run(*args, **kwargs):
        try:
            callback(*args, **kwargs)
        except Exception:
            # 槽内异常不能穿回 Qt（0xC0000409），但也不该完全静默 ——
            # 出问题时把 traceback 留在 debug 日志里。
            logger.debug("binder 回调异常（已忽略）", exc_info=True)

    return _run


class _WindowCloseFilter(QObject):
    """窗口关闭回调过滤器（内部：不拦截事件，只做收尾）。"""

    def __init__(self, window, callback: Callable[[], None]) -> None:
        super().__init__(window)
        self._callback = _guarded(callback)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        if event.type() == QEvent.Type.Close:
            self._callback()
        return False


@dataclass(frozen=True)
class ElaChatTurnSummary:
    """回合结束摘要（由 :meth:`ElaChatStreamBinder.finish` 返回）。

    ``durationMs`` 是端到端耗时；``finishReason`` 来自模型（``emptyTurn`` 时传入）。
    """

    status: str = ElaChatStatusType.Done
    hadText: bool = True
    finishReason: str = ""
    durationMs: float = 0.0

    def isEmptyReply(self) -> bool:
        """是否属于「未返回正文」的回合。"""
        return not self.hadText


class ElaChatStreamBinder:
    """把分轮流式事件映射到 :class:`ElaChatWidget`（纯同步、可独立测试）。

    :param chat: 目标聊天组件
    :param clock: 计时函数（默认 ``time.monotonic``，测试可注入）
    :param worker: 可选后端，传入时自动接线并启用 :meth:`startTurn`
    """

    def __init__(
        self,
        chat: ElaChatWidget,
        clock: Callable[[], float] = time.monotonic,
        *,
        worker=None,
    ) -> None:
        self._chat = chat
        self._clock = clock
        self._worker = None
        #: 已连接的 (信号名, 包装后的槽) 列表（断开时按它精确匹配）
        self._worker_slots: list = []
        self._close_filter = None
        self._round = 0
        self._turn_start: Optional[float] = None
        self._round_start: Optional[float] = None
        # 计时值一律不兼作状态布尔：clock 可注入，返回 0.0 的时钟会让状态判错。
        self._turn_open = False
        # 当前回合操作的助手消息 id（view 层所有消息操作都要显式传它）
        self._message_id: Optional[int] = None
        #: 当前回合的 token（``startTurn`` 取自后端，``beginTurn`` 无 token 时自增）
        self._turn_token: Optional[int] = None
        self._turn_seq = 0
        self._reasoning_open = False
        self._reasoning_start = 0.0
        self._had_text = False
        self._finish_reason = ""
        self._cancelled = False
        #: 自动维护时间线活动行（默认开）
        self._auto_activity = True
        self._activity_provider = None
        self._activity_text = ""
        if worker is not None:
            self.connectWorker(worker)

    # -- 后端接线 ----------------------------------------------------------

    def connectWorker(self, worker) -> None:
        """绑定后端并自动接线机械信号（等价于宿主手写 6 条 connect）。

        连接 ``llmStarted`` / ``chunkReceived`` / ``toolStarted`` / ``toolEnded`` /
        ``statsReady`` / ``emptyTurn``；UI 决策的 ``ready`` / ``failed`` /
        ``errorOccurred`` / ``turnFinished`` 仍由宿主自行连接。幂等，换绑先解旧的。
        """
        if worker is self._worker:
            return
        self._disconnectWorker()
        self._worker = worker
        # 机械信号槽先包守卫再连接：后端数据是外部输入，槽内异常穿过 C++ 边界 = 0xC0000409。
        begin_round = _guarded(self.beginRound)
        stream = _guarded(self.stream)
        tool_started = _guarded(self.toolCallStarted)
        tool_ended = _guarded(self.toolCallEnded)
        stats = _guarded(self.stats)
        empty_turn = _guarded(self.emptyTurn)
        worker.llmStarted.connect(begin_round)
        worker.chunkReceived.connect(stream)
        worker.toolStarted.connect(tool_started)
        worker.toolEnded.connect(tool_ended)
        worker.statsReady.connect(stats)
        worker.emptyTurn.connect(empty_turn)
        self._worker_slots = [
            ("llmStarted", begin_round),
            ("chunkReceived", stream),
            ("toolStarted", tool_started),
            ("toolEnded", tool_ended),
            ("statsReady", stats),
            ("emptyTurn", empty_turn),
        ]

    def _disconnectWorker(self) -> None:
        """解绑当前后端的机械信号（未连接 / 已销毁时静默忽略）。"""
        worker = self._worker
        if worker is None:
            return
        for name, slot in self._worker_slots:
            try:
                getattr(worker, name).disconnect(slot)
            except (AttributeError, TypeError, RuntimeError):
                pass
        self._worker_slots = []

    def worker(self):
        """已绑定的后端（未绑定返回 ``None``）。"""
        return self._worker

    def shutdownOnClose(self, window, timeoutMs: Optional[int] = None) -> None:  # noqa: N802
        """窗口关闭 / 销毁时自动 ``worker.shutdown()``（宿主免写 closeEvent）。

        :param window: 顶层窗口（通常是 ``chat.window()``）
        :param timeoutMs: 传给 :meth:`shutdownWorker`；缺省不阻塞。

        显式调用（不做隐式自动）；后端没有 ``shutdown`` 方法时忽略。
        """
        onClose = _guarded(lambda: self.shutdownWorker(timeoutMs))
        if self._close_filter is not None:
            # 幂等：重复调用不再叠第二个事件过滤器 / 第二条 destroyed 连接
            return
        self._close_filter = _WindowCloseFilter(window, onClose)
        window.installEventFilter(self._close_filter)
        window.destroyed.connect(lambda *_: onClose())

    def shutdownWorker(self, timeoutMs: Optional[int] = None) -> bool:  # noqa: N802
        """收尾后端（幂等；没有后端 / 后端无 ``shutdown`` 时返回 ``True``）。

        :param timeoutMs: ``None`` = 不阻塞，只发关闭请求；给正数则阻塞等到线程退出
            （紧接着销毁宿主窗口时才需要）。
        """
        worker = self._worker
        shutdown = getattr(worker, "shutdown", None)
        if not callable(shutdown):
            return True
        wait = getattr(worker, "waitForShutdown", None)
        if timeoutMs is None or not callable(wait):
            shutdown()
            return True
        shutdown()
        return bool(wait(int(timeoutMs)))

    # -- 回合与轮次 --------------------------------------------------------

    # -- 运行态活动行 ------------------------------------------------------

    def setAutoActivity(self, on: bool = True) -> None:
        """开关「自动维护时间线活动行」（默认开）。"""
        self._auto_activity = bool(on)
        if not self._auto_activity:
            self._clear_activity()

    def autoActivity(self) -> bool:
        """是否自动维护活动行。"""
        return self._auto_activity

    def setActivityProvider(self, provider) -> None:
        """注入活动文案提供者 ``(kind, detail) -> str | None``。

        返回 ``None`` 表示回落库内默认文案；返回空串表示隐藏活动行。
        """
        self._activity_provider = provider if callable(provider) else None
        if self._activity_text:
            self._set_activity(self._activity_text)

    def _activity_for_tool(self, name: str) -> str:
        key = str(name or "").lower()
        if key in ("read", "glob", "grep", "list"):
            return "正在读取上下文…"
        if key in ("edit", "write", "patch", "apply_patch"):
            return "正在修改文件…"
        if key in ("shell", "bash", "execute", "terminal"):
            return "正在运行命令…"
        if key in ("websearch", "webfetch"):
            return "正在搜索…"
        if key in ("subagent", "task", "agent"):
            return "正在委派子代理…"
        return f"正在调用 {name}…" if name else "正在工作…"

    def _set_activity(self, text: str, kind: str = "", detail: str = "") -> None:
        if not self._auto_activity:
            return
        if self._activity_provider is not None:
            try:
                custom = self._activity_provider(kind, detail)
            except Exception:
                custom = None
            if custom is not None:
                text = str(custom)
        self._activity_text = str(text or "")
        self._chat.chatView().setActivity(self._activity_text)

    def _clear_activity(self) -> None:
        self._activity_text = ""
        self._chat.chatView().setActivity("")

    def _clear_retry(self) -> None:
        target = self._target()
        if target is not None:
            self._chat.chatView().clearRetry(target)

    def retry(self, attempt: int, message: str, nextAt: float = 0.0) -> None:
        """显示自动重试状态（后端退避重试时调用）。"""
        target = self._target()
        if target is None:
            return
        self._chat.chatView().setRetry(target, attempt, message, nextAt)
        self._set_activity("正在重试…", "retry", str(attempt))

    def startTurn(
        self,
        prompt: str,
        regenerate: bool = False,
        attachments=None,
        *,
        agent: str = "",
        model: str = "",
        modelVariant: str = "",
    ) -> Optional[int]:
        """开始一个回合：先驱动后端起跑，随后新建助手消息并重置计时。

        后端需保证 ``ask`` / ``regenerate`` 返回后才开始发信号。

        :param prompt: 提问文本
        :param regenerate: ``True`` 时走 ``worker.regenerate``（历史回滚由后端负责）
        :param attachments: 随消息发送的附件；重新生成必须带上，否则模型看不见文件
        :returns: 回合 token；``None`` 表示后端未受理（此时不创建空的助手消息）
        """
        if self._worker is None:
            return None
        method = self._worker.regenerate if regenerate else self._worker.ask
        turn = method(prompt or "", list(attachments or ()))
        if turn is None:
            return None
        # view 层方法都要求显式传 messageId，binder 必须自己攥着这个 id。
        self._message_id = self._chat.beginAssistantMessage(
            agent=agent, model=model, modelVariant=modelVariant
        )
        self.beginTurn(turn)
        self._set_activity("正在思考…", "thinking")
        return turn

    def _target(self) -> Optional[int]:
        """当前回合操作的消息 id（``None`` 表示回合未开，调用方应忽略）。"""
        return self._message_id

    def beginTurn(self, turn: Optional[int] = None) -> int:
        """开始一个回合（宿主提交提问 / 重新生成时调用），返回回合 token。

        ``turn`` 是后端 token；宿主自己 ``ask`` 后不走 :meth:`startTurn` 时把它
        传进来。都不传时本地自增一个，返回值同样要交给 :meth:`finish`。
        """
        if turn is None:
            self._turn_seq += 1
            turn = self._turn_seq
        self._turn_token = turn
        self._round = 0
        self._turn_open = True
        self._turn_start = self._clock()
        self._round_start = None
        self._reasoning_open = False
        self._reasoning_start = 0.0
        self._had_text = False
        self._finish_reason = ""
        self._cancelled = False
        if self._message_id is None:
            # 宿主可能自己建好消息再调 beginTurn()（不经 startTurn），接上当前流式消息。
            self._message_id = self._chat.streamingMessageId()
        self._clear_retry()
        self._set_activity("正在思考…", "thinking")
        return turn

    def beginRound(self) -> None:
        """开始一轮 LLM 调用（第 2 轮起自动开启新步骤）。

        回合外的迟到事件一律忽略。**这里是 steer（插话）的投递点** ——
        ``beginStep`` 之前是「上一步工具都跑完了」的安全边界，一次只投一条。
        """
        if not self.isOpen():
            return
        self._round_start = self._clock()
        self._round += 1
        self._set_activity("正在思考…", "thinking")
        if self._round > 1:
            self._endReasoning()
            self._chat.chatView().beginStep(self._target())
            self._drainSteer()

    def _drainSteer(self) -> None:
        """在 step 边界投递一条待送插话（仅开了自动投递时）。

        组件侧只负责「留回执 + 发信号」；把文本送进后端是宿主的事。
        """
        chat = self._chat
        if not getattr(chat, "steerEnabled", lambda: True)():
            return
        drain = getattr(chat, "drainSteer", None)
        if callable(drain):
            drain()

    def isOpen(self) -> bool:
        """是否处于回合中（``beginTurn`` 之后、``finish`` 之前）且有目标消息。

        判据是显式的 ``_turn_open`` 标志，不是 ``_turn_start != 0.0``：``clock``
        可注入，返回 0.0 的假时钟会让整回合被静默丢弃。
        """
        return self._turn_open and self._message_id is not None

    def roundIndex(self) -> int:
        """当前回合内的 LLM 轮次序号（从 1 开始）。"""
        return self._round

    # -- 内容分片 ----------------------------------------------------------

    def reasoning(self, text: str) -> None:
        """追加推理分片（同一轮复用同一思考段；回合外忽略）。"""
        if not text or not self.isOpen():
            return
        self._set_activity("正在思考…", "thinking")
        if not self._reasoning_open:
            self._reasoning_open = True
            self._reasoning_start = self._clock()
            self._chat.chatView().beginReasoning(self._target())
        self._chat.chatView().appendReasoning(self._target(), text)

    def answer(self, text: str) -> None:
        """追加正文分片（自动结束当前推理段；回合外忽略）。

        纯空白分片不算正文：不置 ``_had_text``、不结束思考段；开段与否由气泡
        按首个非空白分片决定，中段空白照常保留。
        """
        if not text or not self.isOpen():
            return
        if text.strip():
            self._had_text = True
            self._endReasoning()
            self._clear_retry()
            self._set_activity("", "answer")
        self._chat.chatView().appendText(self._target(), text)

    def stream(self, chunk) -> None:
        """分派流式分片（兼容 ``AgentOutput`` / ``ElaChatMockChunk``）。

        依次读取 ``reasoning_content`` / ``answer_content`` 属性，非空则转给
        :meth:`reasoning` / :meth:`answer`；可直接接到
        ``worker.chunkReceived.connect(binder.stream)``。
        """
        reasoning = getattr(chunk, "reasoning_content", "") or ""
        answer = getattr(chunk, "answer_content", "") or ""
        if reasoning:
            self.reasoning(reasoning)
        if answer:
            self.answer(answer)

    # -- 工具调用 ----------------------------------------------------------

    def toolStart(self, callId: str, name: str, arguments="") -> None:
        """工具调用开始（``arguments`` 支持 dict 或 JSON 字符串；回合外忽略）。"""
        if not self.isOpen():
            return
        if not isinstance(arguments, str):
            try:
                arguments = _json.dumps(arguments)
            except (TypeError, ValueError):
                # dict 里可能有非有限浮点等不可序列化值：退化成原文，不让一次畸形参数
                # 把整条工具调用丢掉。
                arguments = str(arguments)
        self._clear_retry()
        self._set_activity(self._activity_for_tool(name), "tool", str(name or ""))
        self._chat.chatView().addToolCall(
            self._target(), name, arguments, callId or None
        )

    def toolEnd(self, callId: str, result: str, ok: Optional[bool] = None) -> None:
        """工具调用结束（``ok`` 为空时按 ``"Error:"`` 前缀推断；回合外忽略）。"""
        if not callId or not self.isOpen():
            return
        text = str(result or "")
        if ok is None:
            ok = not text.startswith("Error:")
        self._chat.chatView().setToolCallResult(
            self._target(), callId, text, ok=bool(ok)
        )
        self._set_activity("正在思考…", "thinking")

    def toolCallStarted(self, toolCall: dict) -> None:
        """工具调用开始（OpenAI 风格 ``tool_call`` dict，可直接连信号）。

        取 ``id`` 与 ``function.name`` / ``function.arguments`` 转给
        :meth:`toolStart`。
        """
        if not isinstance(toolCall, dict):
            return
        # ``{}`` 或缺字段按 "unknown" 兜底；function 是字符串这类畸形结构直接丢弃。
        function = toolCall.get("function") or {}
        if not isinstance(function, dict):
            return
        self.toolStart(
            toolCall.get("id") or "",
            function.get("name") or "unknown",
            function.get("arguments", ""),
        )

    def toolCallEnded(self, toolCall: dict, result: str) -> None:
        """工具调用结束（OpenAI 风格 ``tool_call`` dict，可直接连信号）。"""
        if not isinstance(toolCall, dict):
            return
        self.toolEnd(toolCall.get("id") or "", result)

    # -- 用量与错误 --------------------------------------------------------

    def stats(self, usage, ttftMs: float = 0.0, tps: float = 0.0) -> None:
        """写入当前步骤用量（兼容 OpenAI ``usage`` 或 :class:`ElaChatStats`）。

        回合外忽略，避免迟到用量改写已结束消息的整轮汇总。
        """
        if usage is None or not self.isOpen():
            return
        stats = stats_from_usage(usage, ttftMs, tps)
        durationMs = 0.0
        if self._round_start is not None:
            durationMs = _as_float((self._clock() - self._round_start) * 1000.0)
        if durationMs and not stats.duration_ms:
            stats = replace(stats, duration_ms=durationMs)
        self._chat.chatView().setStepStats(self._target(), stats)

    def error(self, errorType: str, message: str) -> None:
        """写入错误（结束当前推理段并置错误卡片；回合外忽略）。

        ``errorType`` 原样传给 view，不拼进文案 —— 错误卡靠它判断该不该给「重试」，
        类型信息拼进自然语言就再也取不回来了。
        """
        if not self.isOpen():
            return
        self._endReasoning()
        self._clear_activity()
        self._clear_retry()
        self._chat.chatView().setMessageError(self._target(), message, errorType)

    def emptyTurn(self, finishReason: str = "") -> None:
        """标记「回合结束但未返回正文」（由 ``finish`` 汇总返回；回合外忽略）。"""
        if not self.isOpen():
            return
        self._finish_reason = str(finishReason or "")

    # -- 结束 --------------------------------------------------------------

    def cancel(self) -> None:
        """停止生成：收尾当前思考段，并让 :meth:`finish` 默认按 ``Stopped`` 收尾。

        宿主停止按钮：``binder.cancel()`` + 中止后端（``worker.cancel()``）。
        """
        self._cancelled = True
        self._endReasoning()

    def finish(
        self, turn, status: Optional[str] = None
    ) -> Optional[ElaChatTurnSummary]:
        """结束回合：补整轮耗时、结束消息，返回摘要（幂等）。

        :param turn: 回合 token。与当前回合不符说明是迟到信号（后端 ``cancel()``
            异步），直接丢弃并返回 ``None`` —— 收掉新回合会让它的分片全被丢弃。
        :param status: 最终状态；缺省时按是否调用过 :meth:`cancel` 取 ``Stopped`` / ``Done``
        :returns: 本回合摘要；``turn`` 陈旧时为 ``None``（宿主据此跳过状态更新）
        """
        if turn != self._turn_token:
            logger.warning(
                "丢弃迟到的回合收尾：token=%r，当前回合 token=%r",
                turn,
                self._turn_token,
            )
            return None
        if status is None:
            status = (
                ElaChatStatusType.Stopped if self._cancelled else ElaChatStatusType.Done
            )
        self._endReasoning()
        self._clear_activity()
        self._clear_retry()
        target = self._target()
        durationMs = 0.0
        if self._turn_open and self._turn_start is not None:
            durationMs = (self._clock() - self._turn_start) * 1000.0
        # 先清本回合状态再触发宿主回调：endAssistantMessage 会同步续发排队消息，
        # 宿主槽里可能立刻 startTurn() 开新回合 —— 晚清会抹掉新回合的落点。
        self._turn_open = False
        self._turn_start = None
        self._turn_token = None
        self._message_id = None
        if durationMs and target is not None:
            self._chat.chatView().setMessageDuration(target, durationMs)
        # 不能只在 isGenerating() 时收尾：setMessageError / removeMessage 等已把它置
        # False，跳过 endAssistantMessage 会让 generationFinished 不发、排队永不排空。
        if target is not None:
            self._chat.endAssistantMessage(messageId=target, status=status)
        elif self._chat.streamingMessageId() is not None:
            # 落点丢失的兜底（宿主自己建了流式消息但没走 startTurn）：
            # 仍按当前流式消息收尾，但不写耗时（没有可信的 target）。
            self._chat.endAssistantMessage(status=status)
        return ElaChatTurnSummary(
            status=status,
            hadText=self._had_text,
            finishReason=self._finish_reason,
            durationMs=durationMs,
        )

    def abortTurn(self, cancelBackend: bool = True) -> Optional[ElaChatTurnSummary]:
        """立刻作废当前回合（不等后端确认），返回摘要；回合外返回 ``None``。

        = ``cancel()`` + ``finish(turn, Stopped)``（+ 默认 ``worker.cancel()``），
        用于不打算保留这一轮的场景。与 :meth:`cancel` / :meth:`finish` 的差异：
        默认停掉后端且不续发排队消息；顺序是「先收尾再停后端」（部分后端
        ``cancel()`` 会同步发 ``turnFinished``，先收尾能保证那次重入是空操作）。

        :param cancelBackend: 是否同时 ``worker.cancel()``（默认 ``True``）
        """
        if not self.isOpen():
            return None
        autoSend = self._chat.autoSendQueue()
        self._chat.setAutoSendQueue(False)
        try:
            self.cancel()
            summary = self.finish(self._turn_token, ElaChatStatusType.Stopped)
            if cancelBackend and self._worker is not None:
                self._worker.cancel()
            return summary
        finally:
            self._chat.setAutoSendQueue(autoSend)

    # -- 内部 --------------------------------------------------------------

    def _endReasoning(self) -> None:
        if not self._reasoning_open:
            return
        elapsed = (self._clock() - self._reasoning_start) * 1000.0
        self._chat.chatView().endReasoning(self._target(), elapsed)
        self._reasoning_open = False
