"""流式事件 → 聊天组件映射器（``pyqt6_ela_pro.chat``）。

:class:`ElaChatStreamBinder` 把「分轮流式事件」翻译成 :class:`ElaChatWidget`
的分步 API，宿主只需把后端回调转发进来，无需关心步骤边界、思考段复用、
工具面板归属、统计落位与端到端耗时等细节：

- ``beginTurn()``：宿主提交提问时调用（重置计时与标记）；
- ``beginRound()``：每次 LLM 调用前调用（第 2 轮起自动 ``beginStep``）；
- ``reasoning(text)`` / ``answer(text)`` / ``stream(chunk)``：推理与正文分片
  （同一轮的思考内容复用同一折叠块，正文出现时自动结束思考段；``stream`` 可直接连
  ``chunkReceived``）；
- ``toolStart(callId, name, arguments)`` / ``toolEnd(callId, result, ok=None)``：
  工具调用开始 / 结束（``ok=None`` 时按 ``result`` 是否以 ``"Error:"`` 开头推断）；
  ``toolCallStarted`` / ``toolCallEnded`` 直接接收 OpenAI 风格 ``tool_call`` dict；
- ``stats(usage, ttftMs, tps)``：单轮用量（兼容 OpenAI ``usage`` 对象或
  :class:`ElaChatStats`）；每步原始数据存在消息 ``parts`` 中，界面默认合并为整轮
  汇总徽标（见 ``ElaChatWidget.setStatsMode``）；
- ``error(type, message)`` / ``emptyTurn(reason)``：错误与空正文诊断；
- ``finish(turn, status)``：回合结束（补整轮耗时、结束消息、返回摘要）。

**回合边界**：``beginTurn`` 之前 / ``finish`` 之后到达的分片、工具、用量与错误事件
一律忽略（迟到事件不会写进当前消息，也不会污染下一轮）。

**回合 token**：``startTurn`` 返回后端的回合 token（``worker.ask`` 给出），
``finish`` **必须**带上同一个 token —— 迟到的 ``turnFinished`` 会被直接丢弃，
不会把新回合按「完成」掐掉（后端 ``cancel()`` 是异步的，旧回合的收尾信号
可能晚几十毫秒到达，那时新回合往往已经开起来了）。认不出的信号
``finish`` 返回 ``None``，宿主据此跳过状态更新。

用法::

    binder = ElaChatStreamBinder(chat, worker=worker)   # 自动接机械信号

    worker.ready.connect(on_ready)             # 以下 4 条 UI 决策归宿主
    worker.failed.connect(on_failed)
    worker.errorOccurred.connect(on_error)
    worker.turnFinished.connect(binder.finish) # token 原样带回，无需转发

    turn = binder.startTurn("你好")
    summary = binder.finish(turn)
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

    Qt 回调里未捕获的异常直接 0xC0000409 静默终止；PyQt6 的信号槽异常**不会**
    传回 ``emit()`` 调用方，所以唯一有效防线是在**连接时**就把槽包起来。
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
    :param worker: 可选后端（信号契约与
        :class:`~pyqt6_ela_pro.chat.mock.ElaChatMockBackend` 同构）；
        传入时自动接线（见 :meth:`connectWorker`），并可调用
        :meth:`startTurn`
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
        # 回合是否已开。**计时值一律不兼作状态布尔** —— ``clock`` 可注入，任何
        # 可能返回 0.0 的时钟（相对时钟的起点、测试用的假时钟）会让「有没有开过
        # 回合」「这一轮有没有开始计时」双双判错。计时用 Optional[float] 表示，
        # ``None`` = 尚未设置。见 :meth:`isOpen`。
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

        自动连接 6 条机械信号（``llmStarted`` / ``chunkReceived`` / ``toolStarted`` /
        ``toolEnded`` / ``statsReady`` / ``emptyTurn``）；涉及 UI 决策的 ``ready`` /
        ``failed`` / ``errorOccurred`` / ``turnFinished`` 仍由宿主自行连接。

        幂等：重复绑定同一个后端直接返回；换绑其他后端时先解绑旧的。
        """
        if worker is self._worker:
            return
        self._disconnectWorker()
        self._worker = worker
        # 机械信号槽**先包守卫再连接**：后端数据是外部输入（usage 里的 inf、
        # 半截 tool_call…），槽内未捕获异常穿过 C++ 边界 = 0xC0000409。
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
        :param timeoutMs: 传给 :meth:`shutdownWorker`；缺省**不阻塞**（关窗不该冻结
            界面，超时升级由 worker 自己的看门狗在后台完成）。

        显式调用（不做隐式自动）：多窗口 / 跨窗口复用同一后端的宿主不需要调用本
        方法。后端没有 ``shutdown`` 方法时忽略。
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

        :param timeoutMs: ``None`` = **不阻塞**，只发关闭请求并立即返回（超时升级交给
            worker 自己的看门狗）。给正数则阻塞等到线程确实退出（紧接着销毁宿主窗口
            时才需要）。
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

        与 :meth:`finish` 对称（回合生命周期都在 binder 内闭环）。后端需保证
        ``ask`` / ``regenerate`` 返回后才开始发信号（``ElaChatMockBackend``
        与 :class:`~pyqt6_ela_pro.chat.worker.ElaChatAsyncWorker` 均满足）。

        :param prompt: 提问文本
        :param regenerate: ``True`` 时走 ``worker.regenerate``（历史回滚由
            后端负责）
        :param attachments: 随消息发送的附件（``ElaChatAttachment`` 或等价
            dict 的列表）。**重新生成必须把它带上** —— ``regenerateFrom``
            返回的提问快照里带着附件，丢掉就等于模型看不见用户上传的文件；
            宿主通常直接把 ``message.attachments`` 传进来
        :returns: **回合 token**（后端 ``ask`` / ``regenerate`` 的返回值）；
            ``None`` 表示后端未受理 —— 此时不创建空的助手消息，错误文案仍由宿主展示
        """
        if self._worker is None:
            return None
        method = self._worker.regenerate if regenerate else self._worker.ask
        turn = method(prompt or "", list(attachments or ()))
        if turn is None:
            return None
        # 记住消息 id：widget 的转发层已删除，消息内容操作全在 view 层且每个方法
        # 都要求显式传 messageId，所以 binder 必须自己攥着这个 id。
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

        ``turn`` 是后端的回合 token（:meth:`startTurn` 内部就是这么调的）；
        宿主自己 ``ask`` 后不走 ``startTurn`` 时，把后端返回值传进来即可。
        两者都不传（纯手动回合、没有后端）时本地自增一个，返回值同样要交给
        :meth:`finish`。
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
            # 宿主可能自己建好消息再调 beginTurn()（不经 startTurn），接上当前
            # 流式消息。view 层不再有「省略即当前流式」的默认，id 必须由调用链带着。
            self._message_id = self._chat.streamingMessageId()
        self._clear_retry()
        self._set_activity("正在思考…", "thinking")
        return turn

    def beginRound(self) -> None:
        """开始一轮 LLM 调用（第 2 轮起自动开启新步骤）。

        回合外（``beginTurn`` 前 / ``finish`` 后）的迟到事件一律忽略。

        **这里是 steer（插话）的投递点** —— ``beginStep`` 之前是「上一步的
        工具都跑完了」这个安全边界，正好对应 opencode 的
        ``SessionInbox.nextPromotable`` 位置（``runner/llm.ts:83``）：用户
        在生成中说的话在这一刻送进后端，而不是等整轮跑完。一次只投一条。
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
        """是否处于回合中（``beginTurn`` 之后、``finish`` 之前）**且有目标消息**。

        「有目标消息」这个条件来自 view 层：消息操作都要求显式传 ``messageId``，
        没有落点的回合视为未开启 —— 所有以本方法为闸门的写入点自然全部跳过。

        判据是显式的 ``_turn_open`` 标志，**不是** ``_turn_start != 0.0``：那个
        写法把计时值兼作状态布尔，而 ``clock`` 可注入，返回 0.0 的假时钟会让整回合
        被静默丢弃。
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

        **纯空白分片不算正文**：不置 ``_had_text``（空回答诊断据此判断）、不结束
        思考段，也不该在时间线上开出一个空正文段 —— 开段与否由气泡按「首个非
        空白分片」决定（见 ``ElaChatBubble.appendText``）。空白本身不丢：中段的
        ``"hello" + " " + "world"`` 照常保留。
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
                # dict 里可能有非有限浮点等不可序列化值：退化成原文，不能让
                # 一次畸形参数把整条工具调用丢掉（或在 Qt 槽里炸掉进程）。
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
        # ``{}`` 或缺字段仍按 "unknown" 兜底（旧行为，测试钉着）；但 function
        # 是字符串这类畸形结构不能再 .get 打崩，也不能造出一张假工具卡。
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

        回合外（``beginTurn`` 前 / ``finish`` 后）忽略，避免迟到用量
        改写已结束消息的整轮汇总。
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

        ``errorType`` **原样传给 view**，不格式化成 ``"[Type] msg"`` 拼进文案 ——
        错误卡要靠它判断该不该点亮「重试」，宿主也要拿它做结构化埋点。类型信息一旦
        拼进自然语言就再也取不回来了。
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
        下一次 :meth:`beginTurn` / :meth:`startTurn` 会清除该标记。
        """
        self._cancelled = True
        self._endReasoning()

    def finish(self, turn, status: Optional[str] = None) -> Optional[ElaChatTurnSummary]:
        """结束回合：补整轮耗时、结束消息，返回摘要。

        :param turn: 回合 token（:meth:`startTurn` / :meth:`beginTurn` 的返回值）。
            **与当前回合不符说明这是迟到信号**（后端 ``cancel()`` 异步收尾，旧
            回合的 ``turnFinished`` 可能在新回合开起来之后才到），直接丢弃并返回
            ``None`` —— 收掉新回合会让它的分片全被 ``isOpen()`` 丢弃，产出
            「空回答」。
        :param status: 最终状态；缺省时按是否调用过 :meth:`cancel` 自动取
            ``Stopped`` / ``Done``（显式传入优先）
        :returns: 本回合摘要；``turn`` 陈旧时为 ``None``（宿主据此跳过状态更新）

        幂等：若消息已被 ``stopGeneration`` 结束（未处于生成中），
        只补耗时不再重复结束。
        """
        if turn != self._turn_token:
            logger.warning(
                "丢弃迟到的回合收尾：token=%r，当前回合 token=%r",
                turn,
                self._turn_token,
            )
            return None
        if status is None:
            status = ElaChatStatusType.Stopped if self._cancelled else ElaChatStatusType.Done
        self._endReasoning()
        self._clear_activity()
        self._clear_retry()
        target = self._target()
        durationMs = 0.0
        if self._turn_open and self._turn_start is not None:
            durationMs = (self._clock() - self._turn_start) * 1000.0
        # **先清本回合的状态，再触发宿主回调**：``endAssistantMessage`` 会同步
        # 续发排队消息（``autoSendQueue``）→ 宿主的 ``messageSubmitted`` 槽里可能
        # 立刻 ``startTurn()`` 开新回合。若等回调返回后再清 ``_message_id``，抹掉的
        # 就是**新回合**的落点（所有分片被 ``isOpen()`` 丢弃、产出空回答，且下一次
        # ``finish()`` 因 ``_target() is None`` 抛 ``TypeError``）。
        self._turn_open = False
        self._turn_start = None
        self._turn_token = None
        self._message_id = None
        if durationMs and target is not None:
            self._chat.chatView().setMessageDuration(target, durationMs)
        # 不能只在 isGenerating() 时收尾：setMessageError / removeMessage /
        # undoMessage / regenerateFrom / 二次 stop 都已把 _generating 置 False，
        # 那样会跳过 endAssistantMessage —— generationFinished 不发，
        # autoSendQueue 也永远排不空。
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

        = ``cancel()`` + ``finish(turn, Stopped)``（+ 默认 ``worker.cancel()``）：用于
        **不打算保留这一轮**的场景 —— 删除 / 关闭话题、销毁页面。收尾后
        ``isOpen()`` 为 False 且目标 id 被清空，之后到达的分片 / 工具结果无处可落。

        与 :meth:`cancel` / :meth:`finish` 的两条差异：

        - **默认把后端也停掉**：作废了这一轮，让后端继续流下去只会白烧 token；
        - **不续发排队消息**：临时关掉 ``autoSendQueue`` 再还原。

        顺序是「先收尾再停后端」：部分后端（如 ``ElaChatMockBackend``）``cancel()``
        会同步发 ``turnFinished``，宿主常接 ``binder.finish`` —— 先收尾能保证那次
        重入是幂等空操作。

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
