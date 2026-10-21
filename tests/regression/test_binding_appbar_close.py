"""AppBar 默认关闭路径：槽内不得处理 DeferredDelete（bug #19）。

``ElaAppBarPrivate::onCloseButtonClicked`` 原先在 ``window->close()`` 之后调
``QApplication::processEvents()`` —— 对带 ``WA_DeleteOnClose`` 的窗口，这一步会在
当前槽栈内把窗口 / AppBar / 触发点击的按钮同步删掉，随后的 ``windowHandle()``
就是 use-after-free（Win7 实测 access violation）。
"""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QWidget
from PyQt6ElaWidgetTools import ElaWidget


def _close_button(shell: QWidget) -> QPushButton:
    app_bars = [
        child for child in shell.findChildren(QWidget) if child.objectName() == "ElaAppBar"
    ]
    assert app_bars, "ElaWidget 没有创建 ElaAppBar"
    buttons = app_bars[0].findChildren(QPushButton)
    assert buttons, "ElaAppBar 没有关闭按钮"
    return buttons[-1]


def test_default_close_keeps_window_alive_until_event_loop(qapp, make):
    shell = make(ElaWidget)
    shell.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    shell.resize(360, 240)
    shell.show()
    qapp.processEvents()

    close_btn = _close_button(shell)
    close_btn.click()

    # 槽内 processEvents() 会把两者同步删掉；修复后 close() 只投递 DeferredDelete。
    assert sip.isdeleted(shell) is False
    assert sip.isdeleted(close_btn) is False

    qapp.processEvents()
    assert sip.isdeleted(shell) is True
    assert sip.isdeleted(close_btn) is True
