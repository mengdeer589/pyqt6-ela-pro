"""QtWebEngine 接入辅助（宿主在创建 ``QApplication`` 之前调用）。"""

from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, Qt


def prepareWebEngine() -> bool:
    """在创建 ``QApplication`` 之前打开 QtWebEngine 需要的共享 GL 上下文。

    返回 ``False`` 表示已有 ``QCoreApplication`` 实例（调用太晚，属性不再生效）；
    此时只能在创建应用之前导入 ``PyQt6.QtWebEngineWidgets``。
    """
    if QCoreApplication.instance() is not None:
        return False
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    return True
