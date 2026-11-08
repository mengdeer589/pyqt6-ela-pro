"""ElaWindow 导航选中动画必须在视图销毁前收尾。

历史缺陷：``ElaNavigationView`` 的自定义 QStyle 不在 QWidget 所有权内，style 里的
select-mark 动画在窗口销毁后仍回调 ``_pNavigationView->viewport()``；下一次建窗复用
堆内存即 ``0xC0000005``（``Qt6Widgets!QAbstractScrollArea::viewport``）。进程内崩会
带走 pytest，所以用子进程验证退出码。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(sys.platform != "win32", reason="崩溃只在真实 Windows 平台复现"),
]

_PROBE = textwrap.dedent(
    """
    from PyQt6 import sip
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication, QWidget
    from PyQt6ElaWidgetTools import eApp, ElaWindow, ElaIconType

    I = ElaIconType.IconName
    mode = "__MODE__"


    def pump_once(app):
        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()


    app = QApplication(["ela-nav-style-destroy-regression"])
    eApp.init()
    w1 = ElaWindow()
    if mode == "expander":
        _, key = w1.addExpanderNode("group", I.Toolbox)
        w1.addPageNode("child", QWidget(), key, I.Page)
        w1.addPageNode("work", QWidget(), I.Robot)
    else:
        p1 = QWidget()
        p2 = QWidget()
        w1.addPageNode("one", p1, I.Robot)
        w1.addPageNode("two", p2, I.Page)
        w1.navigation(p2.property("ElaPageKey"))
    pump_once(app)
    w1.deleteLater()
    for _ in range(400):
        app.processEvents()
        if sip.isdeleted(w1):
            break
        pump_once(app)
    w2 = ElaWindow()
    w2.addPageNode("work", QWidget(), I.Robot)
    w2.show()
    pump_once(app)
    print("CLEAN", flush=True)
    """
)


@pytest.mark.parametrize("mode", ("expander", "navigation"))
def test_navigation_style_animation_outlives_view(mode: str) -> None:
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}:
        pytest.skip("该崩溃依赖真实 Windows 平台，offscreen 不复现")
    code = _PROBE.replace("__MODE__", mode)
    for attempt in range(3):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert proc.returncode == 0, (
            f"{mode} 第 {attempt + 1} 次子进程退出码 {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        assert "CLEAN" in proc.stdout
