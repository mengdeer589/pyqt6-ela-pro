"""聊天组件模拟后端（``pyqt6_ela_pro.chat``）。

:class:`ElaChatMockBackend` 不需要任何真实模型服务，用 ``QTimer`` 在 GUI
线程按脚本逐步发出流式事件，信号与真实 worker（``llmStarted`` /
``chunkReceived`` / ``toolStarted`` / ``toolEnded`` / ``statsReady`` /
``turnFinished``）完全同构，可直接交给
:class:`~pyqt6_ela_pro.chat.binder.ElaChatStreamBinder` 映射到聊天组件。

典型用途：

- 组件测试（``tickMs=0`` 快进）；
- 示例页演示多步时间线（思考 → 上下文工具 → 步骤统计 → 失败工具 →
  正文 → 步骤统计）；
- 无后端用户快速体验聊天组件。

用法::

    mock = ElaChatMockBackend(tickMs=30, thinkLevel="normal")
    binder = ElaChatStreamBinder(chat)
    mock.llmStarted.connect(binder.beginRound)
    mock.chunkReceived.connect(lambda c: ...)   # reasoning / answer 分派
    ...
    turn = mock.ask("你好")                      # 返回回合 token
    # ... turnFinished.connect(binder.finish) 收尾时会原样带回该 token
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

#: 思考强度档位
THINK_LEVELS = ("off", "normal", "deep")
#: 默认每步事件间隔（毫秒）
_DEFAULT_TICK_MS = 40
#: 流式分片长度
_REASONING_CHUNK = 6
_ANSWER_CHUNK = 8


@dataclass
class ElaChatMockChunk:
    """模拟流式分片（字段与 ``AgentOutput`` 一致）。"""

    id: str = ""
    reasoning_content: str = ""
    answer_content: str = ""


class ElaChatMockUsage:
    """模拟 OpenAI ``CompletionUsage``（含缓存读 / 写与推理词元的常见形态）。"""

    def __init__(
        self,
        promptTokens: int = 128,
        completionTokens: int = 96,
        cachedTokens: int = 0,
        reasoningTokens: int = 0,
        cacheWriteTokens: int = 0,
    ) -> None:
        self.prompt_tokens = int(promptTokens)
        self.completion_tokens = int(completionTokens)
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        self.prompt_cache_hit_tokens = int(cachedTokens)
        #: 缓存写（Anthropic 命名；多数 OpenAI 兼容端点为 0）
        self.cache_creation_input_tokens = int(cacheWriteTokens)
        #: 推理词元（completion 的子集，单独拆分只为展示）
        self.reasoning_tokens = int(reasoningTokens)


def _default_reply(question: str) -> str:
    """默认模拟回答（覆盖标题 / 列表 / 行内代码 / 公式 / 代码块）。"""
    return (
        f"已收到：「{question[:40]}」。\n\n"
        "这是**模拟回答**，用于验证聊天组件的分段流式渲染：\n\n"
        "- 思考段 → 每步工具面板 → 正文段 → 步骤统计\n"
        "- 支持 `行内代码`、公式 $E=mc^2$ 与列表\n\n"
        "```python\nprint('hello')\n```\n"
    )


def _split(text: str, size: int) -> list:
    return [text[index : index + size] for index in range(0, len(text), size)]


class ElaChatMockBackend(QObject):
    """模拟聊天后端（事件源，不依赖线程与模型服务；``tickMs=0`` 测试快进）。

    ``thinkLevel`` 取 ``"off"`` / ``"normal"`` / ``"deep"``。
    """

    #: 后端就绪（构造后异步发出一次，与真实 worker 契约一致）
    ready = pyqtSignal()
    #: 后端失败（模拟后端不失败，保留信号契约）
    failed = pyqtSignal(str)
    #: 错误（模拟后端不发射，保留信号契约）
    errorOccurred = pyqtSignal(str, str)
    #: 空正文诊断（模拟后端不发射，保留信号契约）
    emptyTurn = pyqtSignal(str)
    #: 新一轮 LLM 调用开始（步骤边界）
    llmStarted = pyqtSignal()
    #: 流式分片（:class:`ElaChatMockChunk`）
    chunkReceived = pyqtSignal(object)
    #: 工具调用开始（tool_call dict）
    toolStarted = pyqtSignal(dict)
    #: 工具调用结束（tool_call dict、结果文本）
    toolEnded = pyqtSignal(dict, str)
    #: 单轮用量（usage、首字耗时 ms、词元/秒）
    statsReady = pyqtSignal(object, float, float)
    #: 本回合结束（成功 / 取消），载荷是 :meth:`ask` 返回的**回合 token**
    turnFinished = pyqtSignal(int)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        tickMs: int = _DEFAULT_TICK_MS,
        thinkLevel: str = "normal",
    ) -> None:
        super().__init__(parent)
        self._tick_ms = max(0, int(tickMs))
        self._think_level = thinkLevel if thinkLevel in THINK_LEVELS else "normal"
        self._reply_provider: Optional[Callable[[str], str]] = None
        self._events: list = []
        self._question = ""
        self._turn_attachments: list = []
        self._running = False
        #: 回合 token 自增源（与真实 worker 同构：token 是「这轮生杀」的凭据）
        self._turn_seq = 0
        self._current_turn = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._tick_ms)
        self._timer.timeout.connect(self._on_tick)
        # ready 用挂在 self 上的单次定时器异步发出：对象提前销毁时随父对象
        # 一起析构，避免 singleShot 回调解引用已删除的信号。
        self._ready_timer = QTimer(self)
        self._ready_timer.setSingleShot(True)
        self._ready_timer.setInterval(0)
        self._ready_timer.timeout.connect(self.ready.emit)
        self._ready_timer.start()

    # -- 配置 --------------------------------------------------------------

    def thinkLevel(self) -> str:
        """获取思考强度档位。"""
        return self._think_level

    def setThinkLevel(self, level: str) -> None:
        """设置思考强度档位（对后续回合生效）。"""
        self._think_level = level if level in THINK_LEVELS else "normal"

    def tickMs(self) -> int:
        """获取事件间隔（毫秒）。"""
        return self._tick_ms

    def setTickMs(self, tickMs: int) -> None:
        """设置事件间隔（毫秒，``0`` 表示测试快进）。"""
        self._tick_ms = max(0, int(tickMs))
        self._timer.setInterval(self._tick_ms)

    def setReplyProvider(self, provider: Optional[Callable[[str], str]]) -> None:
        """设置回答文本提供者 ``provider(question) -> str``（``None`` 用默认）。"""
        self._reply_provider = provider

    def isRunning(self) -> bool:
        """是否正在播放回合。"""
        return self._running

    # -- 命令接口（与真实 worker 同构） ------------------------------------

    def ask(self, text: str, attachments=None) -> Optional[int]:
        """开始一个模拟回合（已有回合在跑时先取消），返回**回合 token**。

        token 是这一轮的落定凭据：:attr:`turnFinished` 原样带回，宿主交给
        ``binder.finish(token)`` —— 收尾只认自己那一次 signal。真实 worker 的
        ``cancel()`` 是异步的（要等轮询命中，旧回合的 ``turnFinished`` 可能晚
        到几十毫秒），没有 token 时那个迟到的信号会把新回合直接收掉
        （分片全被 ``isOpen()`` 丢弃 → 用户看到「发出去了、正文全空」）。

        :returns: 回合 token；未受理（宿主已关门 / 取消的回调里另起了一回合）
            返回 ``None``。**不要再当 bool 用** —— 真值即代表已受理。
        """
        if self._running:
            self.cancel()
            if self._running:
                # ``cancel()`` 的 ``turnFinished`` 是同步发射的：监听者可能在
                # 回调里又起了一个新回合，外层不能再用原参数把它覆盖掉。
                return None
        self._turn_seq += 1
        token = self._turn_seq
        self._current_turn = token
        self._question = str(text or "")
        self._turn_attachments = list(attachments or ())
        self._events = self._build_events(self._question)
        self._running = True
        if not self._events:
            self._finish_turn()
            return token
        self._timer.start()
        return token

    def regenerate(self, text: str, attachments=None) -> Optional[int]:
        """重新生成（模拟后端等价于重新提问，附件照收）。返回回合 token。"""
        return self.ask(text, attachments)

    def turnAttachments(self) -> list:  # noqa: N802
        """当前回合随消息收下的附件快照（副本）。"""
        return list(self._turn_attachments)

    def reset(self) -> None:
        """重置模拟后端状态。"""
        self._events = []
        self._question = ""
        self._turn_attachments = []

    def cancel(self) -> None:
        """取消当前回合（停止推送并结束回合）。"""
        if not self._running:
            return
        self._finish_turn()

    def shutdown(self) -> None:
        """关闭后端（模拟后端与取消等价）。"""
        self.cancel()

    # -- 内部 --------------------------------------------------------------

    def _finish_turn(self) -> None:
        self._timer.stop()
        self._events = []
        was_running = self._running
        self._running = False
        if was_running:
            self.turnFinished.emit(self._current_turn)

    def _build_events(self, question: str) -> list:
        """按思考强度构造一个两步回合的事件列表。"""
        events: list = [("llm", None)]
        if self._think_level != "off":
            reasoning = (
                f"先理解问题「{question[:24]}」：确认目标、约束与呈现格式，"
                "准备读取示例文件核对信息。"
            )
            if self._think_level == "deep":
                reasoning += "再推演两种实现路径，比较复杂度后选择更稳妥的一种。"
            events.extend(
                ("reasoning", part) for part in _split(reasoning, _REASONING_CHUNK)
            )
        events.append(
            (
                "tool_start",
                {
                    "id": "mock-read",
                    "function": {
                        "name": "read",
                        "arguments": '{"path": "context.md"}',
                    },
                },
            )
        )
        events.append(("tool_end", ("mock-read", "已读取 context.md（4 KB）")))
        events.append(
            (
                "tool_start",
                {
                    "id": "mock-grep",
                    "function": {
                        "name": "grep",
                        "arguments": '{"pattern": "TODO"}',
                    },
                },
            )
        )
        events.append(("tool_end", ("mock-grep", "命中 3 处")))
        events.append(("stats", (128, 96, 320.0, 64)))
        events.append(("llm", None))
        if self._think_level == "deep":
            reasoning = "复核第一步的检索结果，确认引用无误后再组织最终答案。"
            events.extend(
                ("reasoning", part) for part in _split(reasoning, _REASONING_CHUNK)
            )
        events.append(
            (
                "tool_start",
                {
                    "id": "mock-patch",
                    "function": {
                        "name": "patch",
                        "arguments": '{"path": "draft.md"}',
                    },
                },
            )
        )
        events.append(("tool_end", ("mock-patch", "Error: 写入失败：文件被占用")))
        reply = (
            self._reply_provider(question)
            if self._reply_provider is not None
            else _default_reply(question)
        )
        events.extend(("answer", part) for part in _split(reply, _ANSWER_CHUNK))
        events.append(("stats", (256, 512, 280.0, 0)))
        return events

    def _on_tick(self) -> None:
        if not self._events:
            self._finish_turn()
            return
        kind, payload = self._events.pop(0)
        if kind == "llm":
            self.llmStarted.emit()
        elif kind == "reasoning":
            self.chunkReceived.emit(
                ElaChatMockChunk(id="mock-reasoning", reasoning_content=payload)
            )
        elif kind == "answer":
            self.chunkReceived.emit(
                ElaChatMockChunk(id="mock-answer", answer_content=payload)
            )
        elif kind == "tool_start":
            self.toolStarted.emit(dict(payload))
        elif kind == "tool_end":
            callId, result = payload
            self.toolEnded.emit(
                {
                    "id": callId,
                    "function": {"name": "mock", "arguments": ""},
                },
                result,
            )
        elif kind == "stats":
            prompt, completion, ttft, cached = payload
            self.statsReady.emit(
                ElaChatMockUsage(prompt, completion, cached),
                float(ttft),
                42.0,
            )
        if not self._events:
            self._finish_turn()
