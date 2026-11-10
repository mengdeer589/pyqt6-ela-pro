"""渲染主链 / 排版 / 表格样式方法组。"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QShowEvent,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextLength,
    QTextTable,
    QTextTableFormat,
)

from .._internal import applyMissingGlyphFonts, is_deleted
from ..math_lite import extract_math
from ..tooltip_targets import DOCUMENT_TOOLTIP_PROPERTY, document_format_tooltip
from .media import _IMAGE_SYNTAX_RE
from .syntax import _clamp_pos
from .themes import _QUOTE_LEFT_MARGIN
from .tokens import (
    _CALLOUT_RAIL_PROPERTY,
    _CODE_MARKER,
    _CODE_MARKER_VALUE,
    _CONTROL_ANCHOR_PREFIXES,
    _HR_MARK,
)

logger = logging.getLogger(__name__)


_BATCH_ATTACHED_RENDERS = True


class _MarkdownRenderMixin:
    def _render(self, reset_position: bool = False) -> None:
        """按当前主题全量渲染 ``_source``。
        ``reset_position`` 只由 :meth:`setMarkdown` 在阅读语义（``stickToBottom``
        为 False）且内容真的变化时传入：无视旧滚动位置回到顶部。其余渲染
        """
        # 在途分块渲染不会因为全量渲染自动停下；不取消会把同一份内容再追加一遍
        self._cancel_large_render()
        browser = self._text_browser
        document = browser.document()
        bar = browser.verticalScrollBar()
        old_value, old_max = bar.value(), bar.maximum()

        browser.setUpdatesEnabled(False)
        try:
            self._render_issues = []
            self._image_candidates = False
            self._render_into(document, self._source)
        finally:
            browser.setUpdatesEnabled(True)
        # 源行映射懒建：渲染路径不付逐块双指针匹配的代价（51KB 文档 0.45s、
        # 占全量渲染 40%+），markdownSelection() 首次使用时才构建
        self._block_source_map = None
        # _render_into 已按当前视口宽度处理过全部图片：记录扫描水位，
        # 后续增量重排只扫新增块
        self._mark_images_scanned()
        if self._stream_active:
            # 全量渲染后增量状态失效，从头重新提交
            self._stream_committed = 0
            self._stream_tail_pos = 0
            self._stream_cut_from = 0
        self._apply_render_scroll(old_value, old_max, reset_position)
        browser.viewport().update()
        self._sync_code_buttons()
        self._sync_embedded_height()
        self._schedule_layout_refresh()
        self._needs_render = False

    def _ensure_rendered(self) -> None:
        """可见时补齐被懒掉的重建（主题 / 配色族在隐藏时只标记，见 _applyThemeStyle）。"""
        if is_deleted(self) or is_deleted(self._text_browser):
            return
        if self._needs_render and self._source:
            self._needs_render = False
            self._render()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._ensure_rendered()

    @staticmethod
    def _replace_tokens_in_order(document: QTextDocument, entries, replace) -> None:
        """按文档顺序替换占位符：把上一次命中处作为下一次的搜索起点。

        占位符由预处理按文档顺序生成。逐次 ``document.find`` 都从**文档头**
        全量扫描时，N 个占位符的总代价是 O(N × 文档长)（实测 400 个 ≈ 0.1s、
        占全量渲染 20%）。

        ``entries`` 为 ``[(token, payload)]``，``replace(found, payload)`` 负责
        单次替换；替换后从 ``found.position()``（替换文本末尾）继续 —— 替换
        内容是用户文本或私有区占位符，不会再包含后续 token。
        """
        search = QTextCursor(document)
        find = document.find
        for token, payload in entries:
            found = find(token, search)
            if found.isNull():
                continue
            replace(found, payload)
            search.setPosition(found.position())

    def _render_into(
        self,
        document: QTextDocument,
        source: str,
        resource_doc: Optional[QTextDocument] = None,
    ) -> None:
        """完整渲染管线（主文档与流式片段临时文档共用）。
        可见文档整趟只布局一次：渲染期间屏蔽信号，结束后 markContentsDirty +
        补发 contentsChanged。后处理分三段编辑块，折叠删除必须单独成段，否则
        """
        attached = False
        if _BATCH_ATTACHED_RENDERS:
            try:
                attached = document is self._text_browser.document()
            except RuntimeError:
                attached = False
        if not attached:
            self._render_into_stages(document, source, resource_doc)
            return
        document.blockSignals(True)
        ok = False
        try:
            self._render_into_stages(document, source, resource_doc)
            ok = True
        finally:
            # 收尾跑在 Qt 回调链上（主题信号 / 锚点点击）：绝不允许异常穿出
            try:
                document.blockSignals(False)
                if ok:
                    document.markContentsDirty(0, document.characterCount())
                    document.contentsChanged.emit()
            except Exception:  # noqa: BLE001
                pass

    def _render_into_stages(
        self,
        document: QTextDocument,
        source: str,
        resource_doc: Optional[QTextDocument] = None,
    ) -> None:
        """管线本体（三段编辑块）；信号批处理由 :meth:`_render_into` 负责。"""
        edit = QTextCursor(document)
        edit.beginEditBlock()
        try:
            processed, maths = extract_math(source, self._math_mark)
            processed = self._preprocess(processed)
            has_images = bool(_IMAGE_SYNTAX_RE.search(processed))
            # Mermaid 图片由 _embed_mermaid 稍后插入，但同样要靠布局刷新里的
            # _apply_images 做超宽缩放，所以也算「可能有图片」
            if has_images or self._mermaid_blocks:
                self._image_candidates = True
            document.setMarkdown(processed)
            # 导入器可能重置默认字体 / 根帧边距：在后续排版前重新套用主题
            self._apply_body_font(document)
            self._apply_content_width(document)
            self._insert_fenced_code(document)
            self._apply_inline_code_formats(document)
            self._replace_mark_tokens(document)
            self._replace_footnote_refs(document)
            self._apply_footnote_defs(document)
            self._apply_heading_anchors(document)
            self._replace_toc_token(document)
            self._style_callouts(document)
        finally:
            edit.endEditBlock()
        # 第二段：折叠删除（必须等第一段结束、表格 frame 物化后再删，见 docstring）
        if self._fold_blocks:
            edit = QTextCursor(document)
            edit.beginEditBlock()
            try:
                self._apply_folds(document)
            finally:
                edit.endEditBlock()
        # 第三段：排版 / 表格（读帧树）+ 其余纯模型阶段
        edit = QTextCursor(document)
        edit.beginEditBlock()
        try:
            self._style_typography(document)
            self._style_tables(document)
            self._apply_fragment_colors(document)
            self._style_task_markers(document)
            if maths:
                self._embed_math(document, maths, resource_doc or document)
            # 无图片语法时整趟跳过 _apply_images（块 × 片段遍历，524KB 文档约 0.5s）；
            # Mermaid / 公式图片由各自阶段插入，不经这里。
            if has_images:
                self._apply_images(document, resource_doc)
            self._embed_mermaid(
                document,
                resource_doc,
                reset=document is self._text_browser.document(),
            )
        finally:
            edit.endEditBlock()

        # 主字体缺字形兜底（中文系统默认开）：只改字符字体族、不改文本。
        # 必须放在所有格式阶段之后，避免被后续 mergeCharFormat 覆盖。
        if self._missing_glyph_fallback:
            try:
                applyMissingGlyphFonts(document, document.defaultFont().family())
            except Exception:  # noqa: BLE001 —— 渲染链路上不能把异常穿出 Qt 回调
                logger.warning("缺字形兜底失败", exc_info=True)

    def _apply_inline_code_formats(self, document: QTextDocument) -> None:
        """把行内代码占位符换回真实文本，并套用格式（等宽 + 高亮底 + 内边距）。

        按**占位符**定位而不是按文本 —— 占位符含私有区字符且全文唯一，
        与用户文本零碰撞，所以「第 N 个行内代码」永远就是「第 N 个占位符」。

        原先是 ``document.find(行内代码文本)`` 顺序反推位置：只要同一串
        文本在更早处以非代码形式出现过，标记就整体错位一位—— 普通文本被
        染成代码（等宽 + 圆角底），而真正的 `code` 一点样式都没有。实测
        「正文先提术语、再用反引号引用」这种 AI 输出最高频的形状必中。
        """
        if not self._inline_codes:
            return
        formats: dict = {}
        # 占位符 token 在预处理时与内联代码一起生成（zip 惰性配对，不再
        # 逐条重建 f-string）
        entries = zip(self._inline_code_tokens, self._inline_codes)

        def replace(found: QTextCursor, code_text: str) -> None:
            family = self._font_for_code(code_text)
            fmt = formats.get(family)
            if fmt is None:
                fmt = self._code_format(family)
                formats[family] = fmt
            found.removeSelectedText()
            found.insertText(code_text, fmt)

        self._replace_tokens_in_order(document, entries, replace)

    def _style_typography(self, document: QTextDocument) -> None:
        """Bear / Ink 排版：正文行高、标题层级字号与间距、引用块与列表间距。
        在 ``_style_callouts`` 之后调用：Callout 已带底色，引用块样式不再覆盖；
        表格单元格仅统一行高（代码卡片保持自身行高）。
        """
        base = document.defaultFont().pointSizeF()
        if base <= 0:
            pixel = document.defaultFont().pixelSize()
            base = pixel * 0.75 if pixel > 0 else 10.0
        layout = self._md_layout
        heading_layout = layout["heading"]
        heading_rule = layout["heading_rule"]
        quote_layout = layout["quote"]
        body_line_height = layout["body_line_height"]
        paragraph_margin = layout["paragraph_margin"]
        list_item_margin = layout["list_item_margin"]
        quote_left_margin = quote_layout["left_margin"]
        quote_block_margin = quote_layout["block_margin"]
        cursor = QTextCursor(document)
        probe = QTextCursor(document)
        # 整个排版阶段合并成一次编辑块：逐块 setBlockFormat 会各自触发一次重排，
        # 几百个块的文档会明显卡顿（760 块约 108ms）；合并后只在末尾重排一次
        cursor.beginEditBlock()
        try:
            block = document.begin()
            while block.isValid():
                probe.setPosition(block.position())
                table = probe.currentTable()
                if table is not None:
                    if self._in_code_table(probe):
                        block = block.next()
                        continue
                    table_format = block.blockFormat()
                    table_format.setLineHeight(
                        150.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
                    )
                    # 单元格内统一无块边距（间距由单元格 padding 提供），
                    # 避免导入器给首格加的默认段落边距造成表头基线不齐
                    table_format.setTopMargin(0)
                    table_format.setBottomMargin(0)
                    self._apply_block_format(document, block, table_format, cursor)
                    block = block.next()
                    continue
                block_format = block.blockFormat()
                level = block_format.headingLevel()
                if level:
                    scale, top, bottom, line_height, weight = heading_layout.get(
                        level,
                        (1.0, 16.0, 16.0, 150.0, QFont.Weight.DemiBold),
                    )
                    if (
                        level in heading_rule["levels"]
                        and heading_rule["left_width"] > 0
                    ):
                        block_format.setLeftMargin(
                            block_format.leftMargin()
                            + heading_rule["left_width"]
                            + heading_rule["left_gap"]
                        )
                    block_format.setTopMargin(top)
                    block_format.setBottomMargin(bottom)
                    block_format.setLineHeight(
                        line_height,
                        QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
                    )
                    self._apply_block_format(document, block, block_format, cursor)
                    self._style_heading_fragments(
                        document, block, base * scale, level, weight, cursor
                    )
                elif block_format.hasProperty(
                    QTextFormat.Property.BlockTrailingHorizontalRulerWidth
                ):
                    # hr：Qt 自带横线仅 1px 且颜色不可控（属性 / 调色板均无效），
                    # 清除属性后由 _paint_document_decorations 自绘 2px 主题线
                    block_format.clearProperty(
                        QTextFormat.Property.BlockTrailingHorizontalRulerWidth
                    )
                    block_format.setProperty(_HR_MARK, True)
                    block_format.setTopMargin(16.0)
                    block_format.setBottomMargin(16.0)
                    self._apply_block_format(document, block, block_format, cursor)
                else:
                    block_format.setLineHeight(
                        body_line_height,
                        QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
                    )
                    if block.textList() is not None:
                        block_format.setTopMargin(list_item_margin)
                        block_format.setBottomMargin(list_item_margin)
                    elif block_format.leftMargin() >= _QUOTE_LEFT_MARGIN:
                        block_format.setLeftMargin(quote_left_margin)
                        block_format.setTopMargin(quote_block_margin)
                        block_format.setBottomMargin(quote_block_margin)
                        if quote_layout["background"] and not block_format.property(
                            _CALLOUT_RAIL_PROPERTY
                        ):
                            block_format.setBackground(QBrush(self._quote_bg_color))
                        self._mute_quote_fragments(document, block, cursor)
                    elif block.text().strip():
                        block_format.setBottomMargin(paragraph_margin)
                    self._apply_block_format(document, block, block_format, cursor)
                block = block.next()
        finally:
            cursor.endEditBlock()

    @staticmethod
    def _apply_block_format(
        document: QTextDocument,
        block,
        block_format: QTextBlockFormat,
        cursor: Optional[QTextCursor] = None,
    ) -> None:
        """把块格式写回指定块（``cursor`` 可复用以避免逐块创建）。"""
        cursor = cursor if cursor is not None else QTextCursor(document)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(block_format)

    def _style_heading_fragments(
        self,
        document: QTextDocument,
        block,
        point_size: float,
        level: int,
        weight: QFont.Weight,
        cursor: Optional[QTextCursor] = None,
    ) -> None:
        """标题片段：按层级放大字号、字重，并强制为标题色（h6 次级色）。
        Qt Markdown / HTML 导入器会给标题片段挂 ``FontSizeAdjustment``（``<h3>``
        的相对字号）；它和显式 point size 并存时按 adjustment 渲染，于是带行内
        """
        color = self._muted_color if level >= 6 else self._md_heading_color
        edit = cursor if cursor is not None else QTextCursor(document)
        # 先收集再改写：setCharFormat 会合并相邻同格式片段，边迭代边改会让
        # QTextBlock.iterator 指向已变化的片段。
        spans = []
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.text():
                spans.append(
                    (fragment.position(), fragment.length(), fragment.charFormat())
                )
            iterator += 1
        for position, length, base_format in spans:
            edit.setPosition(position)
            edit.setPosition(
                _clamp_pos(document, position + length),
                QTextCursor.MoveMode.KeepAnchor,
            )
            fmt = QTextCharFormat(base_format)
            fmt.clearProperty(QTextFormat.Property.FontSizeAdjustment)
            fmt.clearProperty(QTextFormat.Property.FontPixelSize)
            fmt.setFontPointSize(point_size)
            fmt.setFontWeight(weight)
            fmt.setForeground(color)
            edit.setCharFormat(fmt)

    def _mute_quote_fragments(
        self, document: QTextDocument, block, cursor: Optional[QTextCursor] = None
    ) -> None:
        """引用块正文：muted 正文色（链接 / 行内代码保持自身颜色）。"""
        edit = cursor if cursor is not None else QTextCursor(document)
        italic = self._md_layout["quote"]["italic"]
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and (
                fragment.charFormat().foreground().style() == Qt.BrushStyle.NoBrush
            ):
                edit.setPosition(fragment.position())
                edit.setPosition(
                    _clamp_pos(document, fragment.position() + fragment.length()),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                fmt = QTextCharFormat()
                fmt.setForeground(self._quote_text_color)
                fmt.setFontItalic(italic)
                edit.mergeCharFormat(fmt)
            iterator += 1

    def _style_task_markers(self, document: QTextDocument) -> None:
        """任务复选框跟随主题 list 色（仍可点击，避免显示成整段链接色）。
        任务项整行是 anchor（点击切换勾选），文字会拿到链接色；勾选框单独
        取 list 色，既跟主题走，又与链接色区分得开。
        """
        if not self._task_items:
            return
        for marker in ("■", "□"):
            cursor = QTextCursor(document)
            while True:
                found = document.find(marker, cursor)
                if found.isNull():
                    break
                fmt = found.charFormat()
                if fmt.isAnchor() and fmt.anchorHref().startswith("#elatask-"):
                    plain = QTextCharFormat()
                    plain.setForeground(self._md_list_color)
                    found.mergeCharFormat(plain)
                cursor = found

    def _style_tables(self, document: QTextDocument) -> None:
        """美化 Markdown 表格：浅网格 + 表头半粗体，不加表头底色。"""
        border_brush = QBrush(self._table_border)

        # 同段落排版：整轮表格样式合并成一次编辑块，避免每个单元格重排一次
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        try:
            stack = [document.rootFrame()]
            while stack:
                frame = stack.pop()
                for child in frame.childFrames():
                    stack.append(child)
                    if isinstance(child, QTextTable):
                        if self._is_code_table(child):
                            continue
                        self._trim_table_cell_blocks(document, child)
                        self._style_table(child, border_brush)
                        self._set_table_margins(document, child)
        finally:
            cursor.endEditBlock()

    def _trim_table_cell_blocks(
        self, document: QTextDocument, table: QTextTable
    ) -> None:
        """移除单元格首尾的纯空块。
        Qt Markdown 导入器在引用块 / 代码块之后的表格首格会多插一个空块
        （渲染时把表头首格文字挤到第二行），这里用段落合并清理
        """
        for row in range(table.rows()):
            for column in range(table.columns()):
                cell = table.cellAt(row, column)
                while True:
                    first = cell.firstCursorPosition().blockNumber()
                    last = cell.lastCursorPosition().blockNumber()
                    if last <= first:
                        break
                    block = document.findBlockByNumber(first)
                    if not block.isValid() or block.text().strip():
                        break
                    following = document.findBlockByNumber(first + 1)
                    if not following.isValid():
                        break
                    cursor = QTextCursor(document)
                    cursor.setPosition(following.position())
                    cursor.deletePreviousChar()
                while True:
                    first = cell.firstCursorPosition().blockNumber()
                    last = cell.lastCursorPosition().blockNumber()
                    if last <= first:
                        break
                    block = document.findBlockByNumber(last)
                    if not block.isValid() or block.text().strip():
                        break
                    cursor = QTextCursor(document)
                    cursor.setPosition(block.position())
                    cursor.deletePreviousChar()

    def _set_table_margins(self, document: QTextDocument, table: QTextTable) -> None:
        """给表格前后的块留出上下间距。
        注意 ``table.firstCursorPosition()`` 指向首个单元格内部，
        直接改它的块边距会把表头首格文字顶下来；应改表格外的相邻块。
        """
        margin = self._md_layout["table_block_margin"]
        before_pos = table.firstPosition() - 1
        if before_pos >= 0:
            before = document.findBlock(before_pos)
            if before.isValid() and before.position() < table.firstPosition():
                self._set_block_margins(document, before, bottom=margin)
        after_pos = table.lastPosition() + 1
        if after_pos < document.characterCount():
            after = document.findBlock(after_pos)
            if after.isValid() and after.position() > table.lastPosition():
                self._set_block_margins(document, after, top=margin)

    def _is_code_table(self, table: QTextTable) -> bool:
        """是否为代码块包裹表（表格式标记优先，单列同色兜底）。
        兜底仅限单列、最多两行的表：浅色主题下表格表头底色与代码底色
        恰好相同，多列普通表格不能按颜色判定。
        """
        if table.rows() < 1 or table.columns() < 1:
            return False
        if table.format().property(_CODE_MARKER) == _CODE_MARKER_VALUE:
            return True
        if table.columns() != 1 or table.rows() > 2:
            return False
        cell = table.cellAt(0, 0)
        if cell is None:
            # cellAt() 对被合并覆盖的单元格返回 None
            return False
        background = cell.format().background()
        return (
            background.style() != Qt.BrushStyle.NoBrush
            and background.color() == self._code_bg
        )

    @staticmethod
    def _set_block_margins(
        document: QTextDocument,
        block,
        top: Optional[float] = None,
        bottom: Optional[float] = None,
    ) -> None:
        """设置指定块的上下外边距（None 表示保持不变）。"""
        block_format = block.blockFormat()
        if top is not None:
            block_format.setTopMargin(top)
        if bottom is not None:
            block_format.setBottomMargin(bottom)
        cursor = QTextCursor(document)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(block_format)

    @staticmethod
    def _blend(base: QColor, over: QColor, alpha: float) -> QColor:
        """将 over 按 alpha 比例混合到 base 上，返回不透明颜色。"""
        return QColor(
            int(base.red() * (1 - alpha) + over.red() * alpha),
            int(base.green() * (1 - alpha) + over.green() * alpha),
            int(base.blue() * (1 - alpha) + over.blue() * alpha),
        )

    def _style_table(self, table: QTextTable, border_brush: QBrush) -> None:
        table_format = QTextTableFormat(table.format())
        table_format.setBorder(0)
        table_format.setBorderCollapse(True)
        table_format.setCellPadding(0)
        table_format.setCellSpacing(0)
        if (
            self._table_column_widths
            and len(self._table_column_widths) == table.columns()
        ):
            table_format.setColumnWidthConstraints(
                [
                    QTextLength(QTextLength.Type.PercentageLength, width)
                    for width in self._table_column_widths
                ]
            )
        table.setFormat(table_format)

        table_layout = self._md_layout["table"]
        stripe_brush = QBrush(self._table_stripe_bg)
        header_brush = QBrush(self._table_header_bg)
        header_weight = QFont.Weight(int(table_layout["header_weight"]))
        top_padding = table_layout["top_padding"]
        bottom_padding = table_layout["bottom_padding"]
        left_padding = table_layout["left_padding"]
        right_padding = table_layout["right_padding"]
        border_width = table_layout["border_width"]
        header_background = table_layout["header_background"]
        zebra = self._table_zebra
        for row in range(table.rows()):
            for column in range(table.columns()):
                cell = table.cellAt(row, column)
                cell_format = cell.format().toTableCellFormat()
                cell_format.setTopPadding(top_padding)
                cell_format.setBottomPadding(bottom_padding)
                cell_format.setLeftPadding(left_padding)
                cell_format.setRightPadding(right_padding)
                cell_format.setBorderBrush(border_brush)
                cell_format.setBorder(border_width)
                if row == 0:
                    cell_format.setBackground(
                        header_brush if header_background else QBrush()
                    )
                    cell_format.setFontWeight(header_weight)
                    cell_format.setForeground(QBrush(self._text_color))
                elif zebra and row % 2 == 0:
                    cell_format.setBackground(stripe_brush)
                else:
                    cell_format.setBackground(QBrush())
                cell.setFormat(cell_format)

    def _schedule_pending_render(self) -> None:
        """被绘制说明已经在屏幕上：把懒掉的整篇重渲染排到下一拍。
        **不能在 paintEvent 里直接改文档**（绘制期重排会重入布局）。定时器是
        子对象，控件销毁时随之停掉。
        """
        if not self._needs_render or is_deleted(self):
            return
        timer = self._pending_render_timer
        if is_deleted(timer):
            return
        if not timer.isActive():
            timer.start(0)

    def _document_css(self) -> str:
        """文档默认样式：代码块与行内代码的字体/背景/文字色。"""
        return (
            f"pre, code, tt {{ font-family: '{self._code_font_family}';"
            f" background-color: {self._code_bg.name()};"
            f" color: {self._code_text.name()}; }}"
        )

    def _apply_fragment_colors(self, document: QTextDocument) -> None:
        """为链接 / 加粗 / 斜体 / 删除线补上语义色（Bear / Ink）。
        正文片段刻意不加显式前景色：由控件 palette 提供，省一次文档编辑。
        列表符号吃 ``palette.Text``，字符格式染不上，``list`` 语义只留给任务勾选框。
        """
        edit_cursor = QTextCursor(document)
        edit_cursor.beginEditBlock()
        link_format = QTextCharFormat()
        link_format.setForeground(self._link_color)
        link_format.setFontUnderline(bool(self._md_layout["link"]["underline"]))
        strike_format = QTextCharFormat()
        strike_format.setForeground(self._muted_color)
        strong_format = QTextCharFormat()
        strong_format.setForeground(self._md_strong_color)
        emphasis_format = QTextCharFormat()
        emphasis_format.setForeground(self._md_emphasis_color)

        # 合并字符格式不改文本长度：文档长度取一次，循环内只做 min，
        # 避免每个合并都过一遍 ``_clamp_pos`` → ``document.characterCount()``。
        doc_length = document.characterCount()
        keep_anchor = QTextCursor.MoveMode.KeepAnchor
        strong_weight = int(QFont.Weight.DemiBold)
        foreground_property = QTextFormat.Property.ForegroundBrush
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    target: Optional[QTextCharFormat] = None
                    if fmt.isAnchor() and fmt.anchorHref():
                        target = QTextCharFormat(link_format)
                        href = fmt.anchorHref()
                        if (
                            href
                            and not document_format_tooltip(fmt)
                            and not href.startswith(_CONTROL_ANCHOR_PREFIXES)
                        ):
                            target.setProperty(DOCUMENT_TOOLTIP_PROPERTY, href)
                    elif not fmt.hasProperty(foreground_property):
                        # 「显式前景色」用属性存在性判断：``foreground().style()``
                        # 每次调用都要让 PyQt 把 C++ 枚举映射回 Python 枚举
                        # （8260 片段 11.9ms vs 7.1ms），结果逐片段一致
                        if fmt.fontStrikeOut():
                            target = strike_format
                        elif int(fmt.fontWeight()) >= strong_weight:
                            target = strong_format
                        elif fmt.fontItalic():
                            target = emphasis_format
                    if target is not None:
                        position = fragment.position()
                        edit_cursor.setPosition(position)
                        edit_cursor.setPosition(
                            min(position + fragment.length(), doc_length), keep_anchor
                        )
                        edit_cursor.mergeCharFormat(target)
                iterator += 1
            block = block.next()

        edit_cursor.endEditBlock()
