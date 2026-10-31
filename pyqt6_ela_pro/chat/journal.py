"""聊天回合的崩溃恢复日志：把一个回合记成追加写事件流，可重放回完整消息。

流式在途分片只存在于气泡缓冲里，回合中途进程死掉会全丢；这里按增量落行，
崩了最多丢最后一行。纯数据 + 标准库，不依赖 Qt，可在任意线程构造与重放。
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Callable, Optional

from . import _json
from ._usage import stats_from_usage
from .message import (
    ElaChatAttachment,
    ElaChatMessage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
)

#: 日志行格式版本（与消息的 ``SCHEMA_VERSION`` 独立演进）
JOURNAL_VERSION = 1


class _Ev:
    """事件类型常量（单字符短名，写进日志省字节）。"""

    Begin = "b"
    Step = "s"
    Text = "t"
    TextEnd = "te"
    Reasoning = "r"
    ReasoningEnd = "re"
    ToolStart = "ts"
    ToolEnd = "tw"
    Stats = "st"
    Duration = "d"
    Meta = "m"
    Attach = "a"
    Compaction = "cp"
    CompactionText = "ct"
    CompactionEnd = "ce"
    End = "e"


class ElaChatTurnJournal:
    """把一个回合记录成追加写事件流，可重放回完整消息（崩溃恢复用）。

    与消息快照的分工：快照是回合结束后的完整状态，本日志是回合进行中的增量流。
    两者都产出 :class:`ElaChatMessage`，读取端无需知道日志存在。
    """

    def __init__(
        self,
        messageId: int = 0,
        role: str = ElaChatRoleType.Assistant,
        title: str = "",
        timestamp: str = "",
        createdAt: float = 0.0,
        *,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._message_id = _int(messageId, 0)
        self._role = role if role in ElaChatRoleType.All else ElaChatRoleType.Assistant
        self._title = title or ""
        self._timestamp = timestamp or ""
        self._created_at = _float(createdAt, 0.0)
        self._clock = clock or time.time
        self._events: list = []
        #: 已经通过 :meth:`dumpsNewLines` 落盘的事件数（``dumps()`` 不用它）
        self._dumped = 0
        #: 已 connectWorker 的后端（幂等守卫 / 换绑时先解旧的）
        self._worker = None
        #: 四个基础信号槽的绑定方法缓存（连 / 断必须同一批对象）
        self._worker_slots = None
        #: 已连接的 ``(signal, slot)`` 列表（连 / 断必须同一批绑定方法）。
        self._worker_connections: Optional[list] = None

        # -- 重放状态（从事件构建 parts） --
        self._parts: list = []
        #: 未落定分段的增量缓冲 ``{partId: [chunk, ...]}``（见 ``_flushBuffer``）
        self._buffers: dict = {}
        self._step = 1
        self._status = ElaChatStatusType.Streaming
        self._error = ""
        self._duration_ms = 0.0
        self._attachments: list = []
        self._ended = False

        # -- 记录状态 --
        self._open = False
        self._rec_text: Optional[str] = None
        self._rec_reasoning: Optional[str] = None
        self._rec_compaction: Optional[str] = None
        self._rec_stats = 0
        self._seq = 0
        #: 当前步骤的 stats part id（同一 step 重复上报要覆盖而不是追加）
        self._stats_ids: dict = {}
        #: 尚未开正文段的纯空白分片（与气泡 ``_pending_text_lead`` 同语义）
        self._pending_text_lead: list = []
        #: 回合 / 本轮开始时间（秒）；用于 reasoning 与 stats 的时长
        self._turn_start = 0.0
        self._round_start = 0.0
        #: 已收到的 ``llmStarted`` 次数（第 1 轮不切步，镜像 binder）
        self._llm_round = 0
        #: 当前思考段开始时间（秒）
        self._reasoning_start = 0.0

    def _reset_state(self) -> None:
        """复位累计状态（复用同一实例开始新回合时调用）。"""
        self._events = []
        self._parts = []
        self._step = 1
        self._status = ElaChatStatusType.Streaming
        self._error = ""
        self._duration_ms = 0.0
        self._attachments = []
        self._ended = False
        self._open = False
        self._rec_text = None
        self._rec_reasoning = None
        self._rec_compaction = None
        self._rec_stats = 0
        self._seq = 0
        self._stats_ids = {}
        self._pending_text_lead = []
        self._turn_start = 0.0
        self._round_start = 0.0
        self._llm_round = 0
        self._reasoning_start = 0.0

    # ------------------------------------------------------------------ 记录

    def begin(self, messageId: Optional[int] = None) -> "ElaChatTurnJournal":
        """开始记录一个回合（``messageId`` 省略则沿用构造时的值）。

        复用同一实例记录第二个回合时先复位累计状态，否则内容会拼进上一回合。
        """
        if self._events:
            self._reset_state()
        if messageId is not None:
            self._message_id = _int(messageId, self._message_id)
        self._open = True
        self._turn_start = self._clock()
        self._round_start = self._turn_start
        self._llm_round = 0
        self._push(
            _Ev.Begin,
            id=self._message_id,
            role=self._role,
            title=self._title,
            timestamp=self._timestamp,
            at=self._created_at,
        )
        return self

    def setTitle(self, title: str) -> "ElaChatTurnJournal":
        """设置消息显示名。"""
        self._title = title or ""
        self._push(_Ev.Meta, title=self._title)
        return self

    def setTimestamp(self, timestamp: str) -> "ElaChatTurnJournal":
        """设置显示时间文本。"""
        self._timestamp = timestamp or ""
        self._push(_Ev.Meta, timestamp=self._timestamp)
        return self

    def setCreatedAt(self, createdAt: float) -> "ElaChatTurnJournal":
        """设置创建时间（``time.time()`` 秒）。"""
        self._created_at = _float(createdAt, 0.0)
        self._push(_Ev.Meta, at=self._created_at)
        return self

    def setAttachments(self, attachments) -> "ElaChatTurnJournal":
        """记录附件（用户消息用）。"""
        for item in attachments or ():
            self._push(_Ev.Attach, data=item.toDict())
        return self

    def beginStep(self) -> "ElaChatTurnJournal":
        """进入下一步骤。

        先收口当前正文段与思考段，再推进步骤。使用 :meth:`connectWorker` 时
        步骤跟随 ``llmStarted`` 自动推进，宿主不要再手动调用（会多切一步）。
        """
        if not self._open:
            return self
        if self._rec_reasoning is not None:
            self.endReasoning()
        self.endText()
        self._push(_Ev.Step)
        self._round_start = self._clock()
        return self

    def text(self, chunk: str) -> "ElaChatTurnJournal":
        """记录一段正文增量（自动开段）。

        纯空白分片在还没有正文段时先攒着，等首个非空白分片一起开段（中间空白照常保留）。
        """
        if not self._open or not chunk:
            return self
        if self._rec_text is None:
            if not chunk.strip():
                self._pending_text_lead.append(chunk)
                return self
            lead = "".join(self._pending_text_lead)
            self._pending_text_lead.clear()
            chunk = lead + chunk
            self._rec_text = self._mint()
            self._push(_Ev.Text, id=self._rec_text, step=self._step, text=chunk)
        else:
            self._push(_Ev.Text, id=self._rec_text, text=chunk)
        return self

    def endText(self) -> "ElaChatTurnJournal":
        """结束当前正文段（未开段的纯空白分片一并丢弃）。"""
        if not self._open:
            return self
        self._pending_text_lead.clear()
        if self._rec_text is not None:
            self._push(_Ev.TextEnd, id=self._rec_text)
            self._rec_text = None
        return self

    def reasoning(self, chunk: str) -> "ElaChatTurnJournal":
        """记录一段思考增量（自动开段）。"""
        if not self._open or not chunk:
            return self
        if self._rec_reasoning is None:
            self._rec_reasoning = self._mint()
            self._reasoning_start = self._clock()
            self._push(
                _Ev.Reasoning, id=self._rec_reasoning, step=self._step, text=chunk
            )
        else:
            self._push(_Ev.Reasoning, id=self._rec_reasoning, text=chunk)
        return self

    def endReasoning(self, durationMs: Optional[float] = None) -> "ElaChatTurnJournal":
        """结束当前思考段（``durationMs`` 省略时按开段以来的实际耗时）。"""
        if not self._open:
            return self
        if durationMs is None:
            elapsed = (
                max(0.0, (self._clock() - self._reasoning_start) * 1000.0)
                if self._reasoning_start
                else 0.0
            )
        else:
            elapsed = _float(durationMs, 0.0)
        self._push(_Ev.ReasoningEnd, id=self._rec_reasoning or "", ms=elapsed)
        self._rec_reasoning = None
        self._reasoning_start = 0.0
        return self

    def toolStart(self, callId: str, name: str, arguments="") -> "ElaChatTurnJournal":
        """记录工具调用开始（``arguments`` 支持 dict / JSON 字符串）。"""
        if not self._open:
            return self
        if not isinstance(arguments, str):
            try:
                arguments = _json.dumps(arguments)
            except (TypeError, ValueError):
                arguments = str(arguments)
        self._push(
            _Ev.ToolStart,
            id=callId or self._mint(),
            name=name or "",
            args=arguments or "",
            step=self._step,
        )
        return self

    def toolEnd(
        self, callId: str, result: str = "", ok: bool = True
    ) -> "ElaChatTurnJournal":
        """记录工具调用结束。"""
        if not self._open:
            return self
        self._push(_Ev.ToolEnd, id=callId or "", result=result or "", ok=bool(ok))
        return self

    def stats(self, stats: Optional[ElaChatStats]) -> "ElaChatTurnJournal":
        """记录当前步骤用量。

        同一 step 重复上报复用同一 part id（重放侧按 id 覆盖），跨 step 各自保留。
        """
        if not self._open or stats is None:
            return self
        partId = self._stats_ids.get(self._step)
        if partId is None:
            partId = "st%d" % self._rec_stats
            self._rec_stats += 1
            self._stats_ids[self._step] = partId
        self._push(
            _Ev.Stats,
            id=partId,
            n=self._rec_stats,
            step=self._step,
            data=stats.toDict(),
        )
        return self

    def setDuration(self, durationMs: float) -> "ElaChatTurnJournal":
        """记录本轮端到端耗时（毫秒）。"""
        if not self._open:
            return self
        self._push(_Ev.Duration, ms=_float(durationMs, 0.0))
        return self

    # -- 上下文压缩 ---------------------------------------------------------

    def beginCompaction(self, reason: str = "auto") -> "ElaChatTurnJournal":
        """记录一次压缩开始（段 id 内部生成，调用方不用管）。

        日志只记「发生过压缩」，摘要怎么来、压哪段都归宿主；段 id 与 :meth:`text` 同样内部记账。
        """
        if not self._open:
            return self
        self._rec_compaction = self._mint()
        self._push(
            _Ev.Compaction,
            id=self._rec_compaction,
            reason=_str(reason),
            step=self._step,
        )
        return self

    def compactionSummary(self, chunk: str) -> "ElaChatTurnJournal":
        """追加压缩摘要（流式；需先 :meth:`beginCompaction`）。"""
        if not self._open or not chunk or self._rec_compaction is None:
            return self
        self._push(_Ev.CompactionText, id=self._rec_compaction, text=chunk)
        return self

    def endCompaction(
        self,
        status: str = ElaChatStatusType.Done,
        historyCount: int = 0,
    ) -> "ElaChatTurnJournal":
        """记录压缩结束并落定摘要。"""
        if not self._open or self._rec_compaction is None:
            return self
        self._push(
            _Ev.CompactionEnd,
            id=self._rec_compaction,
            status=status,
            count=_int(historyCount),
        )
        self._rec_compaction = None
        return self

    def end(
        self, status: str = ElaChatStatusType.Done, error: str = ""
    ) -> "ElaChatTurnJournal":
        """结束记录（``status`` 见 :class:`ElaChatStatusType`）。

        先收口仍打开的正文 / 思考段；没有显式 :meth:`setDuration` 时按
        ``begin → end`` 的墙钟补一次消息级耗时。
        """
        if not self._open:
            return self
        if self._rec_reasoning is not None:
            self.endReasoning()
        self.endText()
        if not self._duration_ms and self._turn_start:
            self.setDuration(max(0.0, (self._clock() - self._turn_start) * 1000.0))
        self._push(_Ev.End, status=status, error=error or "")
        self._open = False
        return self

    def _mint(self) -> str:
        self._seq += 1
        return "j%d" % self._seq

    def _push(self, kind: str, **fields) -> None:
        """记一条事件，**并同步应用到自己的重放状态**。

        记录与重放走同一条路径，所以正在记录的 journal 本身就可直接读
        ``message()``。浮点在记录端就洗干净：``dumps()`` 用 ``allow_nan=False``。
        """
        event = {"v": JOURNAL_VERSION, "e": kind}
        for name, value in fields.items():
            event[name] = _float(value) if isinstance(value, float) else value
        self._events.append(event)
        self._apply(event)

    # ------------------------------------------------------------------ 导出

    def events(self) -> list:
        """全部事件（元素是普通 dict 的浅拷贝，可直接 JSON 化）。"""
        return [dict(item) for item in self._events]

    def dumps(self) -> str:
        """把整份事件流序列化成「一行一条事件」的文本。

        返回**全部**事件；追加落盘请用 :meth:`dumpsNewLines`（原样 append
        整份会在每次调用时重复写入历史，恢复时事件被重放多次）。
        """
        return "\n".join(_json.dumps(item, allow_nan=False) for item in self._events)

    def dumpsNewLines(self) -> str:  # noqa: N802 (与 Qt 命名一致)
        """只序列化**尚未被取走**的新事件（一行一条），追加写的入口。"""
        lines = [
            _json.dumps(item, allow_nan=False) for item in self._events[self._dumped :]
        ]
        self._dumped = len(self._events)
        return "\n".join(lines)

    def isOpen(self) -> bool:
        """是否仍在记录中（未 ``end()``）。"""
        return self._open

    @staticmethod
    def loadsLine(line: str) -> Optional[dict]:
        """解析日志的一行；截断 / 非法 / 非事件返回 ``None``（不抛）。

        进程可能在写一半时被杀，一行坏数据必须能安全地变成「什么都没有」。
        """
        if not line or not isinstance(line, str):
            return None
        try:
            data = _json.loads(line)
        except (ValueError, TypeError):
            return None
        # 只认「事件名是字符串」的行：``{"e": [1,2]}`` 也是合法 JSON，会让 _apply 抛 unhashable。
        if not isinstance(data, dict) or not isinstance(data.get("e"), str):
            return None
        return data

    @classmethod
    def fromEvents(cls, events) -> "ElaChatTurnJournal":
        """由事件序列**忠实重放**（不结算未结束的分段）。"""
        journal = cls()
        journal.replay(events)
        return journal

    @classmethod
    def fromLines(cls, lines, settleOpen: bool = True) -> "ElaChatTurnJournal":
        """由日志文本重放，跳过残行与未知事件。

        每个元素可以是一行，也可以是含多行的整段文本（``fromLines([fh.read()])``）。
        ``settleOpen`` 默认 True：日志必然来自已不存在的进程，在途分段要在这里
        落定，否则恢复出来的界面会留永久转圈。
        """
        events = []
        if isinstance(lines, str):
            # 裸字符串（``fromLines(fh.read())``）当成一整段文本，而不是
            # 逐字符迭代 —— 那会静默产出空日志，问题极难发现。
            lines = [lines]
        for line in lines or ():
            if isinstance(line, dict):
                events.append(line)
                continue
            if not isinstance(line, str):
                continue
            for piece in line.splitlines():
                item = cls.loadsLine(piece)
                if item is not None:
                    events.append(item)
        journal = cls()
        journal.replay(events)
        if settleOpen and not journal._ended:
            journal._settle(ElaChatStatusType.Stopped)
        return journal

    # ------------------------------------------------------------------ 重放

    def replay(self, events) -> "ElaChatTurnJournal":
        """把事件序列应用到本对象（增量重放，可多次调用）。

        不要对正在记录的 journal 调这个 —— 记录路径已自动应用，再喂一遍会重复叠加。
        """
        for item in events or ():
            if not isinstance(item, dict):
                continue
            self._apply(item)
        return self

    def message(self) -> ElaChatMessage:
        """重放出当前这一刻的完整消息快照。

        回合中途调用得到的是已收到的部分；崩了重启后拿它恢复，不会丢在途内容。
        """
        self._flushBuffers()
        base = ElaChatMessage(
            id=self._message_id,
            role=self._role,
            status=self._status,
            created_at=self._created_at,
            title=self._title,
            timestamp=self._timestamp,
            duration_ms=self._duration_ms,
            attachments=tuple(self._attachments),
            error=self._error,
        )
        if self._parts:
            return base.withParts(tuple(self._parts))
        return base

    def replayInto(self, view, messageId: Optional[int] = None) -> int:
        """把日志重放出的消息装进 ``view``（:class:`ElaChatView`），返回消息 id。

        等价于 ``view.addMessageFromDict(self.message().toDict(), messageId)``，
        只是省掉一次序列化往返。
        """
        if messageId is None:
            messageId = self._message_id or None
        return view.addMessageFromDict(self.message().toDict(), messageId=messageId)

    # -- 事件分发 ----------------------------------------------------------

    def _apply(self, event: dict) -> None:
        """把一个事件应用到重放状态（未知类型静默跳过）。"""
        try:
            kind = event.get("e")
            if not isinstance(kind, str):
                return
            handler = _HANDLERS.get(kind)
            if handler is None:
                return  # 旧版本读到新事件类型：跳过而不是崩
            handler(self, event)
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            pass  # 单条坏事件不该毁掉整条恢复链路
            # OverflowError 也在列：int(float('inf')) 抛的是它，且不是上面任何一个的子类

    def _ev_begin(self, event: dict) -> None:
        self._message_id = _int(event.get("id"), self._message_id)
        role = event.get("role")
        if role in ElaChatRoleType.All:
            self._role = role
        self._title = _str(event.get("title"), self._title)
        self._timestamp = _str(event.get("timestamp"), self._timestamp)
        self._created_at = _float(event.get("at"), self._created_at)

    def _ev_meta(self, event: dict) -> None:
        self._title = _str(event.get("title"), self._title)
        self._timestamp = _str(event.get("timestamp"), self._timestamp)
        self._created_at = _float(event.get("at"), self._created_at)

    def _ev_attach(self, event: dict) -> None:
        data = event.get("data")
        if isinstance(data, dict):
            self._attachments.append(ElaChatAttachment.fromDict(data))

    def _ev_step(self, _event: dict) -> None:
        self._step += 1

    def _ev_text(self, event: dict) -> None:
        partId = _str(event.get("id"))
        chunk = _str(event.get("text"))
        if not partId or not chunk:
            return
        step = _int(event.get("step"), self._step)
        existing = self._find(partId)
        if existing is None:
            self._append(
                ElaChatPart(
                    id=partId,
                    kind=ElaChatPartKindType.Text,
                    text=chunk,
                    status=self._openStatus(),
                    step=step,
                )
            )
        else:
            # 走分片缓冲而不是整串拼接：逐分片拼接是 O(n²)，长回答会产生大量临时大字符串。
            self._buffers.setdefault(partId, []).append(chunk)

    def _ev_text_end(self, event: dict) -> None:
        partId = _str(event.get("id"))
        self._flushBuffer(partId)
        part = self._find(partId)
        if part is not None:
            self._replace(part, part.withStatus(ElaChatStatusType.Done))

    def _ev_reasoning(self, event: dict) -> None:
        partId = _str(event.get("id"))
        chunk = _str(event.get("text"))
        if not partId or not chunk:
            return
        step = _int(event.get("step"), self._step)
        existing = self._find(partId)
        if existing is None:
            self._append(
                ElaChatPart(
                    id=partId,
                    kind=ElaChatPartKindType.Reasoning,
                    text=chunk,
                    status=self._openStatus(),
                    step=step,
                )
            )
        else:
            self._buffers.setdefault(partId, []).append(chunk)

    def _ev_reasoning_end(self, event: dict) -> None:
        partId = _str(event.get("id"))
        self._flushBuffer(partId)
        part = self._find(partId)
        if part is not None:
            self._replace(
                part,
                part.withStatus(ElaChatStatusType.Done).withDuration(
                    _float(event.get("ms"), 0.0)
                ),
            )

    # -- 分片缓冲（避免逐分片整串拼接） ------------------------------------

    def _flushBuffer(self, partId: str) -> None:  # noqa: N802 (与 Qt 命名一致)
        """把某个分段的缓冲并回 ``part.text``。"""
        chunks = self._buffers.pop(partId, None)
        if not chunks:
            return
        part = self._find(partId)
        if part is not None:
            self._replace(part, part.withText((part.text or "") + "".join(chunks)))

    def _flushBuffers(self) -> None:  # noqa: N802 (与 Qt 命名一致)
        """把全部分段的缓冲并回（读快照前调一次）。"""
        for partId in list(self._buffers):
            self._flushBuffer(partId)

    def _ev_tool_start(self, event: dict) -> None:
        callId = _str(event.get("id"))
        if not callId:
            return
        call = ElaChatToolCall(
            id=callId,
            name=_str(event.get("name")),
            arguments=_str(event.get("args")),
            status=ElaChatToolStatusType.Running,
        )
        step = _int(event.get("step"), self._step)
        existing = self._find(callId)
        if existing is not None:
            self._replace(existing, existing.withToolCall(call))
            return
        self._append(
            ElaChatPart(
                id=callId,
                kind=ElaChatPartKindType.Tool,
                tool_call=call,
                status=self._openStatus(),
                step=step,
            )
        )

    def _ev_tool_end(self, event: dict) -> None:
        part = self._find(_str(event.get("id")))
        if part is None or part.tool_call is None:
            return
        ok = bool(event.get("ok", True))
        call = part.tool_call.withResult(
            _str(event.get("result")),
            ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error,
        )
        # part 状态保持 Done：工具跑完了，只是失败 —— 失败由 ``tool_call.status`` 承载。
        self._replace(part, part.withToolCall(call).withStatus(ElaChatStatusType.Done))

    def _ev_stats(self, event: dict) -> None:
        stats = ElaChatStats.fromDict(event.get("data"))
        if stats is None:
            return
        partId = _str(event.get("id"))
        if not partId:
            # 旧日志没有 id：按 n 生成，保持旧行为（无法判断同 step 重复上报）
            partId = "st%d" % _int(event.get("n"), 0)
        step = _int(event.get("step"), self._step)
        existing = self._find(partId)
        if existing is not None and existing.kind == ElaChatPartKindType.Stats:
            self._replace(existing, existing.withStats(stats))
            return
        self._append(
            ElaChatPart(
                id=partId,
                kind=ElaChatPartKindType.Stats,
                stats=stats,
                status=ElaChatStatusType.Done,
                step=step,
            )
        )

    def _ev_duration(self, event: dict) -> None:
        self._duration_ms = _float(event.get("ms"), 0.0)

    def _ev_compaction(self, event: dict) -> None:
        partId = _str(event.get("id"))
        if not partId:
            return
        self._append(
            ElaChatPart(
                id=partId,
                kind=ElaChatPartKindType.Compaction,
                status=self._openStatus(),
                step=_int(event.get("step"), self._step),
            )
        )

    def _ev_compaction_text(self, event: dict) -> None:
        part = self._find(_str(event.get("id")))
        chunk = _str(event.get("text"))
        if part is None or part.kind != ElaChatPartKindType.Compaction or not chunk:
            return
        self._buffers.setdefault(part.id, []).append(chunk)

    def _ev_compaction_end(self, event: dict) -> None:
        partId = _str(event.get("id"))
        # 先 flush 再取 part：反过来的话 withStatus 会把刚并进去的摘要文本覆盖掉。
        self._flushBuffer(partId)
        part = self._find(partId)
        if part is None or part.kind != ElaChatPartKindType.Compaction:
            return
        status = _str(event.get("status"), ElaChatStatusType.Done)
        if status not in ElaChatStatusType.All:
            status = ElaChatStatusType.Done
        self._replace(part, part.withStatus(status))

    def _ev_end(self, event: dict) -> None:
        status = _str(event.get("status"), ElaChatStatusType.Done)
        if status not in ElaChatStatusType.All:
            status = ElaChatStatusType.Done
        self._error = _str(event.get("error"))
        self._settle(status)
        self._ended = True

    # -- 结算 --------------------------------------------------------------

    def _openStatus(self) -> str:
        """新分段在「回合进行中」时的状态。"""
        return (
            ElaChatStatusType.Streaming
            if self._status == ElaChatStatusType.Streaming
            else ElaChatStatusType.Done
        )

    def _settle(self, status: str) -> None:
        """把仍处于 streaming 的分段落到终态（绝不留永久转圈）。

        出错回合落 ``Error``，其余（被停止 / 进程崩了）落 ``Aborted``。
        """
        if status in ElaChatStatusType.All:
            self._status = status
        self._flushBuffers()
        settled = []
        for part in self._parts:
            if part.status != ElaChatStatusType.Streaming:
                settled.append(part)
                continue
            if part.kind == ElaChatPartKindType.Tool and part.tool_call is not None:
                if part.tool_call.status in ElaChatToolStatusType.Settled:
                    settled.append(part.withStatus(ElaChatStatusType.Done))
                    continue
                failed = (
                    self._status == ElaChatStatusType.Error
                    or part.tool_call.status == ElaChatToolStatusType.Error
                )
                call = part.tool_call.withStatus(
                    ElaChatToolStatusType.Error
                    if failed
                    else ElaChatToolStatusType.Aborted
                )
                settled.append(
                    part.withToolCall(call).withStatus(
                        ElaChatStatusType.Error if failed else ElaChatStatusType.Done
                    )
                )
                continue
            settled.append(part.withStatus(ElaChatStatusType.Done))
        self._parts = settled

    # -- 内部查找 ----------------------------------------------------------

    def _append(self, part: ElaChatPart) -> None:
        self._parts.append(part)

    def _find(self, partId: str) -> Optional[ElaChatPart]:
        if not partId:
            return None
        for part in self._parts:
            if part.id == partId:
                return part
        return None

    def _replace(self, part: ElaChatPart, newPart: ElaChatPart) -> None:
        for index, item in enumerate(self._parts):
            if item.id == part.id:
                self._parts[index] = newPart
                return

    # -------------------------------------------------- 与 worker 信号对接

    def connectWorker(self, worker) -> "ElaChatTurnJournal":
        """连上 :class:`~pyqt6_ela_pro.chat.worker.ElaChatAsyncWorker` 的信号。

        与 binder 连同一批信号，两者可并存。后端提供 ``llmStarted`` 时自动跟随
        它切步（第 1 轮不切），此时宿主不要再手动调 :meth:`beginStep`。
        幂等：重复绑定同一后端直接返回；换绑其他后端先解旧的。
        """
        if worker is self._worker:
            return self
        if self._worker is not None:
            self.disconnectWorker(self._worker)
        self._worker = worker
        self._worker_connections = self._connections(worker)
        for signal, slot in self._worker_connections:
            signal.connect(slot)
        return self

    def _connections(self, worker) -> list:
        """当前 worker 的 ``(signal, slot)`` 连接表（连 / 断共用同一批对象）。"""
        chunk, toolStart, toolEnd, stats = self._bound_slots()
        pairs = [
            (worker.chunkReceived, chunk),
            (worker.toolStarted, toolStart),
            (worker.toolEnded, toolEnd),
            (worker.statsReady, stats),
        ]
        llmStarted = getattr(worker, "llmStarted", None)
        if llmStarted is not None:
            pairs.insert(0, (llmStarted, self._on_llm_started))
        return pairs

    def _bound_slots(self):
        """四个基础信号槽的绑定方法实例（连 / 断必须用同一批对象）。

        ``disconnect`` 要拿到同一个可调用对象：lambda / ``partial`` 断不掉。
        """
        if self._worker_slots is None:
            self._worker_slots = (
                self._on_chunk,
                self._on_tool_started,
                self._on_tool_ended,
                self._on_stats,
            )
        return self._worker_slots

    def disconnectWorker(self, worker) -> "ElaChatTurnJournal":
        """断开与 worker 的连接（幂等，可重复调用）。

        只断当前已连的那个后端；对没连过的 worker 调只会打 RuntimeWarning。
        """
        if worker is None or worker is not self._worker:
            return self
        connections = self._worker_connections or self._connections(worker)
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._worker_connections = None
        self._worker = None
        return self

    def _on_llm_started(self) -> None:
        """后端每次 LLM 调用开始：第 2 轮起切步（上一轮没有分段时不切）。"""
        if not self._open:
            return
        self._round_start = self._clock()
        self._llm_round += 1
        if self._llm_round <= 1:
            return
        if self._rec_reasoning is not None:
            self.endReasoning()
        if any(part.step == self._step for part in self._parts):
            self.beginStep()

    def _on_chunk(self, chunk) -> None:
        reasoning = getattr(chunk, "reasoning_content", "") or ""
        answer = getattr(chunk, "answer_content", "") or ""
        if reasoning:
            self.reasoning(reasoning)
        if answer:
            # 只有非空白正文才结束思考段；纯空白交给 text() 攒成 pending。
            if answer.strip() and self._rec_reasoning is not None:
                self.endReasoning()
            self.text(answer)

    def _on_tool_started(self, toolCall) -> None:
        if not isinstance(toolCall, dict):
            return
        # 缺 function 时按 "unknown" 兜底；畸形结构直接丢弃，不造出假工具卡。
        function = toolCall.get("function") or {}
        if not isinstance(function, dict):
            return
        self.toolStart(
            toolCall.get("id") or "",
            function.get("name") or "unknown",
            function.get("arguments", ""),
        )

    def _on_tool_ended(self, toolCall, result: str) -> None:
        if not isinstance(toolCall, dict):
            return
        text = str(result or "")
        self.toolEnd(toolCall.get("id") or "", text, ok=not text.startswith("Error:"))

    def _on_stats(self, usage, ttftMs: float = 0.0, tps: float = 0.0) -> None:
        if usage is None:
            return
        stats = stats_from_usage(usage, ttftMs, tps)
        duration = 0.0
        if self._round_start:
            duration = max(0.0, (self._clock() - self._round_start) * 1000.0)
        if duration and not stats.duration_ms:
            stats = replace(stats, duration_ms=duration)
        self.stats(stats)


# ------------------------------------------------------------------ 事件表

_HANDLERS = {
    _Ev.Begin: ElaChatTurnJournal._ev_begin,
    _Ev.Meta: ElaChatTurnJournal._ev_meta,
    _Ev.Attach: ElaChatTurnJournal._ev_attach,
    _Ev.Step: ElaChatTurnJournal._ev_step,
    _Ev.Text: ElaChatTurnJournal._ev_text,
    _Ev.TextEnd: ElaChatTurnJournal._ev_text_end,
    _Ev.Reasoning: ElaChatTurnJournal._ev_reasoning,
    _Ev.ReasoningEnd: ElaChatTurnJournal._ev_reasoning_end,
    _Ev.ToolStart: ElaChatTurnJournal._ev_tool_start,
    _Ev.ToolEnd: ElaChatTurnJournal._ev_tool_end,
    _Ev.Stats: ElaChatTurnJournal._ev_stats,
    _Ev.Duration: ElaChatTurnJournal._ev_duration,
    _Ev.Compaction: ElaChatTurnJournal._ev_compaction,
    _Ev.CompactionText: ElaChatTurnJournal._ev_compaction_text,
    _Ev.CompactionEnd: ElaChatTurnJournal._ev_compaction_end,
    _Ev.End: ElaChatTurnJournal._ev_end,
}


def _str(value, default: str = "") -> str:
    if value is None:
        return default
    return value if isinstance(value, str) else str(value)


def _int(value, default: int = 0) -> int:
    # OverflowError 必须一并捕获：int(float('inf')) 抛的是它，且它不是
    # TypeError / ValueError 的子类
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _float(value, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if out == out and out not in (float("inf"), float("-inf")) else default


__all__ = ["ElaChatTurnJournal", "JOURNAL_VERSION"]
