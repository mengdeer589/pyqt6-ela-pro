"""可选的内置工具结果渲染器（默认不注册，宿主 opt-in）。

``installBuiltinToolRenderers()`` 注册 shell 输出（复用 ``ElaTerminalView``）与
文件变更（懒建 diff）两类；同名已存在时跳过，不覆盖宿主实现。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from .._diff import diffLines, filesFromMetadata
from ..terminal_view import ElaTerminalView
from .blocks.file_changes import ElaChatFileChanges
from .renderers import (
    ToolRenderContext,
    registerToolRenderer,
    toolRenderer,
    unregisterToolRenderer,
)

#: ANSI 转义序列（SGR / 光标 / 清屏等）
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
#: 控制台最大高度
CONSOLE_MAX_HEIGHT = 260
#: 终端保留行数上限
CONSOLE_MAX_LINES = 2000


def cleanAnsi(text: str) -> str:
    """去掉 ANSI 转义，保留最后一次 ``\\r`` 重画的内容（纯文本诊断 / 导出用）。"""
    raw = _ANSI_RE.sub("", str(text or ""))
    lines = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if "\r" in line:
            line = line.rsplit("\r", 1)[-1]
        lines.append(line)
    return "\n".join(lines)


class _ShellBody(ElaTerminalView):
    """shell 输出 body：复用终端组件的 ANSI 解析 / 行数上限 / 右键复制。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(maxLines=CONSOLE_MAX_LINES, parent=parent)
        self.setToolbarVisible(False)
        self.setLineNumbersVisible(False)
        self.setMaximumHeight(CONSOLE_MAX_HEIGHT)
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAutoScroll(True)
        self.linesAppended.connect(self._onLinesAppended)
        self.cleared.connect(self._sync_height)

    def _content_height(self) -> int:
        edit = getattr(self, "_edit", None)
        metrics = edit.fontMetrics() if edit is not None else self.fontMetrics()
        lines = max(1, self.visibleLineCount())
        margin = int(edit.document().documentMargin() * 2) if edit is not None else 8
        return lines * metrics.lineSpacing() + margin + 12

    def _sync_height(self) -> None:
        # 父布局紧张时也不压缩短输出。
        self.setMinimumHeight(min(self._content_height(), CONSOLE_MAX_HEIGHT))
        self.updateGeometry()

    def _onLinesAppended(self, _count: int) -> None:
        self._sync_height()

    def _flush_render(self) -> None:
        # linesAppended 在 flush 前发出，等文档更新后再量行数。
        super()._flush_render()
        self._sync_height()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        """按行数贴合高度，超过最大高度才滚动。"""
        hint = super().sizeHint()
        height = min(self._content_height(), self.maximumHeight())
        return QSize(hint.width(), max(height, self.minimumHeight()))

    def setOutput(self, text: str) -> None:
        self.clear()
        if text:
            self.append(text)
        self._sync_height()

    def updateToolResult(self, result: str, status: str) -> None:
        self.setOutput(result)


def _shellFactory(ctx: ToolRenderContext):
    body = _ShellBody()
    body.setOutput(ctx.result or "")
    return body


class _FileChangesBody(ElaChatFileChanges):
    """文件变更 body；结果更新时按 metadata / 参数重建。"""

    def __init__(
        self, ctx: ToolRenderContext, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._sync()

    def _sync(self) -> None:
        files = []
        raw = self._ctx.metadata.get("files")
        if isinstance(raw, list):
            files = filesFromMetadata(raw)
        if not files:
            args = self._ctx.parsedArguments()
            path = str(args.get("path") or args.get("file") or "")
            if path:
                before = args.get("oldString")
                after = args.get("newString")
                if isinstance(before, str) or isinstance(after, str):
                    files = [diffLines(before or "", after or "", path)]
                elif isinstance(args.get("content"), str):
                    files = [diffLines("", args.get("content") or "", path)]
        self.setFiles(files)

    def updateToolResult(self, result: str, status: str) -> None:
        if not isinstance(self._ctx.metadata.get("files"), list):
            self._sync()


def _fileFactory(ctx: ToolRenderContext):
    return _FileChangesBody(ctx)


def _readImageFactory(ctx: ToolRenderContext):
    path = ""
    image = ctx.metadata.get("image")
    if isinstance(image, str):
        path = image
    if not path:
        args = ctx.parsedArguments()
        candidate = str(args.get("path") or args.get("file") or "")
        if candidate.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        ):
            path = candidate
    if not path:
        return None
    resolved = Path(path)
    if not resolved.is_file():
        return None
    pixmap = QPixmap(str(resolved))
    if pixmap.isNull():
        return None
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    label = QLabel(holder)
    label.setPixmap(
        pixmap.scaled(
            360,
            260,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
    layout.addWidget(label)
    return holder


#: 已由本模块安装的名字（卸载时只移除仍是本模块工厂的项）
_INSTALLED: set = set()


def installBuiltinToolRenderers() -> list:
    """注册内置渲染器（同名已存在时跳过），返回本次实际注册的名字列表。"""
    registrations = [
        ("shell", _shellFactory),
        ("bash", _shellFactory),
        ("execute", _shellFactory),
        ("edit", _fileFactory),
        ("write", _fileFactory),
        ("patch", _fileFactory),
        ("apply_patch", _fileFactory),
    ]
    installed = []
    for name, factory in registrations:
        if toolRenderer(name) is not None:
            continue
        registerToolRenderer(name, factory)
        _INSTALLED.add(name)
        installed.append(name)
    return installed


def uninstallBuiltinToolRenderers() -> list:
    """移除本模块安装且未被宿主覆盖的渲染器，返回移除的名字。"""
    removed = []
    for name in list(_INSTALLED):
        factory = toolRenderer(name)
        if factory in (_shellFactory, _fileFactory, _readImageFactory):
            unregisterToolRenderer(name)
            removed.append(name)
        _INSTALLED.discard(name)
    return removed


__all__ = [
    "CONSOLE_MAX_HEIGHT",
    "cleanAnsi",
    "installBuiltinToolRenderers",
    "uninstallBuiltinToolRenderers",
]
