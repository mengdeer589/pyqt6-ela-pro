"""[示例] 宿主侧「页面在新窗口中打开」的实现守卫。

Python 页面不能被 C++ ``QMetaObject::newInstance()`` 复制，``ElaWindow`` 把
右键菜单的请求转成 ``pageOpenInNewWindowRequested``；示例宿主用它 +
``example/page_window.py`` 造副本开窗。这里覆盖：按 ``ElaPageKey`` 找原页面、
副本是**新实例**、目标不可建时不动作、``PRE_SHOW_BUILD`` 在显示前构建。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import ElaNavigationType, ElaText, ElaWidget, ElaWindow

from pyqt6_ela_pro.example.base_page import ExamplePage
from pyqt6_ela_pro.example.page_window import findPageByKey, openPageInNewWindow


class _StubPage(ExamplePage):
    PAGE_TITLE = "桩页面"

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(ElaText("内容", self))


class _PreShowPage(_StubPage):
    PRE_SHOW_BUILD = True

    def buildDemoContent(self):
        if self._demo_built:
            return
        # GL 视口那类原生子窗口必须在顶层窗口显示前挂上
        self._built_hidden = not self.isVisible()
        super().buildDemoContent()


def _host_with_page(make, page_cls, title: str):
    window = make(ElaWindow)
    window.resize(900, 700)
    result, expander = window.addExpanderNode("分组")
    assert result == ElaNavigationType.NodeResult.Success
    page = make(page_cls, window)
    result = window.addPageNode(title, page, expander)
    assert result == ElaNavigationType.NodeResult.Success
    return window, page


class TestFindPageByKey:
    def test_finds_registered_page(self, qapp, make):
        window, page = _host_with_page(make, _StubPage, "桩")
        assert findPageByKey(window, page.property("ElaPageKey")) is page

    def test_unknown_or_empty_key_is_none(self, qapp, make):
        window, _page = _host_with_page(make, _StubPage, "桩")
        assert findPageByKey(window, "no-such-key") is None
        assert findPageByKey(window, "") is None


class TestOpenPageInNewWindow:
    def test_creates_window_with_fresh_page_copy(self, qapp, make):
        window, page = _host_with_page(make, _StubPage, "桩")
        shell = openPageInNewWindow(window, page.property("ElaPageKey"))
        assert shell is not None
        make.track(shell)
        qapp.processEvents()

        assert isinstance(shell, ElaWidget)
        assert shell.isWindow()
        assert shell.parent() is window
        assert shell.windowTitle() == "桩"
        assert shell.isVisible()
        copies = [w for w in shell.findChildren(_StubPage) if w is not page]
        assert len(copies) == 1, "新窗口里应恰好有一份页面副本"

    def test_unknown_key_returns_none(self, qapp, make):
        window, _page = _host_with_page(make, _StubPage, "桩")
        assert openPageInNewWindow(window, "no-such-key") is None

    def test_non_example_page_returns_none(self, qapp, make):
        window = make(ElaWindow)
        result, expander = window.addExpanderNode("分组")
        assert result == ElaNavigationType.NodeResult.Success
        plain = make(QWidget, window)
        assert window.addPageNode("普通", plain, expander) == (
            ElaNavigationType.NodeResult.Success
        )
        assert openPageInNewWindow(window, plain.property("ElaPageKey")) is None

    def test_pre_show_build_runs_before_window_show(self, qapp, make):
        window, page = _host_with_page(make, _PreShowPage, "预建")
        shell = openPageInNewWindow(window, page.property("ElaPageKey"))
        assert shell is not None
        make.track(shell)
        copy = next(w for w in shell.findChildren(_PreShowPage) if w is not page)
        assert copy._built_hidden is True, "PRE_SHOW_BUILD 的页面必须在显示前构建"
