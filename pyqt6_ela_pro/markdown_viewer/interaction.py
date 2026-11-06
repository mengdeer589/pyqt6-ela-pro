"""锚点 / 搜索 / 右键菜单 / 布局回调方法组。"""

from __future__ import annotations


from PyQt6ElaWidgetTools import ElaIconType, ElaMenu
from PyQt6.QtCore import QEvent, QPointF, Qt, QUrl
from PyQt6.QtGui import (
    QCursor,
    QDesktopServices,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import QApplication, QTextEdit

from .._internal import execElaMenu, is_deleted, single_shot_on
from .preprocess import _TASK_LIST_RE


_CONTEXT_MENU_ITEM_HEIGHT = 28

_EXTERNAL_LINK_SCHEMES = frozenset({"http", "https", "mailto"})

_ANCHOR_HISTORY_CAP = 50

#: 文档内搜索命中上限：单字符搜索长文时避免创建数万条 ExtraSelection
_SEARCH_HIT_LIMIT = 500


class _MarkdownInteractionMixin:
    def setOpenExternalLinks(self, on: bool) -> None:
        """设置外部链接是否用系统浏览器打开。
        内部锚点始终由组件处理；即使为 ``True``，也只有白名单里的 scheme 会交给
        shell，其余只发 ``linkActivated``。白名单见 :meth:`setExternalLinkSchemes`。
        """
        self._open_external_links = bool(on)

    def openExternalLinks(self) -> bool:
        """外部链接是否使用系统浏览器打开。"""
        return self._open_external_links

    def setExternalLinkSchemes(self, schemes) -> None:
        """设置允许交给系统打开的 scheme 白名单（默认 http / https / mailto；
        元素大小写不敏感）。
        """
        self._external_link_schemes = frozenset(
            str(s).strip().lower() for s in schemes if str(s).strip()
        )

    def externalLinkSchemes(self) -> frozenset:
        """当前允许交给系统打开的 scheme 白名单。"""
        return self._external_link_schemes

    def scrollToAnchor(self, name: str) -> None:
        self._text_browser.scrollToAnchor(name)

    def backToPreviousAnchor(self) -> bool:
        """回到上一个内部锚点跳转前的位置；历史为空返回 ``False``。"""
        if not self._anchor_back_stack:
            return False
        value = self._anchor_back_stack.pop()
        bar = self._text_browser.verticalScrollBar()
        bar.setValue(min(value, bar.maximum()))
        return True

    def clearAnchorHistory(self) -> None:
        """清空内部锚点访问历史。"""
        self._anchor_back_stack.clear()

    def _on_anchor_clicked(self, url: QUrl) -> None:
        """链接点击：内部锚点跳转 / 折叠与任务勾选控制 + 外部链接 + 转发 ``linkActivated``。"""
        target = url.toString()
        if target.startswith("#elacode-expand-"):
            self._toggle_code_block_expanded(target[len("#elacode-expand-") :])
            return
        if target.startswith("#elafold-"):
            self._toggle_fold_expanded(target[len("#elafold-") :])
            return
        if target.startswith("#elatask-"):
            self._toggle_task_by_ordinal(target[len("#elatask-") :])
            return
        if not url.scheme() and url.fragment():
            self._anchor_back_stack.append(
                self._text_browser.verticalScrollBar().value()
            )
            if len(self._anchor_back_stack) > _ANCHOR_HISTORY_CAP:
                self._anchor_back_stack.pop(0)
            self._text_browser.scrollToAnchor(url.fragment())
            self.linkActivated.emit(target)
            return
        # 带 scheme / 绝对地址：外部链接。Qt 的 openExternalLinks 恒为 False（否则
        # anchorClicked 不发），这里自己过 scheme 白名单后交给系统浏览器。
        # 被拒链接仍照常发 linkActivated，宿主可自行处理。
        if (
            self._open_external_links
            and url.scheme().lower() in self._external_link_schemes
        ):
            QDesktopServices.openUrl(url)
        self.linkActivated.emit(target)

    def _toggle_code_block_expanded(self, raw_index: str) -> None:
        """折叠链接点击：切换代码块展开状态并重渲染。"""
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return
        if index in self._expanded_code_blocks:
            self._expanded_code_blocks.discard(index)
        else:
            self._expanded_code_blocks.add(index)
        self._render()

    def _toggle_fold_expanded(self, raw_index: str) -> None:
        """推理块 / details 折叠标签点击：切换展开状态并重渲染。"""
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return
        if index in self._expanded_folds:
            self._expanded_folds.discard(index)
        else:
            self._expanded_folds.add(index)
        self._render()

    def _toggle_task_by_ordinal(self, raw: str) -> None:
        """任务复选框点击：翻转源文本并重渲染（流式期间忽略）。"""
        if self._stream_active:
            return
        try:
            ordinal = int(raw)
        except (TypeError, ValueError):
            return
        if not 0 <= ordinal < len(self._task_items):
            return
        line_index, checked = self._task_items[ordinal]
        lines = self._source.split("\n")
        if not 0 <= line_index < len(lines):
            return
        new_checked = not checked

        def flip(match):
            prefix = match.group(1)
            rest = match.group(0)[len(prefix) :]
            body = rest[3:]
            return prefix + ("[x]" if new_checked else "[ ]") + body

        replaced, count = _TASK_LIST_RE.subn(flip, lines[line_index], count=1)
        if count == 0:
            return
        lines[line_index] = replaced
        self._source = "\n".join(lines)
        self._render()
        self.taskToggled.emit(ordinal, new_checked)

    def searchText(self, text: str, caseSensitive: bool = False) -> int:
        """高亮全部匹配并选中第一处，返回匹配数量。"""
        self.clearSearch()
        if not text:
            return 0
        flags = QTextDocument.FindFlag(0)
        if caseSensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        cursor = QTextCursor(self.document())
        while len(self._search_selections) < _SEARCH_HIT_LIMIT:
            found = self.document().find(text, cursor, flags)
            if found.isNull():
                break
            selection = QTextEdit.ExtraSelection()
            selection.cursor = found
            fmt = QTextCharFormat()
            fmt.setBackground(self._search_bg)
            selection.format = fmt
            self._search_selections.append(selection)
            cursor = found
        if self._search_selections:
            self._text_browser.setExtraSelections(self._search_selections)
            self._text_browser.setTextCursor(self._search_selections[0].cursor)
            self._last_search = text
        return len(self._search_selections)

    def findNext(self, backward: bool = False) -> bool:
        """在 :meth:`searchText` 的匹配间循环跳转，返回是否成功跳转。"""
        if not self._search_selections:
            return False
        current = self._text_browser.textCursor().selectionStart()
        positions = [s.cursor.selectionStart() for s in self._search_selections]
        if backward:
            candidates = [p for p in positions if p < current]
            target = max(candidates) if candidates else positions[-1]
        else:
            candidates = [p for p in positions if p > current]
            target = min(candidates) if candidates else positions[0]
        self._text_browser.setTextCursor(
            self._search_selections[positions.index(target)].cursor
        )
        return True

    def clearSearch(self) -> None:
        """清除搜索高亮。"""
        self._search_selections = []
        self._last_search = ""
        self._text_browser.setExtraSelections([])

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        """拦截右键菜单，并在鼠标移动时管理代码复制按钮显隐。"""
        viewport = self._text_browser.viewport()
        event_type = event.type()
        if event_type == QEvent.Type.ContextMenu and obj in (
            self._text_browser,
            viewport,
        ):
            # 右键实际投递到 **viewport**（QAbstractScrollArea 的视口）—— 只拦
            # QTextBrowser 本体的话走的是 Qt 自带菜单（复制 / 复制链接 / 全选），
            # 自建菜单可达性为 0。坐标统一用 globalPos，免得再换算视口偏移。
            self._show_context_menu(event.globalPos())
            return True
        if obj is viewport:
            if event_type == QEvent.Type.MouseMove:
                pressed = bool(
                    event.buttons()
                    & (
                        Qt.MouseButton.LeftButton
                        | Qt.MouseButton.RightButton
                        | Qt.MouseButton.MiddleButton
                    )
                )
                self._update_code_button_hover(
                    event.position().toPoint(), pressed=pressed
                )
            elif event_type == QEvent.Type.Leave:
                # 移向复制按钮（viewport 子控件）也会触发 Leave：
                # 按光标实际位置判定，避免按钮在点击前消失
                self._on_viewport_leave()
        elif obj in self._code_button_widgets and event_type == QEvent.Type.Leave:
            single_shot_on(self, 0, self._hover_from_cursor)
        return super().eventFilter(obj, event)

    def _on_viewport_leave(self, global_pos=None) -> None:
        """viewport 离开处理：光标仍落在代码块矩形内（如按钮上）时保持显示。"""
        if global_pos is None:
            global_pos = QCursor.pos()
        pos = QPointF(self._text_browser.viewport().mapFromGlobal(global_pos))
        for rect in self._code_button_rects:
            if not rect.isNull() and rect.contains(pos):
                return
        self._hide_code_buttons()

    def _show_context_menu(self, global_pos) -> None:
        # 副屏上 ElaMenu 偶发不按 sizeHint 撑开（只显示第一项）—— execElaMenu 兜底
        execElaMenu(self._create_context_menu(), global_pos)

    def _create_context_menu(self) -> ElaMenu:
        """构建右键菜单（Ela 风格：图标 + 统一行高）。
        只保留只读视图真正可用的动作 —— Qt 标准菜单里的撤销 / 剪切 / 粘贴 /
        删除对本组件没有意义（`setReadOnly(True)`），所以不用
        """
        browser = self._text_browser
        cursor = browser.textCursor()
        menu = ElaMenu(self)
        menu.setMenuItemHeight(_CONTEXT_MENU_ITEM_HEIGHT)

        copy = menu.addElaIconAction(ElaIconType.IconName.Copy, "复制")
        copy.setEnabled(cursor.hasSelection())
        copy.triggered.connect(browser.copy)
        select_all = menu.addElaIconAction(ElaIconType.IconName.BorderAll, "全选")
        select_all.triggered.connect(browser.selectAll)

        menu.addSeparator()
        copy_code = menu.addElaIconAction(ElaIconType.IconName.Code, "复制代码块")
        copy_code.setEnabled(self._in_code_table(cursor))
        copy_code.triggered.connect(self._copy_code_at_cursor)
        copy_formula = menu.addElaIconAction(
            ElaIconType.IconName.SquareRootVariable, "复制 LaTeX 公式"
        )
        copy_formula.setEnabled(bool(self._formula_latex_at_cursor()))
        copy_formula.triggered.connect(self._copy_formula_at_cursor)
        copy_mermaid = menu.addElaIconAction(
            ElaIconType.IconName.DiagramProject, "复制 Mermaid 源码"
        )
        copy_mermaid.setEnabled(bool(self._mermaid_source_at_cursor()))
        copy_mermaid.triggered.connect(self._copy_mermaid_at_cursor)
        save_image = menu.addElaIconAction(
            ElaIconType.IconName.FloppyDisk, "图片另存为…"
        )
        save_image.setEnabled(bool(self._image_local_path_at_cursor()))
        save_image.triggered.connect(self._save_image_at_cursor)

        menu.addSeparator()
        quote = menu.addElaIconAction(
            ElaIconType.IconName.FileCode, "复制选中为 Markdown"
        )
        quote.setEnabled(cursor.hasSelection())
        quote.triggered.connect(self._copy_selection_markdown)
        copy_all = menu.addElaIconAction(ElaIconType.IconName.ClipboardList, "复制全文")
        copy_all.triggered.connect(self._copy_all)
        return menu

    def _formula_latex_at_cursor(self) -> str:
        """光标处的公式 LaTeX 源码（非公式返回空字符串）。"""
        return self._image_source_at_cursor("elamath://", "LaTeX: ")

    def _copy_formula_at_cursor(self) -> None:
        latex = self._formula_latex_at_cursor()
        if not latex:
            return
        QApplication.clipboard().setText(latex)
        self.formulaCopied.emit(latex)

    def _copy_all(self) -> None:
        self._copy_text(self.document().toPlainText())

    def _copy_selection_markdown(self) -> None:
        """复制选中内容为 Markdown 源（并发出 ``selectionQuoted``）。"""
        quote = self.markdownSelection()
        if not quote:
            return
        QApplication.clipboard().setText(quote)
        self.selectionQuoted.emit(quote)

    def _copy_text(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.codeCopied.emit(text)

    def _on_layout_refresh(self) -> None:
        """尺寸变化后重排：图片宽度与代码复制按钮位置。"""
        if is_deleted(self) or is_deleted(self._text_browser):
            return
        self._apply_content_width()
        if self._source and self._image_candidates:
            # 宽度未变只扫上次水位之后的新增块；宽度变了才全量重新缩放。
            # 无图片候选时整趟跳过（块 × 片段遍历，235KB 文档约 16ms）。
            width = self._content_text_width()
            start = 0 if width != self._image_scan_width else self._image_scan_watermark
            self._apply_images(self.document(), start_block=start)
            self._mark_images_scanned()
        if self._large_render_chunks:
            # 分块渲染期间不同步按钮：每次布局刷新都是一趟全表树遍历 + 全量定位，
            # 几千个代码块时是 O(n²)（524KB / 4282 表约 1.9s）；统一在收尾建一次。
            self._sync_embedded_height()
            return
        self._sync_code_buttons()
        self._sync_embedded_height()

    def _on_view_scrolled(self, _value: int) -> None:
        # 滚动不改变文档结构：只需重摆按钮位置，不必重扫表格列表
        self._position_code_buttons()
        if self._mermaid_jobs and not self._mermaid_priority_timer.isActive():
            self._mermaid_priority_timer.start()

    def _on_document_size_changed(self, _size) -> None:
        self._schedule_layout_refresh()

    def _schedule_layout_refresh(self, delay: int = 80) -> None:
        """前缘去抖：定时器已激活时不重置，避免文档规模抖动造成无限推迟。"""
        if not self._layout_timer.isActive():
            self._layout_timer.start(delay)

    def _reset_image_scan(self) -> None:
        """文档被整体替换 / 清空：作废图片扫描水位（下次重排全量重扫）。"""
        self._image_scan_width = -1
        self._image_scan_watermark = 0
        self._image_candidates = False

    def _mark_images_scanned(self) -> None:
        """记录「当前文档全部图片已按当前阅读列宽度处理过」。"""
        self._image_scan_width = self._content_text_width()
        self._image_scan_watermark = self._text_browser.document().blockCount()

    def _copy_code_block(self, index: int) -> None:
        """复制指定代码块并给出短暂的对勾反馈。"""
        if not 0 <= index < len(self._code_buttons_tables):
            return
        table = self._code_buttons_tables[index]
        if is_deleted(table):
            return
        self._copy_text(self._code_table_text(table))
        button = self._ensure_code_button(index)
        if button is None:
            return
        button.setIcon(self._code_check_icon())
        single_shot_on(self, 1000, lambda: self._restore_code_button_icon(button))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        if self._embedded:
            # 宽度变化后同步校正一次嵌入高度：不能只依赖 80ms 去抖，慢机器上旧宽度
            # 冻住的高度会一直留到下一次 flush。先激活布局再测量，测不准时函数自己跳过。
            layout = self.layout()
            if layout is not None:
                layout.activate()
            self._sync_embedded_height()
        self._schedule_layout_refresh()
