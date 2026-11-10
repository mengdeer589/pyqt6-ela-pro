"""代码卡 / 语法高亮 / 行号方法组。"""

from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QBrush,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextLength,
    QTextTable,
    QTextTableCellFormat,
    QTextTableFormat,
)

from .._colors import parse_color
from .._internal import fontFamilyAvailable, system_cjk_font_family
from .tokens import (
    _CODE_CELL_LEFT_PADDING,
    _CODE_CELL_PADDING_BOTTOM,
    _CODE_CELL_PADDING_RIGHT,
    _CODE_CELL_PADDING_TOP,
    _CODE_LANG_PROPERTY,
    _CODE_MARKER,
    _CODE_MARKER_VALUE,
    _CODE_SOURCE_PROPERTY,
    _CODE_TEXT_PROPERTY,
    _CODE_TOKEN_PREFIX,
    _CODE_TOKEN_SUFFIX,
    _INLINE_CODE_MARK,
    _LINE_NUMBER_LEFT_GAP,
    _LINE_NUMBER_MIN_DIGITS,
    _LINE_NUMBER_RIGHT_GAP,
)


_PREFERRED_CODE_FONTS = ("Consolas", "Cascadia Mono", "Courier New")

_CODE_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\uac00-\ud7af\U00020000-\U0002fa1f]"
)


def _contains_cjk(text: str) -> bool:
    """代码文本是否含 CJK（含日文假名 / 韩文）。"""
    return bool(text) and _CODE_CJK_RE.search(text) is not None


_HIGHLIGHT_MAX_CHARS = 20000

_STREAM_HIGHLIGHT_MAX_CHARS = 4096

_HIGHLIGHT_CACHE_CAP = 32

_PYGMENTS_STATE = {"loaded": False, "module": None}

_DEFAULT_CODE_FONT_FAMILY: Optional[str] = None

_DEFAULT_LATIN_CODE_FONT_FAMILY: Optional[str] = None

_CJK_MONOSPACE_FONTS = ("NSimSun", "SimSun", "新宋体", "宋体")


def _font_family_available(family: str) -> bool:
    """字体族是否可用（兼容 GDI 中文系统的本地化族名）。"""
    return fontFamilyAvailable(family)


def _default_code_font_family() -> str:
    """选择默认代码字体族（**进程级缓存**）。

    中文系统优先 ``NSimSun`` / ``SimSun``（单族 CJK 等宽，Win7 中文版自带）；
    没有时回退 CJK UI 字体。Consolas 之类的 Latin 等宽渲染 CJK 会走逐字形
    fallback shaping，Win7 上 ~3ms/行且进程级毒化，中文系统不踩。
    """
    global _DEFAULT_CODE_FONT_FAMILY
    if _DEFAULT_CODE_FONT_FAMILY is None:
        cjk_family = system_cjk_font_family()
        if cjk_family:
            for name in _CJK_MONOSPACE_FONTS:
                if _font_family_available(name):
                    _DEFAULT_CODE_FONT_FAMILY = name
                    break
            else:
                _DEFAULT_CODE_FONT_FAMILY = cjk_family
        else:
            families = set(QFontDatabase.families())
            for name in _PREFERRED_CODE_FONTS:
                if name in families:
                    _DEFAULT_CODE_FONT_FAMILY = name
                    break
            else:
                fixed_font = QFontDatabase.systemFont(
                    QFontDatabase.SystemFont.FixedFont
                )
                _DEFAULT_CODE_FONT_FAMILY = (
                    fixed_font.family() or _PREFERRED_CODE_FONTS[0]
                )
    return _DEFAULT_CODE_FONT_FAMILY


def _default_latin_code_font_family() -> str:
    """纯 ASCII 代码默认字体（进程级缓存）。

    中文系统上 ``NSimSun`` 的 Latin 字形偏宋体，纯 ASCII 代码块改用
    Consolas 一类 Latin 等宽字体：没有 CJK 字符就不会触发 fallback shaping。
    """
    global _DEFAULT_LATIN_CODE_FONT_FAMILY
    if _DEFAULT_LATIN_CODE_FONT_FAMILY is None:
        if not system_cjk_font_family():
            _DEFAULT_LATIN_CODE_FONT_FAMILY = _default_code_font_family()
        else:
            for name in _PREFERRED_CODE_FONTS:
                if _font_family_available(name):
                    _DEFAULT_LATIN_CODE_FONT_FAMILY = name
                    break
            else:
                fixed_font = QFontDatabase.systemFont(
                    QFontDatabase.SystemFont.FixedFont
                )
                _DEFAULT_LATIN_CODE_FONT_FAMILY = (
                    fixed_font.family() or _PREFERRED_CODE_FONTS[0]
                )
    return _DEFAULT_LATIN_CODE_FONT_FAMILY


def _code_format_families(code_font: str) -> list:
    """代码字符格式的字体族列表。
    中文系统收成**单族**：多族字体列表在 Win7 上是独立的慢 shaping 路径
    （逐字形族匹配，与各族是否 CJK 无关）且同样进程级毒化，其中后备族
    """
    if system_cjk_font_family():
        return [code_font]
    return [code_font, "Microsoft YaHei UI", "Microsoft YaHei"]


def _load_pygments():
    """惰性导入 Pygments，返回 ``(get_lexer_by_name, Token)``；缺失时返回
    ``None``（组件自动降级为纯代码块样式）。
    """
    if _PYGMENTS_STATE["loaded"]:
        return _PYGMENTS_STATE["module"]
    _PYGMENTS_STATE["loaded"] = True
    try:
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Token

        _PYGMENTS_STATE["module"] = (get_lexer_by_name, Token)
    except ImportError:
        _PYGMENTS_STATE["module"] = None
    return _PYGMENTS_STATE["module"]


_LEXER_CACHE: dict = {}

_LEXER_MISS = object()

_TOKEN_KIND_CACHE: dict = {}

_TOKEN_KIND_MISS = object()

_TOKEN_KIND_STYLES = {
    "comment": ("comment", True),
    "type": ("type", False),
    "constant": ("constant", False),
    "keyword": ("keyword", True),
    "function": ("function", False),
    "class": ("class", False),
    "decorator": ("decorator", False),
    "builtin": ("builtin", False),
    "attribute": ("attribute", False),
    "tag": ("tag", False),
    "string": ("string", False),
    "number": ("number", False),
    "operator": ("operator", False),
}


def _token_kind(token_type, token):
    """Pygments token → 分类名（``None`` = 未覆盖）；结果按 token 类型缓存。"""
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


def _token_style(token_type, token, palette):
    """Pygments token → ``(颜色, 斜体)``；未覆盖的 token 返回 ``None``。"""
    kind = _token_kind(token_type, token)
    if kind is None:
        return None
    key, italic = _TOKEN_KIND_STYLES[kind]
    return palette[key], italic


class _MarkdownCodeMixin:
    def _font_for_code(self, text: str) -> str:
        """纯 ASCII 代码用 Latin 等宽字体；含 CJK 时用 CJK 安全字体。"""
        if _contains_cjk(text):
            return self._code_font_family
        return self._code_latin_font_family

    def _code_format(self, family: Optional[str] = None) -> QTextCharFormat:
        """行内代码格式（等宽 + 标记属性；底色/圆角由自绘提供）。"""
        fmt = QTextCharFormat()
        fmt.setFontFamilies(_code_format_families(family or self._code_font_family))
        fmt.setFontFixedPitch(True)
        point_size = self._math_point_size()
        if point_size > 0:
            fmt.setFontPointSize(point_size * self._md_layout["code"]["font_scale"])
        fmt.setProperty(_INLINE_CODE_MARK, True)
        fmt.setForeground(self._md_code_color)
        return fmt

    def _code_text_format(self, family: Optional[str] = None) -> QTextCharFormat:
        """围栏代码文本格式（0.95em 等宽；底色与边框由单元格提供）。"""
        fmt = QTextCharFormat()
        fmt.setFontFamilies(_code_format_families(family or self._code_font_family))
        fmt.setFontFixedPitch(True)
        fmt.setForeground(self._code_text)
        base_font = self.document().defaultFont()
        point_size = base_font.pointSizeF()
        if point_size > 0:
            fmt.setFontPointSize(point_size * self._md_layout["code"]["font_scale"])
        return fmt

    def _code_table_format(
        self,
        lang: str,
        code: str,
        source_lines: Optional[tuple] = None,
    ) -> QTextTableFormat:
        """代码块包裹表格式：整行宽度、表格边框 0（圆角边框由自绘提供）。"""
        fmt = QTextTableFormat()
        fmt.setBorder(0)
        fmt.setBorderCollapse(True)
        fmt.setCellPadding(0)
        fmt.setCellSpacing(0)
        fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        fmt.setTopMargin(8)
        fmt.setBottomMargin(8)
        fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
        fmt.setProperty(_CODE_MARKER, _CODE_MARKER_VALUE)
        fmt.setProperty(_CODE_TEXT_PROPERTY, code)
        fmt.setProperty(_CODE_LANG_PROPERTY, lang)
        if source_lines is not None:
            fmt.setProperty(
                _CODE_SOURCE_PROPERTY, f"{source_lines[0]},{source_lines[1]}"
            )
        return fmt

    def _code_cell_format(
        self, left_padding: float = _CODE_CELL_LEFT_PADDING
    ) -> QTextTableCellFormat:
        """代码单元格格式：底色 + 内边距（圆角边框由自绘提供）。"""
        fmt = QTextTableCellFormat()
        fmt.setBackground(QBrush(self._code_bg))
        fmt.setBorder(0)
        fmt.setTopPadding(_CODE_CELL_PADDING_TOP)
        fmt.setBottomPadding(_CODE_CELL_PADDING_BOTTOM)
        fmt.setLeftPadding(left_padding)
        fmt.setRightPadding(_CODE_CELL_PADDING_RIGHT)
        return fmt

    def _line_number_metrics(self) -> tuple[QFont, QFontMetricsF]:
        """行号字体与 metrics（按字体配置缓存，避免逐代码块重建）。"""
        key = (
            self._code_latin_font_family,
            self._code_font_family,
            float(self._md_layout["code"]["font_scale"]),
            round(self._base_font_point_size * self._zoom_factor, 4),
        )
        cached = self._line_number_metrics_cache
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        font = QFont(self._code_text_format(self._code_latin_font_family).font())
        if font.pointSizeF() <= 0 and font.pixelSize() <= 0:
            font = QFont(self.document().defaultFont())
            font.setFamilies(_code_format_families(self._code_latin_font_family))
            font.setFixedPitch(True)
        metrics = QFontMetricsF(font)
        self._line_number_metrics_cache = (key, font, metrics)
        return font, metrics

    def _line_number_font(self) -> QFont:
        """行号绘制字体（纯数字，用 Latin 等宽字体）。"""
        return self._line_number_metrics()[0]

    def _code_line_number_padding(self, line_count: int) -> float:
        """按行号位数预留在侧槽宽（含与代码文本的间隔）。"""
        digits = max(_LINE_NUMBER_MIN_DIGITS, len(str(max(1, int(line_count)))))
        advance = self._line_number_metrics()[1].horizontalAdvance("8")
        return _LINE_NUMBER_LEFT_GAP + advance * digits + _LINE_NUMBER_RIGHT_GAP

    def _insert_fenced_code(self, document: QTextDocument) -> None:
        """用真实代码内容替换占位符：表格包裹（可选语言标签行）+ 语法高亮。
        逐行字符底色会覆盖块 margin，导致多段围栏灰色连片、无内边距；
        改为表格：底色与 padding 由单元格提供，块间距由表格外边距提供。
        """
        if not self._fenced_blocks:
            return
        # 多张代码卡合并成一次编辑块：每张卡内部的 endEditBlock 都会触发重排，
        # 一页几十个代码块时能省下可观的布局时间（嵌套编辑块 Qt 会一并合并）
        outer = QTextCursor(document)
        outer.beginEditBlock()
        try:
            entries = []
            for index, (lang, code_text, closed) in enumerate(self._fenced_blocks):
                token = f"{_CODE_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}"
                source_lines = (
                    self._fenced_source_lines[index]
                    if index < len(self._fenced_source_lines)
                    else None
                )
                entries.append((token, (index, lang, code_text, closed, source_lines)))

            def replace(found: QTextCursor, data) -> None:
                index, lang, code_text, closed, source_lines = data
                self._insert_code_card(
                    found,
                    lang,
                    code_text,
                    closed=closed,
                    fold_index=index,
                    source_lines=source_lines,
                )

            self._replace_tokens_in_order(document, entries, replace)
        finally:
            outer.endEditBlock()

    def _insert_code_card(
        self,
        cursor: QTextCursor,
        lang: str,
        code_text: str,
        closed: bool = True,
        fold_index: Optional[int] = None,
        source_lines: Optional[tuple] = None,
    ) -> None:
        """把当前选中的占位符替换为代码卡片（无头栏、单行）。
        语言标签不再占一行，改为存入表格式供复制按钮 tooltip 展示。
        不自己开关编辑块：调用方（``_insert_fenced_code`` / ``_embed_mermaid``）
        """
        document = cursor.document()
        cursor.removeSelectedText()

        lines = code_text.split("\n")
        collapsed = (
            fold_index is not None
            and self._code_collapse_lines > 0
            and not self._stream_active
            and len(lines) > self._code_collapse_lines + 1
            and fold_index not in self._expanded_code_blocks
        )
        visible_code = (
            "\n".join(lines[: self._code_collapse_lines]) if collapsed else code_text
        )
        table = cursor.insertTable(
            1, 1, self._code_table_format(lang, code_text, source_lines)
        )
        code_cell = table.cellAt(0, 0)
        line_count = visible_code.count("\n") + 1
        code_cell.setFormat(
            self._code_cell_format(self._code_line_number_padding(line_count))
        )
        cell_cursor = code_cell.firstCursorPosition()

        highlight_lang = lang
        if not closed and len(visible_code) > _STREAM_HIGHLIGHT_MAX_CHARS:
            # 未闭合围栏的中间态跳过高亮：内容每次刷新都在增长，
            # 全量词法分析且缓存中间态会显著拖慢流式渲染
            highlight_lang = ""
        self._insert_code_text(cell_cursor, visible_code, highlight_lang)
        if fold_index is not None:
            self._insert_code_fold_link(cell_cursor, fold_index, lines, collapsed)
        self._style_code_cell_blocks(document, code_cell)

    def _insert_code_text(
        self, cell_cursor: QTextCursor, code_text: str, lang: str
    ) -> None:
        """把代码写入单元格（``diff`` 行级底色；逐行拆分保留高亮）。"""
        styles = self._highlight_code(code_text, lang)
        is_diff = lang.lower() == "diff"
        if not is_diff:
            for text, fmt in styles:
                if text:
                    cell_cursor.insertText(text, fmt)
            return
        lines = self._split_styled_lines(styles)
        for position, parts in enumerate(lines):
            if position:
                cell_cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
            line_bg = self._diff_line_background(parts)
            for text, fmt in parts:
                if not text:
                    continue
                if line_bg is not None:
                    fmt = QTextCharFormat(fmt)
                    fmt.setBackground(line_bg)
                cell_cursor.insertText(text, fmt)

    def _diff_line_background(self, parts: list) -> Optional[QBrush]:
        """``diff`` 代码行底色：``+`` 绿、``-`` 红、``@@`` 蓝（其余无）。"""
        text = "".join(part[0] for part in parts).lstrip()
        if text.startswith("@@"):
            return QBrush(self._diff_hunk_bg)
        if text.startswith("+") and not text.startswith("+++"):
            return QBrush(self._diff_add_bg)
        if text.startswith("-") and not text.startswith("---"):
            return QBrush(self._diff_del_bg)
        return None

    def _insert_code_fold_link(
        self, cell_cursor: QTextCursor, index: int, lines: list, collapsed: bool
    ) -> None:
        """折叠/展开链接行（仅在启用折叠且代码足够长时插入）。"""
        if self._code_collapse_lines <= 0 or self._stream_active:
            return
        if len(lines) <= self._code_collapse_lines + 1:
            return
        cell_cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        fmt = QTextCharFormat(self._code_text_format())
        fmt.setAnchor(True)
        fmt.setAnchorHref(f"#elacode-expand-{index}")
        fmt.setForeground(self._link_color)
        if collapsed:
            remaining = len(lines) - self._code_collapse_lines
            cell_cursor.insertText(f"+ 展开其余 {remaining} 行", fmt)
        else:
            cell_cursor.insertText("− 收起", fmt)

    @staticmethod
    def _split_styled_lines(styles: list) -> list:
        """高亮 token 序列按换行拆分为每行的 [(文本, 格式)]。"""
        lines: list[list] = [[]]
        for text, fmt in styles:
            parts = text.split("\n")
            for position, part in enumerate(parts):
                if position:
                    lines.append([])
                if part:
                    lines[-1].append((part, fmt))
        return lines

    def _style_code_cell_blocks(self, document: QTextDocument, cell) -> None:
        """代码单元格内块：主题行高、上下 margin 0（间距由单元格 padding 提供）。"""
        first = cell.firstCursorPosition().blockNumber()
        last = cell.lastCursorPosition().blockNumber()
        block = document.findBlockByNumber(first)
        line_height = self._md_layout["code"]["line_height"]
        while block.isValid() and block.blockNumber() <= last:
            block_format = block.blockFormat()
            block_format.setLineHeight(
                line_height,
                QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
            )
            block_format.setTopMargin(0)
            block_format.setBottomMargin(0)
            cursor = QTextCursor(document)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(block_format)
            block = block.next()

    def _highlight_code(self, code: str, lang: str) -> list:
        """代码 → [(文本, 字符格式)]；未安装 Pygments / 无语言时整段底色。"""
        module = _load_pygments()
        if module is None or not lang or len(code) > _HIGHLIGHT_MAX_CHARS:
            return [(code, self._code_text_format(self._font_for_code(code)))]
        get_lexer_by_name, token_module = module
        theme_key = (self._md_theme, "dark" if self._is_dark_theme else "light")
        cache_key = (lang, code, theme_key)
        cached = self._highlight_cache.get(cache_key)
        if cached is not None:
            return cached
        lexer = _LEXER_CACHE.get(lang, _LEXER_MISS)
        if lexer is _LEXER_MISS:
            try:
                lexer = get_lexer_by_name(lang, stripnl=False, ensurenl=False)
            except Exception:
                lexer = None
            _LEXER_CACHE[lang] = lexer
        base = self._code_text_format(self._font_for_code(code))
        if lexer is None:
            return [(code, base)]
        palette = self._token_palette
        result = []
        try:
            for token_type, value in lexer.get_tokens(code):
                if not value:
                    continue
                fmt = QTextCharFormat(base)
                style = _token_style(token_type, token_module, palette)
                if style is not None:
                    color, italic = style
                    fmt.setForeground(parse_color(color))
                    if italic:
                        fmt.setFontItalic(True)
                result.append((value, fmt))
        except Exception:
            return [(code, base)]
        if not result:
            return [(code, base)]
        if self._highlight_cache_cap > 0:
            while len(self._highlight_cache) >= self._highlight_cache_cap:
                self._highlight_cache.pop(next(iter(self._highlight_cache)))
            self._highlight_cache[cache_key] = result
        return result

    def _in_code_table(self, cursor: QTextCursor) -> bool:
        """游标是否位于代码块包裹表内。"""
        frame = cursor.currentFrame()
        while frame is not None:
            if isinstance(frame, QTextTable) and self._is_code_table(frame):
                return True
            frame = frame.parentFrame()
        return False

    @staticmethod
    def _code_table_text(table: QTextTable) -> str:
        """提取代码表内容（优先读取表格式上的原始代码，跳过语言标签行）。"""
        stored = table.format().property(_CODE_TEXT_PROPERTY)
        if isinstance(stored, str):
            return stored
        start = 1 if table.rows() > 1 else 0
        parts = []
        for row in range(start, table.rows()):
            cell = table.cellAt(row, 0)
            cursor = QTextCursor(cell.firstCursorPosition())
            cursor.setPosition(
                cell.lastCursorPosition().position(),
                QTextCursor.MoveMode.KeepAnchor,
            )
            parts.append(cursor.selection().toPlainText())
        return "\n".join(parts)

    def _copy_code_at_cursor(self) -> None:
        frame = self._text_browser.textCursor().currentFrame()
        while frame is not None:
            if isinstance(frame, QTextTable) and self._is_code_table(frame):
                self._copy_text(self._code_table_text(frame))
                return
            frame = frame.parentFrame()
