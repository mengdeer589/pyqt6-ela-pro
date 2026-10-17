"""托盘示例页的接入行为测试。

守两个曾经坏掉的行为：
① 托盘菜单「划词助手」项要真能找到划词页并切换（曾依赖不存在的
   ``window._page_map``，导致该项永远打空）；
② 托盘菜单「退出」要真结束进程（曾只打日志）。

**刻意不构造完整 ``ExampleWindow``** —— 它会把浏览器嵌入等重页面一并建起来
（``concurrent.futures`` 线程 + 原生窗口），在 pytest 里实测 access violation。
这里用最小 ``ElaWindow`` 只挂这两个页面，``addPageNode`` 的 reparent 行为一致。

（原 ``tray_page.py`` 的 ``TrayIconPage`` 已并入 ``app_shell_page.py`` 的
``AppShellPage`` —— 启动画面 / 任务栏进度 / 托盘回答的是同一个问题：
「我的程序怎么在系统里露出存在」。）
"""

from __future__ import annotations

import pytest
from PyQt6ElaWidgetTools import ElaIconType, ElaText, ElaWindow

from pyqt6_ela_pro import ElaButton, ElaTrayIcon
from pyqt6_ela_pro.example.app_shell_page import AppShellPage
from pyqt6_ela_pro.example.selection_page import SelectionAssistantPage


@pytest.fixture(scope="module")
def env(qapp):
    """最小主窗口：只挂托盘页 + 划词页（够验证 reparent 后的 findChildren）。"""
    window = ElaWindow()
    sel = SelectionAssistantPage(window)
    tray = AppShellPage(window)
    # 示例页内容惰性构建；本守卫不经过 make fixture，显式构建（页面在窗口里不会全部显示）
    sel.buildDemoContent()
    tray.buildDemoContent()
    window.addPageNode("划词助手", sel, ElaIconType.IconName.Highlighter)
    window.addPageNode("启动与托盘", tray, ElaIconType.IconName.Plug)
    window.show()
    qapp.processEvents()
    yield window, tray, sel
    window.deleteLater()
    qapp.processEvents()


def _labels(host):
    return [a.text() for a in host.trayIcon().menu().actions() if a.text()]


def _click(host, text):
    for action in host.trayIcon().menu().actions():
        if action.text() == text:
            action.trigger()
            return True
    return False


class TestSelectionToggle:
    def test_page_lookup_uses_find_children(self, env, qapp):
        """回归：不能用 ``window._page_map``（ElaWindow 根本没这个属性）。"""
        window, tray_page, sel = env
        assert not hasattr(window, "_page_map")
        assert tray_page._find_selection_page() is sel
        qapp.processEvents()

    def test_menu_has_selection_item(self, env):
        _window, tray_page, _sel = env
        labels = _labels(tray_page._host)
        assert any("划词助手" in t for t in labels), labels

    def test_toggle_from_tray_enables_assistant(self, env, qapp):
        _window, tray_page, sel = env
        host = tray_page._host
        # 先归零，保证与用例执行顺序无关
        if sel.isAssistantEnabled():
            _click(host, "划词助手：开")
            qapp.processEvents()
        assert sel.isAssistantEnabled() is False

        assert _click(host, "划词助手：关") is True
        qapp.processEvents()
        assert sel.isAssistantEnabled() is True
        # 页面内开关也跟着翻
        assert sel._enable_switch.getIsToggled() is True
        # 托盘文案同步
        assert any("划词助手：开" in t for t in _labels(host)), _labels(host)

    def test_label_syncs_back_from_page_switch(self, env, qapp):
        """页面内开关变化 -> 托盘文案回写（双向同步）。"""
        _window, tray_page, sel = env
        host = tray_page._host
        _click(host, "划词助手：关")
        qapp.processEvents()
        assert sel.isAssistantEnabled() is True

        # 从页面自身关掉
        sel._on_enable_toggled(False)
        qapp.processEvents()
        assert sel.isAssistantEnabled() is False
        assert any("划词助手：关" in t for t in _labels(host)), _labels(host)

    def test_state_relay_signal(self, env, qapp):
        _window, _tray_page, sel = env
        seen = []
        sel.assistantStateChanged.connect(seen.append)
        if not sel.isAssistantEnabled():
            sel._on_enable_toggled(True)
        qapp.processEvents()
        assert True in seen, seen

    def test_is_assistant_enabled_does_not_create(self, env, qapp):
        """读状态不该顺带把助手造出来（托盘初始化时会问一次）。"""
        _window, _tray_page, sel = env
        before = sel._assistant
        sel.isAssistantEnabled()
        assert sel._assistant is before


class TestSelectionParameterLabels:
    """回归：「启用 / 紧凑模式 / …」四个参数标签曾内联 ``ElaText(...)`` 直接交给
    ``addWidget`` 而漏定字号 —— ``ElaText`` 默认 28px，截图里比说明文字大一号。"""

    def test_parameter_labels_use_caption_size(self, env):
        _window, _tray_page, sel = env
        wanted = {"启用", "紧凑模式", "恢复剪贴板", "最小长度"}
        found = [w for w in sel.findChildren(ElaText) if w.text() in wanted]
        assert {w.text() for w in found} == wanted, [w.text() for w in found]
        assert all(w.getTextPixelSize() <= 14 for w in found), [
            (w.text(), w.getTextPixelSize()) for w in found
        ]


class TestQuitAction:
    def test_quit_requested_calls_shutdown(self, env, qapp, monkeypatch):
        """回归：点「退出」必须真调 shutdown()，不能只打日志。"""
        _window, tray_page, _sel = env
        called = []
        monkeypatch.setattr(tray_page._host, "shutdown", lambda: called.append(True))
        tray_page._on_quit_requested()
        assert called == [True]

    def test_quit_menu_item_emits_quit_requested(self, env, qapp, monkeypatch):
        _window, tray_page, _sel = env
        # **别让真实的 shutdown() 跑**：它会 ``QApplication.quit()``，而
        # 「没有执行中的事件循环时调 quit()」会把主线程的 ``quitNow`` 置位且
        # 没人复位 —— 之后所有 ``QEventLoop.exec()``（``QTest.qWait`` / 本仓库
        # 的 ``_spin``）直接返回 -1 变空转（实测 0ms 返回），后续 ela_chat 的
        # 工作线程用例三条时序断言失败、最终整进程 0xC0000409 静默崩。
        monkeypatch.setattr(tray_page._host, "shutdown", lambda: None)
        seen = []
        tray_page._host.quitRequested.connect(lambda: seen.append(True))
        assert _click(tray_page._host, "退出") is True
        assert seen == [True]

    # 注意：不在这里跑 `qapp.exec()` 验证真退出 —— 在 pytest 内重入事件循环
    # 会把整个测试进程带崩（实测 access violation，栈全在 pluggy/pytest 内）。
    # 真退出由独立进程脚本验证，本文件只守「点了退出 → shutdown() 被调用」。


def _click_button(page, text):
    for btn in page.findChildren(ElaButton):
        if btn.text() == text:
            btn.click()
            return True
    return False


class TestRawTrayButtons:
    """第 03 节裸 ``ElaTrayIcon`` 的按钮要有**可见反应**。

    回归：该演示对象从未 ``show()`` —— 点 正常 / 警告 / 错误 时内部状态确实
    在变（``setState`` 生效），但托盘里没有图标可看，症状就是「点了没反应」。
    """

    def test_tray_icons_use_bundled_fluent_pack(self, env, qapp):
        """托盘图标走内置 Fluent 图标包（多尺寸渲染），不是手绘色点。"""
        _window, tray_page, _sel = env
        icon = tray_page._tray.icon()
        assert not icon.isNull()
        assert len(icon.availableSizes()) >= 2, icon.availableSizes()

    def test_state_buttons_show_tray_and_switch_state(self, env, qapp):
        _window, tray_page, _sel = env
        tray = tray_page._tray
        tray.hide()
        qapp.processEvents()
        tray_page._log.setPlainText("")
        try:
            assert _click_button(tray_page, "警告") is True
            qapp.processEvents()
            assert tray.state() == ElaTrayIcon.ElaTrayStateType.Warning
            assert tray.isVisible() is True, "点了状态按钮托盘图标仍未显示"
            assert "托盘状态 -> 警告" in tray_page._log.toPlainText()

            assert _click_button(tray_page, "错误") is True
            qapp.processEvents()
            assert tray.state() == ElaTrayIcon.ElaTrayStateType.Critical
            assert tray.isVisible() is True
        finally:
            tray.hide()
            qapp.processEvents()

    def test_toggle_button_toggles_tray_not_window(self, env, qapp):
        """回归：该按钮曾切换**主窗口**显隐，与文案「显示 / 隐藏托盘」不符。"""
        window, tray_page, _sel = env
        tray = tray_page._tray
        tray.hide()
        qapp.processEvents()
        window_visible = window.isVisible()
        try:
            assert _click_button(tray_page, "显示 / 隐藏托盘") is True
            qapp.processEvents()
            assert tray.isVisible() is True
            assert window.isVisible() is window_visible

            assert _click_button(tray_page, "显示 / 隐藏托盘") is True
            qapp.processEvents()
            assert tray.isVisible() is False
            assert window.isVisible() is window_visible
        finally:
            tray.hide()
            qapp.processEvents()
