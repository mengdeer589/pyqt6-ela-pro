"""裸 HTML 标签守卫：Qt Markdown 导入器会吞掉未配对标签后的正文。"""

from __future__ import annotations

import re
from typing import NamedTuple

_TAG_START_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)(?=[\s/>])")

#: 分段扫描块大小（只控制单次循环跨度，不是标签长度上限）。
_TAG_SCAN_CHUNK = 4096

#: void 元素没有闭合标签；Qt 仍会一路找 </name>，必须补成自闭合。
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _Tag(NamedTuple):
    start: int
    end: int
    name: str
    closing: bool
    self_closing: bool


def _find_tag_end(text: str, start: int) -> int:
    """返回标签 `>` 的下标（跳过引号内的 `>`）；找不到返回 -1。"""
    quote = ""
    length = len(text)
    index = start
    while index < length:
        stop = min(index + _TAG_SCAN_CHUNK, length)
        for cursor in range(index, stop):
            char = text[cursor]
            if quote:
                if char == quote:
                    quote = ""
            elif char in ("'", '"'):
                quote = char
            elif char == ">":
                return cursor
        index = stop
    return -1


def _is_escaped(text: str, index: int) -> bool:
    """`\\<tag>` 是用户显式转义；连续反斜杠按奇偶判断。"""
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def _is_indented_code(text: str, index: int) -> bool:
    """``index`` 所在行是否为缩进代码块（4+ 空格 / tab，含 ``>`` 引用前缀）。"""
    line_start = text.rfind("\n", 0, index) + 1
    cursor = line_start
    # 只剥引用前缀；行首空格要留给缩进判断
    while cursor < index:
        probe = cursor
        while probe < index and text[probe] == " ":
            probe += 1
        if probe < index and text[probe] == ">":
            cursor = probe + 1
            if cursor < index and text[cursor] == " ":
                cursor += 1
            continue
        break
    indent = 0
    while cursor < index and text[cursor] == " ":
        indent += 1
        cursor += 1
    if cursor < index and text[cursor] == "\t":
        return True
    return indent >= 4


def _is_link_destination(text: str, start: int, end: int) -> bool:
    """跳过 `[x](<foo>)` / `[x](<foo> "title")` 这类 Markdown 链接目标。"""
    if start == 0 or text[start - 1] != "(":
        return False
    for index in range(start + 1, end):
        if text[index].isspace():
            return False
    cursor = end + 1
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text):
        return False
    if text[cursor] == ")":
        return True
    if text[cursor] not in ("'", '"'):
        return False
    close = text.find(text[cursor], cursor + 1)
    if close < 0:
        return False
    cursor = close + 1
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return cursor < len(text) and text[cursor] == ")"


def _scan_tags(text: str) -> list[_Tag]:
    tags: list[_Tag] = []
    cursor = 0
    length = len(text)
    while cursor < length:
        start = text.find("<", cursor)
        if start < 0:
            break
        if text.startswith("<!--", start):
            close = text.find("-->", start + 4)
            cursor = length if close < 0 else close + 3
            continue
        match = _TAG_START_RE.match(text, start)
        if match is None:
            cursor = start + 1
            continue
        end = _find_tag_end(text, match.end(2))
        if end < 0:
            cursor = start + 1
            continue
        cursor = end + 1
        if (
            _is_escaped(text, start)
            or _is_link_destination(text, start, end)
            or _is_indented_code(text, start)
        ):
            continue
        name_end = end - 1
        while name_end > match.end(2) and text[name_end].isspace():
            name_end -= 1
        tags.append(
            _Tag(
                start=start,
                end=end,
                name=match.group(2).lower(),
                closing=bool(match.group(1)),
                self_closing=text[name_end] == "/",
            )
        )
    return tags


def _paired_indexes(tags: list[_Tag]) -> set[int]:
    paired: set[int] = set()
    # 按标签名分栈：闭合标签直接取最近同名开标签，避免大量不匹配时 O(n²)
    opens: dict[str, list[int]] = {}
    for index, tag in enumerate(tags):
        if tag.closing:
            stack = opens.get(tag.name)
            if stack:
                paired.add(stack.pop())
                paired.add(index)
        elif not tag.self_closing:
            opens.setdefault(tag.name, []).append(index)
    return paired


def guard_unpaired_html(text: str) -> str:
    """转义未配对的开 / 闭标签；void 开标签补成自闭合，避免 Qt 吞掉后续正文。"""
    if "<" not in text or ">" not in text:
        # 没有闭合的 `>`：Qt 不会把任何 `<字母...` 当标签，按原文保留
        return text
    tags = _scan_tags(text)
    if not tags:
        return text
    paired = _paired_indexes(tags)
    edits: list[tuple[int, int, str]] = []
    for index, tag in enumerate(tags):
        if index in paired or tag.self_closing:
            continue
        if tag.closing:
            edits.append((tag.start, tag.start + 1, "&lt;"))
        elif tag.name in _VOID_TAGS:
            edits.append((tag.end, tag.end, "/"))
        else:
            edits.append((tag.start, tag.start + 1, "&lt;"))
    if not edits:
        return text
    # _scan_tags 按文档顺序产出、标签互不重叠，edits 天然升序
    parts: list[str] = []
    last = 0
    for start, end, replacement in edits:
        parts.append(text[last:start])
        parts.append(replacement)
        last = end
    parts.append(text[last:])
    return "".join(parts)


__all__ = ["guard_unpaired_html"]
