"""pytest configuration and fixtures for pyqt6_ela_pro tests."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from _qthelpers import WidgetFactory
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget


@pytest.fixture
def _clipboard_works(qapp) -> bool:
    """剪贴板此刻是否真的可用（**每条用例各探一次**）。

    需要**读回** ``QApplication.clipboard().text()`` 的用例用
    ``requires_clipboard`` fixture；不可用即跳过。

    为什么需要：本机（Windows 会话）实测 ``clipboard().setText("x")`` 之后
    ``text()`` 读回是空串、``ownsClipboard()`` 为 False。这不是代码问题
    （信号发射与设置剪贴板的库代码路径都对，实测 ``formulaCopied`` 收到正确
    值、只是读回为空），但会让 12 个文件里的复制类用例红着 —— 而红着的测试
    是最容易被整体忽略的信号，那时真正的回归也一起被忽略了。

    **必须每条用例各探一次，不能 session 级缓存**：这个剪贴板是**时好时坏**
    的（同一份代码两次整目录运行，挂掉的用例各不相同）。缓存一次探测结果
    等于把「当时能用」当成「现在能用」，于是同一批用例每次挂的都不一样，
    比全红还难查。

    **探测过了也不等于单次写能读回**：实测「探测通过 → 用例里写一次 → 立刻读」
    仍会读到空串，而只轮询永远等不来（被丢弃的那次写不会补发），只有**重发同一个
    动作**才落盘 —— 这类用例用 ``_qthelpers.wait_for_clipboard``，别 ``processEvents()``
    之后直接断言。
    """
    try:
        cb = qapp.clipboard()
    except Exception:
        return False
    token = "__clipboard_probe__"
    # **必须连续多次全部成功才算可用。** Windows 上 ``setText`` 是把数据交给
    # OLE 剪贴板 owner，数据要等事件循环派发完通知才读得到，所以单次往返
    # 本就可能读到旧值；而本会话的剪贴板更进一步 —— 它是**间歇性**坏掉的：
    # 实测同一份代码连跑 6 次，挂掉的复制用例每次都不同（本次会话里
    # ``setText`` 之后 ``text()`` 直接返回空串、``ownsClipboard()`` 为
    # False）。只探一次的话守卫时灵时不灵；探 5 次任一成功就放行也不行
    # （半坏的剪贴板很容易碰巧蒙对一次）。要求 3/3 全过：真能用的剪贴板
    # 每次都过，坏掉的几乎不可能连蒙三次。
    for _ in range(3):
        try:
            cb.setText(token)
        except Exception:
            return False
        ok = False
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            qapp.processEvents()
            if cb.ownsClipboard() and cb.text() == token:
                ok = True
                break
            time.sleep(0.01)
        if not ok:
            return False
    return True


@pytest.fixture
def requires_clipboard(_clipboard_works):
    """依赖剪贴板读回的用例用它；不可用即跳过（而不是红）。"""
    if not _clipboard_works:
        pytest.skip(
            "本会话剪贴板不可用（setText 后读回为空且 ownsClipboard() 为 False）——"
            " 不是代码问题，跳过而不是让用例永久红着"
        )


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """Provide QApplication instance for all tests."""
    app = QApplication.instance()
    if app is None:
        # 必须带程序名：QtWebEngine 的 base::CommandLine 不接受空参数表，
        # `QApplication([])` + 首次 WebEngine 初始化会 fail-fast（bug #18）。
        app = QApplication(["pyqt6-ela-pro-tests"])
    # ``eApp.init()`` **必须在创建任何 ElaWindow 之前**调用（AGENTS.md 的硬约束），
    # 少了这一步 `ElaWindow()` 直接 access violation，且崩在构造那一行、看不出
    # 跟 init 有关。凡是碰 ElaWindow / ElaAppBar 的用例都靠这一行兜住。
    from PyQt6ElaWidgetTools import eApp

    eApp.init()
    yield app


@pytest.fixture(scope="session", autouse=True)
def _motion_full_for_session(qapp):
    """整轮测试把全局动效策略钉在 ``Full``。

    策略默认**跟随系统**（``SPI_GETCLIENTAREAANIMATION``），而跑测的平台不确定
    （仓库里没有任何地方配 ``QT_QPA_PLATFORM``；本机是 ``windows``、无头 CI 常是
    ``offscreen``）。宿主机器若关了动画，``Reduced`` 会把 ``Duration.Normal`` 压到
    50ms，任何 ``assert duration() == Duration.Normal`` 的断言就假失败。
    """
    from pyqt6_ela_pro._motion import ElaMotionModeType, motion

    previous = motion.mode()
    motion.setOverrideSystem(True)
    motion.setMode(ElaMotionModeType.Full)
    yield
    motion.setMode(previous)
    motion.setOverrideSystem(False)


@pytest.fixture
def motion_full(_motion_full_for_session):
    """显式声明本用例依赖 ``Full`` 模式（让意图可见，而不是靠 autouse 兜住）。"""
    return None


@pytest.fixture(autouse=True)
def qt_cleanup(qapp):
    """每个用例的收尾：回收 ``make()`` 登记的控件 + 冲刷 ``deleteLater`` 队列。

    AGENTS.md 约定「``deleteLater()`` 后必须跟 ``qapp.processEvents()``
    才真正销毁」。这条以前靠一千多处人工 ``processEvents()`` 维持，漏写就跨
    测试泄漏控件；现在统一由本 fixture 兜底，所以测试体里不再需要写收尾样板。

    产出的就是 :class:`~_qthelpers.WidgetFactory`，``make`` fixture 是它的别名。
    """
    factory = WidgetFactory(qapp)
    yield factory
    factory.destroy_all()


@pytest.fixture
def make(qt_cleanup):
    """控件工厂：``make(ElaButton, "ok")``，造出来的控件由 ``qt_cleanup`` 统一销毁。

    取代测试体里的 ``w = X(...)`` … ``w.deleteLater()`` 样板。
    """
    return qt_cleanup


@pytest.fixture
def mock_e_theme(mocker):
    """Mock PyQt6ElaWidgetTools.eTheme for isolated testing."""
    mock = mocker.patch("PyQt6ElaWidgetTools.eTheme")
    mock_theme_mode = MagicMock()
    mock_theme_mode.value = 0
    mock.getThemeMode.return_value = mock_theme_mode
    mock.getThemeColor.return_value = "#FFFFFF"
    mock.themeModeChanged = MagicMock()
    return mock


@pytest.fixture
def widget(qapp):
    """Provide a basic QWidget for testing."""
    w = QWidget()
    yield w
    w.deleteLater()


@pytest.fixture
def window_widget(qapp):
    """Provide a widget that can be shown (for animation tests)."""
    w = QWidget()
    w.setWindowFlags(Qt.WindowType.Window)
    w.resize(400, 300)
    yield w
    if w.isVisible():
        w.close()
    w.deleteLater()
