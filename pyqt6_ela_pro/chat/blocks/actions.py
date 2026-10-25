"""消息底部操作栏。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QPushButton,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconType,
)

from ..toolbar import ElaChatToolBar


class MessageActions(ElaChatToolBar):
    """底部层操作栏（复制 / 撤回 / 重新生成 + 自定义动作）。"""

    #: 复制
    copyRequested = pyqtSignal()
    #: 撤回
    undoRequested = pyqtSignal()
    #: 重新生成
    regenerateRequested = pyqtSignal()
    #: 自定义动作被点击（参数：key）
    actionTriggered = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, compact=True)
        self._mouse_transparent = False
        self.toolTriggered.connect(self._dispatch)

    # -- 鼠标穿透（hover 隐藏时阻止误点） ----------------------------------

    def setMouseTransparent(self, on: bool) -> None:
        """设置操作栏（含全部子按钮）是否鼠标穿透。

        隐藏态下穿透可避免点击到不可见按钮；程序化 ``click()`` 不受影响。
        """
        self._mouse_transparent = bool(on)
        self._apply_mouse_transparency()

    def mouseTransparent(self) -> bool:
        """操作栏是否鼠标穿透。"""
        return self._mouse_transparent

    def _apply_mouse_transparency(self) -> None:
        widgets = [self]
        widgets.extend(self.findChildren(QWidget))
        for widget in widgets:
            widget.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                self._mouse_transparent,
            )

    def addButton(self, *args, **kwargs) -> QPushButton:
        """添加按钮后同步鼠标穿透状态（宿主可随时追加自定义动作）。"""
        button = super().addButton(*args, **kwargs)
        button.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            self._mouse_transparent,
        )
        return button

    def addWidget(self, *args, **kwargs) -> QWidget:
        """添加控件后同步鼠标穿透状态。"""
        widget = super().addWidget(*args, **kwargs)
        widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            self._mouse_transparent,
        )
        return widget

    def addCopyAction(self) -> QPushButton:
        """添加「复制」按钮。"""
        return self.addButton(
            icon=ElaIconType.IconName.Copy, tooltip="复制", key="copy"
        )

    def addUndoAction(self) -> QPushButton:
        """添加「撤回」按钮（删除该轮及之后消息并回填输入框）。"""
        return self.addButton(
            icon=ElaIconType.IconName.ArrowRotateLeft,
            tooltip="撤回该轮及其后的消息",
            key="undo",
        )

    def addRegenerateAction(self) -> QPushButton:
        """添加「重新生成」按钮。"""
        return self.addButton(
            icon=ElaIconType.IconName.ArrowsRotate,
            tooltip="重新生成",
            key="regenerate",
        )

    def addCustomAction(
        self,
        key: str,
        icon=None,
        tooltip: str = "",
        callback=None,
    ) -> QPushButton:
        """添加自定义动作按钮（同时发 ``actionTriggered(key)``）。"""
        return self.addButton(icon=icon, tooltip=tooltip, key=key, callback=callback)

    def _dispatch(self, key: str) -> None:
        if key == "copy":
            self.copyRequested.emit()
        elif key == "undo":
            self.undoRequested.emit()
        elif key == "regenerate":
            self.regenerateRequested.emit()
        else:
            self.actionTriggered.emit(key)
