"""terminal_view.view：ElaTerminalView 主控件与文档重建。"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PyQt6.QtCore import (
    QEvent,
    QFile,
    QRect,
    QRectF,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QShowEvent,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaLineEdit,
    ElaMenu,
    ElaPlainTextEdit,
    ElaText,
    ElaThemeType,
)

from .._colors import parse_color
from .._internal import (
    applyMissingGlyphFonts,
    execElaMenu,
    is_deleted,
    system_cjk_font_family,
)
from .._styles import editBorderlessStyle
from ..ela_button import ElaButton
from ..tooltips import ElaToolTipPositionType, set_tooltip
from ..widget_base import ElaThemeWidget
from .ansi import (
    AnsiColor,
    AnsiParser,
    TerminalLine,
    TerminalStyle,
    _DIM_RATIO,
    _ZERO,
    _blend,
    _indexed_key,
    _indexed_rgb,
)
from .theme import (
    _DEFAULT_FONT_FAMILY,
    defaultTerminalTheme,
    _TERMINAL_THEMES,
    _default_font_families,
    _resolve_palette,
)

logger = logging.getLogger(__name__)


#: 逐帧合并写入的定时器间隔（毫秒）
_FLUSH_INTERVAL_MS = 0

#: 过滤重建的去抖间隔（毫秒）
_FILTER_DEBOUNCE_MS = 150

#: 默认保留行数上限（0 表示不限）
_DEFAULT_MAX_LINES = 10000

#: 默认字号（像素）
_DEFAULT_FONT_SIZE = 13

#: 字号可调范围（像素）
_MIN_FONT_SIZE = 8
_MAX_FONT_SIZE = 32

#: ``maxLines`` 的上限。``0`` 表示不限，而 ``inf`` 语义上就是「不限」，
#: 但落到 1,000,000 这个明确上限更好：让「上限」这个概念始终有确定值。
_MAX_LINES_CAP = 1_000_000


def _clamped_int(value, low: int, high: int, default: int) -> int:
    """把可能非有限的数值夹到 ``[low, high]`` 再取整。
    必须先夹后转：``int(inf)`` 抛 ``OverflowError``（不是 ``ValueError``），
    ``max(low, min(high, int(x)))`` 会让异常先抛出。``nan`` / 不可转换值落 ``default``。
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError 必须显式列出：``float(10 ** 400)``（宿主传了个巨大 int）
        # 抛的是它，而它**不是** ValueError 的子类
        return default
    if number != number:  # nan
        return default
    if number < low:
        return low
    if number > high:  # inf 也落在这里
        return high
    return int(number)


#: 终端卡片圆角半径
def _alive(widget) -> bool:  # noqa: ANN001
    """C++ 对象是否仍存活（定时器 / 主题回调里必须先问一句）。"""
    try:
        return not is_deleted(widget)
    except (RuntimeError, TypeError):
        return False


_CARD_RADIUS = 8

#: 行号槽左右内边距 / 最小宽度
_GUTTER_PAD = 10
_GUTTER_MIN_WIDTH = 46

#: 搜索命中高亮色（向背景混合）
_HIGHLIGHT = QColor("#ffcf4d")
_HIGHLIGHT_RATIO = 0.45
#: 格式缓存上限：truecolor 输出可产生近乎无限的唯一样式
_FORMAT_CACHE_LIMIT = 512


class _TerminalCard(QWidget):
    """终端底板：自绘圆角底色 + 边框（聚焦时边框换强调色）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bg = QColor()
        self._border = QColor()
        self._focused = False

    def setFocused(self, on: bool) -> None:  # noqa: N802 (Qt 命名)
        on = bool(on)
        if on == self._focused:
            return
        self._focused = on
        self.update()

    def applyTheme(self, bg: QColor, border: QColor) -> None:  # noqa: N802
        self._bg = QColor(bg)
        self._border = QColor(border)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)
        painter.fillPath(path, self._bg)
        pen = QPen(self._border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


class _Gutter(QWidget):
    """行号槽：与编辑框垂直滚动严格同步，右对齐绘制当前可见块的行号。"""

    def __init__(self, view: "ElaTerminalView") -> None:
        super().__init__(view)
        self._view = view
        self.setFixedWidth(_GUTTER_MIN_WIDTH)

    def syncWidth(self) -> None:  # noqa: N802 (Qt 命名)
        """按最大行号位数 + 绘制字体重算槽宽（跟随终端字号 / 字体族）。"""
        digits = len(str(max(1, self._view.maxLines() or 9999)))
        advance = QFontMetrics(self._view._gutter_font).horizontalAdvance("8") * digits
        self.setFixedWidth(max(_GUTTER_MIN_WIDTH, _GUTTER_PAD * 2 + advance))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        view = self._view
        if not view._doc_lines:
            return
        painter = QPainter(self)
        edit = view._edit
        painter.setFont(view._gutter_font)
        painter.setPen(view._gutter_text_color())
        block = edit.firstVisibleBlock()
        if block.isValid():
            offset = edit.blockBoundingGeometry(block).translated(edit.contentOffset())
            bottom = offset.top() + edit.viewport().height()
            number = block.blockNumber() + 1
            rect = QRect(0, 0, self.width() - _GUTTER_PAD, 0)
            while block.isValid() and offset.top() <= bottom:
                rect.setY(int(offset.top()))
                rect.setHeight(int(offset.size().height()))
                painter.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(number),
                )
                block = block.next()
                if not block.isValid():
                    break
                offset = edit.blockBoundingGeometry(block).translated(
                    edit.contentOffset()
                )
                number += 1
        painter.end()


class ElaTerminalView(ElaThemeWidget):
    """终端输出展示组件（只读）：ANSI 色彩、行号槽、自动跟随、过滤、导出。

    组件不执行命令，输出由宿主 ``append`` 喂入；缺字形兜底与进度条字符约束见
    ``docs/terminal.md``。信号：``linesAppended`` / ``cleared`` /
    ``filterChanged`` / ``matchPositionChanged``。

    :param maxLines: 保留行数上限，``0`` 表示不限
    :param paletteName: 调色板名称（见 :func:`terminalThemes`）
    """

    linesAppended = pyqtSignal(int)
    cleared = pyqtSignal()
    filterChanged = pyqtSignal(str, int)
    matchPositionChanged = pyqtSignal(int)

    def __init__(
        self,
        maxLines: int = _DEFAULT_MAX_LINES,  # noqa: N803 (Qt 命名)
        paletteName: str = "",  # noqa: N803 (Qt 命名)
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ElaTerminalView")
        self.setMinimumHeight(120)

        self._parser = AnsiParser()
        self._lines: list = []
        self._max_lines = _clamped_int(maxLines, 0, _MAX_LINES_CAP, _MAX_LINES_CAP)
        self._pending_render = 0
        self._filter = ""
        self._match_index: list = []
        self._match_pos = -1
        #: 已发射给宿主的过滤词（用于 :attr:`filterChanged` 的「只在真变时发」判定）
        self._emitted_filter = ""
        self._font_size = _DEFAULT_FONT_SIZE
        #: 终端字体族列表（按序回退；中文系统默认单族 CJK 字体，其它系统 Consolas）
        self._font_families: list[str] = _default_font_families()
        #: 中文系统：主字体缺字形时给字符套单族符号字体（默认开；不改文本）
        self._missing_glyph_fallback = system_cjk_font_family() is not None
        #: 已做过缺字形兜底的文档位置（尾行重写 / 裁头时回退）
        self._glyph_guard_pos = 0
        self._palette_name = (
            paletteName if paletteName in _TERMINAL_THEMES else defaultTerminalTheme()
        )
        self._palette: dict = {}
        self._format_cache: dict = {}
        self._highlight = QColor()
        # 宿主持久覆盖的高亮色（None = 用背景派生的默认黄）。与 ``_highlight``
        # 分开，``_refresh_palette`` 换肤时不会冲掉用户覆盖。
        self._highlight_override: Optional[QColor] = None
        self._gutter_font = QFont(_DEFAULT_FONT_FAMILY)
        self._doc_lines = 0
        # 文档末尾是否挂着「当前行」块（未被 \n 收口的那一行，见 _rebuild_tail）
        self._doc_tail = False
        # 已上屏尾行的内容快照（文本 + 逐 span 样式）；只有它变了才重画尾块
        self._doc_tail_key: Optional[tuple] = None
        self._auto_scroll = True
        self._following = True
        self._auto_scrolling = False
        self._line_numbers_visible = True
        self._toolbar_visible = True
        self._word_wrap = False

        self._buildUi()
        self._buildTimers()
        self._apply_font()
        self._refresh_palette()

    # ── 构建 ──────────────────────────────────────────────────────────

    def _buildUi(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self._toolbar = self._build_toolbar()
        outer.addWidget(self._toolbar)

        self._card = _TerminalCard(self)
        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        card_layout.setSpacing(0)

        self._gutter = _Gutter(self)
        card_layout.addWidget(self._gutter)

        self._edit = ElaPlainTextEdit(self._card)
        # 原生自绘边框（1px 边框 + 底色 + 底部粗线 + 聚焦展开条）由卡片接管
        # 走共享单例：setStyle 不接管所有权，临时实例会被 sip 立刻回收
        self._edit.setStyle(editBorderlessStyle())
        self._edit.setFrameShape(QFrame.Shape.NoFrame)
        self._edit.setReadOnly(True)
        # QPlainTextEdit 的 document 天生只按纯文本排版（与 QTextEdit 不同，
        # 不存在 mightBeRichText 判定），所以输出里的 "<b>" 不会被当标签解析
        self._edit.document().setUndoRedoEnabled(False)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._edit.installEventFilter(self)
        # 右键菜单事件投递到 viewport（QAbstractScrollArea 的视口），不是编辑框本体
        self._edit.viewport().installEventFilter(self)
        self._edit.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self._edit.textChanged.connect(self._on_text_changed)
        card_layout.addWidget(self._edit, 1)
        outer.addWidget(self._card, 1)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget(self)
        bar.setObjectName("ElaTerminalToolbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        def button(text: str, icon, slot, tip: str) -> ElaButton:
            btn = ElaButton(
                text,
                icon=icon,
                iconSize=14,
                variant="text",
                color="primary",
                size="small",
                parent=bar,
            )
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip(tip)
            set_tooltip(btn, tip, ElaToolTipPositionType.Top)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
            return btn

        button(
            "复制全部",
            ElaIconType.IconName.Copy,
            self.copyAll,
            "复制全部内容到剪贴板",
        )
        button(
            "导出",
            ElaIconType.IconName.FolderOpen,
            self._export_dialog,
            "导出为文本文件",
        )
        button(
            "清除",
            ElaIconType.IconName.DeleteLeft,
            self.clear,
            "清空终端内容",
        )
        lay.addStretch(1)
        button(
            "",
            ElaIconType.IconName.Minus,
            lambda: self.setFontSize(self._font_size - 1),
            "缩小字号",
        )
        button(
            "",
            ElaIconType.IconName.Plus,
            lambda: self.setFontSize(self._font_size + 1),
            "放大字号",
        )
        self._follow_button = button(
            "跟随",
            ElaIconType.IconName.ArrowDown,
            self._toggle_follow,
            "新输出自动滚动到底部",
        )
        self._follow_button.setCheckable(True)
        self._follow_button.setChecked(True)

        self._search = ElaLineEdit(bar)
        self._search.setObjectName("ElaTerminalSearch")
        self._search.setPlaceholderText("搜索输出…")
        self._search.setClearButtonEnabled(True)
        self._search.setBorderRadius(6)
        self._search.setFixedWidth(220)
        self._search.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._search.textChanged.connect(self.setFilter)
        self._search.returnPressed.connect(self.findNext)
        lay.addWidget(self._search)

        self._match_label = ElaText("", bar)
        self._match_label.setObjectName("ElaTerminalMatchLabel")
        self._match_label.setTextPixelSize(12)
        # 匹配计数只由内部整数派生，仍按仓库约定显式声明纯文本格式
        self._match_label.setTextFormat(Qt.TextFormat.PlainText)
        self._match_label.setFixedWidth(88)
        lay.addWidget(self._match_label)
        return bar

    def _buildTimers(self) -> None:  # noqa: N802 (Qt 命名)
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(_FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_render)

        #: 换肤 / 换配色族时若不可见则只标记，等 showEvent 补重建（见 _rebuild_when_visible）
        self._needs_rebuild = False
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(_FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self._rebuild_document)

    # ── 写入 ──────────────────────────────────────────────────────────

    def append(self, data) -> None:  # noqa: ANN001
        """追加一段原始输出（可含 ANSI 转义序列）。

        可高频调用：内部按帧合并，同一帧内多次 ``append`` 只重排一次。

        :param data: ``str`` 直接追加；``bytes`` / ``bytearray`` 按 UTF-8 宽松
            解码后追加（``errors="replace"``，非法字节不抛异常）
        """
        if not data:
            return
        if not isinstance(data, str):
            data = bytes(data).decode("utf-8", errors="replace")
        lines = self._parser.feed(data)
        if self._parser.takeClear():
            self.clear()
        if not lines:
            # 没有收口整行，但「当前行」仍可能要画：解析器缓冲里已有内容
            # （如 ``Password:``）。不在此启动 flush 的话，那行既不显示也不计数。
            # 文本没变也要重画：``append("\x1b[0m")`` 只改样式不带文本。
            if self._parser.pendingLine() is None:
                return
            # 过滤态也走 flush：它只同步尾块（完整行的增量在过滤态下没有
            # 意义、等重建），否则尾行会冻在「上一次收行」那一刻
            self._flush_timer.start()
            return
        self._lines.extend(lines)
        self._trim_lines()
        self._pending_render += len(lines)
        if self._filter:
            # 过滤态下增量渲染没有意义，等去抖后整体重建
            self._filter_timer.start()
        else:
            self._flush_timer.start()
        self.linesAppended.emit(len(lines))

    def appendLine(self, text: str) -> None:  # noqa: N802 (Qt 命名)
        """追加一行（自动补换行，忽略文本自带的结尾换行）。"""
        self.append(text.rstrip("\r\n") + "\n")

    def clear(self) -> None:
        """清空全部内容（数据模型、文档、命中列表）。"""
        self._flush_timer.stop()
        self._filter_timer.stop()
        self._parser.reset()
        self._lines = []
        self._pending_render = 0
        self._doc_lines = 0
        self._doc_tail = False
        self._doc_tail_key = None
        self._glyph_guard_pos = 0
        self._match_index = []
        self._match_pos = -1
        self._format_cache.clear()
        self._edit.clear()
        self._update_match_label()
        self.cleared.emit()

    def _trim_lines(self) -> None:
        """按上限淘汰数据模型头部。"""
        if self._max_lines and len(self._lines) > self._max_lines:
            del self._lines[: len(self._lines) - self._max_lines]

    # ── 读取 ──────────────────────────────────────────────────────────

    def lineCount(self) -> int:  # noqa: N802 (Qt 命名)
        """数据模型中的保留行数（不受过滤影响）。"""
        return len(self._lines)

    def visibleLineCount(self) -> int:  # noqa: N802 (Qt 命名)
        """当前实际渲染的行数（过滤后可能少于 :meth:`lineCount`）。"""
        return self._doc_lines + (1 if self._doc_tail else 0)

    def toPlainText(self) -> str:  # noqa: N802 (Qt 命名)
        """导出全部内容为纯文本（不含转义序列，不受过滤影响）。
        含**尚未收口的那一行**（``append("Password: ")`` 之后没有换行符，
        真实终端就把它显示在光标处）—— 不含的话口令提示这类内容既看不见
        """
        texts = [line.text for line in self._lines]
        tail = self._parser.pendingLine()
        if tail is not None:
            texts.append(tail.text)
        if not texts:
            return ""
        return "\n".join(texts)

    def saveTo(self, path: str, encoding: str = "utf-8") -> bool:  # noqa: N802
        """把全部内容写入文本文件（默认 UTF-8），路径不可写等情况返回 ``False``。"""
        try:
            payload = self.toPlainText()
            if payload:
                payload += "\n"
            blob = payload.encode(encoding, errors="replace")
            handle = QFile(path)
            if not handle.open(
                QFile.OpenModeFlag.WriteOnly | QFile.OpenModeFlag.Truncate
            ):
                return False
            written = handle.write(blob)
            handle.close()
            return written == len(blob)
        except (OSError, ValueError, RuntimeError):
            return False

    def copyAll(self) -> None:
        """复制全部内容到剪贴板。"""
        QApplication.clipboard().setText(self.toPlainText())

    def selectedText(self) -> str:
        """获取当前选中的文本（无选区时为空串）。"""
        if not _alive(self._edit):
            return ""
        return self._edit.textCursor().selectedText().replace("\u2029", "\n")

    def copySelection(self) -> bool:
        """把当前选区复制到剪贴板，有选区并已复制才返回 ``True``。"""
        if not self.selectedText():
            return False
        self._edit.copy()
        return True

    def selectAll(self) -> None:
        """全选当前渲染的内容（过滤态下只选过滤后的行）。"""
        if _alive(self._edit):
            self._edit.selectAll()

    # ── 容量 ──────────────────────────────────────────────────────────

    def setMaxLines(self, count: int) -> None:  # noqa: N802 (Qt 命名)
        """设置保留行数上限，``0`` 表示不限。调小会立即淘汰并重建。
        非有限值（``inf`` / ``nan``）落到 ``_MAX_LINES_CAP``（效果上等同
        ``OverflowError``，让「0 表示不限」这条约定对 ``inf`` 失效。
        """
        count = _clamped_int(count, 0, _MAX_LINES_CAP, _MAX_LINES_CAP)
        if count == self._max_lines:
            return
        self._max_lines = count
        self._trim_lines()
        self._gutter.syncWidth()
        # 重建要**保持滚动位置**：改上限不是「用户要看新内容」，别把上滚的
        # 用户拽回底部（与 _rebuild_document 注释的清单一致）；隐藏时只标记，
        # showEvent 补做（与换肤路径同口径）
        self._rebuild_when_visible()

    def maxLines(self) -> int:  # noqa: N802 (Qt 命名)
        """获取保留行数上限。"""
        return self._max_lines

    # ── 搜索 ──────────────────────────────────────────────────────────

    def setFilter(self, text: str) -> None:  # noqa: N802 (Qt 命名)
        """设置过滤 / 搜索关键词（大小写敏感），空串表示不过滤。

        实际生效有 150ms 去抖；要立即生效调用 :meth:`applyFilterNow`。

        :param text: 关键词
        """
        text = text or ""
        if text == self._filter:
            return
        self._filter = text
        self._filter_timer.start()

    def filterText(self) -> str:  # noqa: N802 (Qt 命名)
        """获取当前过滤关键词（不用 ``filter()`` 命名，避开内建同名函数）。"""
        return self._filter

    def applyFilterNow(self) -> None:  # noqa: N802 (Qt 命名)
        """立即应用当前过滤（跳过去抖）。"""
        self._filter_timer.stop()
        self._rebuild_document()

    def matchCount(self) -> int:  # noqa: N802 (Qt 命名)
        """当前过滤词在全部内容中的命中处数（未过滤时为 0）。"""
        return len(self._match_index)

    def findNext(self) -> bool:  # noqa: N802 (Qt 命名)
        """跳到下一处命中（末尾回绕），无命中返回 ``False``。"""
        return self._step_match(1)

    def findPrevious(self) -> bool:  # noqa: N802 (Qt 命名)
        """跳到上一处命中（头部回绕），无命中返回 ``False``。"""
        return self._step_match(-1)

    def _step_match(self, step: int) -> bool:
        if not _alive(self) or not self._match_index:
            return False
        count = len(self._match_index)
        self._match_pos = (self._match_pos + step) % count
        block, start, length = self._match_index[self._match_pos]
        self._select_match(block, start, length)
        self._update_match_label()
        self.matchPositionChanged.emit(self._match_pos + 1)
        return True

    def _select_match(self, block_number: int, start: int, length: int) -> None:
        block = self._edit.document().findBlockByNumber(block_number)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + start)
        cursor.setPosition(
            block.position() + start + length, QTextCursor.MoveMode.KeepAnchor
        )
        self._edit.setTextCursor(cursor)
        self._edit.setFocus()
        self._edit.centerCursor()

    def _update_match_label(self) -> None:
        if not _alive(self._match_label):
            return
        if not self._filter:
            text = ""
        elif not self._match_index:
            text = "无匹配"
        else:
            text = f"{self._match_pos + 1}/{len(self._match_index)}"
        self._match_label.setText(text)

    # ── 滚动 ──────────────────────────────────────────────────────────

    def setAutoScroll(self, on: bool) -> None:  # noqa: N802 (Qt 命名)
        """设置是否自动跟随新输出滚动到底部。"""
        on = bool(on)
        if on == self._auto_scroll:
            return
        self._auto_scroll = on
        if on:
            self._scroll_to_bottom()
        if _alive(self._follow_button) and self._follow_button.isChecked() != on:
            self._follow_button.setChecked(on)

    def autoScroll(self) -> bool:  # noqa: N802 (Qt 命名)
        """是否开启了自动跟随。"""
        return self._auto_scroll

    def isFollowing(self) -> bool:  # noqa: N802 (Qt 命名)
        """当前是否真的处于跟随状态（用户上滚会临时转为 ``False``）。"""
        return self._auto_scroll and self._following

    def scrollToBottom(self) -> None:  # noqa: N802 (Qt 命名)
        """立即滚动到底部（并恢复跟随）。"""
        self._scroll_to_bottom()

    def scrollToLine(self, lineNo: int) -> bool:  # noqa: N803 (Qt 命名)
        """把第 ``lineNo`` 行（1 起，基于**当前渲染**的行号）滚到视口顶部。

        过滤态下行号是过滤后的序号，因此请配合 :meth:`matchPositionChanged`
        或 :meth:`findNext` 一起用。行号越界返回 ``False``。

        :param lineNo: 目标行号，从 1 开始
        """
        if not _alive(self._edit):
            return False
        block = self._edit.document().findBlockByNumber(max(0, int(lineNo) - 1))
        if not block.isValid():
            return False
        cursor = QTextCursor(block)
        self._edit.setTextCursor(cursor)
        self._edit.ensureCursorVisible()
        # 不抑制 _on_scrolled：跳行是「用户主动离开底部」，跟随应当停掉
        offset = int(
            self._edit.blockBoundingGeometry(block)
            .translated(self._edit.contentOffset())
            .top()
        )
        bar = self._edit.verticalScrollBar()
        bar.setValue(max(bar.minimum(), min(bar.maximum(), offset)))
        return True

    def _scroll_to_bottom(self) -> None:
        if not _alive(self._edit):
            return
        self._following = True
        self._auto_scrolling = True
        try:
            self._edit.moveCursor(QTextCursor.MoveOperation.End)
            self._edit.ensureCursorVisible()
            # ``ensureCursorVisible`` 只保证「光标那行完整可见」，文档末尾恰好
            # 抵住视口底边时它会差 1px（末尾不再多一个空块）。
            # 「贴底」的契约是 ``value == maximum``，显式落到最大值。
            bar = self._edit.verticalScrollBar()
            if bar.value() < bar.maximum():
                bar.setValue(bar.maximum())
        finally:
            self._auto_scrolling = False

    def _on_scrolled(self, _value: int) -> None:
        if not _alive(self._gutter):
            return
        self._gutter.update()
        if self._auto_scrolling or not self._auto_scroll:
            return
        bar = self._edit.verticalScrollBar()
        self._following = _value >= bar.maximum() - 2

    def _toggle_follow(self) -> None:
        if self._follow_button.isChecked():
            self.setAutoScroll(True)
        else:
            self._auto_scroll = False

    # ── 外观 ──────────────────────────────────────────────────────────

    def setLineNumbersVisible(self, visible: bool) -> None:  # noqa: N802
        """显示 / 隐藏行号槽。"""
        self._line_numbers_visible = bool(visible)
        self._gutter.setVisible(self._line_numbers_visible)

    def lineNumbersVisible(self) -> bool:  # noqa: N802 (Qt 命名)
        """行号槽是否处于显示态（不受父级可见性影响）。"""
        return self._line_numbers_visible

    def setFontSize(self, size: int) -> None:  # noqa: N802 (Qt 命名)
        """设置等宽字号（像素），自动夹到 8-32。
        ``inf`` / ``-inf`` 照常夹到上/下限（这才兑现本文档承诺的「自动夹到
        ``max(8, min(32, int(size)))`` 时 ``int(inf)`` 的 ``OverflowError``
        """
        size = _clamped_int(size, _MIN_FONT_SIZE, _MAX_FONT_SIZE, self._font_size)
        if size == self._font_size:
            return
        self._font_size = size
        self._apply_font()

    def fontSize(self) -> int:  # noqa: N802 (Qt 命名)
        """获取当前字号（像素）。"""
        return self._font_size

    def setFontFamilies(self, families: list[str]) -> None:  # noqa: N802 (Qt 命名)
        """设置终端字体族列表（按序回退；默认：中文系统单族 CJK 字体，其它 Consolas）。

        Win7 上 Latin 等宽字体渲染 CJK 逐字回退、多族列表本身也是慢 shaping
        路径，两者都会让重绘慢一个数量级并进程级毒化（见「下游项目反馈bug.md」
        §2/§3）—— 需要中文输出时给**单个** CJK 字体（如 ``["Microsoft YaHei"]``）。
        空列表回落默认值。缺字形兜底按**首族**判断（中文系统默认开，见
        :meth:`setMissingGlyphFallbackEnabled`）。
        """
        cleaned = [str(name) for name in (families or []) if str(name)]
        self._font_families = cleaned or _default_font_families()
        self._apply_font()
        # 字体族变了：旧的缺字形兜底格式要按新主字体重判（重建会一并清掉）
        if self._missing_glyph_fallback and self._lines:
            self._glyph_guard_pos = 0
            self._rebuild_when_visible()

    def fontFamilies(self) -> list[str]:  # noqa: N802 (Qt 命名)
        """获取终端字体族列表（副本）。"""
        return list(self._font_families)

    def setMissingGlyphFallbackEnabled(self, on: bool = True) -> None:
        """主字体缺字形时给字符套单族符号字体（中文系统默认开）。
        只改 ``QTextCharFormat`` 的字体族，**不改文本**（复制 / 导出保真）。
        开启 / 关闭会重建文档：关闭时恢复主字体，开启时补上兜底。
        """
        on = bool(on)
        if on == self._missing_glyph_fallback:
            return
        self._missing_glyph_fallback = on
        self._glyph_guard_pos = 0
        if self._lines:
            self._rebuild_when_visible()

    def missingGlyphFallbackEnabled(self) -> bool:
        """是否启用「主字体缺字形 → 单族符号字体」兜底。"""
        return self._missing_glyph_fallback

    def setWordWrap(self, on: bool) -> None:  # noqa: N802 (Qt 命名)
        """开关自动换行（默认关闭，终端按整行显示并横向滚动）。"""
        on = bool(on)
        if on == self._word_wrap:
            return
        self._word_wrap = on
        self._edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if on
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def wordWrap(self) -> bool:  # noqa: N802 (Qt 命名)
        """是否自动换行。"""
        return self._word_wrap

    def setToolbarVisible(self, visible: bool) -> None:  # noqa: N802 (Qt 命名)
        """显示 / 隐藏顶部工具条（复制 / 导出 / 清除 / 字号 / 跟随 / 搜索）。"""
        self._toolbar_visible = bool(visible)
        if _alive(self._toolbar):
            self._toolbar.setVisible(self._toolbar_visible)

    def toolbarVisible(self) -> bool:  # noqa: N802 (Qt 命名)
        """工具条是否处于显示态（不受父级可见性影响）。"""
        return self._toolbar_visible

    def setPaletteName(self, name: str) -> None:  # noqa: N802 (Qt 命名)
        """切换调色板（未注册名称回退到默认）；可见时就地重渲染，隐藏时只标记待补。"""
        if name not in _TERMINAL_THEMES:
            name = defaultTerminalTheme()
        if name == self._palette_name:
            return
        self._palette_name = name
        self._refresh_palette()
        self._rebuild_when_visible()

    def paletteName(self) -> str:  # noqa: N802 (Qt 命名)
        """获取当前调色板名称。"""
        return self._palette_name

    def setHighlightColor(self, color) -> None:  # noqa: N802
        """设置搜索命中高亮色（``QColor`` 或色串），并就地重渲染。

        覆盖值会**跨换肤保留**（``setPaletteName`` / 主题切换只重算背景派生的
        默认黄，不动用户设过的色）；传 ``None`` 清除覆盖、回到派生默认黄。

        :param color: 高亮色；传 ``None`` 恢复按背景派生的默认黄色
        """
        if color is None:
            self._highlight_override = None
        else:
            new = parse_color(color)
            if not new.isValid():
                # 非法色存进 QTextCharFormat 后QPainter 直接不画 —— 搜索高亮
                # 会「整块消失」而不是「显示成某个颜色」，静默且难查
                return
            self._highlight_override = new
        if self._refresh_highlight():
            if self._filter:
                self._rebuild_document(keep_scroll=True)

    def _refresh_highlight(self) -> bool:
        """重算高亮色（用户覆盖优先）；返回是否真的变了。"""
        if self._highlight_override is not None:
            new = QColor(self._highlight_override)
        else:
            new = _blend(self._palette["background"], _HIGHLIGHT, _HIGHLIGHT_RATIO)
        if self._highlight == new:
            return False
        self._highlight = new
        return True

    def _gutter_text_color(self) -> QColor:
        """行号文字色（前景与背景的中间调）。"""
        return _blend(self._palette["background"], self._palette["foreground"], 0.45)

    def _gutter_border_color(self) -> QColor:
        """行号槽分隔线色。"""
        return _blend(self._palette["background"], self._palette["foreground"], 0.14)

    def _apply_font(self) -> None:
        if not _alive(self._edit):
            return
        font = QFont()
        font.setFamilies(list(self._font_families))
        font.setPixelSize(self._font_size)
        # 只用 StyleHint 让 Qt 自动回退 CJK —— 不走 markdown 的 CSS 字体栈
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self._edit.setFont(font)
        self._gutter_font = QFont(font)
        self._gutter.syncWidth()
        self._gutter.update()

    # ── 渲染 ──────────────────────────────────────────────────────────

    def _refresh_palette(self) -> None:
        light = self._theme_mode == ElaThemeType.ThemeMode.Light
        self._palette = _resolve_palette(self._palette_name, light)
        self._format_cache.clear()
        self._refresh_highlight()
        if _alive(self._card):
            self._card.applyTheme(
                self._palette["background"],
                _blend(self._palette["background"], self._palette["foreground"], 0.18),
            )
        if _alive(self._gutter):
            self._gutter.update()

    def _visible_tail(self) -> Optional[TerminalLine]:
        """要显示的「当前行」；过滤态下不含过滤词的按未命中处理。"""
        tail = self._parser.pendingLine()
        if tail is not None and self._filter and self._filter not in tail.text:
            return None
        return tail

    @staticmethod
    def _tail_snapshot(tail: Optional[TerminalLine]) -> Optional[tuple]:
        """尾行内容快照（文本 + 逐 span 样式），用于判断屏上那行是否过期。

        **只比较「尾行有无」是不够的**：``\\r`` 重画当前行时尾行一直在，
        内容却每帧都变 —— 按有无比较会把所有重画都当成「没变化」跳过，
        进度条 / spinner 冻在第一帧（实测文档停在 ``' 10%'`` 而模型已到
        ``' 90%'``）。样式同样要进快照：纯 SGR 片文本没变但必须重画。
        """
        if tail is None:
            return None
        return (tail.text, tuple((span.text, span.style) for span in tail.spans))

    def _drop_tail_block(self) -> bool:
        """摘掉文档末尾的尾块（若有）。

        Qt 文档恒有 ≥1 个块，所以摘完会留一个**空块** —— 它正好是下一批内容的
        复用位（``_render_rows`` 拿到 ``reuseLast=True`` 时把首行直接写进去，
        不再 ``insertBlock``）。原先那个空块没人用，而 ``_render_rows`` 只按
        ``_doc_lines`` 判断要不要插块，于是每次 ``\\r`` 重画都白白多留一个空块：
        块数逐帧增长而 ``_doc_lines`` 不动，文档无界膨胀（长进度条能把文档撑到
        上万块）。

        :returns: 是否摘掉了尾块（``True`` = 末块现在是空的，可直接复用）
        """
        if not self._doc_tail:
            return False
        cursor = QTextCursor(self._edit.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(
            QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.removeSelectedText()
        self._doc_tail = False
        self._doc_tail_key = None
        return True

    def _render_rows(
        self,
        cursor: QTextCursor,
        lines: list,
        tail: Optional[TerminalLine],
        *,
        reuseLast: bool = False,
    ) -> None:
        """把 ``lines`` 与可选的「当前行」按顺序写进文档。

        ``reuseLast=True`` 表示末块是空块（刚被 :meth:`_drop_tail_block` 摘空，
        或文档刚清空），首批内容直接写进去。**末块不是空块时必须照常插块** ——
        那时它装的是上一批的最后一行，插块才不会把两行接成一行。

        **全程用调用方给的同一个游标。** 曾经让「当前行」那段自建游标，结果
        外层游标停在旧位置，后面的 ``deletePreviousChar()`` 删错了地方 ——
        实测清空过滤词后渲染出 ``'keep me\\n\\ndrop m'``：多一个空块、尾行还
        少了最后一个字符。
        """
        # 末块为空有两种来源：刚被摘空的尾块（reuseLast），或文档本来就只有
        # Qt 必有的那一个初始空块（``_doc_lines == 0``）。两种都能原地写首行 ——
        # 判据只能是「末块是不是空的」，不能只看其中一个。
        reuse = reuseLast or self._doc_lines == 0
        first = True
        for line in lines:
            if not (first and reuse):
                cursor.insertBlock()
            self._render_line(cursor, line)
            first = False
        if tail is not None:
            if not (first and reuse):
                cursor.insertBlock()
            self._render_line(cursor, tail)

    def _flush_render(self) -> None:
        """把待渲染的新行追加进文档（每帧一次）。

        过滤态下**只同步尾块**：完整行的增量渲染在过滤态没有意义（等
        ``_filter_timer`` 整体重建），但未收口的「当前行」必须随 ``append``
        实时更新 —— 否则 ``\r`` 进度条会被冻在过滤词出现之前的那一帧。
        """
        if not _alive(self) or not _alive(self._edit):
            return
        if self._filter:
            lines = []
        else:
            # 没有完整行不代表无事可做：「当前行」（未被 \n 收口的那一行）就靠
            # 这条路径上屏；若只按 ``not self._pending_render`` 直接 return，尾行永远画不出来。
            lines = self._lines[-self._pending_render :] if self._pending_render else []
            self._pending_render = 0
        tail = self._visible_tail()
        tail_key = self._tail_snapshot(tail)
        # 尾行「屏上那份」是否还是最新的：比较**内容快照**，不是有无 ——
        # \r 重画时尾行一直在、内容每帧都变，只比有无会把重画全部跳过
        # （进度条 / spinner 冻在第一帧）。
        if not lines and tail_key == self._doc_tail_key:
            return
        self._auto_scrolling = True
        try:
            # 先摘尾块：新行要接在它**前面**，不摘就只能往尾块后面追加
            tail_start = None
            if self._doc_tail:
                last_block = self._edit.document().lastBlock()
                if last_block.isValid():
                    tail_start = last_block.position()
            reuse = self._drop_tail_block()
            cursor = QTextCursor(self._edit.document())
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._render_rows(cursor, lines, tail, reuseLast=reuse)
            self._doc_lines += len(lines)
            self._doc_tail = tail is not None
            self._doc_tail_key = tail_key
            removed = self._trim_document()
            # 尾块被重写 → 从它的起点重扫；裁头 → 所有位置左移 removed
            guard_start = self._glyph_guard_pos
            if tail_start is not None:
                guard_start = min(guard_start, tail_start)
            guard_start = max(0, guard_start - removed)
            self._apply_missing_glyph_fonts(guard_start)
            if self._following:
                self._scroll_to_bottom()
        finally:
            self._auto_scrolling = False
        self._gutter.update()

    def _trim_document(self) -> int:
        """按上限淘汰文档头部块（行号随之从 1 重新计）。

        :return: 被删掉的字符数（缺字形兜底水位线要按它左移）。
        """
        if not self._max_lines or self._doc_lines <= self._max_lines:
            return 0
        excess = self._doc_lines - self._max_lines
        cursor = QTextCursor(self._edit.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.Down,
            QTextCursor.MoveMode.KeepAnchor,
            excess,
        )
        removed = cursor.selectionEnd()
        cursor.removeSelectedText()
        self._doc_lines -= excess
        return removed

    def _apply_missing_glyph_fonts(self, start: int = 0) -> None:
        """从 ``start`` 起给缺字字符套单族符号字体（**不改文本**）。"""
        if not self._missing_glyph_fallback or not _alive(self._edit):
            return
        if not self._font_families:
            return
        try:
            self._glyph_guard_pos = applyMissingGlyphFonts(
                self._edit.document(),
                self._font_families[0],
                start=max(0, int(start)),
            )
        except Exception:  # noqa: BLE001 —— 渲染链路上不能把异常穿出 Qt 回调
            logger.warning("终端缺字形兜底失败", exc_info=True)

    def _rebuild_when_visible(self) -> None:
        """可见时立即重建（保持滚动位置）；隐藏时只标记，等 ``showEvent`` 补做。
        换肤 / 换配色族改的都是**渲染期**颜色，文档文本不变；隐藏时整篇重渲染在宿主
        2.3s → 53ms）。过滤词变了**不走这里**（那会改内容，必须立即重建）。
        """
        if self.isVisible():
            self._rebuild_document(keep_scroll=True)
        else:
            self._needs_rebuild = True

    def _rebuild_document(self, keep_scroll: bool = False) -> None:
        """按数据模型整体重建文档（过滤 / 换肤 / 改上限时走这条路）。

        :param keep_scroll: **保持当前滚动位置与跟随状态**。换配色 / 换主题 /
            改高亮色 / 改行数上限都不是「用户要看新内容」，原先无条件
            ``_scroll_to_bottom()`` 会把用户上滚到的位置拽回底部、并把
            ``_following`` 重新置 True —— 用户正在回看的那段历史被强行抢走
            （实测：滚到顶后 ``setPaletteName()`` 直接跳到底）。
            只有「过滤词变了」和「首次构建」才该强制回到底部。
        """
        if not _alive(self) or not _alive(self._edit):
            return
        self._needs_rebuild = False
        needle = self._filter
        if needle:
            rendered = [line for line in self._lines if needle in line.text]
        else:
            rendered = list(self._lines)
        self._match_index = _collect_matches(rendered, needle)
        # -1 表示"尚未定位"：重建后第一次 findNext() 正好落在第 1 处命中上，
        # 不会因为预置游标而跳过首个命中。
        self._match_pos = -1
        tail = self._visible_tail()

        self._edit.setUpdatesEnabled(False)
        try:
            cursor = QTextCursor(self._edit.document())
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.removeSelectedText()
            self._edit.document().clearUndoRedoStacks()
            # 归零后再渲染：``_render_rows`` 靠 ``reuseLast`` 判断「能否复用文档
            # 自带的那一个空块」，末块此刻是清空后剩下的空块，可以直接写
            self._doc_lines = 0
            self._doc_tail = False
            self._render_rows(cursor, rendered, tail, reuseLast=True)
            self._doc_lines = len(rendered)
            self._doc_tail = tail is not None
            self._doc_tail_key = self._tail_snapshot(tail)
            self._glyph_guard_pos = 0
            self._apply_missing_glyph_fonts(0)
        finally:
            self._edit.setUpdatesEnabled(True)
        self._pending_render = 0
        self._update_match_label()
        # 只在过滤词**真的变了**时才发。换配色 / 改上限 / 主题切换都走同一条
        # 重建路径，无条件发会让宿主收到「词变了」却发现词没变。
        filter_changed = needle != self._emitted_filter
        if filter_changed:
            self._emitted_filter = needle
            self.filterChanged.emit(needle, len(self._match_index))
        if keep_scroll and self._doc_lines:
            # 保持跟随状态：还在跟随就继续贴底（内容高度变了），已脱跟就一动不动
            if self._following:
                self._scroll_to_bottom()
        else:
            self._scroll_to_bottom()
        if _alive(self._gutter):
            self._gutter.update()

    def _render_line(self, cursor: QTextCursor, line: TerminalLine) -> None:
        """把一行写入 ``cursor`` 所在块（匹配片段叠高亮底色）。"""
        needle = self._filter
        for span in line.spans:
            text = span.text
            if not text:
                continue
            fmt = self._format_for(span.style)
            if not needle or needle not in text:
                cursor.insertText(text, fmt)
                continue
            start = _ZERO
            while True:
                index = text.find(needle, start)
                if index < 0:
                    break
                if index > start:
                    cursor.insertText(text[start:index], fmt)
                marked = QTextCharFormat(fmt)
                marked.setBackground(self._highlight)
                cursor.insertText(text[index : index + len(needle)], marked)
                start = index + len(needle)
            if start < len(text):
                cursor.insertText(text[start:], fmt)

    def _format_for(self, style: TerminalStyle) -> QTextCharFormat:
        """样式 → ``QTextCharFormat``（按样式缓存，换肤时整体清空）。

        刻意不设字体：字号由控件级字体决定，改字号后文档自动重排。
        """
        cached = self._format_cache.get(style)
        if cached is not None:
            return cached
        fg = self._palette["foreground"]
        bg = self._palette["background"]
        if style.fg is not None:
            fg = self._resolve_color(style.fg) or fg
        if style.bg is not None:
            bg = self._resolve_color(style.bg) or bg
        if style.inverse:
            fg, bg = bg, fg
        if style.dim:
            fg = _blend(fg, bg, _DIM_RATIO)
        fmt = QTextCharFormat()
        fmt.setForeground(fg)
        fmt.setBackground(bg)
        if style.bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if style.italic:
            fmt.setFontItalic(True)
        if style.underline:
            fmt.setFontUnderline(True)
        if style.strike:
            fmt.setFontStrikeOut(True)
        if len(self._format_cache) >= _FORMAT_CACHE_LIMIT:
            self._format_cache.clear()
        self._format_cache[style] = fmt
        return fmt

    def _resolve_color(self, color: AnsiColor) -> Optional[QColor]:
        if color.kind == "rgb":
            return QColor.fromRgb(color.value)
        if color.kind == "indexed":
            return _indexed_rgb(color.value) or self._palette[_indexed_key(color.value)]
        return self._palette[_indexed_key(color.value)]

    # ── 右键菜单 / 快捷键 ─────────────────────────────────────────────

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        viewport = self._edit.viewport()
        if watched is viewport and event.type() == QEvent.Type.ContextMenu:
            # 右键实际投递到 viewport（QAbstractScrollArea 的视口）—— 只挂
            # ``self._edit`` 拦不到，会落到 Qt 自带的「复制 / 全选」菜单
            self._show_context_menu(event.globalPos())
            return True
        if watched is self._edit:
            etype = event.type()
            if etype == QEvent.Type.ContextMenu:
                self._show_context_menu(event.globalPos())
                return True
            if etype == QEvent.Type.FocusIn:
                self._card.setFocused(True)
            elif etype == QEvent.Type.FocusOut:
                self._card.setFocused(False)
            elif etype == QEvent.Type.KeyPress:
                return self._handle_key(event)
        return super().eventFilter(watched, event)

    def _handle_key(self, event) -> bool:  # noqa: ANN001
        """编辑框内快捷键（``F3`` / ``Shift+F3`` 跳转，``Ctrl+F`` 聚焦搜索）。"""
        key = event.key()
        if key == Qt.Key.Key_F3:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.findPrevious()
            else:
                self.findNext()
            return True
        if key == Qt.Key.Key_F and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._search.setFocus()
            self._search.selectAll()
            return True
        return False

    def _show_context_menu(self, global_pos) -> None:  # noqa: ANN001
        # execElaMenu：副屏上 ElaMenu 偶发不按 sizeHint 撑开（只显示第一项），
        # 内部用 setMinimumSize(sizeHint) 兜底；阻塞到关闭后回收
        execElaMenu(self._build_context_menu(), global_pos)

    def _build_context_menu(self) -> ElaMenu:
        """构建终端右键菜单（Ela 风格：图标 + 统一行高）。"""
        menu = ElaMenu(self)
        menu.setMenuItemHeight(28)
        has_text = bool(self._lines)
        copy_action = menu.addElaIconAction(ElaIconType.IconName.Copy, "复制")
        copy_action.setEnabled(self._edit.textCursor().hasSelection())
        copy_action.triggered.connect(self.copySelection)

        menu.addSeparator()
        copy_all = menu.addElaIconAction(ElaIconType.IconName.Copy, "复制全部")
        copy_all.setEnabled(has_text)
        copy_all.triggered.connect(self.copyAll)

        select_all = menu.addElaIconAction(ElaIconType.IconName.BorderAll, "全选")
        select_all.setEnabled(has_text)
        select_all.triggered.connect(self.selectAll)

        menu.addSeparator()
        export_action = menu.addElaIconAction(
            ElaIconType.IconName.FolderOpen, "导出到文件…"
        )
        export_action.setEnabled(has_text)
        export_action.triggered.connect(self._export_dialog)

        clear_action = menu.addElaIconAction(ElaIconType.IconName.DeleteLeft, "清空")
        clear_action.setEnabled(has_text)
        clear_action.triggered.connect(self.clear)

        menu.addSeparator()
        zoom_in = menu.addElaIconAction(
            ElaIconType.IconName.MagnifyingGlassPlus, "放大字号"
        )
        zoom_in.triggered.connect(lambda: self.setFontSize(self._font_size + 1))
        zoom_out = menu.addElaIconAction(
            ElaIconType.IconName.MagnifyingGlassMinus, "缩小字号"
        )
        zoom_out.triggered.connect(lambda: self.setFontSize(self._font_size - 1))
        # 注意：ElaMenu 里「有 checkable 项」会让所有项的 ElaIconType 图标都不再绘制
        # （ElaMenuStyle 的图标列与勾选框互斥），所以状态写进文案 + 换图标
        if self._auto_scroll:
            follow = menu.addElaIconAction(ElaIconType.IconName.Pause, "暂停自动跟随")
        else:
            follow = menu.addElaIconAction(ElaIconType.IconName.Play, "开启自动跟随")
        follow.triggered.connect(lambda: self.setAutoScroll(not self._auto_scroll))
        return menu

    def _export_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出终端内容",
            "terminal.log",
            "文本文件 (*.log *.txt);;所有文件 (*)",
        )
        if not path:
            return
        if self.saveTo(path):
            self.alert(f"已导出到 {os.path.basename(path)}", level="success")
        else:
            self.alert(f"导出失败：{path}", level="error")

    def _on_text_changed(self) -> None:
        if _alive(self._gutter):
            self._gutter.update()

    # ── 主题 ──────────────────────────────────────────────────────────

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:  # noqa: N802
        self._theme_mode = mode
        self._refresh_palette()
        self._rebuild_when_visible()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if self._needs_rebuild:
            self._needs_rebuild = False
            self._rebuild_document(keep_scroll=True)

    def deleteLater(self) -> None:  # noqa: N802 (Qt 命名)
        self._flush_timer.stop()
        self._filter_timer.stop()
        super().deleteLater()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        return QSize(520, 280)


def _collect_matches(lines: list, needle: str) -> list:
    """扫描渲染后的行，产出 ``(块号, 起始偏移, 长度)`` 命中表。"""
    if not needle:
        return []
    width = len(needle)
    out = []
    for block, line in enumerate(lines):
        start = line.text.find(needle)
        while start >= 0:
            out.append((block, start, width))
            start = line.text.find(needle, start + width)
    return out
