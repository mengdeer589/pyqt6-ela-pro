"""回合变更汇总行：一行文件数 / 增删，展开看合并后的 diff。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import ElaThemeType

from ..._styles import ColorText
from .._changes import ElaChatTurnChanges
from .._theme import muted_color
from .collapsible import _CollapsibleBlock
from .file_changes import ElaChatFileChanges


class TurnChangesRow(_CollapsibleBlock):
    """助手消息末尾的变更汇总（折叠态只占一行）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(title="文件变更", opened=False, parent=parent, surface=False)
        self.setCardMargins(0, 0, 0, 0)
        self._changes = ElaChatTurnChanges()
        self._body_built = False
        self._files: Optional[ElaChatFileChanges] = None
        self._summary_label = ColorText(self)
        self._summary_label.setWordWrap(False)
        self._summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.insertHeaderWidget(self.headerLayout().count() - 1, self._summary_label)
        self.hide()
        self._apply_theme()

    def setChanges(self, changes) -> None:
        """替换汇总内容；空变更自动隐藏。"""
        self._changes = changes or ElaChatTurnChanges()
        count = self._changes.count
        self.setTitle(f"{count} 个文件变更" if count else "文件变更")
        summary = (
            f"+{self._changes.additions} −{self._changes.deletions}" if count else ""
        )
        self._summary_label.setText(summary)
        self._summary_label.setVisible(bool(summary))
        if self._body_built and self._files is not None:
            self._files.setFiles(list(self._changes.files))
        self.setVisible(bool(count))

    def changes(self) -> ElaChatTurnChanges:
        """获取当前汇总快照。"""
        return self._changes

    def _build_body(self) -> None:
        self._body_built = True
        self._files = ElaChatFileChanges(self)
        self._files.setFiles(list(self._changes.files))
        self.bodyLayout().addWidget(self._files)
        self._apply_theme()
        self.updateGeometry()
        if self.layout() is not None:
            self.layout().activate()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if self.isOpened() and not self._body_built:
            self._build_body()

    def _on_toggled(self, checked: bool) -> None:
        if checked and not self._body_built:
            self._build_body()
        super()._on_toggled(checked)

    def setOpenedSilently(self, opened: bool) -> None:
        if opened and not self._body_built:
            self._build_body()
        super().setOpenedSilently(opened)

    def _apply_theme(self) -> None:
        super()._apply_theme()
        if not hasattr(self, "_summary_label"):
            return
        self._summary_label.setTextColor(muted_color(self._theme_mode, 0.55))
        self._summary_label.setTextPixelSize(11)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()


__all__ = ["TurnChangesRow"]
