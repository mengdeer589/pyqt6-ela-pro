"""只读 diff / 代码查看器（无 QSS，主题跟随 ``eTheme``）。

- 统一 diff：双行号槽（旧 / 新）+ ``+/-`` 标记 + 行底色 + 可选 Pygments 着色；
- 未改动长段自动折叠成「⋯ N 行未改动（点击展开）」，点击就地展开；
- 大 diff 有上限（默认 4000 行），超出只渲染前 N 行并标注；
- 只读但可选中 / 复制，右键菜单走 ``ElaMenu``。

``split`` 视图暂未实现：工具卡里的 diff 以统一视图为主，审阅面板（P2）再补。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPalette,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import QFrame, QPlainTextEdit, QWidget
from PyQt6ElaWidgetTools import ElaMenu, ElaScrollBar, ElaThemeType, eTheme

from ._internal import _ThemeAwareMixin, execElaMenu, system_cjk_font_family
from ._styles import setTextBaseColor
from ._theme import surfaceRaised, text as text_color, textMuted
from ._diff import (
    DIFF_ADD,
    DIFF_CONTEXT,
    DIFF_DEL,
    DIFF_HUNK,
    DIFF_META,
    ElaDiffFile,
    ElaDiffLine,
    diffFileFromAny,
    diffLines,
    parseUnifiedDiff,
)

#: 默认上下文行数
DEFAULT_CONTEXT_LINES = 3
#: 默认最大渲染行数
DEFAULT_MAX_LINES = 4000
#: 代码字号
CODE_PIXEL_SIZE = 12
#: 行号 / 标记列基础宽度
_GUTTER_PAD = 8

#: 默认语法配色（opencode 主题，与 Markdown 代码块同源）
_SYNTAX_LIGHT = {
    "keyword": "#d68c27",
    "constant": "#d68c27",
    "type": "#b0851f",
    "function": "#3b7dd8",
    "class": "#b0851f",
    "decorator": "#3b7dd8",
    "builtin": "#3b7dd8",
    "attribute": "#d1383d",
    "tag": "#d1383d",
    "string": "#3d9a57",
    "number": "#d68c27",
    "comment": "#8a8a8a",
    "operator": "#318795",
}
_SYNTAX_DARK = {
    "keyword": "#9d7cd8",
    "constant": "#f5a742",
    "type": "#e5c07b",
    "function": "#fab283",
    "class": "#e5c07b",
    "decorator": "#fab283",
    "builtin": "#fab283",
    "attribute": "#e06c75",
    "tag": "#e06c75",
    "string": "#7fd88f",
    "number": "#f5a742",
    "comment": "#808080",
    "operator": "#56b6c2",
}

_PYGMENTS_STATE = {"loaded": False, "module": None}
_LEXER_CACHE: dict = {}
_TOKEN_KIND_CACHE: dict = {}
_TOKEN_KIND_MISS = object()


def _load_pygments():
    """惰性加载 Pygments（缺失 / 平台不兼容时返回 ``None``）。"""
    if _PYGMENTS_STATE["loaded"]:
        return _PYGMENTS_STATE["module"]
    _PYGMENTS_STATE["loaded"] = True
    try:
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Token

        _PYGMENTS_STATE["module"] = (get_lexer_by_name, Token)
    except Exception:
        _PYGMENTS_STATE["module"] = None
    return _PYGMENTS_STATE["module"]


def _token_kind(token_type, token) -> Optional[str]:
    """Pygments token → 语法分类（结果按 token 类型缓存）。"""
    kind = _TOKEN_KIND_CACHE.get(token_type, _TOKEN_KIND_MISS)
    if kind is _TOKEN_KIND_MISS:
        if token_type in token.Comment:
            kind = "comment"
        elif token_type in token.Keyword.Type:
            kind = "type"
        elif token_type in token.Keyword.Constant:
            kind = "constant"
        elif token_type in token.Keyword:
            kind = "keyword"
        elif token_type in token.Name.Function:
            kind = "function"
        elif token_type in token.Name.Class:
            kind = "class"
        elif token_type in token.Name.Decorator:
            kind = "decorator"
        elif token_type in token.Name.Builtin:
            kind = "builtin"
        elif token_type in token.Name.Attribute:
            kind = "attribute"
        elif token_type in token.Name.Tag:
            kind = "tag"
        elif token_type in token.String:
            kind = "string"
        elif token_type in token.Number:
            kind = "number"
        elif token_type in token.Operator:
            kind = "operator"
        else:
            kind = None
        _TOKEN_KIND_CACHE[token_type] = kind
    return kind


def _language_for(path: str) -> str:
    suffix = str(path or "").rsplit(".", 1)[-1].lower()
    return {
        "py": "python",
        "pyw": "python",
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "json": "json",
        "md": "markdown",
        "html": "html",
        "css": "css",
        "scss": "scss",
        "xml": "xml",
        "yml": "yaml",
        "yaml": "yaml",
        "toml": "toml",
        "ini": "ini",
        "sh": "bash",
        "bash": "bash",
        "ps1": "powershell",
        "bat": "batch",
        "cmd": "batch",
        "c": "c",
        "h": "c",
        "cpp": "cpp",
        "hpp": "cpp",
        "cs": "csharp",
        "java": "java",
        "go": "go",
        "rs": "rust",
        "rb": "ruby",
        "php": "php",
        "sql": "sql",
        "kt": "kotlin",
        "swift": "swift",
        "lua": "lua",
        "r": "r",
    }.get(suffix, "text")


def _lexer_for(path: str):
    module = _load_pygments()
    if module is None:
        return None
    lang = _language_for(path)
    if lang == "text":
        return None
    cached = _LEXER_CACHE.get(lang, _TOKEN_KIND_MISS)
    if cached is not _TOKEN_KIND_MISS:
        return cached
    try:
        get_lexer_by_name, _token = module
        lexer = get_lexer_by_name(lang, stripnl=False, ensurenl=False)
    except Exception:
        lexer = None
    _LEXER_CACHE[lang] = lexer
    return lexer


def _tokenize_lines(lines: list, path: str) -> list:
    """把一组行文本转为逐行 ``[(start, length, kind, italic)]`` 列表。"""
    if not lines:
        return []
    lexer = _lexer_for(path)
    if lexer is None:
        return [[] for _ in lines]
    module = _load_pygments()
    if module is None:
        return [[] for _ in lines]
    _get, token = module
    text = "\n".join(lines)
    result = [[] for _ in lines]
    line_index = 0
    column = 0
    try:
        for token_type, value in lexer.get_tokens(text):
            kind = _token_kind(token_type, token)
            if not value:
                continue
            pieces = value.split("\n")
            for offset, piece in enumerate(pieces):
                if piece and kind is not None and 0 <= line_index < len(result):
                    result[line_index].append(
                        (column, len(piece), kind, kind == "comment")
                    )
                if offset < len(pieces) - 1:
                    line_index += 1
                    column = 0
                else:
                    column += len(piece)
    except Exception:
        return [[] for _ in lines]
    return result


@dataclass
class _VisibleRow:
    """视图里的一行（可能是一个折叠占位行）。"""

    text: str = ""
    kind: str = DIFF_CONTEXT
    old_no: Optional[int] = None
    new_no: Optional[int] = None
    #: 折叠占位：``(file_index, run_ordinal)``
    fold: Optional[tuple] = None
    #: 文件头 / 截断提示等整行弱化文本
    weak: bool = False
    #: 所属文件下标（语法 span 映射用；-1 = 不属于任何文件）
    file_index: int = -1


class _LineNumberArea(QWidget):
    """diff 左侧行号槽（旧号 / 新号 / 标记）。"""

    def __init__(self, view: "ElaDiffView") -> None:
        super().__init__(view)
        self._view = view
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._view.gutterWidth(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._view.paintGutter(event)


class _DiffHighlighter(QSyntaxHighlighter):
    """按预计算 span 上色；只处理可见块，不重新 tokenize。"""

    def __init__(self, view: "ElaDiffView") -> None:
        super().__init__(view.document())
        self._view = view

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        block = self.currentBlock()
        if block is None:
            return
        spans = self._view._spans_by_block.get(block.blockNumber(), ())
        if not spans:
            return
        palette = self._view.syntaxPalette()
        length = len(text)
        for start, size, kind, italic in spans:
            if start >= length:
                break
            color = palette.get(kind)
            if color is None:
                continue
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if italic:
                fmt.setFontItalic(True)
            self.setFormat(start, min(size, length - start), fmt)


class ElaDiffView(_ThemeAwareMixin, QPlainTextEdit):
    """只读 diff / 代码查看器（统一视图）。"""

    #: 点击文件头 / 行（参数：路径、行号；暂无行号时为空）
    fileClicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._files: list[ElaDiffFile] = []
        self._rows: list[_VisibleRow] = []
        self._spans_by_block: dict = {}
        self._file_spans: list = []
        self._all_runs: set = set()
        self._expanded_runs: set = set()
        self._context_lines = DEFAULT_CONTEXT_LINES
        self._max_lines = DEFAULT_MAX_LINES
        self._file_headers_visible = True
        self._syntax_enabled = True
        self._custom_palette = None
        self._syntax_palette = dict(_SYNTAX_LIGHT)
        self._gutter_old_width = 24
        self._gutter_new_width = 24
        self._gutter_marker_width = 12

        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setUndoRedoEnabled(False)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBar(ElaScrollBar(Qt.Orientation.Vertical, self))
        self.setHorizontalScrollBar(ElaScrollBar(Qt.Orientation.Horizontal, self))
        self.setTabChangesFocus(False)

        self._gutter = _LineNumberArea(self)
        self._highlighter = _DiffHighlighter(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._on_cursor_changed)
        self._update_gutter_width()
        self.setFont(self._code_font())
        self.setTabStopDistance(QFontMetrics(self.font()).horizontalAdvance(" ") * 4)
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def setFiles(self, files) -> None:
        """整体替换文件列表（``ElaDiffFile`` 或 ``dict``）。"""
        items = []
        for item in files or ():
            if isinstance(item, ElaDiffFile):
                items.append(item)
            elif isinstance(item, dict):
                parsed = diffFileFromAny(item)
                if parsed is not None:
                    items.append(parsed)
        self._files = items
        self._expanded_runs.clear()
        self._rebuild()

    def setDiff(self, text: str, path: str = "") -> None:
        """用统一 diff 文本设置内容（无法解析时按纯文本显示）。"""
        files = parseUnifiedDiff(text)
        if not files and str(text or "").strip():
            files = [diffLines("", str(text or ""), path)]
        self.setFiles(files)

    def setFileDiff(self, before: str, after: str, path: str = "") -> None:
        """用 before / after 内容设置单文件 diff。"""
        self.setFiles([diffLines(before, after, path)])

    def files(self) -> list:
        """获取当前文件快照。"""
        return list(self._files)

    def setContextLines(self, lines: int) -> None:
        """设置折叠时保留的上下文行数。"""
        self._context_lines = max(0, int(lines))
        self._rebuild()

    def contextLines(self) -> int:
        """获取上下文行数。"""
        return self._context_lines

    def setMaxLines(self, lines: int) -> None:
        """设置最大渲染行数（超出只显示前 N 行）。"""
        self._max_lines = max(100, int(lines))
        self._rebuild()

    def maxLines(self) -> int:
        """获取最大渲染行数。"""
        return self._max_lines

    def setFileHeadersVisible(self, on: bool) -> None:
        """是否显示文件头行（单文件 diff 可关）。"""
        self._file_headers_visible = bool(on)
        self._rebuild()

    def setSyntaxHighlightEnabled(self, on: bool) -> None:
        """开关语法着色。"""
        self._syntax_enabled = bool(on)
        self._rebuild()

    def syntaxHighlightEnabled(self) -> bool:
        """语法着色是否开启。"""
        return self._syntax_enabled

    def setTokenColors(self, colors: Optional[dict]) -> None:
        """覆盖语法配色（``None`` 恢复默认明暗配色）。"""
        self._custom_palette = dict(colors) if isinstance(colors, dict) else None
        self._apply_theme()

    def syntaxPalette(self) -> dict:
        """当前语法配色快照。"""
        return dict(self._syntax_palette)

    def expandAll(self) -> None:
        """展开全部折叠段。"""
        self._expanded_runs = set(self._all_runs)
        self._rebuild()

    def collapseAll(self) -> None:
        """收起全部可折叠段。"""
        self._expanded_runs.clear()
        self._rebuild()

    def isTruncated(self) -> bool:
        """是否因超过上限被截断。"""
        return any(row.text.startswith("⋯ 已截断") for row in self._rows)

    def fileAt(self, block_number: int) -> Optional[str]:
        """按块号取所属文件路径（用于点击 / 测试）。"""
        row = self._row(block_number)
        return row[0] if row else None

    # -- 构建 --------------------------------------------------------------

    def _row(self, block_number: int):
        if 0 <= block_number < len(self._rows):
            return self._rows[block_number], block_number
        return None

    def _code_font(self) -> QFont:
        cjk = system_cjk_font_family()
        families = [cjk] if cjk else ["Consolas", "Cascadia Mono", "Courier New"]
        font = QFont()
        font.setFamilies(families)
        font.setPixelSize(CODE_PIXEL_SIZE)
        font.setStyleHint(QFont.StyleHint.Monospace)
        return font

    def _rebuild(self) -> None:
        rows: list[_VisibleRow] = []
        all_runs: set = set()
        file_spans: list = []
        total_limit = self._max_lines
        truncated = False
        show_headers = self._file_headers_visible and (
            len(self._files) > 1 or bool(self._files and self._files[0].path)
        )
        for file_index, file in enumerate(self._files):
            file_row_start = len(rows)
            old_lines = [line.text for line in file.lines if line.old_no is not None]
            new_lines = [line.text for line in file.lines if line.new_no is not None]
            if self._syntax_enabled and file.line_count <= total_limit:
                old_spans = _tokenize_lines(old_lines, file.path)
                new_spans = _tokenize_lines(new_lines, file.path)
            else:
                old_spans = [[] for _ in old_lines]
                new_spans = [[] for _ in new_lines]
            file_spans.append((old_spans, new_spans))
            if show_headers and file.path:
                rows.append(_VisibleRow(text=file.path, kind=DIFF_META, weak=True))
            if file.binary:
                rows.append(
                    _VisibleRow(
                        text=f"{file.path}（二进制文件，无文本 diff）",
                        kind=DIFF_META,
                        weak=True,
                    )
                )
                continue
            pending: list[ElaDiffLine] = []
            run_ordinal = 0

            def flush_context() -> None:
                nonlocal run_ordinal
                if not pending:
                    return
                count = len(pending)
                key = (file_index, run_ordinal)
                run_ordinal += 1
                if count > self._context_lines * 2:
                    all_runs.add(key)
                expanded = key in self._expanded_runs
                if count <= self._context_lines * 2 or expanded:
                    for line in pending:
                        rows.append(
                            _VisibleRow(
                                text=line.text,
                                kind=line.kind,
                                old_no=line.old_no,
                                new_no=line.new_no,
                            )
                        )
                else:
                    head = pending[: self._context_lines]
                    tail = (
                        pending[-self._context_lines :] if self._context_lines else []
                    )
                    for line in head:
                        rows.append(
                            _VisibleRow(
                                text=line.text,
                                kind=line.kind,
                                old_no=line.old_no,
                                new_no=line.new_no,
                            )
                        )
                    hidden = count - len(head) - len(tail)
                    rows.append(
                        _VisibleRow(
                            text=f"⋯ {hidden} 行未改动（点击展开）",
                            kind=DIFF_META,
                            weak=True,
                            fold=key,
                        )
                    )
                    for line in tail:
                        rows.append(
                            _VisibleRow(
                                text=line.text,
                                kind=line.kind,
                                old_no=line.old_no,
                                new_no=line.new_no,
                            )
                        )
                pending.clear()

            for line in file.lines:
                if line.kind == DIFF_CONTEXT:
                    pending.append(line)
                else:
                    flush_context()
                    rows.append(
                        _VisibleRow(
                            text=line.text,
                            kind=line.kind,
                            old_no=line.old_no,
                            new_no=line.new_no,
                        )
                    )
                if len(rows) >= total_limit:
                    truncated = True
                    break
            flush_context()
            for row in rows[file_row_start:]:
                if row.file_index < 0:
                    row.file_index = file_index
            if truncated:
                break
        if truncated:
            rows = rows[:total_limit]
            rows.append(
                _VisibleRow(
                    text=f"⋯ 已截断：diff 超过 {total_limit} 行",
                    kind=DIFF_META,
                    weak=True,
                )
            )
        self._rows = rows
        self._all_runs = all_runs
        self._file_spans = file_spans
        self._spans_by_block = self._build_spans(rows, file_spans)
        self.setPlainText("\n".join(row.text for row in rows))
        self._apply_block_backgrounds()
        self._update_gutter_width()
        self._highlighter.rehighlight()
        self.viewport().update()

    def _build_spans(self, rows: list, file_spans: list) -> dict:
        """把每行 token span 映射到块号（文件头 / 占位行没有 span）。"""
        result: dict = {}
        if not self._syntax_enabled:
            return result
        for block, row in enumerate(rows):
            if row.file_index < 0 or row.file_index >= len(file_spans):
                continue
            if row.kind in (DIFF_META, DIFF_HUNK):
                continue
            old_spans, new_spans = file_spans[row.file_index]
            if row.old_no is not None and row.old_no - 1 < len(old_spans):
                spans = old_spans[row.old_no - 1]
            elif row.new_no is not None and row.new_no - 1 < len(new_spans):
                spans = new_spans[row.new_no - 1]
            else:
                spans = ()
            if spans:
                result[block] = spans
        return result

    # -- 绘制 --------------------------------------------------------------

    def _row_background(self, kind: str) -> Optional[QColor]:
        if kind == DIFF_ADD:
            return self._add_bg
        if kind == DIFF_DEL:
            return self._del_bg
        if kind == DIFF_HUNK:
            return self._hunk_bg
        return None

    def _apply_block_backgrounds(self) -> None:
        document = self.document()
        block = document.firstBlock()
        index = 0
        while block.isValid():
            if index >= len(self._rows):
                break
            row = self._rows[index]
            fmt = block.blockFormat()
            bg = self._row_background(row.kind)
            if bg is not None:
                fmt.setBackground(bg)
            else:
                fmt.clearBackground()
            cursor = QTextCursor(block)
            cursor.setBlockFormat(fmt)
            block = block.next()
            index += 1

    def gutterWidth(self) -> int:
        """行号槽总宽。"""
        return (
            self._gutter_old_width
            + self._gutter_new_width
            + self._gutter_marker_width
            + _GUTTER_PAD
        )

    def _update_gutter_width(self, *_args) -> None:
        metrics = QFontMetrics(self.font())
        digits = max(2, len(str(max(1, self.blockCount()))))
        width = metrics.horizontalAdvance("9") * digits + 10
        self._gutter_old_width = width
        self._gutter_new_width = width
        self.setViewportMargins(self.gutterWidth(), 0, 0, 0)
        self._gutter.setGeometry(
            QRect(0, 0, self.gutterWidth(), self.viewport().height())
        )
        self._gutter.update()

    def _update_gutter(self, rect, dy) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def _on_cursor_changed(self) -> None:
        self._gutter.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._gutter.setGeometry(
            QRect(0, 0, self.gutterWidth(), self.viewport().height())
        )
        self._update_gutter_width()

    def paintGutter(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), self._gutter_bg)
        block = self.firstVisibleBlock()
        top = int(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        metrics = QFontMetrics(self.font())
        line_height = metrics.height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and top + line_height >= event.rect().top():
                index = block.blockNumber()
                if 0 <= index < len(self._rows):
                    row = self._rows[index]
                    self._paint_row_numbers(painter, row, top, line_height)
            step = int(self.blockBoundingRect(block).height())
            block = block.next()
            top += step
        painter.end()

    def _paint_row_numbers(self, painter, row, top: int, height: int) -> None:
        if row.weak:
            return
        mode = self._theme_mode
        muted = textMuted(mode)
        painter.setPen(muted)
        old_width = self._gutter_old_width
        new_width = self._gutter_new_width
        if row.old_no is not None:
            painter.drawText(
                QRect(0, top, old_width - 4, height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(row.old_no),
            )
        if row.new_no is not None:
            painter.drawText(
                QRect(old_width, top, new_width - 4, height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(row.new_no),
            )
        if row.kind == DIFF_ADD:
            painter.setPen(self._add_fg)
            painter.drawText(
                QRect(old_width + new_width, top, self._gutter_marker_width, height),
                Qt.AlignmentFlag.AlignCenter,
                "+",
            )
        elif row.kind == DIFF_DEL:
            painter.setPen(self._del_fg)
            painter.drawText(
                QRect(old_width + new_width, top, self._gutter_marker_width, height),
                Qt.AlignmentFlag.AlignCenter,
                "-",
            )

    # -- 交互 --------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            cursor = self.cursorForPosition(event.position().toPoint())
            row = self._row(cursor.blockNumber())
            if row is not None:
                item = row[0]
                if item.fold is not None:
                    self._expanded_runs.add(item.fold)
                    self._rebuild()
                    event.accept()
                    return
                if item.kind == DIFF_META and item.text:
                    self.fileClicked.emit(item.text)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = ElaMenu(self)
        copy = menu.addAction("复制")
        copy.setEnabled(self.textCursor().hasSelection())
        copy.triggered.connect(self.copy)
        select_all = menu.addAction("全选")
        select_all.triggered.connect(self.selectAll)
        execElaMenu(menu, event.globalPos())
        event.accept()

    # -- 主题 --------------------------------------------------------------

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        base = surfaceRaised(mode)
        self._gutter_bg = base
        self._add_fg = QColor(
            "#2da44e" if mode == ElaThemeType.ThemeMode.Light else "#3fb950"
        )
        self._del_fg = QColor(
            "#cf222e" if mode == ElaThemeType.ThemeMode.Light else "#f85149"
        )
        self._add_bg = self._blend(
            base, self._add_fg, 0.12 if mode == ElaThemeType.ThemeMode.Light else 0.16
        )
        self._del_bg = self._blend(
            base, self._del_fg, 0.10 if mode == ElaThemeType.ThemeMode.Light else 0.14
        )
        self._hunk_bg = self._blend(
            base,
            QColor("#0969da"),
            0.08 if mode == ElaThemeType.ThemeMode.Light else 0.12,
        )
        palette = self._custom_palette or (
            _SYNTAX_LIGHT if mode == ElaThemeType.ThemeMode.Light else _SYNTAX_DARK
        )
        self._syntax_palette = dict(palette)
        text_palette = self.palette()
        text_palette.setColor(QPalette.ColorRole.Text, text_color(mode))
        text_palette.setColor(QPalette.ColorRole.PlaceholderText, textMuted(mode))
        self.setPalette(text_palette)
        viewport_palette = self.viewport().palette()
        viewport_palette.setColor(QPalette.ColorRole.Text, text_color(mode))
        viewport_palette.setColor(QPalette.ColorRole.PlaceholderText, textMuted(mode))
        self.viewport().setPalette(viewport_palette)
        # Base 最后写：setPalette 可能把 viewport 的 Base 重置回系统色，而
        # QPlainTextEdit 读的就是 viewport Base（背景发白的根因）。
        setTextBaseColor(self, base)
        self._apply_block_backgrounds()
        self._highlighter.rehighlight()
        self._gutter.update()
        self.viewport().update()

    @staticmethod
    def _blend(base: QColor, other: QColor, t: float) -> QColor:
        from ._theme import blend

        return blend(base, other, t)

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


__all__ = [
    "DEFAULT_CONTEXT_LINES",
    "DEFAULT_MAX_LINES",
    "ElaDiffView",
]
