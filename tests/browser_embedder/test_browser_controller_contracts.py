"""``_BrowserController`` 的外部输入面与生命周期契约。

CDP 通道是**外部输入**入口：``--remote-debugging-port`` 绑 127.0.0.1，
任何本地进程都能连上发任意 JSON。所以「格式合法」不等于「类型合法」。

三条：

1. ``_on_text_message`` 整段必须有兜底 —— 它是 ``textMessageReceived`` 槽，
   抛出去 = 进程 0xC0000409 零traceback 终止；
2. ``msg_id`` 必须校验类型 —— 原先直接当 dict key 用，
   ``{"id": []}`` 抛 ``TypeError: unhashable type: 'list'``（实测复现）；
3. controller 与 QWebSocket 必须挂 parent —— 否则 embedder 走 C++ 析构路径时
   它们存活下来继续收消息，而 ``_log_func`` 是宿主 embedder 的直接 Python
   引用（不是信号）→ ``RuntimeError``。
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import weakref
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro import browser_embedder as be
from pyqt6_ela_pro.browser_embedder import _BrowserController

URL = "ws://127.0.0.1:9222/devtools/page/stub"


def destroy_hook():
    """惰性取析构收尾钩子。

    顶层 ``from ... import _release_browser_on_destroy`` 在符号缺失时会变成
    **collection error**，整份文件一条都跑不到 —— 回退验证因此只能看到 1 个
    ImportError 而看不到真正的断言失败。这里改成断言，让每条用例各自转红。
    """
    fn = getattr(be, "_release_browser_on_destroy", None)
    assert fn is not None, "_release_browser_on_destroy 缺失（析构收尾钩子）"
    return fn


@pytest.fixture
def controller(make):
    ctrl = make(_BrowserController, URL)
    ctrl._log_calls: list = []
    ctrl._log = lambda msg, level=30: ctrl._log_calls.append(msg)  # type: ignore[method-assign]
    return ctrl


class TestUnhashableResponseId:
    """``{"id": []}`` 原先抛 TypeError 并穿出 Qt 槽。"""

    @pytest.mark.parametrize(
        "bad_id",
        [[], {}, "1", 1.5, None, True, False],
        ids=["list", "dict", "str", "float", "null", "true", "false"],
    )
    def test_bad_id_type_is_ignored(self, controller, bad_id):
        seen: list = []
        controller._callbacks[1] = seen.append
        controller._on_text_message(json.dumps({"id": bad_id, "result": {"v": 1}}))
        # 不得抛；且**不得**把回调误消费掉
        assert seen == [], f"非法 id {bad_id!r} 触发了回调"
        assert list(controller._callbacks) == [1], "非法 id 把回调误弹出了"

    def test_bool_id_does_not_alias_int_one(self, controller):
        """``True == 1`` 且 ``hash(True) == hash(1)`` —— 不显式拒就会误匹配。"""
        seen: list = []
        controller._callbacks[1] = seen.append
        controller._on_text_message(json.dumps({"id": True, "result": {"v": 1}}))
        assert seen == []

    def test_valid_int_id_still_dispatches(self, controller):
        seen: list = []
        controller._callbacks[1] = seen.append
        controller._on_text_message(json.dumps({"id": 1, "result": {"ok": True}}))
        assert seen == [{"ok": True}]
        assert controller._callbacks == {}


class TestMessageEntryIsFullyGuarded:
    @pytest.mark.parametrize(
        "raw",
        ["not json", "[1,2,3]", '"a string"', "null", "123", ""],
        ids=["garbage", "list", "str", "null", "number", "empty"],
    )
    def test_non_command_payloads_are_ignored(self, controller, raw):
        controller._on_text_message(raw)  # 不得抛

    def test_log_func_raising_does_not_escape(self, controller):
        """``_log_func`` 是宿主 embedder 的直接 Python 引用，销毁后会抛。"""
        controller._log = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("wrapped C/C++ object has been deleted")
        )
        controller._on_text_message(json.dumps({"id": 5, "result": {}}))
        controller._on_text_message("not json")

    def test_error_response_is_handled(self, controller):
        controller._on_text_message(json.dumps({"id": 1, "error": {"code": -1}}))

    def test_event_without_id_goes_to_handle_event(self, controller):
        seen: list = []
        controller._handle_event = lambda m, p: seen.append((m, p))  # type: ignore[method-assign]
        controller._on_text_message(
            json.dumps({"method": "Page.loadEventFired", "params": {}})
        )
        assert seen == [("Page.loadEventFired", {})]

    def test_handler_exception_is_contained(self, controller):
        controller._handle_event = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom")
        )
        controller._on_text_message(
            json.dumps({"method": "Page.loadEventFired", "params": {}})
        )


class TestParentChain:
    def test_controller_takes_parent(self, make):
        host = make(QWidget)
        ctrl = make(_BrowserController, URL, None, None, "", host)
        assert ctrl.parent() is host

    def test_websocket_is_parented_to_controller(self, make):
        host = make(QWidget)
        ctrl = make(_BrowserController, URL, None, None, "", host)
        ctrl.connect()
        try:
            assert ctrl._ws is not None
            # **PyQt5 的签名是 QWebSocket(origin, version, parent)** ——
            # ``QWebSocket(ctrl)`` 会把 controller 当 origin 塞进去而 TypeError
            assert ctrl._ws.parent() is ctrl
        finally:
            ctrl.close()


class TestDestroyHook:
    def test_calls_release(self):
        calls: list = []
        fake = MagicMock()
        fake.release = lambda: calls.append("release")
        destroy_hook()(fake)
        assert calls == ["release"]

    def test_missing_release_is_noop(self):
        destroy_hook()(MagicMock(spec=[]))

    def test_raising_release_is_contained(self):
        fake = MagicMock()
        fake.release = MagicMock(side_effect=RuntimeError("boom"))
        destroy_hook()(fake)

    def test_dead_proxy_is_contained(self):
        class Target:
            def release(self):  # pragma: no cover - 不会被调用
                raise AssertionError("不该走到这里")

        target = Target()
        proxy = weakref.proxy(target)
        del target
        destroy_hook()(proxy)  # 不得抛

    def test_constructor_installs_hook(self):
        source = inspect.getsource(be.ElaBrowserEmbedder.__init__)
        assert "functools.partial" in source
        assert "weakref.proxy" in source
        assert "_release_browser_on_destroy" in source


class TestWindowWaitTimeoutEmitsSignals:
    """等待浏览器窗口超时必须发对外信号。

    原先只 ``_log`` + ``finish_launch``，``embedCompleted`` /
    ``embedTimeout`` / ``embedError`` 一个都不发 —— 只监听
    ``embedCompleted`` 的宿主（示例 ``embed_page.py`` 就是）会**永久等待**。
    对照 ``_do_debug_url_request`` 的超时路径是会发
    ``embedCompleted.emit(False)`` 的，两条超时路径不一致。
    """

    def test_timeout_branch_emits(self):
        source = pathlib.Path(be.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_poll_hwnd"
        )
        body = ast.unparse(fn)
        assert "self.embedTimeout.emit()" in body
        assert "self.embedCompleted.emit(False)" in body
        assert "self.embedError.emit(" in body
        assert "self._session.finish_launch(self)" in body

    def test_timeout_signal_is_declared(self):
        assert hasattr(be.ElaBrowserEmbedder, "embedTimeout")