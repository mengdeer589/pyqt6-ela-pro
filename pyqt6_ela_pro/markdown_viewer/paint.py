"""代码卡按钮定位 / 文档装饰绘制方法组。"""

from __future__ import annotations

import bisect

from PyQt6ElaWidgetTools import ElaIconButton, ElaIconType
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QPainter,
    QPainterPath,
    QPen,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextTable,
)
from PyQt6.QtWidgets import QAbstractScrollArea, QApplication

from .._internal import is_deleted
from ..tooltips import ElaToolTipPositionType, set_tooltip
from .syntax import _clamp_pos
from .themes import _QUOTE_LEFT_MARGIN
from .tokens import (
    _CALLOUT_RAIL_PROPERTY,
    _CODE_BUTTON_SIZE,
    _CODE_LANG_PROPERTY,
    _CODE_VIEW_CULL_MARGIN,
    _HR_MARK,
    _INLINE_CODE_MARK,
    _LINE_NUMBER_LEFT_GAP,
    _LINE_NUMBER_RIGHT_GAP,
)


class _MarkdownPaintMixin:
    def _sync_code_buttons(self) -> None:
        """同步代码复制按钮：按表对象身份做**增量**，且只为可见带内的表建按钮。

        原先列表一变就整体重建（流式每次 flush 销毁 + 重建几十个
        ``FlatIconButton``，实测 10 秒约 2.3 万个），是流式卡顿的最大单笔
        开销。稳定段里的代码表对象不会被替换，按钮可以直接复用。

        **按钮按需创建**：全量渲染（``setMarkdown`` / ``endStream`` / 换主题）
        会替换全部表对象，一次给上千个代码块建控件实测占渲染时间 ~35%
        （73KB / 1200 块：``_sync_code_buttons`` 168ms）。现在只给可见带
        内的表建，离屏项留 ``None``，滚回来再建（约 0.08ms/个）。
        """
        try:
            tables = [
                table
                for table in self._iter_tables(self.document())
                if self._is_code_table(table)
            ]
        except RuntimeError:
            # 文档正在销毁（窗口关闭路径）：丢弃本轮同步
            return
        # 上一轮的表可能已随文档改动析构（尾段替换 / clear）：逐个判存活，
        # **失效表的按钮必须显式回收**（只从列表里摘掉的话控件仍留在视口里、
        # eventFilter 也还挂着 —— 换文档 / 换主题时按钮数会虚长）
        surviving: list = []
        for table, button in zip(self._code_buttons_tables, self._code_buttons):
            if is_deleted(table):
                self._drop_code_button(button)
            else:
                surviving.append((table, button))
        kept_tables = [table for table, _ in surviving]
        if len(kept_tables) <= len(tables) and all(
            a is b for a, b in zip(kept_tables, tables)
        ):
            # 存活表是新列表的前缀：复用按钮，尾部新增留空按需创建
            self._code_buttons_tables = tables
            self._code_table_positions = [table.firstPosition() for table in tables]
            self._code_buttons = [button for _, button in surviving]
            self._code_buttons.extend([None] * (len(tables) - len(self._code_buttons)))
            self._position_code_buttons()
            return
        self._rebuild_code_buttons(tables)

    @staticmethod
    def _iter_tables(document: QTextDocument) -> list:
        """按文档顺序收集全部表格（含嵌套）。"""
        tables = []
        stack = [document.rootFrame()]
        while stack:
            frame = stack.pop()
            for child in frame.childFrames():
                if isinstance(child, QTextTable):
                    tables.append(child)
                stack.append(child)
        tables.sort(key=lambda t: t.firstPosition())
        return tables

    def _rebuild_code_buttons(self, tables: list) -> None:
        """重建按钮表（文档重渲染后表对象会失效）；按钮本身按需创建。"""
        for button in self._code_buttons:
            self._drop_code_button(button)
        self._code_buttons = [None] * len(tables)
        self._code_button_rects = []
        self._code_button_range = (0, -1)
        self._shown_code_button = -1
        self._code_buttons_tables = list(tables)
        self._code_table_positions = [table.firstPosition() for table in tables]
        self._position_code_buttons()

    def _ensure_code_button(self, index: int):
        """取按钮（不存在则创建）；下标越界返回 ``None``。"""
        if not 0 <= index < len(self._code_buttons_tables):
            return None
        button = self._code_buttons[index] if index < len(self._code_buttons) else None
        if button is None or is_deleted(button):
            button = self._create_code_button(index)
            if index >= len(self._code_buttons):
                self._code_buttons.extend(
                    [None] * (index + 1 - len(self._code_buttons))
                )
            self._code_buttons[index] = button
        return button

    def _create_code_button(self, index: int) -> ElaIconButton:
        """创建单个复制按钮（``index`` 为代码表序号）。"""
        viewport = self._text_browser.viewport()
        button = ElaIconButton(
            ElaIconType.IconName.Copy,
            14,
            _CODE_BUTTON_SIZE,
            _CODE_BUTTON_SIZE,
            viewport,
        )
        button.setObjectName("ElaMarkdownCopyButton")
        button.setFixedSize(_CODE_BUTTON_SIZE, _CODE_BUTTON_SIZE)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lang = (
            self._code_buttons_tables[index].format().property(_CODE_LANG_PROPERTY)
            or ""
        )
        set_tooltip(
            button,
            f"复制代码 · {lang}" if lang else "复制代码",
            ElaToolTipPositionType.Top,
        )
        button.clicked.connect(lambda _checked=False, i=index: self._copy_code_block(i))
        button.installEventFilter(self)
        button.hide()
        self._apply_code_button_style(button)
        self._code_button_widgets.add(button)
        return button

    def _drop_code_button(self, button) -> None:
        """移除单个复制按钮（隐藏 + 延迟销毁 + 退出归属集合）。"""
        if button is None:
            return
        button.hide()
        button.deleteLater()
        self._code_button_widgets.discard(button)

    def _apply_code_button_style(self, button: ElaIconButton) -> None:
        """按钮图标与悬浮底色（随主题刷新，交给 ElaIconButton 自绘）。"""
        button.setAwesome(ElaIconType.IconName.Copy)
        button.setLightIconColor(self._muted_color)
        button.setDarkIconColor(self._muted_color)
        button.setLightHoverIconColor(self._text_color)
        button.setDarkHoverIconColor(self._text_color)
        button.setLightHoverColor(self._code_button_hover_bg)
        button.setDarkHoverColor(self._code_button_hover_bg)
        button.setBorderRadius(6)

    def _code_table_in_view(
        self, table, layout, offset: int, top: int, bottom: int
    ) -> bool:
        """代码表是否落在这段可见区间内（文档坐标 vs 滚动偏移）。
        先用便宜的帧矩形做粗筛，只有可见的表才走昂贵的 ``cursorRect`` 几何；
        否则每一帧 / 每次滚动都要为全部代码块（含离屏）算一遍。
        """
        if is_deleted(table):
            return False
        frame = layout.frameBoundingRect(table)
        if frame.isNull():
            return False
        return (
            frame.bottom() >= offset + top - _CODE_VIEW_CULL_MARGIN
            and frame.top() <= offset + bottom + _CODE_VIEW_CULL_MARGIN
        )

    def _visible_band(self) -> tuple:
        """浏览器视口坐标系下的可见纵向区间 ``(top, bottom)``（可能跨出 0）。

        非嵌入模式直接用自身视口；嵌入模式的 ``viewport()`` 高度等于整篇
        文档（查看器没有自己的滚动条），真实可见区间要把**外层滚动区视口**
        映射回浏览器坐标 —— 否则按钮定位 / 绘制裁剪全都退化成「不裁剪」。

        整体滚出视口时返回 ``(0, -1)``（空区间，调用方据此全部跳过）。
        """
        browser = self._text_browser
        viewport_height = browser.viewport().height()
        if not self._embedded:
            return 0, viewport_height
        area = self._enclosing_scroll_area()
        if area is None:
            return 0, viewport_height
        viewport = area.viewport()
        origin = browser.mapFrom(viewport, QPoint(0, 0))
        band = QRect(origin, viewport.size()).intersected(browser.rect())
        if band.isNull() or band.height() <= 0:
            return 0, -1
        return band.top(), min(viewport_height, band.bottom())

    def _enclosing_scroll_area(self):
        """最近的 ``QAbstractScrollArea`` 祖先（嵌入模式的真实裁剪来源）。"""
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, QAbstractScrollArea):
                return widget
            widget = widget.parentWidget()
        return None

    def _visible_block_numbers(self, browser, top: float, bottom: float) -> tuple:
        """视口纵向区间 ``[top, bottom]`` 覆盖的首 / 末块号。

        不能用 ``cursorForPosition(QPoint(0, y))``：x=0 落在表格左侧边距时
        会命中表格前面的块，表格 / 代码卡块被漏掉。这里按
        ``blockBoundingRect`` 二分，不依赖横坐标。
        """
        document = self.document()
        layout = document.documentLayout()
        offset = browser.verticalScrollBar().value()
        top_y = top + offset
        bottom_y = bottom + offset
        count = max(1, document.blockCount())

        def rect_at(number: int):
            return layout.blockBoundingRect(document.findBlockByNumber(number))

        lo, hi = 0, count - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if rect_at(mid).bottom() < top_y:
                lo = mid + 1
            else:
                hi = mid
        first = lo

        lo, hi = 0, count - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if rect_at(mid).top() > bottom_y:
                hi = mid - 1
            else:
                lo = mid
        return first, lo

    def _code_table_index_range(self, top: float, bottom: float) -> tuple:
        """可见带对应的代码表下标区间（按文档位置二分，O(log 表数)）。
        逐表 ``frameBoundingRect`` 在几百个代码块的文档里要 50ms+（1200 表
        实测 54ms），而 ``_iter_tables`` 本来就是按 ``firstPosition()`` 排序的 ——
        """
        tables = self._code_buttons_tables
        count = len(tables)
        if count == 0:
            return 0, -1
        positions = self._code_table_positions
        if len(positions) != count:
            positions = [table.firstPosition() for table in tables]
            self._code_table_positions = positions
        browser = self._text_browser
        document = self.document()
        limit = max(0, browser.viewport().height() - 1)
        top = min(max(0, int(top)), limit)
        bottom = min(max(0, int(bottom)), limit)
        top_number, bottom_number = self._visible_block_numbers(browser, top, bottom)
        top_block = document.findBlockByNumber(top_number)
        bottom_block = document.findBlockByNumber(bottom_number)
        top_position = top_block.position()
        bottom_position = bottom_block.position() + bottom_block.length()
        first = max(0, bisect.bisect_left(positions, top_position) - 1)
        last = min(count - 1, bisect.bisect_right(positions, bottom_position) - 1)
        if last < first:
            return 0, -1
        return first, last

    def _drop_code_buttons_outside(self, first: int, last: int) -> None:
        """回收物化区间之外的按钮（区间连续，只扫上一次的两端）。"""
        previous_first, previous_last = self._code_button_range
        for index in range(previous_first, min(previous_last, first - 1) + 1):
            if 0 <= index < len(self._code_buttons):
                self._drop_code_button(self._code_buttons[index])
                self._code_buttons[index] = None
        for index in range(max(previous_first, last + 1), previous_last + 1):
            if 0 <= index < len(self._code_buttons):
                self._drop_code_button(self._code_buttons[index])
                self._code_buttons[index] = None
        self._code_button_range = (first, last) if last >= first else (0, -1)
        if not first <= self._shown_code_button <= last:
            self._shown_code_button = -1

    def _position_code_buttons(self) -> None:
        """把按钮摆到各代码块右上角（随滚动/尺寸变化；只处理可见带内的表）。"""
        top, bottom = self._visible_band()
        count = len(self._code_buttons_tables)
        previous_first, previous_last = self._code_button_range
        rects = self._code_button_rects
        if len(rects) != count:
            rects = [QRectF() for _ in range(count)]
            self._code_button_rects = rects
            previous_first, previous_last = 0, -1
        else:
            # 只清上一轮的窗口（其余位置恒为空矩形），避免每帧重建整张表
            for index in range(
                max(0, previous_first), min(count - 1, previous_last) + 1
            ):
                rects[index] = QRectF()
        if count == 0 or bottom < top:
            self._drop_code_buttons_outside(0, -1)
            return
        first, last = self._code_table_index_range(
            top - _CODE_VIEW_CULL_MARGIN, bottom + _CODE_VIEW_CULL_MARGIN
        )
        self._drop_code_buttons_outside(first, last)
        for index in range(first, last + 1):
            table = self._code_buttons_tables[index]
            if is_deleted(table):
                continue
            rect = self._code_table_viewport_rect(table)
            if rect.isNull() or rect.bottom() < top or rect.top() > bottom:
                continue
            rects[index] = rect
            button = self._ensure_code_button(index)
            if button is None:
                continue
            x = int(rect.right() - button.width() - 6)
            y = self._code_button_y(table, rect, button)
            button.move(max(0, x), max(0, y))

    def _code_button_y(self, table: QTextTable, rect: QRectF, button) -> int:
        """复制按钮的纵向位置（无头栏，固定在代码卡右上角）。"""
        return int(rect.top() + 6)

    def _code_table_viewport_rect(self, table: QTextTable) -> QRectF:
        """代码表在 viewport 坐标系中的矩形（用于按钮定位与悬浮判定）。
        Qt 的 ``frameBoundingRect`` 对表格返回的 x/y 会被首个单元格的
        内边距整体平移（宽度与高度可信），因此这里用首个单元格光标位置
        """
        if is_deleted(table) or table.rows() < 1 or table.columns() < 1:
            return QRectF()
        layout = self.document().documentLayout()
        frame_rect = layout.frameBoundingRect(table)
        if frame_rect.isNull():
            return QRectF()
        document = self.document()
        cell = table.cellAt(0, 0)
        cell_format = cell.format().toTableCellFormat()
        table_format = table.format()
        border = table_format.border()
        caret = self._text_browser.cursorRect(QTextCursor(cell.firstCursorPosition()))
        left = caret.left() - cell_format.leftPadding() - border
        top = caret.top() - cell_format.topPadding() - border
        frame = document.rootFrame().frameFormat()
        right = self._text_browser.viewport().width() - frame.rightMargin()

        # 底边：最后一行文本 + 单元格下内边距 + 边框 + 表格下外边距
        bottom = top + frame_rect.height()
        code_cell = table.cellAt(table.rows() - 1, 0)
        code_format = code_cell.format().toTableCellFormat()
        last_caret = self._text_browser.cursorRect(
            QTextCursor(code_cell.lastCursorPosition().block())
        )
        if last_caret.isValid():
            candidate = (
                last_caret.y()
                + last_caret.height()
                + code_format.bottomPadding()
                + border
                + table_format.bottomMargin()
            )
            bottom = max(top, candidate)
        return QRectF(left, top, max(right - left, 0.0), max(bottom - top, 0.0))

    @staticmethod
    def _paint_band(browser, exposed) -> tuple:
        """本次绘制的纵向可见区间 ``(top, bottom)``（viewer 视口坐标）。
        ``exposed`` 为 ``paintEvent`` 的暴露矩形；缺省时退回整个视口高度
        （非嵌入模式下的完整重绘）。
        """
        if exposed is None or exposed.isEmpty():
            return 0, max(0, browser.viewport().height())
        return max(0, exposed.top()), exposed.bottom()

    def _visible_blocks(self, browser, exposed=None) -> tuple:
        """本次绘制覆盖的块范围 ``(first, last)``。
        同一帧里的行内代码层与装饰层都会问一次；命中测试
        （``cursorForPosition``）在 Win7 上很贵，所以按「文档版本 + 滚动位置 +
        """
        document = self.document()
        top, bottom = self._paint_band(browser, exposed)
        limit = max(0, browser.viewport().height() - 1)
        top = min(top, limit)
        bottom = min(bottom, limit)
        key = (
            document.revision(),
            browser.verticalScrollBar().value(),
            top,
            bottom,
            browser.viewport().width(),
            browser.viewport().height(),
        )
        if key == self._visible_blocks_key:
            return self._visible_blocks_value
        first_number, last_number = self._visible_block_numbers(browser, top, bottom)
        first = document.findBlockByNumber(first_number)
        last = document.findBlockByNumber(last_number)
        if not first.isValid():
            first = document.begin()
        if not last.isValid():
            last = first
        self._visible_blocks_key = key
        self._visible_blocks_value = (first, last)
        return first, last

    def _ensure_paint_index(self, first=None, last=None) -> None:
        """按文档 revision + 可见块范围懒建绘制索引（装饰块 / 行内代码 marks）。

        两个消费方只遍历 ``_visible_blocks`` 范围；全量扫描会让大文档的每次
        流式 flush 都重扫全文，这里只扫当前可见区。无参数调用保留全量兜底。
        """
        try:
            document = self.document()
        except RuntimeError:
            return
        revision = document.revision()
        first_number = (
            first.blockNumber() if first is not None and first.isValid() else -1
        )
        last_number = last.blockNumber() if last is not None and last.isValid() else -1
        key = (revision, first_number, last_number)
        if key == self._paint_index_key:
            return
        decorations: set = set()
        inline: dict = {}
        heading_levels = self._md_layout["heading_rule"]["levels"]
        block = first if first_number >= 0 else document.begin()
        end_number = last_number if last_number >= 0 else document.blockCount() - 1
        while block.isValid() and block.blockNumber() <= end_number:
            number = block.blockNumber()
            block_format = block.blockFormat()
            if (
                block_format.headingLevel() in heading_levels
                or block_format.property(_HR_MARK)
                or block_format.property(QTextFormat.Property.BlockQuoteLevel)
            ):
                decorations.add(number)
            marks = []
            base = block.position()
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().property(
                    _INLINE_CODE_MARK
                ):
                    marks.append((fragment.position() - base, fragment.length()))
                iterator += 1
            if marks:
                inline[number] = marks
            block = block.next()
        self._paint_index_revision = revision
        self._paint_index_key = key
        self._paint_index_decorations = decorations
        self._paint_index_inline = inline

    def _paint_inline_code_backgrounds(self, browser, painter, exposed=None) -> None:
        """行内代码圆角底 + 边框（在文档绘制之前调用，避免盖住文字）。

        画笔（描边）+ 画刷（底色）在循环外设一次：全部标记共用同一对，
        密集行内代码时省掉每标记两次状态切换。

        只处理**本次暴露区间内**的块与视觉行：嵌入模式（聊天正文 / 思考）
        的 ``viewport()`` 高度等于整篇文档，按它遍历等于每帧给全文每行 ×
        每个标记算几何 —— 单个长块上千行时是 O(行 × 标记) 的平方级。
        """
        document = self.document()
        layout = document.documentLayout()
        offset = browser.verticalScrollBar().value()
        top, bottom = self._paint_band(browser, exposed)
        first, last = self._visible_blocks(browser, exposed)
        self._ensure_paint_index(first, last)
        if not self._paint_index_inline:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        inline_layout = self._md_layout["inline_code"]
        if inline_layout["border"]:
            pen = QPen(self._inline_code_border)
            pen.setWidthF(1.0)
            painter.setPen(pen)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._inline_code_bg)
        last_number = last.blockNumber()
        block = first
        while block.isValid():
            number = block.blockNumber()
            marks = self._paint_index_inline.get(number)
            if marks:
                block_top = layout.blockBoundingRect(block).top() - offset
                self._paint_block_inline_codes(
                    browser, painter, block, top, bottom, block_top, marks
                )
            if number >= last_number:
                break
            block = block.next()

    @staticmethod
    def _visible_line_range(text_layout, block_top, top, bottom) -> tuple:
        """块内与 ``[top, bottom]`` 相交的视觉行下标区间（含端点，空区间返回 ``(0, -1)``）。
        ``QTextLine.y()`` 是块内布局坐标，加上块顶在视口中的位置即为行顶
        （与 ``cursorRect`` 实测逐行一致，亚像素舍入内）。二分查找而非逐行
        """
        count = text_layout.lineCount()
        if count <= 0:
            return 0, -1

        last_line = text_layout.lineAt(count - 1)
        if block_top > bottom or (block_top + last_line.y() + last_line.height() < top):
            return 0, -1

        def line_top(index):
            return block_top + text_layout.lineAt(index).y()

        lo, hi = 0, count
        while lo < hi:
            mid = (lo + hi) // 2
            line = text_layout.lineAt(mid)
            if block_top + line.y() + line.height() < top:
                lo = mid + 1
            else:
                hi = mid
        first = max(0, lo - 1)

        lo, hi = min(first, count - 1), count
        while lo < hi:
            mid = (lo + hi) // 2
            if line_top(mid) > bottom:
                hi = mid
            else:
                lo = mid + 1
        last = min(count - 1, lo)
        if last < first:
            return 0, -1
        return first, last

    def _paint_block_inline_codes(
        self, browser, painter, block, top=0, bottom=None, block_top=None, marks=None
    ) -> None:
        """绘制单个块内可见行的行内代码圆角底与边框。
        坐标用 ``cursorRect`` 反推行原点，``cursorToX`` 只算段内宽度；每个视觉行
        只取一次 cursorRect，标记按起点二分定位。
        """
        text_layout = block.layout()
        if text_layout is None:
            return
        if bottom is None:
            bottom = max(0, browser.viewport().height())
        if block_top is None:
            block_top = (
                self.document().documentLayout().blockBoundingRect(block).top()
                - browser.verticalScrollBar().value()
            )
        first_line, last_line = self._visible_line_range(
            text_layout, block_top, top, bottom
        )
        if last_line < first_line:
            return
        block_start = block.position()
        if marks is None:
            marks = []
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().property(
                    _INLINE_CODE_MARK
                ):
                    marks.append((fragment.position() - block_start, fragment.length()))
                iterator += 1
        if not marks:
            return
        document = self.document()
        cursor = QTextCursor(document)
        inline_layout = self._md_layout["inline_code"]
        padding = inline_layout["padding"]
        radius = inline_layout["radius"]
        mark_starts = [item[0] for item in marks]
        for index in range(first_line, last_line + 1):
            line = text_layout.lineAt(index)
            line_start = line.textStart()
            line_end = line_start + line.textLength()
            cursor.setPosition(_clamp_pos(document, block_start + line_start))
            line_rect = browser.cursorRect(cursor)
            if not line_rect.isValid():
                continue
            origin_x = line_rect.left() - line.cursorToX(line_start)[0]
            position = max(0, bisect.bisect_right(mark_starts, line_start) - 1)
            while position < len(marks):
                frag_pos, frag_len = marks[position]
                if frag_pos >= line_end:
                    break
                position += 1
                segment_start = max(frag_pos, line_start)
                segment_end = min(frag_pos + frag_len, line_end)
                if segment_end <= segment_start:
                    continue
                x1 = origin_x + line.cursorToX(segment_start)[0]
                x2 = origin_x + line.cursorToX(segment_end)[0]
                if x2 <= x1:
                    continue
                background = QRectF(
                    x1 - padding,
                    line_rect.top() + 1.0,
                    (x2 - x1) + 2 * padding,
                    max(1.0, line_rect.height() - 2.0),
                )
                painter.drawRoundedRect(background, radius, radius)

    def _paint_document_decorations(self, browser, painter, exposed=None) -> None:
        """标题分隔线 / hr / 引用竖线 / 代码卡圆角（文档绘制之后调用）。"""
        document = self.document()
        layout = document.documentLayout()
        offset = browser.verticalScrollBar().value()
        top, bottom = self._paint_band(browser, exposed)
        first, last = self._visible_blocks(browser, exposed)
        self._ensure_paint_index(first, last)
        if not self._paint_index_decorations and not self._code_buttons_tables:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        md_layout = self._md_layout
        heading_rule = md_layout["heading_rule"]
        quote_layout = md_layout["quote"]
        last_number = last.blockNumber()
        block = first
        while block.isValid():
            number = block.blockNumber()
            if number in self._paint_index_decorations:
                rect = layout.blockBoundingRect(block)
                block_format = block.blockFormat()
                level = block_format.headingLevel()
                if level in heading_rule["levels"]:
                    painter.fillRect(
                        QRectF(
                            rect.x(),
                            rect.bottom() - offset - heading_rule["width"],
                            rect.width(),
                            heading_rule["width"],
                        ),
                        self._heading_rule_color,
                    )
                    if heading_rule["left_width"] > 0:
                        painter.fillRect(
                            QRectF(
                                rect.x(),
                                rect.top() - offset,
                                heading_rule["left_width"],
                                rect.height(),
                            ),
                            self._heading_left_color,
                        )
                if block_format.property(_HR_MARK):
                    painter.fillRect(
                        QRectF(
                            rect.x(),
                            rect.center().y() - offset - md_layout["hr"]["width"] / 2.0,
                            rect.width(),
                            md_layout["hr"]["width"],
                        ),
                        self._hr_color,
                    )
                quote_level = (
                    block_format.property(QTextFormat.Property.BlockQuoteLevel) or 0
                )
                if quote_level:
                    rail = block_format.property(_CALLOUT_RAIL_PROPERTY)
                    color = QColor(rail) if rail else self._quote_rail_color
                    painter.fillRect(
                        QRectF(
                            rect.x()
                            + quote_layout["rail_inset"]
                            + (int(quote_level) - 1) * _QUOTE_LEFT_MARGIN,
                            rect.top() - offset,
                            quote_layout["rail_width"],
                            rect.height(),
                        ),
                        color,
                    )
            if number >= last_number:
                break
            block = block.next()
        self._paint_code_card_chrome(browser, painter, top, bottom, first, last)

    @staticmethod
    def _is_code_fold_link_block(block) -> bool:
        """块内是否有代码折叠 / 展开锚点（该块不参与行号编号）。"""
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                href = fragment.charFormat().anchorHref()
                if href.startswith("#elacode-expand-"):
                    return True
            iterator += 1
        return False

    def _paint_code_line_numbers(
        self, browser, painter, table, rect, top, bottom, visible_first, visible_last
    ) -> None:
        """在代码卡左侧槽内绘制行号（不写入文档文本）。"""
        document = self.document()
        cell = table.cellAt(0, 0)
        if cell is None:
            return
        cell_format = cell.format().toTableCellFormat()
        right = rect.left() + cell_format.leftPadding() - _LINE_NUMBER_RIGHT_GAP
        left = rect.left() + _LINE_NUMBER_LEFT_GAP
        if right <= left:
            return
        first_block = document.findBlock(cell.firstCursorPosition().position())
        last_block = document.findBlock(cell.lastCursorPosition().position())
        if not first_block.isValid() or not last_block.isValid():
            return
        start_no = max(first_block.blockNumber(), visible_first.blockNumber())
        end_no = min(last_block.blockNumber(), visible_last.blockNumber())
        if end_no < start_no:
            return
        layout = document.documentLayout()
        offset = browser.verticalScrollBar().value()
        font, metrics = self._line_number_metrics()
        painter.setFont(font)
        painter.setPen(self._muted_color)
        block = document.findBlockByNumber(start_no)
        while block.isValid() and block.blockNumber() <= end_no:
            if not self._is_code_fold_link_block(block):
                block_rect = layout.blockBoundingRect(block)
                text_layout = block.layout()
                if text_layout is not None and text_layout.lineCount() > 0:
                    line = text_layout.lineAt(0)
                    line_top = block_rect.top() + line.y() - offset
                    baseline = line_top + line.ascent()
                    line_height = line.height()
                else:
                    line_top = block_rect.top() - offset
                    baseline = line_top + metrics.ascent()
                    line_height = block_rect.height()
                if line_top + line_height >= top and line_top <= bottom:
                    number = str(block.blockNumber() - first_block.blockNumber() + 1)
                    painter.drawText(
                        QPointF(right - metrics.horizontalAdvance(number), baseline),
                        number,
                    )
            block = block.next()

    def _paint_code_card_chrome(
        self,
        browser,
        painter,
        top=0,
        bottom=None,
        visible_first=None,
        visible_last=None,
    ) -> None:
        """代码软卡片：主题圆角（Qt 表格无圆角 API，用四角遮罩补齐）。
        只给**本次绘制暴露区间内**的表算几何（离屏的代码块再多也不付
        ``cursorRect`` 代价）。区间必须由调用方给出：嵌入模式下
        """
        if bottom is None:
            bottom = max(0, browser.viewport().height())
        if bottom < top:
            return
        offset = browser.verticalScrollBar().value()
        layout = self.document().documentLayout()
        # 先按文档位置二分出相交的表：逐表 ``frameBoundingRect`` 在几百个
        # 代码块的文档里是 O(表数)（1200 表 ≈ 54ms/帧），二分后只剩可见几张。
        first, last = self._code_table_index_range(top, bottom)
        if last < first:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        code_layout = self._md_layout["code"]
        radius = code_layout["radius"]
        for index in range(first, last + 1):
            table = self._code_buttons_tables[index]
            if not self._code_table_in_view(table, layout, offset, top, bottom):
                continue
            rect = self._code_table_viewport_rect(table)
            if rect.isNull() or rect.bottom() < top or rect.top() > bottom:
                continue
            rounded = QRectF(rect)
            path = QPainterPath()
            path.addRoundedRect(rounded, radius, radius)
            painter.save()
            painter.setClipRect(rect)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._base_bg)
            outer = QPainterPath()
            outer.addRect(rect)
            painter.drawPath(outer.subtracted(path))
            if code_layout["border"]:
                painter.setPen(QPen(self._code_border, 1.0))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5),
                    radius,
                    radius,
                )
            painter.restore()
            if (
                self._line_numbers_enabled
                and visible_first is not None
                and visible_last is not None
            ):
                self._paint_code_line_numbers(
                    browser,
                    painter,
                    table,
                    rect,
                    top,
                    bottom,
                    visible_first,
                    visible_last,
                )

    def _update_code_button_hover(self, pos, pressed: bool = False) -> None:
        """鼠标移动时显示所在代码块的复制按钮，其余隐藏；``pressed`` 为真
        （拖选文本）时不弹按钮。
        """
        if pressed or QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            # 拖选文本期间不弹出按钮，避免遮挡选择
            self._hide_code_buttons()
            return
        first, last = self._code_button_range
        rects = self._code_button_rects
        for index in range(max(0, first), min(last, len(rects) - 1) + 1):
            rect = rects[index]
            if rect.isNull():
                continue
            if rect.contains(QPointF(pos)):
                self._show_code_button(index)
                return
        self._hide_code_buttons()

    def _show_code_button(self, index: int) -> None:
        """显示指定代码块的复制按钮（只动前后两个按钮，O(1)）。"""
        rect = (
            self._code_button_rects[index]
            if index < len(self._code_button_rects)
            else QRectF()
        )
        visible = (
            not rect.isNull()
            and 0 <= rect.top() <= self._text_browser.viewport().height()
        )
        if index == self._shown_code_button:
            button = (
                self._code_buttons[index] if index < len(self._code_buttons) else None
            )
            if visible:
                if button is not None and not button.isVisible():
                    # 被 _position_code_buttons 因离屏隐藏过：补显示
                    button.setVisible(True)
            else:
                self._hide_code_buttons()
            return
        self._hide_code_buttons()
        if visible:
            button = self._ensure_code_button(index)
            if button is not None:
                button.setVisible(True)
                self._shown_code_button = index

    def _hide_code_buttons(self) -> None:
        index = self._shown_code_button
        self._shown_code_button = -1
        if 0 <= index < len(self._code_buttons):
            button = self._code_buttons[index]
            if button is not None:
                button.hide()

    def _hover_from_cursor(self) -> None:
        pos = self._text_browser.viewport().mapFromGlobal(QCursor.pos())
        self._update_code_button_hover(pos)

    def _restore_code_button_icon(self, button: ElaIconButton) -> None:
        try:
            button.setAwesome(ElaIconType.IconName.Copy)
            button.setLightIconColor(self._muted_color)
            button.setDarkIconColor(self._muted_color)
        except RuntimeError:
            # 控件已随文档重渲染销毁
            pass
