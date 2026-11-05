"""选区 Markdown / 源行映射方法组。"""

from __future__ import annotations


from .syntax import (
    _match_source_lines,
    _source_line_text,
)
from .tokens import _CODE_SOURCE_PROPERTY


class _MarkdownSelectionMixin:
    def markdownSelection(self) -> str:
        """把当前选中内容还原为 Markdown 源（块级近似）。

        - 代码块按源围栏精确还原（含围栏行）；
        - 普通块按归一化文本匹配源行，多块合并为连续切片；
        - 任一块无法映射时退回选中纯文本（无选中内容时返回空串）。
        """
        self._finish_pending_render()
        cursor = self._text_browser.textCursor()
        raw_selection = cursor.selection().toPlainText()
        if not cursor.hasSelection():
            return ""
        document = self.document()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        first = document.findBlock(start)
        last = document.findBlock(max(end - 1, start))
        if not first.isValid() or not last.isValid():
            return raw_selection
        ranges: list[tuple[int, int]] = []
        mapping = self._ensure_source_map()
        block = first
        while block.isValid():
            mapped = mapping.get(block.blockNumber())
            if block.text().strip() or mapped is not None:
                if mapped is None:
                    return raw_selection
                ranges.append(mapped)
            if block.blockNumber() >= last.blockNumber():
                break
            block = block.next()
        if not ranges:
            return raw_selection
        lines = self._source.split("\n")
        quote_start = min(item[0] for item in ranges)
        quote_end = max(item[1] for item in ranges)
        quote = "\n".join(lines[quote_start:quote_end]).strip("\n")
        return quote or raw_selection

    def _ensure_source_map(self) -> dict:
        """取源行映射；未构建时**按需**构建一次并缓存。
        渲染入口一律把它置回 ``None``（作废），构建成本只由真正用到
        ``markdownSelection()``（引用回复）的会话支付。
        """
        mapping = self._block_source_map
        if mapping is None:
            mapping = self._build_block_source_map()
            self._block_source_map = mapping
        return mapping

    def _build_block_source_map(self) -> dict:
        """构建 文档块号 → 源行范围 的近似映射（引用回复用）。
        代码块使用表格式上记录的源围栏范围；普通块用归一化文本双指针匹配。
        源行归一化结果**预计算一次**（原先每个候选起点重复归一次，实测
        """
        lines = self._source.split("\n")
        normalized = [_source_line_text(line) for line in lines]
        code_ranges: dict = {}
        for table in self._iter_tables(self.document()):
            stored = table.format().property(_CODE_SOURCE_PROPERTY)
            if not isinstance(stored, str):
                continue
            start_text, _, end_text = stored.partition(",")
            try:
                code_range = (int(start_text), int(end_text))
            except ValueError:
                continue
            for row in range(table.rows()):
                cell = table.cellAt(row, 0)
                first = cell.firstCursorPosition().blockNumber()
                last = cell.lastCursorPosition().blockNumber()
                for number in range(first, last + 1):
                    code_ranges[number] = code_range
        mapping: dict = {}
        source_index = 0
        block = self.document().begin()
        while block.isValid():
            number = block.blockNumber()
            code_range = code_ranges.get(number)
            if code_range is not None:
                mapping[number] = code_range
                source_index = max(source_index, code_range[1])
            else:
                text = block.text().strip()
                if not text:
                    mapping[number] = None
                else:
                    matched = _match_source_lines(normalized, source_index, text)
                    if matched is not None:
                        mapping[number] = matched
                        source_index = matched[1]
                    else:
                        mapping[number] = None
            block = block.next()
        return mapping
