"""划词助手包：全局划词监视、剪贴板取词、动作条与结果对话框。

纯 ctypes 实现，动作项完全由宿主定义；用法见 ``docs/selection-assistant.md``。"""

from ..menu_item import ElaMenuItem
from ._native import (
    ElaMouseMonitor,
    foreground_pid,
    window_pid_at,
    window_rect_at,
)
from .assistant import ElaSelectionAssistant
from .capture import (
    SKIP_CLIPBOARD_CHANGED,
    SKIP_NON_TEXT_BASELINE,
    SKIP_USER_COPIED,
    ElaClipboardCapture,
)
from .popup import ElaSelectionPopup
from .result_dialog import ElaSelectionResultDialog

__all__ = [
    "SKIP_CLIPBOARD_CHANGED",
    "SKIP_NON_TEXT_BASELINE",
    "SKIP_USER_COPIED",
    "ElaClipboardCapture",
    "ElaMenuItem",
    "ElaMouseMonitor",
    "ElaSelectionAssistant",
    "ElaSelectionPopup",
    "ElaSelectionResultDialog",
    "foreground_pid",
    "window_pid_at",
    "window_rect_at",
]
