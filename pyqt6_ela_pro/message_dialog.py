"""
消息对话框组件。

提供一个简化的消息对话框接口，使用 ElaText 组件渲染内容。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaText

from .dialog_base import ElaDialogBase


class ElaMessageDialog(ElaDialogBase):
    """简单的消息对话框：正文用 ``ElaText`` 渲染，``middleText=None`` 时隐藏中间按钮。"""

    def __init__(
        self,
        title: str = "标题",
        message: str = "",
        middleText: str | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(title=title, middleText=middleText, parent=parent)
        self._message_widget: Optional[ElaText] = None
        self.setMessage(message)

    def setMessage(self, message: str) -> None:
        old_message = self._message_widget
        self._message_widget = None
        if old_message is not None:
            try:
                old_message.deleteLater()
            except RuntimeError:
                pass

        message_widget = ElaText(message, self._paramWidget)
        message_widget.setTextPixelSize(12)
        message_widget.setWordWrap(True)
        self._message_widget = message_widget
        self._paramLay.insertWidget(2, message_widget)

    def show(
        self,
        title: str = "标题",
        message: str = "",
        middleText: str | None = None,
    ) -> Optional[int]:
        """显示消息对话框（类调用模态）或普通显示（实例调用）。

        类调用 ``ElaMessageDialog.show(parent, ...)`` 返回按钮值（0=左 / 1=右 /
        2=中间）；实例调用 ``dlg.show()`` 与 ``QDialog.show`` 一致，返回 ``None``。
        """
        if isinstance(self, ElaMessageDialog):
            super().show()
            return None
        parent = self
        dialog = ElaMessageDialog(
            title=title, message=message, middleText=middleText, parent=parent
        )
        dialog.setWindowTitle(title)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        return dialog.exec()
