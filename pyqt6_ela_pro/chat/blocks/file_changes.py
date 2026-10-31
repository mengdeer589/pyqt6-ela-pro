"""文件变更列表（工具结果 body / 回合变更汇总）。

一行一个文件：图标 + 目录弱化 + 文件名 + ``+N/-N`` + 状态；点开展开懒建的
``ElaDiffView``。刻意**不再套一层卡片** —— 它通常就是 ``edit`` / ``patch``
工具卡的 body，外面已经有一层工具卡头。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import ElaIconButton, ElaIconType, eTheme

from ..._internal import _ThemeAwareMixin
from ..._styles import BareButton, ColorText
from ..._theme import statusColor, text as text_color, textMuted
from ..._theme import ElaStatusRoleType
from ...ela_button import ElaButton
from ...ela_diff_view import ElaDiffView
from ..._diff import (
    DIFF_ADDED,
    DIFF_DELETED,
    DIFF_MODIFIED,
    ElaDiffFile,
    diffFileFromAny,
)

#: 默认最多显示的文件数
DEFAULT_MAX_VISIBLE_FILES = 8
#: 单个 diff body 的最大高度（超出内部滚动）
DEFAULT_DIFF_MAX_HEIGHT = 320
#: 行高
_FILE_ROW_HEIGHT = 30


class _FileHeader(BareButton):
    """文件行头：可点、可聚焦、无外观。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(_FILE_ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)


class ElaChatFileChanges(_ThemeAwareMixin, QWidget):
    """文件变更列表（每个文件一个可展开的 diff body）。"""

    #: 点击文件行（参数：路径）
    fileClicked = pyqtSignal(str)
    #: 文件展开状态变化（参数：路径、是否展开）
    fileToggled = pyqtSignal(str, bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._files: list[ElaDiffFile] = []
        self._rows: list[dict] = []
        self._expanded: dict = {}
        self._max_visible = DEFAULT_MAX_VISIBLE_FILES
        self._show_all = False
        self._default_open = True
        self._diff_max_height = DEFAULT_DIFF_MAX_HEIGHT
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._empty_label: Optional[ColorText] = None

    # -- 数据 --------------------------------------------------------------

    def setFiles(self, files) -> None:
        """整体替换文件列表（``ElaDiffFile`` / dict / None）。"""
        items = []
        for item in files or ():
            if isinstance(item, ElaDiffFile):
                items.append(item)
            elif isinstance(item, dict):
                parsed = diffFileFromAny(item)
                if parsed is not None:
                    items.append(parsed)
        self._files = items
        self._expanded.clear()
        self._show_all = False
        self._rebuild()

    def setFile(self, file) -> None:
        """设置单文件 diff。"""
        self.setFiles([file] if file is not None else [])

    def files(self) -> list:
        """获取文件列表快照。"""
        return list(self._files)

    def setMaxVisible(self, count: int) -> None:
        """设置最多直接显示的文件数（其余用「显示全部」按钮）。"""
        self._max_visible = max(1, int(count))
        self._rebuild()

    def maxVisible(self) -> int:
        """获取最多直接显示的文件数。"""
        return self._max_visible

    def setDefaultOpen(self, on: bool) -> None:
        """设置新文件行默认展开（默认开）。"""
        self._default_open = bool(on)
        self._rebuild()

    def setDiffMaxHeight(self, height: int) -> None:
        """设置单个 diff body 的最大高度。"""
        self._diff_max_height = max(80, int(height))
        for row in self._rows:
            body = row.get("body")
            if body is not None:
                body.setMaximumHeight(self._diff_max_height)

    def expandAll(self) -> None:
        """展开全部文件。"""
        for file in self._files:
            self._expanded[file.path] = True
        self._rebuild()

    def collapseAll(self) -> None:
        """收起全部文件。"""
        self._expanded.clear()
        self._rebuild()

    # -- 构建 --------------------------------------------------------------

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._rows.clear()
        self._empty_label = None
        self._more_button = None

    def _rebuild(self) -> None:
        self._clear()
        if not self._files:
            self._empty_label = ColorText("没有文件变更", self)
            self._empty_label.setTextFormat(Qt.TextFormat.PlainText)
            self._empty_label.setTextPixelSize(12)
            self._apply_theme()
            self._layout.addWidget(self._empty_label)
            return
        visible = self._files if self._show_all else self._files[: self._max_visible]
        for file in visible:
            row = self._build_row(file)
            self._rows.append(row)
            self._layout.addWidget(row["header"])
            if row["opened"]:
                self._ensure_body(row)
        remaining = len(self._files) - len(visible)
        if remaining > 0:
            more = ElaButton(
                f"显示其余 {remaining} 个文件",
                variant="text",
                size="small",
                parent=self,
            )
            more.clicked.connect(self._show_all_rows)
            self._layout.addWidget(more)
            self._more_button = more
        else:
            self._more_button = None
        self._apply_theme()

    def _show_all_rows(self) -> None:
        self._show_all = True
        self._rebuild()

    def _build_row(self, file: ElaDiffFile) -> dict:
        header = _FileHeader(self)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        chevron = ElaIconButton(ElaIconType.IconName.ChevronRight, 12, 16, 16, header)
        chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        icon = ElaIconButton(ElaIconType.IconName.Code, 12, 16, 16, header)
        icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        path_label = ColorText(header)
        path_label.setTextFormat(Qt.TextFormat.PlainText)
        path_label.setWordWrap(False)
        add_label = ColorText(header)
        add_label.setTextFormat(Qt.TextFormat.PlainText)
        add_label.setWordWrap(False)
        del_label = ColorText(header)
        del_label.setTextFormat(Qt.TextFormat.PlainText)
        del_label.setWordWrap(False)
        status_label = ColorText(header)
        status_label.setTextFormat(Qt.TextFormat.PlainText)
        status_label.setWordWrap(False)
        layout.addWidget(chevron)
        layout.addWidget(icon)
        layout.addWidget(path_label, 1)
        layout.addWidget(add_label)
        layout.addWidget(del_label)
        layout.addWidget(status_label)
        opened = self._expanded.get(file.path, self._default_open)
        row = {
            "file": file,
            "header": header,
            "body": None,
            "chevron": chevron,
            "path": path_label,
            "add": add_label,
            "del": del_label,
            "status": status_label,
            "opened": opened,
        }
        header.clicked.connect(lambda _checked=False, r=row: self._toggle_row(r))
        path_label.setToolTip(file.path)
        self._sync_header(row)
        return row

    def _sync_header(self, row: dict) -> None:
        file: ElaDiffFile = row["file"]
        directory, _, name = file.path.replace("\\", "/").rpartition("/")
        text = f"{directory}/" if directory else ""
        row["path"].setText(f"{text}{name or file.path}")
        row["add"].setText(f"+{file.additions}")
        row["del"].setText(f"-{file.deletions}")
        row["status"].setText(
            {
                DIFF_ADDED: "新增",
                DIFF_DELETED: "删除",
                DIFF_MODIFIED: "修改",
            }.get(file.status, file.status)
        )
        row["chevron"].setAwesome(
            ElaIconType.IconName.ChevronDown
            if row["opened"]
            else ElaIconType.IconName.ChevronRight
        )
        row["header"].setToolTip(file.path)

    def _ensure_body(self, row: dict) -> None:
        if row["body"] is not None:
            return
        body = ElaDiffView(self)
        body.setFileHeadersVisible(False)
        body.setFiles([row["file"]])
        body.setMaximumHeight(self._diff_max_height)
        body.setMinimumHeight(60)
        body.fileClicked.connect(self.fileClicked)
        row["body"] = body
        index = self._layout.indexOf(row["header"])
        if index >= 0:
            self._layout.insertWidget(index + 1, body)

    def _toggle_row(self, row: dict) -> None:
        row["opened"] = not row["opened"]
        self._expanded[row["file"].path] = row["opened"]
        self._ensure_body(row)
        if row["body"] is not None:
            row["body"].setVisible(row["opened"])
        self._sync_header(row)
        self.fileToggled.emit(row["file"].path, row["opened"])

    # -- 主题 --------------------------------------------------------------

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        muted = textMuted(mode)
        for row in self._rows:
            row["path"].setTextColor(text_color(mode))
            row["path"].setTextPixelSize(12)
            row["add"].setTextColor(statusColor(mode, ElaStatusRoleType.Success))
            row["add"].setTextPixelSize(12)
            row["del"].setTextColor(statusColor(mode, ElaStatusRoleType.Error))
            row["del"].setTextPixelSize(12)
            row["status"].setTextColor(muted)
            row["status"].setTextPixelSize(11)
            row["chevron"].setLightIconColor(muted)
            row["chevron"].setDarkIconColor(muted)
        if self._empty_label is not None:
            self._empty_label.setTextColor(muted)
            self._empty_label.setTextPixelSize(12)

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


__all__ = [
    "DEFAULT_DIFF_MAX_HEIGHT",
    "DEFAULT_MAX_VISIBLE_FILES",
    "ElaChatFileChanges",
]
