"""llm_test 入口：后端选择（mock / agent）的离线冒烟测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

#: 仓库根目录（tests/example/ → 上两级）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

#: llm_test/ 目前不入库（见 .gitignore：agents/config.py 里有硬编码 key）。
#: 全新 clone 上没有这个目录，模块级 import 会让整个 tests/example 收集失败。
if not (_REPO_ROOT / "llm_test" / "main.py").is_file():
    pytest.skip("llm_test/ 未入库", allow_module_level=True)

import llm_test.agent_demo as agent_demo  # noqa: E402
from llm_test.main import DemoWindow, classify_error, create_worker  # noqa: E402

from pyqt6_ela_pro.chat import ElaChatMockBackend, ElaChatRoleType  # noqa: E402


class TestCreateWorker:
    def test_default_backend_is_mock(self, qapp, monkeypatch):
        monkeypatch.delenv("LLM_TEST_BACKEND", raising=False)

        worker = create_worker()
        assert isinstance(worker, ElaChatMockBackend)
        worker.deleteLater()
        qapp.processEvents()

    def test_agent_backend_uses_agents_copy(self, qapp, monkeypatch):
        pytest.importorskip("openai")
        pytest.importorskip("loguru")
        monkeypatch.setenv("LLM_TEST_BACKEND", "agent")

        worker = create_worker()
        assert isinstance(worker, agent_demo.AgentWorker)
        worker.shutdown()
        worker.deleteLater()
        qapp.processEvents()

    def test_agent_worker_wires_on_error(self):
        """**必须接** ``on_error``，否则 API 错误被 agents 静默吞掉。

        agents 把所有 API 异常编码成 ``__ERROR__:<类型>:<文案>`` 哨兵字符串
        yield 出来（**不抛异常**），唯一出口就是 ``AgentCallbacks.on_error``
        （``agents/agent.py:1013-1019``），随后直接 ``return`` 结束流。漏接的
        症状：回合没有正文、也没有错误，界面只剩「模型未返回正文」。
        """
        import inspect

        source = inspect.getsource(agent_demo.AgentWorker._setup)
        assert "on_error=" in source, "AgentWorker 必须把 on_error 接到 errorOccurred"
        assert "errorOccurred.emit" in source


class TestClearContextWiring:
    """清空上下文 = 组件清界面 + 宿主 reset 后端（少了后端那半模型还记得上文）。"""

    def test_cleared_resets_worker(self, qapp):

        worker = ElaChatMockBackend()
        window = DemoWindow(worker)
        calls = []
        worker.reset = lambda: calls.append(1)  # 覆盖实例方法做探针

        window.chat.addMessage(1, "你好")
        qapp.processEvents()
        window.chat.clear()
        qapp.processEvents()

        assert calls == [1]
        assert window.chat.chatView().messages() == []
        window.deleteLater()
        worker.deleteLater()
        qapp.processEvents()


class TestClassifyError:
    """错误类型归一：决定错误卡的「重试」按钮亮不亮。

    ``ElaChatAsyncWorker`` 恒发 ``("worker", "ExcName: 文案")``，不归一的话真实
    后端上「重试」永远不会出现（``RETRYABLE_ERROR_TYPES`` 里没有 ``worker``）。
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # 抛异常的路径：异常类名拼在文案最前
            ("APITimeoutError: Request timed out", "timeout"),
            ("RateLimitError: 429 Too Many Requests", "ratelimit"),
            ("APIConnectionError: Connection error", "network"),
            ("InternalServerError: 500", "overloaded"),
            # 哨兵路径：agents 不抛异常，上报 "<类型>: <文案>"
            ("api_timeout: LLM 请求超时", "timeout"),
            ("api_rate_limit: 请求频率超限", "ratelimit"),
            ("api_connection: 无法连接到 LLM 服务", "network"),
            ("api_server_error: 服务端错误(5xx)", "overloaded"),
        ],
    )
    def test_retryable_names_are_mapped(self, raw, expected):
        assert classify_error("worker", raw) == expected

    @pytest.mark.parametrize(
        "raw",
        ["AuthenticationError: x", "api_auth: API 密钥认证失败", "api_bad_request: y"],
    )
    def test_non_retryable_keeps_original(self, raw):
        """鉴权 / 参数错误不该给「重试」：换次机会只会再失败一次。"""
        assert classify_error("worker", raw) == "worker"


class TestErrorAndStatusWiring:
    """错误与状态必须有**可见**反馈，而不是只进 stdout。"""

    def _window(self, qapp, tickMs=60_000):
        # tick 默认调很大：mock 回合在本用例里不推进（否则 processEvents 会把它
        # 跑完，顺手改变消息 id 与 binder 的落点）
        worker = ElaChatMockBackend(tickMs=tickMs)
        window = DemoWindow(worker)
        qapp.processEvents()
        return window, worker

    def _turn(self, window, prompt="hi"):
        """造一个「用户提问 + 正在流式的助手消息」，返回 ``(userId, mid, turn)``。

        ``turn`` 是回合 token（``turnFinished`` 原样带回，``binder.finish`` 靠它
        认领收尾）。不走 ``sendUserMessage``：它会发 ``messageSubmitted``，宿主槽
        真的起一轮，消息 id 与 binder 落点都会多出一层（测试要的就是「一次正常的
        回合」）。
        """
        view = window.chat.chatView()
        userId = view.addMessage(ElaChatRoleType.User, prompt)
        turn = window.binder.startTurn(prompt)
        assert turn is not None
        return userId, window.chat.streamingMessageId(), turn

    def _teardown(self, qapp, window, worker):
        window.deleteLater()
        worker.deleteLater()
        qapp.processEvents()

    def test_status_bar_reports_backend(self, qapp):
        window, worker = self._window(qapp, tickMs=0)
        assert window.status.info() == "mock 后端 · tick 0 ms"
        self._teardown(qapp, window, worker)

    def test_status_info_override_wins(self, qapp):
        """真实后端传入「模型 @ 地址」——连接失败时要先确认连的哪个地址。"""
        worker = ElaChatMockBackend(tickMs=0)
        window = DemoWindow(worker, statusInfo="model-x @ 127.0.0.1:8000/v1")
        qapp.processEvents()
        assert window.status.info() == "model-x @ 127.0.0.1:8000/v1"
        self._teardown(qapp, window, worker)

    def test_ready_switches_status_to_success(self, qapp):
        window, worker = self._window(qapp)
        window.on_ready()
        assert window.status.level() == "success"
        assert "就绪" in window.status.status()
        self._teardown(qapp, window, worker)

    def test_failed_surfaces_in_status_and_transcript(self, qapp):
        """初始化失败没有回合可落错误卡 → 状态栏 + 系统消息（否则界面全空）。"""
        window, worker = self._window(qapp)
        window.on_failed("缺 openai 依赖")

        assert window.status.level() == "error"
        assert "缺 openai 依赖" in window.status.status()
        messages = window.chat.chatView().messages()
        assert len(messages) == 1
        assert messages[0].role == "system"
        assert "缺 openai 依赖" in messages[0].text

        self._teardown(qapp, window, worker)

    def test_turn_error_lands_on_card_and_lights_retry(self, qapp):
        window, worker = self._window(qapp)
        _userId, mid, _turn = self._turn(window)
        window.on_error("worker", "APITimeoutError: Request timed out")

        view = window.chat.chatView()
        assert view.messageError(mid) == (
            "APITimeoutError: Request timed out",
            "timeout",
        )
        assert view.bubble(mid).errorCard().canRetry() is True
        assert window.status.level() == "error"

        self._teardown(qapp, window, worker)

    def test_turn_finished_reports_error_not_done(self, qapp):
        """错误回合收尾不能显示「完成」——靠 ``_turn_failed`` 标记而不是摘要。"""
        window, worker = self._window(qapp)
        _userId, mid, turn = self._turn(window)
        window.on_error("worker", "APIConnectionError: Connection error")
        window.on_turn_finished(turn)

        assert window.status.level() == "error"
        assert "重试" in window.status.status()

        self._teardown(qapp, window, worker)

    def test_retry_requested_resends_same_prompt(self, qapp):
        window, worker = self._window(qapp)
        userId, mid, _turn = self._turn(window, "再试一次")
        window.chat.chatView().setMessageError(mid, "超时", "timeout")

        sent = []
        window.start_turn = (
            lambda prompt, attachments=None, regenerate=False: sent.append(prompt)
        )
        window.chat.retryRequested.emit(mid)

        assert sent == ["再试一次"]
        # 消息位置保留（不删），错误被清掉 —— 这正是「重试」与「重新生成」的区别
        assert [m.id for m in window.chat.chatView().messages()] == [userId, mid]
        assert window.chat.chatView().messageError(mid) == ("", "")

        self._teardown(qapp, window, worker)

    def test_regenerate_forwards_attachments(self, qapp):
        """重新生成必须把提问快照里的附件一起交给后端。

        回归：``regenerateFrom`` 返回的快照带着附件，但 ``startTurn`` 原先没有
        attachments 通道，宿主只能传文本 —— 重新生成后模型看不见用户上传的文件。
        """
        window, worker = self._window(qapp)
        view = window.chat.chatView()
        userId = view.addMessage(ElaChatRoleType.User, "看图")
        view.setMessageAttachments(userId, [{"name": "a.png", "path": "C:/a.png"}])
        mid = window.chat.beginAssistantMessage()
        window.binder.beginTurn()

        sent = []
        window.start_turn = (
            lambda prompt, attachments=None, regenerate=False: sent.append(
                (prompt, [a.name for a in (attachments or ())], regenerate)
            )
        )
        window.chat.regenerateRequested.emit(mid)

        assert sent == [("看图", ["a.png"], True)]
        self._teardown(qapp, window, worker)

    def test_retry_without_user_message_reports(self, qapp):
        window, worker = self._window(qapp)
        mid = window.chat.beginAssistantMessage()
        window.chat.chatView().setMessageError(mid, "超时", "timeout")

        window.chat.retryRequested.emit(mid)

        assert window.status.level() == "error"
        assert "可重试" in window.status.status()

        self._teardown(qapp, window, worker)
