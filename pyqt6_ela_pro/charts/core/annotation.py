"""标注行内编辑器。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import QLineEdit


class _AnnotationEditor(QLineEdit):
    """标注标签的行内编辑器：Enter 提交、Esc 取消（失焦也提交）。"""

    cancelled = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.editingFinished.emit()
            event.accept()
            return
        super().keyPressEvent(event)
