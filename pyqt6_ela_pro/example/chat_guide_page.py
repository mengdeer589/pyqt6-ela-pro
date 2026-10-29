"""[pyqt6_ela_pro] 聊天组件指南（ElaChatWidget 怎么用）。

本页用 :class:`ElaMarkdownViewer` 渲染 Markdown 文档，讲解聊天组件接入：

1. 组件栈概览（含 worker 契约）；
2. 四步接入（``llm_test/main.py`` 全文）；
3. 关键 API 速查；
4. 真实后端（``llm_test/agent_demo.py`` 全文）；
5. 运行与依赖。

代码块是 ``llm_test`` 源码的**快照**：``tests/example/test_chat_guide_snapshot.py``
会校验与仓库实际文件一致；llm_test 改动后请同步更新本页常量。
"""

from __future__ import annotations

from pyqt6_ela_pro import ElaMarkdownViewer

from .base_page import ExamplePage

#: 快照：llm_test/main.py
LLM_TEST_MAIN_SOURCE = r'''"""llm_test 最小示例：ElaChatWidget + 假 / 真后端（默认无需模型服务）。

宿主接入就四步（见 ``DemoWindow``）：摆组件 → 选后端 → 接信号 → 宿主行为。

**错误与状态必须有可见反馈**（状态栏 + 错误卡 + 重试）。它们不属于「四步」，
但每一步都会用到：只把错误 ``print`` 进 stdout 的话，真实后端初始化失败时界面
全空，用户只会以为组件坏了。

运行::

    .\\.venv\\Scripts\\Activate.ps1
    python llm_test\\main.py                          # 默认 mock（QTimer 假后端）
    $env:LLM_TEST_BACKEND="agent"                     # 切真实 LLM（agents 副本）
    python llm_test\\main.py

真实后端复用 ``llm_test/agents/``（连接参数见 ``agent_demo.py``）。
"""

import os

os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts.warning=false"
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根目录

from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import eApp

from pyqt6_ela_pro.chat import (
    ElaChatAsyncWorker,
    ElaChatMockBackend,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatStatusBar,
    ElaChatStreamBinder,
    ElaChatWidget,
)

#: 后端错误归一表：``(规范类型, 命中关键词)``。
#:
#: ``ElaChatAsyncWorker`` 只发 ``("worker", "ExcName: 文案")``，而错误卡的
#: 「重试」只对 ``RETRYABLE_ERROR_TYPES``（限流 / 超时 / 网络 / 5xx）里的类型点亮
#: —— 不做这层归一，真实后端上**「重试」永远不会出现**；反过来鉴权 / 参数错误
#: 本来也不该给重试（换次机会只会再失败一次）。
#:
#: 两类来源都要认：
#:
#: - **抛异常的路径**：异常类名拼在文案最前（``APITimeoutError: …``）；
#: - **哨兵字符串的路径**：``llm_test/agents`` 不抛异常，把 API 错误编码成
#:   ``__ERROR__:<类型>:<文案>`` 上报（``llm_client.py``），类型是
#:   ``api_timeout`` / ``api_connection`` / ``api_rate_limit`` /
#:   ``api_server_error`` / ``api_auth`` / ``api_bad_request``。服务不可用走的
#:   就是这条，**不认它 = 错误不可重试**（用户看到的仍是错误卡，只是没有重试键）。
#:
#: 这是**宿主**该做的事：库把类型原样传下来，不替宿主猜。
_ERROR_TYPE_HINTS = (
    # 抛异常的路径（OpenAI SDK 异常类名）
    ("timeout", ("timeout", "timedout", "timed out")),
    ("ratelimit", ("ratelimit", "rate_limit", "rate limit")),
    ("network", ("connection", "network", "unreachable")),
    ("overloaded", ("overloaded", "serviceunavailable", "internalservererror")),
    # 哨兵路径（agents 的 api_* 前缀）
    ("timeout", ("api_timeout",)),
    ("ratelimit", ("api_rate_limit",)),
    ("network", ("api_connection",)),
    ("overloaded", ("api_server_error",)),
)


def classify_error(errorType, message):
    """把后端原始错误归一成错误卡认识的规范类型（决定「重试」是否点亮）。

    :param errorType: 后端给的类型（``ElaChatAsyncWorker`` 恒为 ``"worker"``）
    :param message: 错误文案（异常类名 / ``api_*`` 前缀通常在最前面）
    :returns: 命中的规范类型；没命中就原样返回 ``errorType``

    ``api_auth`` / ``api_bad_request`` / ``unknown`` **故意不归一**：密钥错了、
    参数错了重试只会再失败一次，不该给用户一个点了必然又失败的重试键。
    """
    text = f"{errorType} {message}".lower()
    for name, needles in _ERROR_TYPE_HINTS:
        if any(needle in text for needle in needles):
            return name
    return errorType or ""


class DemoWindow(QWidget):
    """聊天窗口：只依赖 worker 的信号契约，可换任意同构后端。"""

    def __init__(self, worker, parent=None, statusInfo=None):
        """:param statusInfo: 状态栏左侧信息（模型 / 服务地址）。
        缺省按 worker 类型自己给一句；真实后端传入具体值才有排查价值
        （连接失败时用户第一眼要确认的就是"连的哪个地址"）。"""
        super().__init__(parent)
        self.resize(920, 720)
        self.setWindowTitle("ElaChatWidget 最小示例")
        self.worker = worker
        #: 本回合是否出过错。最终态以这里 + ``binder.finish(turn)`` 摘要为准；
        #: ``generationFinished`` 现在一次回合只发一次（错误回合按 error 收尾），
        #: 也可直接用它驱动状态栏。
        self._turn_failed = False

        # ① 摆组件：ElaChatWidget（消息区 + 输入区都在组件内）
        layout = QVBoxLayout(self)
        self.chat = ElaChatWidget(self)
        self.chat.chatView().setEmptyTitle("发送一条消息试试")
        layout.addWidget(self.chat)
        # 状态栏是宿主的一部分：就绪 / 生成中 / 出错 / 完成的**唯一可见反馈**
        self.status = ElaChatStatusBar(self)
        self.status.setInfo(
            statusInfo
            or (
                f"mock 后端 · tick {worker.tickMs()} ms"
                if isinstance(worker, ElaChatMockBackend)
                else "真实后端（AgentWorker · llm_test/agents）"
            )
        )
        self.status.setStatus("正在启动后端…", level="busy")
        layout.addWidget(self.status)

        # ② 接后端：传 worker 即自动接机械信号；关窗自动收尾后端
        self.binder = ElaChatStreamBinder(self.chat, worker=worker)
        self.binder.shutdownOnClose(self)
        worker.ready.connect(self.on_ready)
        worker.turnFinished.connect(self.on_turn_finished)
        worker.failed.connect(self.on_failed)
        worker.errorOccurred.connect(self.on_error)

        # ③ 宿主行为：提交 / 停止 / 撤回 / 重新生成 / 重试 / 清空上下文
        # 用 messageSubmittedFull（不是 messageSubmitted）：它多带一份附件，
        # 附件要原样送进后端，否则用户上传的文件模型根本看不见。
        self.chat.messageSubmittedFull.connect(self.start_turn)
        self.chat.stopRequested.connect(self.on_stop)
        self.chat.undoRequested.connect(self.on_undo)
        self.chat.regenerateRequested.connect(self.on_regenerate)
        # 错误卡上的「重试」= 同参数重发（**不删消息**，与「重新生成」不同）
        self.chat.retryRequested.connect(self.on_retry)
        self.chat.generationStarted.connect(self.on_generation_started)
        # 清空上下文：组件只清界面 + 队列，后端会话要宿主同步重置，
        # 否则下一轮模型还带着清空前的历史
        self.chat.cleared.connect(self.on_cleared)

        # ④ 真实后端是 QThread，需要 start()；假后端不用
        if isinstance(worker, ElaChatAsyncWorker):
            worker.start()

    # -- 回合 --------------------------------------------------------------

    def start_turn(self, prompt, attachments=None, regenerate=False):
        self._turn_failed = False
        if self.binder.startTurn(
            prompt, regenerate=regenerate, attachments=attachments
        ) is None:
            self.status.setStatus("后端未就绪，这条消息没发出去", level="error")

    def on_generation_started(self, messageId):
        self._turn_failed = False
        self.status.setStatus("生成中…", level="busy")
        self.status.setBusy(True)

    def on_stop(self):
        self.binder.cancel()  # 记录停止（finish 自动按 Stopped 收尾）
        self.worker.cancel()

    def on_ready(self):
        self.status.setBusy(False)
        self.status.setStatus("后端已就绪", level="success")

    def on_turn_finished(self, turn):
        # turn 是发起本回合时 worker 给的 token：迟到的旧回合收尾会被 binder
        # 丢弃（返回 None），此时不动状态栏。
        summary = self.binder.finish(turn)  # 收尾：补耗时 + 结束消息
        if summary is None:
            return
        self.status.setBusy(False)
        if self._turn_failed:
            self._turn_failed = False
            self.status.setStatus("生成出错（错误卡上可「重试」）", level="error")
        elif summary.status == ElaChatStatusType.Stopped:
            self.status.setStatus("已停止（保留已输出内容）")
        elif summary.isEmptyReply():
            self.status.setStatus(
                f"模型未返回正文（finish_reason={summary.finishReason or 'unknown'}）",
                level="error",
            )
        else:
            self.status.setStatus(
                f"完成 · {summary.durationMs:.0f} ms", level="success"
            )

    def on_failed(self, message):
        """后端**初始化**失败：这一轮还没开始，没有消息可以落错误卡。

        所以走状态栏 + 一条系统消息 —— 只 ``print`` 到 stderr 的话，界面全空。
        """
        print(f"后端初始化失败：{message}", file=sys.stderr)
        self.status.setBusy(False)
        self.status.setStatus(f"后端不可用：{message}", level="error")
        self.chat.chatView().addMessage(
            ElaChatRoleType.System, f"后端初始化失败：{message}"
        )

    def on_error(self, errorType, message):
        self._turn_failed = True
        self.status.setStatus(f"生成出错：{message}", level="error")
        # 错误卡 + 「重试」（类型归一后才可能点亮那个按钮）
        self.binder.error(classify_error(errorType, message), message)

    def on_undo(self, messageId):
        self.worker.cancel()
        self.chat.undoMessage(messageId)  # 删该条及其后 + 原文回填输入框

    def on_regenerate(self, messageId):
        self.worker.cancel()
        message = self.chat.regenerateFrom(messageId)  # 删原回答，返回提问
        if message is not None:
            # ★ 附件必须一起带上：快照里有，丢了就是「重新生成后模型看不见文件」
            self.start_turn(
                message.text, attachments=message.attachments, regenerate=True
            )

    def on_retry(self, messageId):
        """错误卡的「重试」：同参数重发，原地保留那条消息（不删不重建）。"""
        self.worker.cancel()
        message = self.chat.retryMessage(messageId)  # 只清错误，返回前置提问
        if message is None:
            self.status.setStatus("找不到可重试的提问", level="error")
            return
        self.start_turn(message.text, attachments=message.attachments)

    def on_cleared(self):
        """界面已清空：同步重置后端会话（mock / 真实后端同签名）。"""
        self.worker.reset()


def create_worker(parent=None):
    """按 ``LLM_TEST_BACKEND`` 选后端：默认 mock；``agent`` 接真实模型。

    ``agent`` 复用 ``llm_test/agents/`` 副本：先 ``bootstrap_agents()``
    做依赖桩并注册工具（必须在主线程），再返回 ``agent_demo.AgentWorker``；
    需要 ``openai`` / ``loguru``（``uv pip install openai loguru``）。
    """
    backend = os.environ.get("LLM_TEST_BACKEND", "mock").strip().lower()
    if backend in ("agent", "openai", "real"):
        from llm_test.agent_demo import AgentWorker, bootstrap_agents

        bootstrap_agents()
        return AgentWorker(parent)
    return ElaChatMockBackend(parent, tickMs=28)


def main():
    app = QApplication(sys.argv)
    eApp.init()
    window = DemoWindow(create_worker())  # 必须持有引用
    window.show()
    rc = app.exec()
    # 退出前显式销毁并冲刷删除队列：让组件清理钩子（断开全局主题信号等）
    # 在解释器退出前完成，避免进程退出时的 Qt 清理竞态（偶发 0xC0000409）
    window.deleteLater()
    app.processEvents()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
'''

#: 快照：llm_test/agent_demo.py
LLM_TEST_AGENT_DEMO_SOURCE = r'''"""真实后端最小示例：把假后端换成 AgentWorker（本地 agents/ 副本 + 本地模型）。

窗口复用 ``main.DemoWindow``（只认 worker 信号，不认具体后端）；
本文件只写 agent 专属的三件事：引导导入、worker 子类、启动。

前置：venv 已安装 openai / loguru；本地模型服务已启动（默认 127.0.0.1:8000/v1）。

运行::

    python llm_test\\agent_demo.py
    # 或从 main.py 进入（等价）：$env:LLM_TEST_BACKEND="agent"; python llm_test\\main.py

可用环境变量：``LLM_TEST_BASE_URL`` / ``LLM_TEST_MODEL`` / ``LLM_TEST_API_KEY`` /
``LLM_TEST_THINKING``（1 开启推理输出）/ ``LLM_TEST_WORK_DIR``。
"""

import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根目录

from PyQt6.QtWidgets import QApplication
from PyQt6ElaWidgetTools import eApp

from pyqt6_ela_pro.chat import ElaChatAsyncWorker

from llm_test.main import DemoWindow

# -- 配置（环境变量可覆盖） -------------------------------------------------
BASE_URL = os.environ.get("LLM_TEST_BASE_URL", "http://127.0.0.1:8000/v1")
MODEL = os.environ.get("LLM_TEST_MODEL", "Spark-X2.5-4B-FP8")
API_KEY = os.environ.get("LLM_TEST_API_KEY", "not-needed")
WORK_DIR = Path(
    os.environ.get("LLM_TEST_WORK_DIR") or Path(__file__).resolve().parent / "workspace"
)
SYSTEM_PROMPT = (
    "你是一个有帮助的助手，请始终使用中文回答。"
    "需要查阅文件时使用 read_file / glob_file / grep_file。"
)


def bootstrap_agents():
    """导入 agents/ 副本（跳过 chart / shell / MCP 依赖，只要只读工具）。

    导入前先放两个桩，避免拉入 dash / plotly / Git Bash / mcp 包。
    必须在主线程调用：agents/background.py 导入期会注册 signal。
    """
    if "llm_test.agents" in sys.modules:
        return

    mcp_stub = types.ModuleType("llm_test.agents.mcp")

    class MCPServer:  # 占位：本示例不配置 MCP
        def __init__(self, *args, **kwargs):
            raise RuntimeError("未启用 MCP")

    mcp_stub.MCPServer = MCPServer
    sys.modules["llm_test.agents.mcp"] = mcp_stub

    tools_stub = types.ModuleType("llm_test.agents.tools")
    tools_stub.__path__ = [str(Path(__file__).resolve().parent / "agents" / "tools")]
    sys.modules["llm_test.agents.tools"] = tools_stub

    import llm_test.agents  # noqa: F401  （导入即注册工具）
    from llm_test.agents import set_tool_mode
    from llm_test.agents.tools import file_tools, grep_tool, plan_tool  # noqa: F401

    # 声明可用模式（未声明的工具不会进入 enabled_tools）
    for name in ("read_file", "glob_file", "read_image", "grep_file"):
        set_tool_mode(name, ["plan", "build"])
    set_tool_mode("plan_write", ["plan"])


class AgentWorker(ElaChatAsyncWorker):
    """agent 后端：只实现 4 个钩子，线程 / 队列 / 取消由基类处理。"""

    async def _setup(self):
        import llm_test.agents as agents

        WORK_DIR.mkdir(parents=True, exist_ok=True)
        agents.AgentsConfig.configure(
            {"base_url": BASE_URL, "api_key": API_KEY, "model": MODEL}
        )
        thinking = os.environ.get("LLM_TEST_THINKING", "").strip().lower()
        agents.AgentsConfig.set_thinking_mode(thinking in ("1", "true", "yes", "on"))
        agents.AgentsConfig.set_work_dir(WORK_DIR)
        agents.set_work_dir(WORK_DIR)
        self.agent = agents.create_async_agent(
            enabled_tools=agents.get_registered_tools("plan"),
            system_prompt=SYSTEM_PROMPT,
            callbacks=agents.AgentCallbacks(
                on_llm_start=lambda _messages: self.llmStarted.emit(),
                on_tool_start=lambda tc: self.toolStarted.emit(tc),
                on_tool_end=lambda tc, result: self.toolEnded.emit(tc, str(result)),
                on_llm_end=lambda usage, ttft, tps: self.statsReady.emit(
                    usage, float(ttft or 0), float(tps or 0)
                ),
                # **必须接**：agents 把所有 API 异常编码成 ``__ERROR__:<类型>:<文案>``
                # 哨兵字符串 yield 出来（llm_client.py），**不抛异常**；agent 只经
                # 这个回调上报（agent.py:1013-1019），随后直接 ``return`` 结束流。
                # 不接 -> 错误凭空消失，回合以「没有正文」收尾，界面上只剩
                # 「模型未返回正文（finish_reason=unknown）」，真实原因查不到。
                on_error=lambda error_type, message: self.errorOccurred.emit(
                    "worker", f"{error_type}: {message}"
                ),
            ),
            agent_id="llm_test",
        )
        self.ready.emit()

    @staticmethod
    def _compose_prompt(prompt, attachments):
        """把附件拼进提问：本示例的 agent 只吃纯文本，附件名 / 路径交给模型
        让它用 read_file / read_image 去读。真实宿主应在这里构造多模态消息。

        ``_stream_turn`` 与 ``_rollback_turn`` 必须用**同一个**口径拼，
        否则回滚比较对不上（历史里存的是拼好的那份）。
        """

        def label(item):
            if hasattr(item, "name"):
                return item.name or item.path or ""
            if isinstance(item, dict):
                return item.get("name") or item.get("path") or ""
            return str(item)

        if not attachments:
            return prompt
        names = "、".join(filter(None, (label(item) for item in attachments)))
        return f"{prompt}\n\n（附件：{names}）" if names else prompt

    def _stream_turn(self, prompt, attachments):
        return self.agent.run(self._compose_prompt(prompt, attachments))

    async def _rollback_turn(self, prompt, attachments):
        """重新生成前回滚上一轮提问，避免历史里出现重复提问。"""
        composed = self._compose_prompt(prompt, attachments)
        history = getattr(self.agent.session, "history", None)
        if history and getattr(history[-1], "user_message", "") == composed:
            history.pop()

    async def _reset_backend(self):
        self.agent.reset()


def main():
    app = QApplication(sys.argv)
    eApp.init()
    bootstrap_agents()  # 必须在主线程
    # 状态栏左侧显示「模型 @ 地址」：连接失败时第一眼要确认的就是这个
    window = DemoWindow(AgentWorker(), statusInfo=f"{MODEL} @ {BASE_URL}")
    window.show()  # 必须持有引用
    rc = app.exec()
    # 同 main.py：退出前显式销毁并冲刷删除队列，避免进程退出时的 Qt 清理竞态
    window.deleteLater()
    app.processEvents()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
'''


class ChatGuidePage(ExamplePage):
    """聊天组件使用指南（Markdown 渲染，代码为 llm_test 源码快照）。"""

    PAGE_TITLE = "[ela_ext] 聊天组件指南"

    def _addDemoContent(self, main_layout):
        sections = (
            ("1. 组件栈概览", self._demoOverview),
            ("2. 四步接入（llm_test/main.py 全文）", self._demoMainSource),
            ("3. 关键 API 速查", self._demoApi),
            ("4. 真实后端（llm_test/agent_demo.py 全文）", self._demoAgentSource),
            ("5. 运行与依赖", self._demoRun),
        )
        for title, demo in sections:
            main_layout.addSpacing(12)
            main_layout.addLayout(self._createHeaderRow(title, demo))
            demo(main_layout)

    # -- 通用 --------------------------------------------------------------

    def _addMarkdown(self, main_layout, markdown: str) -> ElaMarkdownViewer:
        """加入一个嵌入式查看器（高度随文档，随页面统一滚动）。"""
        viewer = ElaMarkdownViewer(parent=self)
        viewer.setEmbeddedMode(True)
        viewer.setLineNumbersEnabled(True)
        viewer.setMarkdown(markdown)
        main_layout.addWidget(viewer)
        return viewer

    @staticmethod
    def _code_block(source: str, lang: str = "python") -> str:
        """代码围栏。**闭合围栏必须独占一行**：贴到源码末行（快照常量常无尾换行）
        会被解析成未闭合围栏（= 流式中间态），超过 4096 字符时静默丢掉全部 pygments
        着色，同一 viewer 里后续内容还会被吞进代码块。
        """
        return f"```{lang}\n{source.rstrip()}\n```\n"

    # -- 1. 组件栈概览 -----------------------------------------------------

    def _demoOverview(self, main_layout):
        markdown = r"""# 组件栈概览

`pyqt6_ela_pro.chat` 提供「组件 + 接线基础设施」，宿主只写业务代码：

| 组件 | 作用 |
|---|---|
| `ElaChatWidget` | 消息区 + 输入区（步骤化气泡 / 工具面板 / 排队 / 撤回按钮都在组件内） |
| `ElaChatStreamBinder` | 后端事件 → 步骤 / 思考 / 工具 / 统计 / 耗时；闭环一个回合 |
| `ElaChatAsyncWorker` | 真实异步后端基类：QThread + asyncio + 命令队列 + 取消收尾 |
| `ElaChatMockBackend` | 假后端（QTimer），无模型服务即可跑通全链路 |
| `ElaChatStatusBar` | 可选宿主状态栏（info / busy / success / error 四档） |

**worker 是鸭子类型**：任意对象只要满足下面的信号与方法，就能直接交给
binder 和窗口（本页示例里 `worker` 就是这个角色）。

| 信号 | 说明 |
|---|---|
| `ready` / `failed` | 后端初始化完成 / 失败 |
| `llmStarted` | 新一轮 LLM 调用开始（步骤边界） |
| `chunkReceived` | 流式分片（`reasoning_content` / `answer_content`） |
| `toolStarted` / `toolEnded` | 工具调用开始 / 结束 |
| `statsReady` | 单次调用用量（usage, ttftMs, tps） |
| `errorOccurred` / `emptyTurn` | 错误 / 回合无正文诊断 |
| `turnFinished` | 回合结束（成功 / 失败 / 停止），载荷是发起时 `ask` 返回的**回合 token** |

| 方法 | 说明 |
|---|---|
| `ask(text, attachments=None)` / `regenerate(text, attachments=None)` | 提问 / 重新生成，**返回回合 token**（未就绪返回 `None`）；附件原样交给 `_stream_turn(prompt, attachments)`，不带附件时为空列表 |
| `cancel()` | 中止当前回合（保留已输出内容） |
| `reset()` / `shutdown()` | 重置会话 / 退出收尾 |
"""
        self._addMarkdown(main_layout, markdown)

    # -- 2. 四步接入 -------------------------------------------------------

    def _demoMainSource(self, main_layout):
        markdown = r"""# 四步接入（`llm_test/main.py` 全文）

1. **摆组件**：`ElaChatWidget`（消息区 + 输入区 + 步骤化时间线都在组件内）；
2. **选后端**：`create_worker()` 默认 `ElaChatMockBackend`（假）；
   `LLM_TEST_BACKEND=agent` 时切 `AgentWorker`（真，走 `agents/` 副本，见第 4 节），
   两者信号完全同构，窗口不感知差异；
3. **接信号**：`ElaChatStreamBinder(chat, worker=worker)` 自动接 6 条机械信号
   （`llmStarted` / `chunkReceived` / `toolStarted` / `toolEnded` / `statsReady` /
   `emptyTurn`），`shutdownOnClose(window)` 关窗自动收尾；
4. **宿主行为**：提交 → `binder.startTurn`；停止 → `binder.cancel()` +
   `worker.cancel()`；撤回 / 重新生成用组件 API（**重新生成要把
   `message.attachments` 一起带上**，`startTurn(attachments=...)` 会送进后端）；
   **清空上下文 → `cleared` 里 `worker.reset()`**（组件只清界面与队列）；
   回合结束 → `binder.finish(turn)`（token 由 `startTurn` 给出）。

   另有一组**「错了要有话说」**的接线（示例里是 `ElaChatStatusBar` 四档状态 +
   错误卡 + 「重试」）：`ready` / `failed` / `errorOccurred` / `retryRequested`
   四个信号必须都接上，否则后端初始化失败时界面全空、错误只进 stdout。
   注意 `binder.error(errorType, msg)` **原样**把类型传下去，而「重试」只对
   `RETRYABLE_ERROR_TYPES` 里的类型点亮 —— 真实后端恒发 `"worker"`，宿主要自己
   归一（示例里的 `classify_error`）。

""" + self._code_block(LLM_TEST_MAIN_SOURCE)
        self._addMarkdown(main_layout, markdown)

    # -- 3. 关键 API 速查 --------------------------------------------------

    def _demoApi(self, main_layout):
        markdown = r"""# 关键 API 速查

## Binder（回合生命周期，宿主主入口）

| API | 说明 |
|---|---|
| `ElaChatStreamBinder(chat, worker=...)` | 传 worker 自动接线；`connectWorker(worker)` 幂等（重复传同一后端忽略，换绑会解绑旧后端） |
| `startTurn(prompt, regenerate=False, attachments=None)` | 建助手消息 + `beginTurn` + 驱动后端，**返回回合 token**；未就绪返回 `None`（不建空消息）。**重新生成必须带 `attachments=message.attachments`** —— `regenerateFrom` 返回的快照里就有，丢了就是模型看不见用户上传的文件 |
| `cancel()` | 记录停止 + 收尾思考段；之后 `finish(turn)` 自动按 `Stopped` |
| `finish(turn, status=None)` | 补整轮耗时 + 结束消息，返回 `ElaChatTurnSummary`。**`turn` 必填**（`startTurn` / `beginTurn` 的返回值）：认不出的**迟到收尾直接丢弃并返回 `None`** —— 后端 `cancel()` 是异步的，旧回合的 `turnFinished` 可能在新回合开起来之后才到，收掉它等于把新回合的分片全丢弃（用户看到「发出去了、正文全空」）。`worker.turnFinished.connect(binder.finish)` 写法自带 token，无需转发 |
| `abortTurn(cancelBackend=True)` | **作废当前回合**（删除 / 关闭话题）：默认连后端一起 `worker.cancel()`、收尾为 `Stopped`、**不续发排队消息**；回合外返回 `None` |
| `beginTurn(turn=None)` / `beginRound()` | 手动驱动回合一：宿主自己 `ask()` 后把回合 token 交给 `beginTurn`；`beginRound` 由 worker 的 `llmStarted` 自动驱动（自动接线已接，别手动调） |
| `isOpen()` / `roundIndex()` | 是否有回合在跑 / 当前回合内的 LLM 轮次（1 起） |
| `shutdownWorker(timeoutMs=None)` | 后端收尾（`shutdownOnClose` 内部用的就是它；`timeoutMs=None` = 不等线程退出） |
| `shutdownOnClose(window)` | 关窗 / 销毁时自动 `worker.shutdown()`（免写 `closeEvent`） |
| `stream(chunk)` / `toolCallStarted(tc)` / `toolCallEnded(tc, r)` | worker 信号直连（自动接线的底层） |

## Widget（宿主行为）

| API | 说明 |
|---|---|
| `messageSubmitted` / `messageSubmittedFull` / `stopRequested` / `undoRequested` / `regenerateRequested` / `retryRequested` | 宿主行为信号。**要附件就接 `messageSubmittedFull(text, attachments)`**：`messageSubmitted(text)` 只有文本，附件到不了后端 |
| `permissionRequested` / `permissionReplied` | 工具审批（**组件不阻塞**：收到 `permissionRequested(id, requestId)` 自行挂起后端，收到 `permissionReplied(id, requestId, reply, answer, feedback)` 自行恢复） |
| `steerReady` / `steerChanged` | steer 插话投递 / 队列变化 |
| `newTopicRequested` | 输入区「新建话题」按钮（组件**什么都不做** —— 宿主在此 `view.clear()` + `worker.reset()` + 新建 `ElaChatSessionInfo` 并切换） |
| `contextUsageClicked` | 点击输入区工具栏的上下文占用圆环（组件**什么都不做**，宿主据此弹上下文详情面板等） |
| `undoMessage(id)` / `undoLastUserMessage()` | 撤回用户消息：删除该条及其后消息，原文 / 附件回填输入框。`undoMessage` **只对用户消息生效**（传助手消息返回 `None`，别拿 `messages()[-1]` 的助手回答 id 去撤）；`undoLastUserMessage()` 自己找**最后一条用户消息**，是「撤回最后一条消息」的正确入口 |
| `regenerateFrom(id)` | 删除该回答，返回前置用户消息（**按钮与整条底部行只在回合结束后出现** —— 流式 / 排队中不显示：回答没写完点了会整段丢掉，复制到的也只是半句话） |
| `retryMessage(id)` | **重试**（同参数重发）：清错误并把状态落成 `stopped`、**保留消息位置与 id**，返回前置用户消息。与 `regenerateFrom` 的区别就是不删消息 —— 删掉重建会让「重试」看起来像「重新生成」，也会打断用户正在读的上下文 |
| `steerMessage(text)` / `drainSteer()` / `setSteerEnabled(on)` | 生成中插话：在 `beginStep` 安全边界把新指令送进**正在跑的这一轮**（对齐 opencode 的 `Delivery = "steer" \| "queue"`，那边 prompt 默认 steer），而不是排队等它跑完。`drainSteer()` 一次只投一条 |
| `sendNextQueued()` / `setAutoSendQueue(on)` | 排队续发（回合结束默认自动发送队首；仅空闲时发送） |
| `sendQueuedNow(id)` | 排队 dock「立即发送」：先按 `Stopped` 收尾当前流并发出 `stopRequested`，再提交该条（同一时刻只有一个活跃流）。**只发被点的那条**，其余排队消息保持排队 |
| `clear()` | 清空消息与排队；生成中会发出 `stopRequested`；发出 `cleared` 信号 |
| `cleared` | 界面已清空（消息 + 队列 + 生成态）——**宿主在这里重置后端会话**（`worker.reset()`），后端上下文只有宿主知道，组件管不到 |
| `clearRequested` | 输入区工具栏「清空上下文」按钮点击**且有待清内容**时（确认弹框**之前**发出，可做埋点；空会话不发、也不弹框） |
| `requestClear()` | 主动走「ElaConfirmDialog 确认 → `clear()`」链路（空会话不弹框） |
| `setMessageError(message, messageId=None, errorType="")` | 标记某条消息出错（只影响生成态与 widget 独占状态）。`errorType` 单独存字段而不是拼进文案 —— 错误卡靠它决定是否点亮「重试」 |
| `removeMessage(id)` | 删除单条消息（维护 widget 侧状态） |
| `inputDock()` / `permissionDock()` / `queueDock()` / `setDockWidget(widget, replace=True, *, ownership=Borrowed)` / `clearDock()` / `clearPermissionDock()` / `pendingPermissionCards()` | 三个常驻 dock 的句柄 + 输入区上方「替换输入区」内容。`setDockWidget` 默认 **Borrowed（不删除）**，要组件负责销毁必须显式 `ownership=ElaWidgetOwnershipType.Owned`；审批 dock 一次只放一张卡（后续请求进 `queued`，落定后自动接上），`pendingPermissionCards()` 给宿主看队列 |
| `enqueueMessage(text, attachments=None)` / `queuedMessages()` / `queueCount()` / `dequeueMessage(id)` / `editQueuedMessage(id)` / `clearQueue()` / `queueChanged(list)` | 排队队列的增删改查；`editQueuedMessage` 把该条回填输入框并出队（再提交就是普通发送） |
| `generationStarted(id)` / `generationFinished(id, status)` / `messageUpdated(id)` / `messageActionTriggered(id, action)` / `sessionChanged(id)` / `attachmentsChanged(list)` / `batchRenderFinished()` | 状态 / 遥测信号：生成开始 / 结束（`status` 是字符串枚举）、消息快照更新、消息操作按钮、会话标记、附件变化、批量恢复的首批排空（**不是**「全部渲染完」） |
| `setUserName(name)` / `setAssistantName(name)` / `setPlaceholderText(text)` / `setMentionProvider(fn)` / `mentions()` / `sendUserMessage(text, attachments=None, messageId=None)` / `addMessage(role, text)` | 外壳与程序化消息：名字作用于已有与后续消息；`@` 引用 `provider(query) -> list`，提交时用 `mentions()` 取有效 id；`sendUserMessage` 建用户消息 + 进生成态（返回 id），`addMessage` 只建消息不提交 |
| `setGenerating(on)` / `isGenerating()` / `streamingMessageId()` | 生成态与当前流式消息 id（`stopGeneration()` 见「三层边界」） |

> **widget 不再转发 view 的细粒度接口** —— `addToolCall()` / `beginText()` /
> `setReasoningStyle()` 等一律在 `chatView()` 上，`messageId` 也在那里**首位必填**。
> widget 只保留「输入区 + 回合编排」相关的宿主行为方法。

## 三层各自的 API 边界（哪些能依赖，哪些是内部协议）

| 层 | 宿主 API（可以依赖） | 内部协议 / 性能开关（别依赖） |
|---|---|---|
| `ElaChatWidget` | 回合（`beginAssistantMessage` / `endAssistantMessage` / `stopGeneration` / `setMessageError`）、提交与排队、dock、`setCurrentSessionId`（纯标记） | —— （内容方法已全部移除，见上面的提示） |
| `ElaChatView` | 建 / 改 / 读消息：`addMessage` / `addMessageFromDict` / `restoreMessages` / `removeMessage` / `appendText` / `addToolCall` / `setStepStats` / `setMessageTitle` / `setMessageError` / `messageError` / `clearMessageError` …；agent 能力：`beginPermission` / `resolvePermission` / `pendingPermissions` / `beginCompaction` / `appendCompactionSummary` / `endCompaction` / `addSteerNotice`；外观：`setReasoningStyle` / `setStatsMode` / `setToolGrouping` / `setToolDefaultOpen` / `setAvatar*` / `setCopyNotificationEnabled` / `setWaitingPlaceholderEnabled` / `setContentMaxWidth`；持久化：`exportSession` / `importSession`；虚拟化：`materializeMessage` / `scrollToMessage` / `setVirtualPartsEnabled` / `setShellVirtualizationEnabled` / `setVirtualListEnabled` | **性能开关**：`beginBatch` / `endBatch`（历史骨架 + 渐进渲染）、`setViewportSuspension`（视口外挂起）、`setResizeReflowDeferred`（交互 resize 延迟重排）；**渲染内部**：`bubble` / `contentWidget` / `holdFollow` / `jumpThreshold` / `isBatchActive` / `guardNestedScroll`。单条消息的延迟渲染（`setRenderDeferred` / `flushRender` / `hasPendingRender`）**只在 `bubble` 上**，view 仅在批量路径内部调用 |
| `ElaChatBubble` | 取子控件与形态：`actions()` / `footer()` / `meta()` / `header()` / `text()` / `parts()` / `markdownViewer()` / `inlineReasoningViewer()` / `statsBadge()` / `toolPanels()` / `setAvatarShape()` / `setActionsHoverReveal()` | 其余 `beginText` / `appendText` / `addToolCall` / `setParts` / `setPartsDeferred` / `materializeParts` / `partsDeferred` / `partsWindowed` / `expandParts` / `setStatus` / `setStepStats` / `setRenderDeferred` … 是 **view ↔ bubble 内部协议**：宿主改消息请走 view 层，否则会绕过 `_sync_parts` 派生结算与 `_dirty_syncs` 防抖 |

## Input（输入区，经 `chatInput()` 调用）

| API | 说明 |
|---|---|
| 拖放 | **整个聊天组件都是放置点**：拖文件 / 拖图片到消息区、标签外区域、输入卡片、编辑框都会进附件条（`ElaChatWidget` 收下后落到 `ElaChatInput`） |
| 粘贴 | Ctrl+V：图片（截图 / 浏览器复制）与「复制的文件」（资源管理器 Ctrl+C）都进附件，文本正常插入 —— 粘贴与拖入共用 `insertFromMimeData` 一个钩子 |
| `filesAdded(paths)` | 文件进入输入区（拖放 / 粘贴复制的文件；已自动加入附件） |
| `imagePasted(image)` | 图片进入输入区（粘贴 / 拖入，已自动加入附件）；粘贴图片的图像挂在附件对象上（运行时，不序列化），消息显示 / 撤回回填都带缩略图 |
| `newTopicRequested` | 点击「新建话题」按钮（组件**什么都不做**，话题 / 会话由宿主创建） |
| `newTopicButton()` / `setNewTopicVisible(on)` | 内置「新建话题」按钮句柄 / 显隐（默认显示） |
| `acceptsMime(mime)` / `attachMime(mime)` | 「这个 mime 收不收」/「收下并入附件」——组件各处拖放判定都走这两个，宿主自定义放置点时可复用 |
| `setContextUsage(used, window, costUsd)` | 底部工具栏里的上下文占用圆环（与「清空上下文」同排的**默认组件**；无数据时画空底环、`window<=0` 按 0%；`<60%` 弱化 / `60~85%` 警示 / `>85%` 危险），hover 显示花费 / 百分比 / 词元数。数据全由宿主提供；**圆环可点击**（发 `contextUsageClicked`，弹什么面板归宿主）；显隐走 `setContextUsageVisible(on)` |
| `setContextUsageVisible(on)` / `contextUsage()` / `contextUsagePercent()` | 上下文圆环显隐 / 读取（`contextUsage()` 返回 `(used, window, costUsd)`）/ 百分比 |
| `setSendOnEnter(on)` / `sendOnEnter()` | 回车发送（默认开）；关掉后回车插入换行，发送只走按钮 / `submit()` |
| `setSendText(text)` / `setStopText(text)` / `setPlaceholderText(text)` / `setMaxLines(n)` / `setMinLines(n)` | 发送 / 停止按钮文案、占位文案与编辑框高度（`maxLines` 是自增上限，超过后内部滚动） |
| `setAttachments(list)` / `addAttachments(paths)` / `addAttachment(name, path="", size=0)` / `attachments()` / `attachmentPaths()` / `clearAttachments()` | 附件条的程序化入口（拖放 / 粘贴之外）；`attachments()` 是快照，`attachmentPaths()` 只给有本地路径的项 |
| `setMentionProvider(fn)` / `mentions()` / `clearMentions()` / `mentionSelected(text, value)` | `@` 引用：候选由宿主给；提交时用 `mentions()` 或 `mentionSelected` 拿有效 id |
| `addFileButton()` / `setAddFileVisible(on)` / `clearButton()` / `setClearVisible(on)` / `setFilePicker(fn)` | 工具栏按钮句柄 / 显隐；`setFilePicker` 可把系统文件框换成宿主自己的选择器 |
| `setQueueEnabled(on)` / `queueEnabled()` | 生成中是否允许排队（默认开；关掉时发送键置灰、回车不被吞） |
| `submit()` / `text()` / `setText(text)` / `clear()` | 程序化提交 / 读写草稿（`submit()` 走与回车相同的校验与信号） |

## View（消息内容层，经 `chatView()` 调用）

| API | 说明 |
|---|---|
| `addMessage(role, text)` / `addMessageFromDict(data)` | 新建消息；后者沿用存储 id（冲突抛 `ValueError`） |
| `restoreMessages(list, preserveIds=False)` | 重新分配 id 批量恢复（走 `beginBatch` / `endBatch`）；`preserveIds=True` 时保留存储 id，先全量校验再写入、撞 id 抛 `ValueError` |
| `materializeMessage(id)` / `scrollToMessage(id)` | 物化延迟加载的消息 / 物化并滚动到它。批量恢复后首屏之外的消息只存 `parts` 数据（`bubble.partsDeferred()`），滚动到附近会自动物化 |
| `setVirtualPartsEnabled(on)` | 关闭时下一次导入立即建全部工具卡 / 思考块（小会话或逐控件断言测试用）；已延迟的消息会当场物化 |
| `setShellVirtualizationEnabled(on, minMessages=None)` | 批量恢复 ≥ 80 条时默认连气泡壳一起延迟；关闭后立即建壳。未物化消息的 `bubble(id)` 返回 `None`，`message(id)` / `messages()` / 导出仍是完整数据 |
| `setVirtualListEnabled(on, minMessages=None)` | 批量 ≥ 200 条时默认改用 spacer 虚拟列表（只保留视口附近气泡，不逐条建占位）；关闭后当场物化全部消息 |
| `addToolCall(messageId, name, args, toolCallId)` | 追加工具调用（上下文工具自动归组） |
| `setReasoningStyle(style)` / `setToolGrouping(on)` / `setStatsMode(mode)` | 展示形态，立即对已有消息生效 |
| `setDisclaimer(text)` / `setDisclaimerVisible(on)` | 助手消息底部的「内容由 AI 生成，仅供参考」提示（默认开启；流式期间随整行隐藏）；`DISCLAIMER_TEXT` 是默认文案 |
| `setCopyNotificationEnabled(on)` | 点击消息底部「复制」后是否弹 `ElaMessageBar`「已复制到剪贴板」成功提示（默认开启，立即对已有消息生效；应用偏好，不进 `exportSession`） |
| `setWaitingPlaceholderEnabled(on)` | 等待首个 token（TTFT）期间是否在助手气泡内显示 `ElaShimmer` 骨架（默认开启，立即对已有消息生效）。骨架不是 part：不进 `parts` / 导出 / journal；收到首个正文 / 思考 / 工具 / 审批 / 统计即隐藏。应用偏好，不进 `exportSession` |
| `setUserAvatar(source)` / `setAssistantAvatar(source)` / `setAvatarShape(shape)` | 头像自定义：SVG / 路径 / `QPixmap` / `QImage` / `QIcon` / `bytes` 等（含已存在与后续消息）；形状 `"circle"`（默认）/ `"rounded"`（**带圆角的矩形**）/ `"square"`，非法值回落圆形 |
| `setToolDefaultOpen(policy)` | 注入工具卡展开策略（`policy(name, args, ok) -> bool`），只影响**之后新建**的卡片 |
| `registerToolRenderer(name, factory, *, subtitle, groupable, replace=False)` | **工具结果富渲染**（模块级函数）：`factory(ToolRenderContext) -> QWidget` 只替换卡片**内容区**，头部 / 折叠 / 错误竖线 / 忙碌环 / 展开策略仍由 `ToolCallCard` 负责。可选实现 `updateToolResult(result, status)` 收推送。`subtitle(args) -> (键, 值)` 的键自动从参数摘要排除。`replace=False` 时注册同名渲染器直接报错（防静默覆盖）。库内不内置任何渲染器 |
| `beginPermission(messageId, request)` / `resolvePermission(messageId, requestId, reply, answer, feedback)` | 工具审批。**交互与记录分离**：等待回复时交互卡在**输入区上方的 `ElaChatPermissionDock`**（输入区照常可用，不顶替它），答完在时间线该 part 的**原位**留下一张**默认折叠**的 `PermissionRecord`（与「工具调用 (N)」同一套折叠交互）。**组件只画卡 + 发信号，不阻塞**（Qt 里挂起等用户点按钮会卡死事件循环）；「始终允许」的规则持久化归宿主。`request.questions` 非空 = **问答型逐题向导**（见下），为空 = 批准型三键。传入**已是落定态**的 request 时直接落成记录卡（重放后端历史用），不进 dock、不发 `permissionRequested` |
| `pendingPermissions(messageId)` / `permissionCard(messageId, requestId)` / `interactivePermissionCard(messageId, requestId)` / `permissionAnswers(messageId, requestId)` | 读审批状态。`permissionCard` 只返回时间线上的**记录卡**（等待期间是 `None`），还在 dock 里等回复的交互卡用 `interactivePermissionCard`。`permissionAnswers` 给**未塌缩**的 `{key: [label, ...]}`，用于「答到一半还没提交」时看进度 |
| `beginCompaction(messageId, reason)` / `appendCompactionSummary(...)` / `endCompaction(...)` | 上下文压缩在时间线上的表达。**库不实现压缩算法**，只负责「能表达 + 能持久化」 |
| `addSteerNotice(messageId, text)` | 插话回执行（`↳ <text>`）。刻意不插用户气泡 —— 助手消息正在流式输出，中途插一条用户消息视觉上很怪 |
| `setContentMaxWidth(px)` | 气泡宽度约束。限的是**整列**（正文 + 附件条 + 底部行），宽窗口下右边缘对齐；不限宽时行为完全不变 |
| `setScrollBarPolicy(policy)` / `scrollBar()` | 垂直滚动条策略（默认 `ScrollBarAsNeeded`，仅溢出时显示）与滚动条句柄；手动拖动把手会自动退出贴底跟随 |
| `setStrictIds(on)` | 严格模式：对**不存在的消息**抛 `KeyError`（默认关闭，迟到事件静默忽略） |
| `setEmptyTitle(text)` / `setEmptySubtitle(text)` / `setSuggestions(list)` | 空态标题 / 副标题 / 建议按钮（元素是字符串，点击发 `suggestionClicked`） |
| `setAvatarVisible(on)` / `setUserBubbleMaxWidth(ratio)` | 全局头像显隐 / 用户气泡最大宽度比例（0.1~1.0） |
| `scrollToBottom()` / `setStickToBottom(on)` / `setJumpThreshold(px)` | 主动回底 / 自动贴底开关 / 「回到底部」按钮的显示阈值（`None` 恢复动态阈值） |
| `messages()` / `message(id)` / `lastMessage()` | 读快照（读取时才结算派生字段） |
| `sessionStats(limit=0)` | 会话级用量汇总（`ElaChatSessionStats`）：计数 / 当前上下文四路词元与合计 / 使用率 / 累计成本 / 最后活动 / **工具调用统计**（`tool_calls` 次数、`tool_rounds` 轮数 = 有工具调用的步骤数、`tool_errors` / `tool_aborted` / `tool_unsettled` 状态分档、`tool_counts` 按名计数）/ `reasoning_ms` 思考耗时合计；口径对齐 opencode `getSessionContext`（最后一条有 tokens 的助手消息的最后一步）。**输入词元不含缓存命中**（OpenAI / DeepSeek 的 `prompt_tokens` 含缓存，binder / journal 落库前已扣掉；Anthropic 的 `input_tokens` 原样），四路互不重叠。`total_tokens` / `total_cost_usd` 可直接喂输入区圆环 |
| `parts()` / `text()` / `reasoning()` | 纯读取；`part.text` 只含**已落定**内容，可直接序列化落库 |

## 持久化与崩溃恢复

| API | 说明 |
|---|---|
| `message.toDict()` / `ElaChatMessage.fromDict()` | 成对序列化，纯 JSON 类型（`allow_nan=False` 可写）；`fromDict` 一律容错 |
| `ElaChatTurnJournal` | 回合的**追加写事件流**：每片用 **`dumpsNewLines()`**（只给新增行，一行一条）追加到文件；`dumps()` 返回**整份历史**，只用于整体导出（原样 append 会重复重放）。崩了最多丢最后一行。`connectWorker(worker)` 自动跟随 `llmStarted` 切步（第 1 轮不切，别手动 `beginStep`）；同一 step 的 stats 按最新值覆盖；正文 / 思考 / 步骤时长自动记录 |
| `journal.replayInto(...)` / `ElaChatTurnJournal.fromLines(...)` | 重放 / 读回（跳过未知事件、结算未完成工具） |

## 统计与上下文占用

| API | 说明 |
|---|---|
| `ElaChatStats` | 单次 / 单步用量：`prompt_tokens`（**不含**缓存命中）/ `completion_tokens`（含 reasoning）/ `reasoning_tokens` / `cache_read_tokens` / `cache_write_tokens` / `ttft_ms` / `tps` / `duration_ms` / `cost_usd`；`contextTokens()` 是四路和，`merge()` 合并多步，`tooltip()` 生成悬浮提示文本 |
| `binder.stats(usage, ttftMs=0.0, tps=0.0)` / `view.setStepStats(messageId, stats)` | 写入单步统计（`statsReady` 自动接线已覆盖；手动驱动回合时才需要直接调） |
| `chatInput().setContextUsage(stats.contextTokens(), window, stats.cost_usd)` | 喂输入区圆环：used = 四路和、window = 模型上下文窗口、cost = 累计美元 |
| `view.sessionStats(limit=0)` | 会话级汇总（`ElaChatSessionStats`）；`limit>0` 只看最近 N 条消息 |

## Mock 后端（无模型服务跑通全链路）

| API | 说明 |
|---|---|
| `ElaChatMockBackend(parent, tickMs=40)` | 假后端：QTimer 按 `tickMs` 吐流式分片，`ready` 异步发出 |
| `setTickMs(ms)` / `tickMs()` | 分片间隔；`0` = 不经定时器（事件循环里尽快跑完，测试用） |
| `setReplyProvider(fn)` / `setThinkLevel(level)` / `thinkLevel()` | 自定义回答 `fn(question) -> str`；思考强度档位 `off` / `normal` / `deep` |
| `turnAttachments()` | 最近一次回合收到的附件快照（断言 / 回滚用） |

## 问答型审批（逐题向导）

`permission.questions` 非空时，交互卡变成**逐题向导**（对齐 opencode 的
`session-question-dock`）。它住在**输入区上方的 dock** 里而不是时间线上
（交互是「现在要你动手」，摆在历史流里既窄又旧），仍然不阻塞 —— 挂起后端是
宿主的事。

```python
view.beginPermission(messageId, ElaChatPermission(
    request_id="q0", action="question",
    questions=(
        ElaChatQuestion(
            key="scope",                       # 回传答案的键
            header="范围",                      # 短标签（进度行左侧）
            question="哪些目录需要一起看？",       # 题面正文
            options=(                          # 候选项，**每项两行**
                ElaChatOption("pyqt6_ela_pro/", "组件库本体"),
                ElaChatOption("tests/", "回归测试（改 API 必须同步）"),
            ),
            multiple=True,                     # True -> checkbox 可多选
            custom=True,                       # 追加「输入自己的答案」行
        ),
    ),
))
```

| 数据类 | 字段 |
|---|---|
| `ElaChatQuestion` | `key` / `header` / `question` / `options` / `multiple` / `custom`，另有 `isMultiple` 别名属性 |
| `ElaChatOption` | `label` / `description`（**描述不是可选项** —— 只给标题逼着用户靠猜） |
| `ElaChatPermission` | `questions`（非空 = 问答型；**这就是判据，勿另设标志位**）、`isQuestion`、`parsedAnswer()` |

**答案编码**（`permissionReplied` 的 `answer`，也是 `json.dumps` 的串）：

- **单选塌缩成标量** —— `{"scope": "tests/"}`；
- **多选发整个数组** —— `{"scope": ["tests/", "example/"]}`；
- **未答题整条不进 payload** —— 不是空串、不是空数组（空数组会被模型读成
  「用户答了『一个都不选』」）；
- **自定义答案与候选项互斥** —— 写了自定义答案，这道题就答它（多选时仍是单元素
  数组），因为「选项 A 或我自己的话」没法同时成立。

**交互**：标题行是「需要你回答 · 短标签」+ 右侧「N / M」+ 可点的进度段胶囊
（仅多题时出现）；`1`–`9` 选中对应行、`Space` 切换、`↑↓←→` / `Home` / `End` 移
焦点、`Ctrl+⏎` 下一步 / 提交、`Alt+←` 上一步、`Esc` 忽略。页脚三个键都是
`ElaButton`（`text` 弱化 / `outlined` 中性 / `solid+primary` 主动作）——
**不印快捷键提示**，快捷键照常生效。

**「输入自己的答案」那一行**：点它的标记 / 点整行 / 按 `Space` 是同一件事 ——
选中它并展开输入框，一步就能开始输入。单选下它是 radio（再点标记不会取消，
要换答案点其它选项），多选下再点标记 = 取消勾选并收起输入框；空文本勾上**不算
答案**（`answer` 里不会有这一题）。敲完字直接点「下一步 / 提交」或按 `Ctrl+⏎`
都会**先把这段文字落定**再前进 / 提交，不会丢。

单选 = `ElaRadioButton`（圆点）、多选 = `ElaCheckBox`（方框）：**标记是真控件，
不是自绘** —— 自绘版本两种模式画得一模一样，用户根本分不出单选还是多选。

**选项区是普通容器，不封顶也不滚动**（`QScrollArea.sizeHint()` 是个无意义的小值，
会把内容压扁；内层滚动区滚到头后事件还会冒泡到外层，滚选项会连消息区一起动）。

**落定后** dock 收起，时间线上留下一张**默认折叠**的 `PermissionRecord`
（标题如「已允许一次：范围」，正文是各题答案，多选用 `、` 连接）。

> 强调色取自 `eTheme` 主题令牌，**不硬编码 opencode 的品牌色** —— 本库是可换肤
> 组件库，抄外来品牌色会在用户换主题时显得突兀。

## 常见坑

- **顶层窗口必须保存引用**（`window = DemoWindow(...); window.show()`）：
  否则窗口只被信号 lambda 的引用环持有，循环 GC 回收后窗口销毁、程序退出；
- 停止时先 `binder.cancel()` 再 `worker.cancel()`，消息状态才会是 `stopped`；
- 生成中点排队 dock 的「立即发送」等价于「中止当前回答 + 立刻发这条」：
  宿主会先收到 `stopRequested`（需 `worker.cancel()`），旧回答状态为 `stopped`；
- `setMessageError()` 只在目标是当前流式消息（或无活跃流）时才结束生成态；
  给其他历史消息设错误不会打断正在进行中的流；
- 底部行（复制 / 重新生成 / 用量 / 耗时）与用量徽标**只在回合结束后出现**：
  流式期间整行不摆 —— 回答没写完时点「重新生成」会丢掉已经看到的内容
  （`regenerateFrom` 删该条及其后所有消息），复制到的也只是半句话；
- 真实后端的 `ask` / `regenerate` 只在 `ready` 之后返回 `True`，
  未就绪时应提示用户而不是静默丢弃；
- **附件要接 `messageSubmittedFull`**（不是 `messageSubmitted`）：后者只有
  文本。重新生成 / 重试时把快照里的 `message.attachments` 交给
  `startTurn(attachments=...)`，否则模型看不见用户上传的文件。
"""
        self._addMarkdown(main_layout, markdown)

    # -- 4. 真实后端 -------------------------------------------------------

    def _demoAgentSource(self, main_layout):
        markdown = r"""# 真实后端（`llm_test/agent_demo.py` 全文）

窗口完全复用 `main.DemoWindow`（只认 worker 契约）；本文件只写三件事：

1. `bootstrap_agents()`：导入 `agents/` 副本前放两个桩，
   跳过 dash / plotly / Git Bash / mcp 依赖（只需要只读工具）；
2. `AgentWorker(ElaChatAsyncWorker)`：只实现 `_setup()` /
   `_stream_turn(prompt, attachments)` / `_rollback_turn(prompt, attachments)` /
   `_reset_backend()`——线程、事件循环、命令队列、取消收尾全部由基类处理；
   示例把附件名拼进提问（agent 只吃纯文本，模型再用 `read_file` / `read_image`
   去读），两个钩子用同一口径拼、回滚比较才对得上；
3. `main()`：主线程引导（`agents` 导入期注册 signal）+ 持有窗口引用。

> `agents/` 是外部完整副本，不随库 / wheel 分发；换成其他 OpenAI 兼容
> 流式后端时，可按同样的 `ElaChatAsyncWorker` 子类模式接入。

""" + self._code_block(LLM_TEST_AGENT_DEMO_SOURCE)
        self._addMarkdown(main_layout, markdown)

    # -- 5. 运行与依赖 -----------------------------------------------------

    def _demoRun(self, main_layout):
        markdown = r"""# 运行与依赖

```powershell
.\.venv\Scripts\Activate.ps1
python llm_test\main.py                       # 默认 mock：无需模型服务
uv pip install openai loguru                  # 真实后端需要（不写入 pyproject.toml）
$env:LLM_TEST_BACKEND="agent"
python llm_test\main.py                       # 真实后端：本地模型服务
python llm_test\agent_demo.py                 # 等价入口（直接起 AgentWorker）
```

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_TEST_BACKEND` | `mock` | `main.py` 后端选择（`agent` / `openai` / `real` 切真实） |
| `LLM_TEST_BASE_URL` | `http://127.0.0.1:8000/v1` | OpenAI 兼容服务地址 |
| `LLM_TEST_MODEL` | `Spark-X2.5-4B-FP8` | 模型名 |
| `LLM_TEST_API_KEY` | `not-needed` | API Key |
| `LLM_TEST_THINKING` | 空（关闭） | 置 `1` / `true` / `yes` / `on` 请求推理输出 |
| `LLM_TEST_WORK_DIR` | `llm_test/workspace` | 工作目录（`demo.txt` 供 `read_file` 演示） |

限制：工具调用是否发生取决于模型能力；`agents/` 副本的依赖（openai / loguru）
只装在本仓库 venv，不属于库的运行时依赖。
"""
        self._addMarkdown(main_layout, markdown)
