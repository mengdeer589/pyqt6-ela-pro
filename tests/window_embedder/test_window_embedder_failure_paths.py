from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import sip
import pywintypes
from PyQt6.QtCore import QTimer

from pyqt6_ela_pro import window_embedder as we
from pyqt6_ela_pro.window_embedder import (
    _release_on_destroy,
    ElaWindowEmbedder,
)

HWND = 0x1234
INFO = {
    "hwnd": HWND,
    "phwnd": 0,
    "title": "t",
    "class_name": "c",
    "style": 0x00CF0000,
    "exstyle": 0,
    "wrect": (0, 0, 100, 100),
}


def _win32(**overrides) -> MagicMock:
    """够用的 win32gui 替身。

    **别写 ``dict(MagicMock())``** —— 那是 dict不是 mock，属性访问会变成
    ``AttributeError: 'dict' object has no attribute 'IsWindow'``，然后被
    兜底 ``except`` 吞掉，测试「通过」但什么都没验证到。
    """
    fake = MagicMock()
    fake.IsWindow = MagicMock(return_value=True)
    fake.GetWindowLong = MagicMock(return_value=0)
    fake.SetParent = MagicMock()
    fake.SetWindowLong = MagicMock()
    fake.AttachThreadInput = MagicMock()
    fake.ShowWindow = MagicMock()
    fake.SetWindowPos = MagicMock()
    for key, value in overrides.items():
        setattr(fake, key, value)
    return fake


@pytest.fixture
def embedder(make):
    widget = make(ElaWindowEmbedder)
    widget.isWindowValid = lambda h: True
    widget.getWindowInfo = lambda h: dict(INFO)
    return widget


def _embed_env(fake: MagicMock):
    return patch.multiple(
        we,
        win32gui=fake,
        win32api=MagicMock(),
        win32con=MagicMock(),
        win32process=MagicMock(),
    )


class TestTryEmbedOnceNeverRaises:
    """``except`` 块里不许引用可能未绑定的局部变量。"""

    def test_q_window_none(self, embedder):
        """``QWindow.fromWinId`` 对已销毁窗口返回 ``None``。"""
        with _embed_env(_win32()), patch.object(
            we.QWindow, "fromWinId", staticmethod(lambda h: None)
        ):
            assert embedder._tryEmbedOnce(HWND) is False

    def test_container_none(self, embedder):
        """非 top-level HWND 时 ``createWindowContainer`` 返回 ``nullptr``。"""
        with _embed_env(_win32()), patch.object(
            we.QWindow, "fromWinId", staticmethod(lambda h: MagicMock())
        ), patch.object(
            we.QWidget, "createWindowContainer", staticmethod(lambda qw, p: None)
        ):
            assert embedder._tryEmbedOnce(HWND) is False

    def test_window_info_missing_key(self, embedder):
        embedder.getWindowInfo = lambda h: {"hwnd": h}  # 缺 phwnd/style/exstyle/wrect
        with _embed_env(_win32()), patch.object(
            we.QWindow, "fromWinId", staticmethod(lambda h: MagicMock())
        ), patch.object(
            we.QWidget, "createWindowContainer", staticmethod(lambda qw, p: MagicMock())
        ):
            assert embedder._tryEmbedOnce(HWND) is False


class TestPartialContainerIsReclaimed:
    def test_container_deleted_on_failure(self, embedder):
        """容器是 ``self`` 的 child，不删就每次失败泄漏一个（重试最多 30 次）。"""
        container = MagicMock()
        embedder.getWindowInfo = lambda h: {"hwnd": h}  # 在赋属性那步失败
        with _embed_env(_win32()), patch.object(
            we.QWindow, "fromWinId", staticmethod(lambda h: MagicMock())
        ), patch.object(
            we.QWidget,
            "createWindowContainer",
            staticmethod(lambda qw, parent: container),
        ):
            assert embedder._tryEmbedOnce(HWND) is False
        assert container.deleteLater.called, "半成品容器没有被回收"


class TestDebouncedResizeIsGuarded:
    def test_set_window_pos_error_is_contained(self, embedder):
        embedder._embeddedInfo = dict(INFO)
        embedder._embeddedWidget = embedder
        embedder._isEmbedded = True
        boom = _win32(
            SetWindowPos=MagicMock(
                side_effect=pywintypes.error(1400, "SetWindowPos", "bad handle")
            )
        )
        with _embed_env(boom):
            embedder._apply_debounced_resize()  # 不得抛

    def test_error_through_qtimer_slot_does_not_kill_process(self, make, qapp):
        """经真实 ``QTimer`` 槽 —— 这才是原先会 0xC0000409 的路径。"""
        widget = make(ElaWindowEmbedder)
        widget._embeddedInfo = dict(INFO)
        widget._embeddedWidget = widget
        widget._isEmbedded = True
        boom = _win32(
            SetWindowPos=MagicMock(
                side_effect=pywintypes.error(1400, "SetWindowPos", "bad handle")
            )
        )
        with _embed_env(boom):
            timer = QTimer(widget)
            timer.setSingleShot(True)
            timer.timeout.connect(widget._apply_debounced_resize)
            timer.start(5)
            for _ in range(8):
                qapp.processEvents()

    def test_dead_hwnd_gets_no_message(self, embedder):
        """外部窗口已被杀 / 关掉时不该再对它发消息。"""
        embedder._embeddedInfo = dict(INFO)
        embedder._embeddedWidget = embedder
        embedder._isEmbedded = True
        spy = _win32(IsWindow=MagicMock(return_value=False))
        with _embed_env(spy):
            embedder._apply_debounced_resize()
        assert spy.SetWindowPos.call_count == 0


class _AttrRecorder:
    """记录属性赋值的普通对象。

    **不能用 MagicMock** —— 它对任何属性访问都自动造值，``hasattr`` 恒为
    True，那样的断言「无论实现对错都绿」（本条就是这么被写成恒真的）。

    未知属性的**读取**返回 no-op 可调用（``setGeometry`` / ``show`` 等方法
    会被调用），但**写入**照实记录 —— 我们只关心「到底写了哪些名字」。
    """

    def __init__(self):
        object.__setattr__(self, "written", {})
        object.__setattr__(self, "calls", [])

    def __setattr__(self, name, value):
        self.written[name] = value

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _noop(*args, **kwargs):
            self.calls.append(name)
            return None

        return _noop


class TestContainerDoesNotShadowStyle:
    def test_uses_win_style_not_style(self, embedder):
        """``widget.style = ...`` 会**遮蔽 ``QWidget.style()`` 方法**。

        之后宿主（或 Ela 的 C++ 绑定层）任何 ``container.style()`` 都会变成
        ``TypeError: 'int' object is not callable``。
        """
        container = _AttrRecorder()
        with _embed_env(_win32()), patch.object(
            we.QWindow, "fromWinId", staticmethod(lambda h: MagicMock())
        ), patch.object(
            we.QWidget,
            "createWindowContainer",
            staticmethod(lambda qw, parent: container),
        ):
            embedder._tryEmbedOnce(HWND)
        assert "win_style" in container.written, container.written
        assert "win_exstyle" in container.written, container.written
        assert "style" not in container.written, (
            "wrote widget.style again - it shadows QWidget.style()"
        )
        assert "exstyle" not in container.written


class TestReleaseOnDestroy:
    """``destroyed`` 收尾：把外部窗口从 Qt 父 HWND 上摘下来。

    直接调模块级函数而**不** ``sip.delete()`` 整个控件 —— 后者在共享的
    pytest 进程里反复建销顶层控件会撞 Qt 清理竞态（AGENTS.md 记过：
    0xC0000409 静默终止），那样测的是 Qt 不是本函数。
    """

    def test_setparent_zero_called(self):
        calls: list = []
        hook = _win32(
            SetParent=MagicMock(side_effect=lambda *a: calls.append(("SetParent",) + a))
        )
        target = SimpleNamespace(
            _embeddedInfo=dict(INFO), _isEmbedded=True, _attached_tid=None
        )
        with patch.multiple(we, win32gui=hook, win32con=MagicMock()):
            _release_on_destroy(target)
        assert calls == [("SetParent", HWND, 0)], (
            "销毁时没有 SetParent(hwnd, 0) —— 外部窗口会随 Qt 父 HWND 一起销毁"
        )
        assert target._embeddedInfo is None
        assert target._isEmbedded is False

    def test_noop_when_nothing_embedded(self):
        hook = _win32()
        target = SimpleNamespace(
            _embeddedInfo=None, _isEmbedded=False, _attached_tid=None
        )
        with patch.multiple(we, win32gui=hook, win32con=MagicMock()):
            _release_on_destroy(target)
        assert hook.SetParent.call_count == 0

    def test_dead_hwnd_is_not_touched(self):
        hook = _win32(IsWindow=MagicMock(return_value=False))
        target = SimpleNamespace(
            _embeddedInfo=dict(INFO), _isEmbedded=True, _attached_tid=None
        )
        with patch.multiple(we, win32gui=hook, win32con=MagicMock()):
            _release_on_destroy(target)
        assert hook.SetParent.call_count == 0
        assert target._embeddedInfo is None, "状态仍要清干净"

    def test_thread_input_detached(self):
        hook = _win32()
        target = SimpleNamespace(
            _embeddedInfo=dict(INFO), _isEmbedded=True, _attached_tid=4321
        )
        with patch.multiple(
            we, win32gui=hook, win32con=MagicMock(), win32api=MagicMock()
        ):
            _release_on_destroy(target)
        assert hook.AttachThreadInput.called, "AttachThreadInput 没有 detach"
        assert target._attached_tid is None


class TestDestroyHookIsModuleLevel:
    def test_hook_uses_partial_and_weakproxy(self):
        """PyQt5 不调用「绑定到自身」的 ``destroyed`` 槽。

        所以必须是**模块级函数 + ``functools.partial(weakref.proxy(self))``**，
        写成 ``self.destroyed.connect(self._x)`` 等于清理从来没发生过。
        """
        import inspect

        source = inspect.getsource(ElaWindowEmbedder._install_destroy_hook)
        assert "functools.partial" in source
        assert "weakref.proxy" in source
        assert "_release_on_destroy" in source

    def test_hook_is_installed_by_constructor(self, make):
        widget = make(ElaWindowEmbedder)
        # 构造末尾就挂上了；这里只验证「重复调用不会叠连接」
        widget._install_destroy_hook()
        widget._install_destroy_hook()
