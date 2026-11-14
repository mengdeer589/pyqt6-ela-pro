"""顶层无 parent 的 ElaTabBar 在 show() 时不得崩溃。

历史缺陷：``ElaTabBar::sizeHint()`` 无条件取 ``parentWidget()->maximumWidth()``，
顶层实例 parent 为空即 ``0xC0000005``；进程内崩会带走 pytest，所以用子进程验证。
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="项目仅支持 Windows")

_PROBE = textwrap.dedent(
    """
    from PyQt6.QtWidgets import QApplication
    from PyQt6ElaWidgetTools import ElaTabBar

    app = QApplication(["ela-tabbar-top-level-regression"])
    tb = ElaTabBar()
    tb.addTab("A")
    tb.show()
    app.processEvents()
    assert tb.isVisible()
    print("CLEAN", tb.width(), tb.height(), flush=True)
    """
)


def test_top_level_tabbar_show_does_not_crash() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, (
        f"退出码 {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "CLEAN" in proc.stdout
