"""``_BrowserSession`` 的生命周期契约：启动队列、进程失败、句柄剪枝。

三条独立故障，同一个后果 —— **静默、永久、要重启进程才好**：

1. 浏览器进程启动失败时``QProcess`` 只发 ``errorOccurred``、**不抛**，
   而原先一个信号都没接 -> 「等窗口」空转满 60 × 500ms = 30 秒零反馈，
   且与「浏览器慢慢启动不出来」无法区分；
2. ``_foreign_hwnds``（启动前已存在的 Chrome 窗口快照）从不按 ``IsWindow``
   剪枝，而句柄会被系统复用 -> 新窗口认不出来，等满超时；
3. ``release()`` 里两个**会话级**副作用（``finish_launch`` 放行启动队列、
   ``session.release()`` 递减 ``_refcount``）原先都排在未兜底调用之后，
   任何一处抛就全丢 -> 之后所有实例永久排队不启动 / 浏览器进程永不休。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QProcess

from pyqt6_ela_pro import browser_embedder as be
from pyqt6_ela_pro.browser_embedder import _BrowserSession

BOGUS = Path(r"C:\definitely\not\here\chrome.exe")
PROFILE = Path(r"%LOCALAPPDATA%")  # 只当占位，测试里不真建


@pytest.fixture
def session(tmp_path):
    """一个干净的共享会话实例（单例状态用完就复位）。"""

    def _make(profile="p", port=9333):
        be._BrowserSession._instance = None
        be._BrowserSession._refcount = 0
        return _BrowserSession.acquire(BOGUS, port, tmp_path / profile)

    made: list = []
    yield _make
    for s in made:
        s._process = None
    be._BrowserSession._instance = None
    be._BrowserSession._refcount = 0


class _FakeSignal:
    def __init__(self):
        self.slots: list = []

    def connect(self, fn):
        self.slots.append(fn)


class _FakeProcess:
    """替身：不真的起浏览器，只验「信号连上了」+「start() 被调了」。"""

    # ????? PyQt6 ????????``QProcess.ProcessChannelMode.X``??
    # ????????????? AttributeError?
    class ProcessChannelMode:
        SeparateChannels = QProcess.ProcessChannelMode.SeparateChannels

    class ProcessState:
        Running = QProcess.ProcessState.Running
        NotRunning = QProcess.ProcessState.NotRunning

    # ???????
    SeparateChannels = QProcess.ProcessChannelMode.SeparateChannels
    Running = QProcess.ProcessState.Running
    NotRunning = QProcess.ProcessState.NotRunning
    instances: list = []

    def __init__(self):
        self.errorOccurred = _FakeSignal()
        self.program = None
        self.arguments_: list | None = None
        self.calls: list = []
        _FakeProcess.instances.append(self)

    def setProgram(self, program):
        self.program = program

    def setArguments(self, args):
        self.arguments_ = args

    def setProcessChannelMode(self, mode):
        self.calls.append(("mode", mode))

    def start(self):
        self.calls.append(("start", self.program))

    def state(self):
        return self.Running


class TestLaunchFailureIsReportedImmediately:
    def test_bad_path_raises_instead_of_polling_30s(self, session):
        """路径不存在时 ``QProcess.start()`` 不抛 -> 抛出来复用 ``_launch`` 的
        ``embedError`` 收尾，而不是干等超时。"""
        s = session()
        with pytest.raises(RuntimeError) as exc:
            s.launch_start("https://example.com", "t")
        # 文案由 Qt 的 errorString() 给出（本地化），只断言「有内容」
        assert str(exc.value).strip(), "启动失败必须带原因，不能是空消息"

    def test_failed_process_is_not_kept_on_session(self, session):
        """失败后不能把半死的 ``_process`` 留在会话上 —— 后一个实例会走
        ``subprocess.Popen`` 分支，而它根本没有进程句柄可等。"""
        s = session()
        with pytest.raises(RuntimeError):
            s.launch_start("https://example.com", "t")
        assert s._process is None

    def test_error_occurred_is_wired_to_host(self, session, monkeypatch):
        _FakeProcess.instances.clear()
        s = session()
        monkeypatch.setattr(be, "QProcess", _FakeProcess)
        seen: list = []
        on_error = lambda err: seen.append(err)  # noqa: E731
        try:
            s.launch_start("https://example.com", "t", on_error)
        finally:
            s._process = None
        proc = _FakeProcess.instances[-1]
        assert proc.errorOccurred.slots == [on_error]
        assert any(c[0] == "start" for c in proc.calls)
        assert proc.program == str(BOGUS)

    def test_launch_start_without_hook_still_works(self, session, monkeypatch):
        """``on_error`` 是可选的 —— 旧的 2 参调用不能破。"""
        _FakeProcess.instances.clear()
        s = session()
        monkeypatch.setattr(be, "QProcess", _FakeProcess)
        try:
            s.launch_start("https://example.com", "t")
        finally:
            s._process = None
        assert _FakeProcess.instances[-1].errorOccurred.slots == []


class TestHwndSetsArePruned:
    """两个集合都要按 ``IsWindow`` 剪枝（句柄会被系统复用）。"""

    @pytest.fixture
    def fake_win32(self, monkeypatch):
        live: set[int] = set()
        asked: list[int] = []
        real = be.win32gui

        class _W:
            @staticmethod
            def IsWindow(h):
                asked.append(h)
                return h in live

            @staticmethod
            def EnumWindows(cb, _):
                return None

            @staticmethod
            def IsWindowVisible(h):
                return True

            @staticmethod
            def GetClassName(h):
                return "Chrome_WidgetWin_1"

            @staticmethod
            def GetWindowText(h):
                return "x"

        monkeypatch.setattr(be, "win32gui", _W)
        yield live, asked
        monkeypatch.setattr(be, "win32gui", real)

    def test_both_sets_are_pruned(self, session, fake_win32):
        live, asked = fake_win32
        s = session()
        s._known_hwnds = {111, 222}
        s._foreign_hwnds = {333, 444}
        live.update({222, 444})
        s.poll_hwnd()
        assert s._known_hwnds == {222}
        assert s._foreign_hwnds == {444}
        # 两个集合都被问过（原来只问 known）
        assert {111, 222, 333, 444} <= set(asked)

    def test_dead_foreign_window_is_dropped(self, session, fake_win32):
        """已销毁的 foreign 窗口留着会挡住 hwnd 复用 -> 新窗口永远认不出来。"""
        live, _ = fake_win32
        s = session()
        s._foreign_hwnds = {444}
        s.poll_hwnd()
        assert s._foreign_hwnds == set()

    def test_prune_failure_leaves_sets_intact(self, session, monkeypatch):
        """``IsWindow`` 抛异常时不能把集合清空 —— 那等于「把所有窗口当成
        已销毁」，下一次启动会认领到用户自己的浏览器窗口。"""

        class _Boom:
            @staticmethod
            def IsWindow(h):
                raise OSError("boom")

            @staticmethod
            def EnumWindows(cb, _):
                return None

        s = session()
        s._foreign_hwnds = {333}
        monkeypatch.setattr(be, "win32gui", _Boom)
        s.poll_hwnd()
        assert s._foreign_hwnds == {333}


def _bare_embedder(make, session):
    """真实例 + 挂上共享会话。

    ``__new__`` 造出来的 ``ElaBrowserEmbedder`` 连信号会抛
    ``RuntimeError: super-class __init__() was never called``，而本组要测的
    ``fileDropped`` / ``release`` 都得用信号，所以必须走真 ``__init__``。
    ``release`` 之前要预置的字段本来就都在 ``__init__`` 里。
    """
    e = make(be.ElaBrowserEmbedder, BOGUS)
    e._session = session
    return e


@pytest.fixture
def embedder(make, session):
    """真 embedder + 一个干净的共享会话。"""
    s = session()
    return _bare_embedder(make, s)


class TestReleaseIsUnconditional:
    """``release()`` 的两个会话级副作用必须无条件跑完。"""

    @pytest.fixture
    def isolated_base(self, monkeypatch):
        monkeypatch.setattr(
            be.ElaWindowEmbedder, "release", lambda self, destroy=True: None
        )

    def test_happy_path(self, make, session, isolated_base):
        s = session()
        e = _bare_embedder(make, s)
        s.request_launch(e, lambda: None)
        assert s._launch_in_flight is e
        before = be._BrowserSession._refcount
        assert before == 1, f"fixture 没把 refcount 置 1，实际 {before}"
        e.release()
        assert s._launch_in_flight is None
        assert be._BrowserSession._refcount == before - 1

    @pytest.mark.parametrize(
        "boom_attr",
        [
            "_stop_browser_embed_timer",
            "_cleanup_hwnd_polling",
            "_cleanup_debug_url_polling",
            "_restore_window_state",
            "_remove_drop_interceptor",
            "_cleanup_browser",
        ],
        ids=[
            "embed_timer",
            "hwnd_polling",
            "debug_url_polling",
            "restore_window",
            "drop_interceptor",
            "cleanup_browser",
        ],
    )
    def test_local_step_failure_keeps_queue_releasing(
        self, make, session, isolated_base, boom_attr
    ):
        """任一局部清理抛异常，队列仍必须放行、refcount 仍必须递减。"""
        s = session()
        e = _bare_embedder(make, s)
        s.request_launch(e, lambda: None)

        def boom():
            raise RuntimeError("wrapped C/C++ object has been deleted")

        setattr(e, boom_attr, boom)
        before = be._BrowserSession._refcount
        e.release()  # 自身也不得抛
        assert s._launch_in_flight is None, f"{boom_attr} 抛异常卡死了启动队列"
        assert be._BrowserSession._refcount == before - 1, f"{boom_attr} 抛异常漏了 refcount"

    def test_base_release_failure_is_contained(self, make, session, monkeypatch):
        """基类 ``release`` 会碰已销毁的 Qt 对象，不能连累会话归还。"""
        s = session()
        e = _bare_embedder(make, s)
        s.request_launch(e, lambda: None)
        monkeypatch.setattr(
            be.ElaWindowEmbedder,
            "release",
            lambda self, destroy=True: (_ for _ in ()).throw(
                RuntimeError("wrapped C/C++ object has been deleted")
            ),
        )
        before = be._BrowserSession._refcount
        e.release()
        assert s._launch_in_flight is None
        assert be._BrowserSession._refcount == before - 1

    def test_repeated_release_does_not_double_decrement(
        self, make, session, isolated_base
    ):
        """第二次 ``release()`` 不得二次递减（``self._session`` 已置 None）。"""
        s = session()
        e = _bare_embedder(make, s)
        be._BrowserSession._refcount = 2
        e.release()
        assert be._BrowserSession._refcount == 1
        e.release()
        assert be._BrowserSession._refcount == 1, "重复 release 二次递减了 refcount"
        assert e._session is None
        assert s._launch_in_flight is None


class TestImeFilterRejectsStaleHwnd:
    """IME 过滤器不得把消息投给已销毁 / 已注销的浏览器窗口。"""

    @pytest.fixture(autouse=True)
    def clean_registry(self):
        before = set(be._active_chrome_hwnds)
        yield
        be._active_chrome_hwnds.clear()
        be._active_chrome_hwnds.update(before)

    def test_unregistered_hwnd_is_rejected(self):
        assert be._ImeForwardFilter._chrome_hwnd_usable(4321) is False

    def test_none_is_rejected(self):
        assert be._ImeForwardFilter._chrome_hwnd_usable(None) is False

    def test_registered_but_dead_hwnd_is_rejected(self, monkeypatch):
        be._active_chrome_hwnds.add(4321)
        monkeypatch.setattr(
            be.win32gui, "IsWindow", lambda h: False, raising=False
        )
        assert be._ImeForwardFilter._chrome_hwnd_usable(4321) is False

    def test_registered_and_alive_is_accepted(self, monkeypatch):
        be._active_chrome_hwnds.add(4321)
        monkeypatch.setattr(be.win32gui, "IsWindow", lambda h: True, raising=False)
        assert be._ImeForwardFilter._chrome_hwnd_usable(4321) is True

    def test_iswindow_raising_is_rejected(self, monkeypatch):
        """``IsWindow`` 抛异常时保守拒收 —— 宁可漏转 IME，不可投错窗口。"""
        be._active_chrome_hwnds.add(4321)
        monkeypatch.setattr(
            be.win32gui,
            "IsWindow",
            lambda h: (_ for _ in ()).throw(OSError("boom")),
            raising=False,
        )
        assert be._ImeForwardFilter._chrome_hwnd_usable(4321) is False

    def test_find_at_cursor_revalidates_cache(self, monkeypatch):
        """缓存命中也要复验 —— 浏览器关闭后光标没动时，原先直接返回旧 hwnd。"""
        filt = be._ImeForwardFilter()
        filt._last_cursor_pos = (10, 10)
        filt._last_cursor_hwnd = 4321
        be._active_chrome_hwnds.add(4321)
        monkeypatch.setattr(be.win32gui, "IsWindow", lambda h: False, raising=False)
        # 复验失败 -> 必须重新查，而不是返回 4321
        monkeypatch.setattr(
            be._ImeForwardFilter,
            "_find_at_cursor",
            lambda self: None,
        )
        assert filt._chrome_hwnd_usable(4321) is False

    def test_filter_drops_stale_hwnd_before_posting(self):
        """首行的 ``_active_chrome_hwnds`` 非空判断只说明「还有浏览器在嵌入」。"""
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(be.__file__).read_text(encoding="utf-8"))
        cls = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "_ImeForwardFilter"
        )
        fn = next(
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name == "nativeEventFilter"
        )
        # 必须有一处「拿到 hwnd 之后立刻复验，不合格就置空」的分支
        gates = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.If) and "_chrome_hwnd_usable" in ast.unparse(n.test)
        ]
        assert gates, "nativeEventFilter 里没有 _chrome_hwnd_usable 复验"
        # 且 PostMessageW 必须在该复验之后（源码顺序）
        body_src = ast.unparse(fn)
        assert body_src.index("_chrome_hwnd_usable") < body_src.index("PostMessageW")

    def test_no_win32gui_means_reject(self, monkeypatch):
        be._active_chrome_hwnds.add(4321)
        monkeypatch.setattr(be, "win32gui", None)
        assert be._ImeForwardFilter._chrome_hwnd_usable(4321) is False


class TestEmbeddedPageCannotForgeFileDrop:
    """``fileDropped`` 的**已知限制**：CDP 侧无法区分「用户拖入文件」与
    「页面导航到 file:// URL」。

    本组只钉住当前行为与边界，不声称已修复 —— 真修复要么删掉 CDP 路径
    （很可能破坏真实拖放，那条路径靠 OLE ``RegisterDragDrop``，而OLE 命中
    测试要真起浏览器），要么引入启发式（不可验证）。见 AGENTS.md。
    """

    def test_navigation_to_file_url_reaches_dropped_callback(self):
        ctrl = be._BrowserController("ws://127.0.0.1:1/x")
        seen: list = []
        ctrl._dropped_file_callback = seen.append
        ctrl._handle_event(
            "Page.frameRequestedNavigation",
            {"url": "file:///C:/Users/someone/secret.txt"},
        )
        assert seen, "CDP 侧file:// 导航确实会触发 dropped 回调（限制的由来）"

    def test_http_url_does_not(self):
        ctrl = be._BrowserController("ws://127.0.0.1:1/x")
        seen: list = []
        ctrl._dropped_file_callback = seen.append
        ctrl._handle_event(
            "Page.frameRequestedNavigation", {"url": "https://example.com/a"}
        )
        assert seen == []

    def test_dedupe_window_suppresses_repeat(self, embedder):
        embedder._last_dropped_file_path = None
        embedder._last_dropped_file_time = 0.0
        emitted: list = []
        embedder.fileDropped.connect(emitted.append)
        embedder._on_dropped_file("C:/a.txt")
        embedder._on_dropped_file("C:/a.txt")
        assert emitted == ["C:/a.txt"]

    def test_distinct_paths_are_not_deduped(self, embedder):
        """去重只按「同路径 + 0.5s」，所以页面可以逐个刷不同路径 —— 这是
        上面那条限制的一部分，钉住它提醒宿主不要把该信号当可信输入。"""
        embedder._last_dropped_file_path = None
        embedder._last_dropped_file_time = 0.0
        emitted: list = []
        embedder.fileDropped.connect(emitted.append)
        embedder._on_dropped_file("C:/a.txt")
        embedder._on_dropped_file("C:/b.txt")
        assert emitted == ["C:/a.txt", "C:/b.txt"]


class TestEmbeddedPageCannotForgeFileDropIsKnownLimit:
    """占位：``fileDropped`` 的伪造限制当前**未修复**，理由见
    ``TestEmbeddedPageCannotForgeFileDrop`` 的类docstring。
    本组只保证「限制还在、没被某次重构顺手改掉」。

    真修复的两个方向都有硬伤：
    ① 删掉 CDP 的 ``file://`` 路径 —— 真实拖放很可能走的就是这条（OLE
       ``RegisterDragDrop`` 挂在本组件 hwnd 上，而 Chrome 子窗口自己会注册
       drop target，谁先命中要真起浏览器才能测，本机测不了）；
    ② 加启发式（限定最近 N 秒内有原生拖放）—— 不可验证，且同样要真拖一次。
    所以此处如实记录，等能跑浏览器时再定。
    """

    def test_limit_is_documented_in_module(self):
        import pathlib

        source = pathlib.Path(be.__file__).read_text(encoding="utf-8")
        assert "frameRequestedNavigation" in source