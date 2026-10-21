"""「ElaWindow 应用外壳」示例页的接入守卫。

这一页和别的示例页不同：它操作的是**真实宿主窗口**，所以守两类东西：

1. **没有宿主时也必须能构造**（``tests/example/`` 的其它守卫直接 ``make(页面)``，
   没有 ElaWindow）—— 否则整页守卫会连带崩掉；
2. **有宿主时的副作用正确**：位标志读取（``ButtonType`` 是普通 Enum 伪成员，
   ``&`` / ``int()`` 都不可用，只能走 ``.value``）、背景绘制模式、动态 dock、
   内容堆栈、页脚节点计数。

访问方式用「直接调页面自己的方法」：页面里的按钮回调就是这些方法，
按钮本身在 offscreen 下点不动（AGENTS.md：别依赖 QTest 命中路由）。
"""

from __future__ import annotations

import pytest
from PyQt6ElaWidgetTools import (
    ElaAppBarType,
    ElaDockWidget,
    ElaIconType,
    ElaText,
    ElaWindow,
    ElaWindowType,
)

from pyqt6_ela_pro.example.window_shell_page import WindowShellPage


class TestStandalonePage:
    """无宿主：构造 + 构建内容不得崩，每节退化成说明文字。"""

    def test_builds_without_host(self, qapp, make):
        page = make(WindowShellPage)
        assert page._demo_built
        assert page._host_window() is None
        texts = [t.text() for t in page.findChildren(ElaText)]
        assert any("需要一个 ElaWindow 宿主窗口" in t for t in texts)

    def test_no_live_controls_without_host(self, qapp, make):
        page = make(WindowShellPage)
        # 没有宿主就不该出现「加入内容堆栈」这类会打到 None 上的按钮
        assert not hasattr(page, "_demo_stack_widget")


@pytest.fixture
def hosted(qapp, make):
    """最小宿主窗口 + 外壳页（含一个普通页面，模拟真实注册顺序）。"""
    window = make(ElaWindow)
    window.resize(1000, 700)
    window.addPageNode("Home", make(ElaText, window), ElaIconType.IconName.House)
    page = make(WindowShellPage, window)
    window.addPageNode("Shell", page, ElaIconType.IconName.WindowRestore)
    page.buildDemoContent()
    qapp.processEvents()
    yield window, page
    qapp.processEvents()


class TestHostedPage:
    def test_host_detected(self, hosted):
        window, page = hosted
        assert page._host_window() is window

    def test_flag_helper_matches_binding_reality(self, hosted):
        """``getWindowButtonFlags()`` 是普通 Enum 伪成员：位测试只能走 ``.value``。"""
        window, page = hosted
        flags = window.getWindowButtonFlags()
        assert isinstance(flags.value, int)
        assert page._flag_on(flags, ElaAppBarType.ButtonType.CloseButtonHint) is True

        window.setWindowButtonFlag(ElaAppBarType.ButtonType.StayTopButtonHint, False)
        flags = window.getWindowButtonFlags()
        assert page._flag_on(flags, ElaAppBarType.ButtonType.StayTopButtonHint) is False
        assert page._flag_on(flags, ElaAppBarType.ButtonType.CloseButtonHint) is True

    def test_background_toggle_switches_paint_mode(self, hosted):
        window, page = hosted
        page._apply_background(window, True)
        assert window.getWindowPaintMode() == ElaWindowType.PaintMode.Pixmap
        page._apply_background(window, False)
        assert window.getWindowPaintMode() == ElaWindowType.PaintMode.Normal

    def test_dock_add_and_remove(self, hosted):
        window, page = hosted
        before = len(window.findChildren(ElaDockWidget))
        page._add_dock(window)
        page._add_dock_and_tab(window)
        assert len(window.findChildren(ElaDockWidget)) == before + 2
        page._remove_docks(window)
        assert page._demo_docks == []
        assert len(window.findChildren(ElaDockWidget)) == before

    def test_stack_page_added_and_addressable(self, hosted, qapp):
        window, page = hosted
        page._add_stack_page(window)
        assert page._demo_stack_widget is not None
        # 加过一次后不再重复添加
        page._add_stack_page(window)
        assert window.getCentralWidget(1) is page._demo_stack_widget
        page._show_stack_page(window, False)
        assert window.getCurrentStackIndex() >= 0
        qapp.processEvents()

    def test_new_window_request_updates_label(self, hosted):
        window, page = hosted
        key = next(
            suggestion.getSuggestData()["ElaPageKey"]
            for suggestion in window.getNavigationSuggestDataList()
            if suggestion.getSuggestText() == "Home"
        )
        # 组件对 Python 页面发的就是这条请求信号（C++ 复制不出来，见 page_window.py）
        window.pageOpenInNewWindowRequested.emit(key)
        text = page._new_window_label.text()
        assert "已打开的新窗口：1" in text
        assert "Home" in text
        window.pageOpenInNewWindowRequested.emit(key)
        assert "已打开的新窗口：2" in page._new_window_label.text()
