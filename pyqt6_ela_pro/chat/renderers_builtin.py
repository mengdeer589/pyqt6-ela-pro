"""可选的内置工具结果渲染器（默认不注册，宿主 opt-in）。

覆盖 shell / 文件变更 / read / 搜索 / fetch / MCP / todo；同名已存在时跳过，
不覆盖宿主实现。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QImageReader, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import eTheme

from .._diff import diffLines, filesFromMetadata, parseUnifiedDiff
from .._internal import _ThemeAwareMixin
from .._styles import ColorText
from ..terminal_view import ElaTerminalView
from . import _json
from ._theme import muted_color
from .blocks.file_changes import ElaChatFileChanges
from .blocks.plan_panel import PlanListView
from .message import ElaChatPlan
from .renderers import (
    ToolRenderContext,
    parseToolArguments,
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
#: 普通文本 body 最大高度
TEXT_MAX_HEIGHT = 320
#: 列表（glob / list / ls）body 最大高度：行数多，矮了马上出内部滚动条
LIST_MAX_HEIGHT = 420
#: MCP / JSON body 最大高度（与列表同档）
MCP_MAX_HEIGHT = 420
#: 代码块统一字号（与 ElaDiffView 的 CODE_PIXEL_SIZE 一致）
BODY_CODE_FONT_PX = 12
#: 单行结果的最小高度（避免一行文本撑成一张空卡）
BODY_MIN_HEIGHT = 40
#: 普通文本结果的展示行数上限
TEXT_MAX_LINES = 400
#: fetch 结果的展示行数上限（网页内容通常更长）
FETCH_MAX_LINES = 200
#: 图片预览的最大逻辑尺寸（不放大）
IMAGE_MAX_WIDTH = 480
IMAGE_MAX_HEIGHT = 320
#: 图片圆角
IMAGE_RADIUS = 6
#: 超过这个字符数不再做 JSON 缩进（避免 UI 线程整份重排）
PRETTY_MAX_CHARS = 256 * 1024


class _EmptyBody(_ThemeAwareMixin, QWidget):
    """空结果占位：一行弱化文本，不再画空终端框。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._label = ColorText("（无输出）", self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setTextPixelSize(12)
        layout.addWidget(self._label)
        self._apply_theme()

    def _apply_theme(self) -> None:
        self._label.setTextColor(muted_color(self._theme_mode, 0.5))

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class _ImageBody(QWidget):
    """图片预览：圆角、DPR 感知、小图不放大。"""

    def __init__(self, path, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._load(path)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def _load(self, path) -> None:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        source = reader.size()
        if not source.isValid() or source.isEmpty():
            return
        scale = min(
            1.0,
            IMAGE_MAX_WIDTH / max(1, source.width()),
            IMAGE_MAX_HEIGHT / max(1, source.height()),
        )
        width = max(1, round(source.width() * scale))
        height = max(1, round(source.height() * scale))
        dpr = max(1.0, float(self.devicePixelRatioF()))
        reader.setScaledSize(QSize(round(width * dpr), round(height * dpr)))
        image = reader.read()
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(dpr)
        self._pixmap = pixmap
        self.setFixedSize(width, height)

    def hasImage(self) -> bool:
        """图片是否加载成功（失败时工厂落回文本）。"""
        return not self._pixmap.isNull()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), IMAGE_RADIUS, IMAGE_RADIUS)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()


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
    """工具输出 body：嵌入工具卡、统一 12px 等宽、高度贴合行数。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        max_lines: int = CONSOLE_MAX_LINES,
        max_height: int = CONSOLE_MAX_HEIGHT,
        auto_scroll: bool = True,
    ) -> None:
        super().__init__(maxLines=max_lines, parent=parent)
        self._output = ""
        self._max_height = max_height
        self.setEmbedded(True)
        self.setFontSize(BODY_CODE_FONT_PX)
        self.setToolbarVisible(False)
        self.setLineNumbersVisible(False)
        self.setMaximumHeight(max_height)
        self.setMinimumHeight(BODY_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAutoScroll(bool(auto_scroll))

    def _content_height(self) -> int:
        # 按终端实际行高算，再留出滚动条 / 文档边距的余量：
        # 少算 2px 就会立刻长出竖向滚动条。
        return self.contentHeight() + 16

    def _sync_height(self) -> None:
        # 父布局紧张时也不压缩短输出。
        self.setMinimumHeight(min(self._content_height(), self._max_height))
        self.updateGeometry()

    def _flush_render(self) -> None:
        super()._flush_render()
        self._sync_height()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        """按行数贴合高度，超过最大高度才滚动。"""
        hint = super().sizeHint()
        height = min(self._content_height(), self._max_height)
        return QSize(hint.width(), max(height, self.minimumHeight()))

    def setOutput(self, text: str) -> None:
        text = str(text or "")
        if text == self._output:
            return
        self._output = text
        self.clear()
        if text:
            self.append(text)
        self._sync_height()

    def updateToolResult(self, result: str, status: str) -> None:
        self.setOutput(result)


def _shellFactory(ctx: ToolRenderContext):
    text = str(ctx.result or "")
    if not text.strip():
        return _EmptyBody()
    body = _ShellBody(max_lines=CONSOLE_MAX_LINES, auto_scroll=True)
    body.setOutput(text)
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
        # metadata / 参数是建卡时的快照；结果里如果自带 unified diff，补建文件列表。
        if self.files():
            return
        parsed = parseUnifiedDiff(result or "")
        if parsed:
            self.setFiles(parsed)


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
    body = _ImageBody(resolved)
    return body if body.hasImage() else None


def _truncate_lines(text: str, max_lines: int = 400) -> str:
    """按行截断超长工具输出（保留末尾提示）。"""
    lines = str(text or "").splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines]) + f"\n… 已截断，共 {len(lines)} 行"


def _pretty(text: str) -> str:
    """JSON 结果格式化；解析失败 / 超大输入原样返回。"""
    raw = str(text or "").strip()
    if not raw or raw[0] not in "{[" or len(raw) > PRETTY_MAX_CHARS:
        return str(text or "")
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return str(text or "")
    try:
        return _json.dumps(data, indent=2)
    except (TypeError, ValueError):
        return str(text or "")


def _text_body(
    result: str,
    max_lines: int = TEXT_MAX_LINES,
    *,
    max_height: int = TEXT_MAX_HEIGHT,
    auto_scroll: bool = False,
    pretty: bool = True,
) -> QWidget:
    text = _pretty(result) if pretty else str(result or "")
    text = _truncate_lines(text, max_lines)
    if not text.strip():
        return _EmptyBody()
    body = _ShellBody(
        max_lines=max_lines,
        max_height=max_height,
        auto_scroll=auto_scroll,
    )
    body.setOutput(text)
    return body


def _readFactory(ctx: ToolRenderContext):
    image = _readImageFactory(ctx)
    if image is not None:
        return image
    return _text_body(ctx.result or "", max_lines=TEXT_MAX_LINES)


def _listFactory(ctx: ToolRenderContext):
    return _text_body(
        ctx.result or "",
        max_lines=TEXT_MAX_LINES,
        max_height=LIST_MAX_HEIGHT,
    )


def _searchFactory(ctx: ToolRenderContext):
    return _text_body(ctx.result or "", max_lines=TEXT_MAX_LINES)


def _fetchFactory(ctx: ToolRenderContext):
    return _text_body(ctx.result or "", max_lines=FETCH_MAX_LINES)


def _mcpFactory(ctx: ToolRenderContext):
    return _text_body(
        ctx.result or "",
        max_lines=TEXT_MAX_LINES,
        max_height=MCP_MAX_HEIGHT,
    )


def _todoFactory(ctx: ToolRenderContext):
    data = ctx.parsedArguments()
    raw = data.get("todos") or data.get("items") or data.get("plan")
    if isinstance(raw, str):
        plan = ElaChatPlan.fromMarkdown(raw)
    else:
        plan = ElaChatPlan.fromList(raw) if isinstance(raw, (list, tuple)) else None
    if plan is None:
        return None
    view = PlanListView()
    view.setPlan(plan)
    return view


def _first_subtitle(arguments, keys):
    """按候选键取第一个非空值，返回真实键（参数摘要据此去重）。"""
    data = parseToolArguments(arguments)
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return (key, value.strip())
    return ("", "")


def _pathSubtitle(arguments):
    return _first_subtitle(arguments, ("path", "file", "file_path"))


def _searchSubtitle(arguments):
    return _first_subtitle(arguments, ("pattern", "query", "q"))


def _fetchSubtitle(arguments):
    return _first_subtitle(arguments, ("url", "uri"))


def _mcpSubtitle(arguments):
    return _first_subtitle(arguments, ("server", "tool", "name"))


def _todoSubtitle(arguments):
    data = parseToolArguments(arguments)
    key = "todos" if isinstance(data.get("todos"), (list, tuple)) else "items"
    raw = data.get(key)
    if isinstance(raw, (list, tuple)):
        return (key, f"{len(raw)} 项")
    return ("", "")


#: 已由本模块安装的名字（卸载时只移除仍是本模块工厂的项）
_INSTALLED: set = set()
#: 本模块自己的工厂（卸载时按身份识别，不误删宿主覆盖）
_OWN_FACTORIES = (
    _shellFactory,
    _fileFactory,
    _readImageFactory,
    _readFactory,
    _listFactory,
    _searchFactory,
    _fetchFactory,
    _mcpFactory,
    _todoFactory,
)


def installBuiltinToolRenderers() -> list:
    """注册内置渲染器（同名已存在时跳过），返回本次实际注册的名字列表。"""
    registrations = [
        ("shell", _shellFactory, None),
        ("bash", _shellFactory, None),
        ("execute", _shellFactory, None),
        ("edit", _fileFactory, None),
        ("write", _fileFactory, None),
        ("patch", _fileFactory, None),
        ("apply_patch", _fileFactory, None),
        ("read", _readFactory, _pathSubtitle),
        ("view", _readFactory, _pathSubtitle),
        ("cat", _readFactory, _pathSubtitle),
        ("glob", _listFactory, _pathSubtitle),
        ("list", _listFactory, _pathSubtitle),
        ("ls", _listFactory, _pathSubtitle),
        ("grep", _searchFactory, _searchSubtitle),
        ("search", _searchFactory, _searchSubtitle),
        ("find", _searchFactory, _searchSubtitle),
        ("fetch", _fetchFactory, _fetchSubtitle),
        ("webfetch", _fetchFactory, _fetchSubtitle),
        ("web", _fetchFactory, _fetchSubtitle),
        ("curl", _fetchFactory, _fetchSubtitle),
        ("mcp", _mcpFactory, _mcpSubtitle),
        ("todowrite", _todoFactory, _todoSubtitle),
        ("todo_write", _todoFactory, _todoSubtitle),
        ("update_todo_list", _todoFactory, _todoSubtitle),
    ]
    installed = []
    for name, factory, subtitle in registrations:
        if toolRenderer(name) is not None:
            continue
        registerToolRenderer(name, factory, subtitle=subtitle)
        _INSTALLED.add(name)
        installed.append(name)
    return installed


def uninstallBuiltinToolRenderers() -> list:
    """移除本模块安装且未被宿主覆盖的渲染器，返回移除的名字。"""
    removed = []
    for name in list(_INSTALLED):
        factory = toolRenderer(name)
        if factory in _OWN_FACTORIES:
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
