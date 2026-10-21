"""守卫「侧边栏右键 → 在新窗口中打开」对 Python 页面的通路。

Python 定义的页面类（PyQt 子类）的 metaobject 没有可被 C++ 调用的构造函数，
``QMetaObject::newInstance()`` 恒返回 nullptr —— 上游实现里失败后**静默返回**
（既不开窗也不发信号）：右键菜单能弹出、动作能触发，点完毫无反应。本地重编轮
改为发 ``pageOpenInNewWindowRequested(nodeKey)``（``ElaWindow`` 转发），宿主
据此自建窗口；C++ 可复制页面的成功路径不动（仍走 ``pageOpenInNewWindow``）。

这里走**真实菜单路径**（``customContextMenuRequested`` → C++ 弹菜单 → 触发动作）：
``QMenu.exec`` 阻塞到关闭，PyQt6 里类级 monkeypatch 拦不住它，只能放一个挂在
view 上的定时器把弹层关掉。

不测「C++ 可复制页面」的成功路径：全库唯一带 ``Q_INVOKABLE`` 构造的 Ela 类是
``ElaWindow`` 自己，拿它当页面反复建 / 销时 Qt 侧本就不稳定（实测单轮能过、
第二轮到 ``processEvents`` 必 access violation），与本次改动无关。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QTimer
from PyQt6.QtWidgets import QApplication, QTreeView, QWidget
from PyQt6ElaWidgetTools import ElaNavigationBar, ElaNavigationType, ElaWindow

_NAV_VIEW_NAME = "ElaNavigationView"


def _trigger_open_in_new_window(qapp, view, index) -> None:
    """在 ``index`` 上弹 C++ 右键菜单并触发「在新窗口中打开」（菜单里的唯一动作）。"""

    def _trigger() -> None:
        popup = QApplication.activePopupWidget()
        if popup is None:
            return
        actions = popup.actions()
        if actions:
            actions[0].trigger()
        popup.close()
        closer.stop()

    closer = QTimer(view)
    closer.setInterval(10)
    closer.timeout.connect(_trigger)
    closer.start()
    view.customContextMenuRequested.emit(QPoint(view.visualRect(index).center()))
    qapp.processEvents()


@pytest.fixture
def sidebar(qapp, make):
    """返回构造器：``(页面控件) -> (window, view, page_index)``（页面已注册到侧边栏）。"""

    def _build(page):
        window = make(ElaWindow)
        window.resize(900, 600)
        result, expander = window.addExpanderNode("分组")
        assert result == ElaNavigationType.NodeResult.Success
        result = window.addPageNode("页面", page, expander)
        assert result == ElaNavigationType.NodeResult.Success
        window.show()
        qapp.processEvents()

        view = window.findChild(QTreeView, _NAV_VIEW_NAME)
        assert view is not None, "找不到导航树（ElaNavigationView）"
        view.expandAll()
        qapp.processEvents()
        model = view.model()
        root = model.index(0, 0, model.index(-1, -1))
        index = model.index(0, 0, root)
        assert index.isValid(), "页面节点不可见，右键菜单无法命中"
        return window, view, index

    return _build


class TestBinding:
    """重编轮子必须带新信号（旧轮子上示例会 AttributeError）。"""

    def test_both_signals_exposed(self, qapp, make):
        window = make(ElaWindow)
        assert hasattr(window, "pageOpenInNewWindow")
        assert hasattr(window, "pageOpenInNewWindowRequested")
        assert hasattr(ElaNavigationBar, "pageOpenInNewWindowRequested")


class TestPythonPage:
    """Python 页面：组件发请求信号（宿主据此自建窗口）。"""

    def test_python_page_requests_host_window(self, qapp, make, sidebar):
        page = make(QWidget)
        window, view, index = sidebar(page)
        key = page.property("ElaPageKey")
        requested: list[str] = []
        opened: list[str] = []
        window.pageOpenInNewWindowRequested.connect(requested.append)
        window.pageOpenInNewWindow.connect(opened.append)

        _trigger_open_in_new_window(qapp, view, index)

        assert requested == [key], "Python 页面应改发 pageOpenInNewWindowRequested"
        assert opened == [], "C++ 复制失败就不该发 pageOpenInNewWindow"
