"""[pyqt6_ela_pro] 示例：把页面在独立窗口里打开。

Python 定义的页面（``ExamplePage`` 子类）没有可被 C++ 调用的构造函数，
``QMetaObject::newInstance()`` 复制不出来 —— 所以 ``ElaWindow`` 侧边栏右键的
「在新窗口中打开」对这类页面改发 ``pageOpenInNewWindowRequested(nodeKey)``
（本地重建轮），由宿主自己建窗口：

- 按 ``ElaPageKey`` 属性找注册时的原页面（``addPageNode`` 成功后由 C++ 写入），
  用它的类造一个副本；
- 副本装进 ``ElaWidget``（自带标题栏 / 拖动 / 阴影 / 主题）；
- ``PRE_SHOW_BUILD`` 的页面先在 ``show()`` 前构建内容（GL 视口要在窗口显示前挂）。

``ElaWidget`` 必须**无父构造**再 ``setParent(window, Qt.WindowType.Window)``：
带父构造时它只是个普通子控件（``isWindow() == False``），而 ``ElaAppBar``
构造里会拿 ``window()``（此时是主窗口）去 ``setContentsMargins`` —— 会把主窗口
的边距改坏。
"""

from __future__ import annotations

import warnings

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaWidget

from .base_page import ExamplePage


def findPageByKey(window: QWidget, nodeKey: str) -> QWidget | None:
    """按 ``ElaPageKey`` 属性找注册过的原页面；找不到返回 ``None``。"""
    if not nodeKey:
        return None
    for child in window.findChildren(QWidget):
        if child.property("ElaPageKey") == nodeKey:
            return child
    return None


def openPageInNewWindow(window: QWidget, nodeKey: str) -> ElaWidget | None:
    """为 ``nodeKey`` 对应的页面开一个独立 ``ElaWidget`` 窗口。

    只处理 ``ExamplePage`` 子类（构造签名已知是 ``(parent)``）；其它页面
    返回 ``None``，由宿主自己决定怎么建。
    """
    origin = findPageByKey(window, nodeKey)
    if origin is None or not isinstance(origin, ExamplePage):
        return None

    title = origin.PAGE_TITLE or origin.windowTitle()
    node_title = getattr(window, "getNavigationNodeTitle", None)
    if node_title is not None:
        title = node_title(nodeKey) or title

    # 先无父构造（此时它才是顶层窗口），再挂到宿主名下 —— 随主窗口销毁。
    shell = ElaWidget()
    shell.setParent(window, Qt.WindowType.Window)
    shell.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    shell.setWindowTitle(title)
    icon = origin.windowIcon()
    if icon.isNull():
        icon = window.windowIcon()
    shell.setWindowIcon(icon)
    try:
        page = type(origin)(shell)
    except Exception:  # noqa: BLE001 - 副本构造失败不能让宿主崩（Qt 回调链上）
        warnings.warn(f"页面「{title}」无法复制到新窗口，已跳过", stacklevel=2)
        shell.deleteLater()
        return None
    if getattr(page, "PRE_SHOW_BUILD", False):
        page.buildDemoContent()

    # 无父布局先设边距再 setLayout：QLayout.setContentsMargins 会写回控件，
    # 在 ElaAppBar 之后调用会清掉标题栏让出的上边距。
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(page)
    shell.setLayout(layout)

    size = window.size()
    screen = window.screen()
    if screen is not None:
        available = screen.availableGeometry().size()
        size.setWidth(min(size.width(), available.width()))
        size.setHeight(min(size.height(), available.height()))
    shell.resize(size)
    shell.show()
    shell.moveToCenter()
    return shell
