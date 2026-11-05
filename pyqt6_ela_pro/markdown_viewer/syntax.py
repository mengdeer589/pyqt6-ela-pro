"""Markdown 纯文本辅助（位置钳制 / 稳定切分）。"""

from __future__ import annotations

import re

from PyQt6.QtGui import QTextDocument

from ..math_lite import MATH_ENVS
from .tokens import (
    _CALLOUT_TOKEN_PREFIX,
    _CODE_TOKEN_PREFIX,
    _FOLD_END_TOKEN_PREFIX,
    _FOLD_TOKEN_PREFIX,
    _FOOTNOTE_DEF_PREFIX,
    _MERMAID_TOKEN_PREFIX,
    _TOC_TOKEN,
)


def _clamp_pos(document: QTextDocument, position: int) -> int:
    """把字符位置钳进文档合法区间（``0 .. characterCount - 1``）。

    越界时 Qt 只警告、光标不动，后续 movePosition / mergeCharFormat 会落在错误位置。
    """
    try:
        limit = max(0, int(document.characterCount()) - 1)
    except Exception:  # noqa: BLE001 —— 文档已析构等异常形态
        return 0
    return max(0, min(int(position), limit))


_FENCE_MARKERS = ("```", "~~~")


def _fence_open(line: str) -> tuple[str, str]:
    """判断一行是否开启围栏代码块。

    :returns: ``(完整围栏串, 语言)``；不是围栏则 ``("", "")``。围栏串是
        **完整**的连续标记（`` ```` `` / `` ```` ``），不是固定 3 个字符。
    """
    stripped = line.lstrip()
    if not stripped.startswith(_FENCE_MARKERS):
        return "", ""
    i = 0
    while i < len(stripped) and stripped[i] in "`~":
        i += 1
    marker = stripped[:i]
    # 纯标记行（没有语言）时长度就是围栏长度；有语言时取标记部分
    return marker, stripped[i:].strip().split(" ", 1)[0].lower()


def _fence_close(line: str, fence: str) -> bool:
    """判断一行是否闭合 ``fence`` 开启的围栏。

    两条规则都必要，缺一条就会静默改坏代码内容：

    * **长度必须 ≥ 开围栏且不得更长的同类串** —— CommonMark 里用 4 个反引号
      包裹 3 个反引号是标准写法，只看前 3 字符会让内层 ``` 提前闭合围栏。
    * **闭合行除空白外不得有其它字符** —— ```` ```not-a-close ```` 不是闭合标记。
    """
    if not fence:
        return False
    stripped = line.strip()
    if not stripped.startswith(fence):
        return False
    rest = stripped[len(fence) :]
    if rest and rest[0] == fence[0]:
        return False
    return not rest.strip()


_STREAM_SENTENCE_MIN = 4096

_STREAM_SENTENCE_MAX = 16384

_SENTENCE_RE = re.compile(r"[。！？!?;；]")

_SOURCE_DECOR_RE = re.compile(
    r"^\s*(?:>+\s*|[-+*]\s+|\d+[.)]\s+|\[[ xX]\]\s+|#{1,6}\s+)+"
)

_INLINE_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")

_INLINE_SYMBOL_RE = re.compile(
    r"(\*\*|\*|__|_|~~|==|`+|<sub>|</sub>|<sup>|</sup>|~|\^)"
)


def _strip_inline_links(text: str) -> str:
    """``[文字](目标)`` / ``![alt](src)`` → 只留 ``文字``。

    必须手写扫描：``\\([^)]*\\)`` 在「有 ``[`` 没 ``)``」的长行上是 O(n²)，
    而它挂在每次全量渲染的 ``_normalize_text`` 上。语义与正则的最左匹配一致。
    """
    out: list[str] = []
    i = 0
    n = len(text)
    paren = -1  # 缓存：下一个 ')' 的位置，-1 表示待求值
    while i < n:
        op = text.find("](", i)
        if op < 0:
            out.append(text[i:])
            break
        # label 里不得含 ']'（等价原正则的 [^\]]*）：所以 '[' 必须在最后一个
        # ']' 之后
        prev_close = text.rfind("]", i, op)
        lb = text.find("[", prev_close + 1 if prev_close >= 0 else i, op)
        if lb < 0:
            out.append(text[i : op + 2])
            i = op + 2
            continue
        if paren != -1 and paren <= op + 1:
            paren = -1
        if paren == -1:
            paren = text.find(")", op + 2)
        if paren < 0:
            out.append(text[i:])
            break
        start = lb - 1 if lb > i and text[lb - 1] == "!" else lb
        out.append(text[i:start])
        out.append(text[lb + 1 : op])
        i = paren + 1
        paren = -1
    return "".join(out)


def _normalize_text(text: str) -> str:
    """块/行文本归一化：去装饰符、链接语法与全部空白（含任务标记）。"""
    # 新标记（■/□）+ 旧标记（☑/☐）：已导出的旧渲染文本与宿主粘贴仍要能对齐。
    for marker in ("■", "□", "☑", "☐"):
        text = text.replace(marker, "")
    text = _strip_inline_links(text)
    text = _SOURCE_DECOR_RE.sub("", text)
    text = _INLINE_SYMBOL_RE.sub("", text)
    return "".join(text.split())


def _source_line_text(line: str) -> str:
    """源行 → 归一化文本；不可匹配的行（代码围栏/占位符/标签/脚注定义）返回空。"""
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith(_FENCE_MARKERS):
        return ""
    if any(
        token in stripped
        for token in (
            _FOLD_TOKEN_PREFIX,
            _FOLD_END_TOKEN_PREFIX,
            _CODE_TOKEN_PREFIX,
            _MERMAID_TOKEN_PREFIX,
            _FOOTNOTE_DEF_PREFIX,
            _TOC_TOKEN,
            _CALLOUT_TOKEN_PREFIX,
        )
    ):
        return ""
    if stripped.startswith(("<", "[")) and (
        _DETAILS_OPEN_RE.match(stripped)
        or _DETAILS_CLOSE_RE.match(stripped)
        or _SUMMARY_RE.match(stripped)
        or _FOOTNOTE_DEF_RE.match(line)
    ):
        return ""
    return _normalize_text(line)


def _match_source_lines(lines: list, start: int, block_text: str):
    """从 ``start`` 起搜索与块文本匹配的源行（支持跨行段落/合并引用）。

    ``lines`` 是**预计算**的 ``_source_line_text`` 结果（不可匹配的行为空串），
    由 :meth:`ElaMarkdownViewer._build_block_source_map` 一次生成、逐块复用。

    在窗口内逐行作为起点尝试消费；累计文本必须是目标的前缀才继续，
    否则换下一行起点（避免把无关行误吞进匹配）。

    :returns: ``(匹配起始行号, 结束行号)``；无法匹配返回 ``None``
    """
    target = _normalize_text(block_text)
    if not target:
        return None
    total = len(lines)
    index = start
    while index < total and index < start + 80:
        if not lines[index]:
            index += 1
            continue
        accumulated = ""
        cursor = index
        while cursor < total and cursor < index + 40:
            part = lines[cursor]
            cursor += 1
            if not part:
                continue
            accumulated += part
            if accumulated == target:
                return (index, cursor)
            if not target.startswith(accumulated):
                break
        index += 1
    return None


def _stable_cut(
    text: str,
    committed: int = 0,
    allow_sentence: bool = False,
    safe_from: int = 0,
) -> tuple[int, int]:
    """返回 ``(稳定提交边界偏移, 下次可复用的安全扫描起点)``（无边界时切点为 0）。
    未闭合的围栏 / 公式块整体留在尾部；``allow_sentence`` 供超长段落在句末提交。
    ``safe_from`` 之后只做增量扫描，避免每次从 0 重扫变成 O(n²)。
    """
    length = len(text)
    base = min(max(int(safe_from), 0), length)
    line_start = text.rfind("\n", 0, base) + 1 if base else 0
    lines = text[line_start:].split("\n")
    n = len(lines)
    offsets = [0]
    for line in lines[:-1]:
        offsets.append(offsets[-1] + len(line) + 1)
    first_line_is_doc_start = line_start == 0
    cut = 0
    sentence_cut = 0
    #: 已知在围栏 / 公式块之外的最大偏移（供下一次增量扫描用）
    outside_end = base
    i = 0
    while i < n:
        line = lines[i]
        stripped = line.strip()
        opened, _lang = _fence_open(line)
        if opened:
            i += 1
            while i < n and not _fence_close(lines[i], opened):
                i += 1
            i += 1
            continue
        closer = None
        env_m = re.match(r"\\begin\{(\w+\*?)\}\s*$", stripped)
        if stripped in ("$$", "\\["):
            closer = stripped if stripped == "$$" else "\\]"
        elif env_m and env_m.group(1).rstrip("*") in MATH_ENVS:
            closer = "\\end{" + env_m.group(1) + "}"
        if closer is not None:
            i += 1
            while i < n and lines[i].strip() != closer:
                i += 1
            i += 1
            continue
        if line == "" and (i > 0 or not first_line_is_doc_start) and i < n - 1:
            cut = line_start + offsets[i + 1]
        elif allow_sentence and not line.startswith(("    ", "\t")):
            for match in _SENTENCE_RE.finditer(line):
                sentence_cut = line_start + offsets[i] + match.end()
        outside_end = line_start + offsets[i] + len(line) + 1
        i += 1

    if cut > committed:
        return cut, cut
    if allow_sentence:
        if (
            sentence_cut > committed
            and sentence_cut - committed >= _STREAM_SENTENCE_MIN
        ):
            return sentence_cut, sentence_cut
        if length - committed >= _STREAM_SENTENCE_MAX:
            limit = min(committed + _STREAM_SENTENCE_MAX, length)
            pos = max(
                text.rfind(" ", committed, limit),
                text.rfind("\n", committed, limit),
            )
            if pos > committed:
                return pos + 1, min(pos + 1, outside_end)
    return cut, min(cut, outside_end)


_DETAILS_OPEN_RE = re.compile(r"^<details>\s*$", re.IGNORECASE)

_DETAILS_CLOSE_RE = re.compile(r"^</details>\s*$", re.IGNORECASE)

_SUMMARY_RE = re.compile(r"^<summary>(.*)</summary>\s*$", re.IGNORECASE)

_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:[ \t]*(.*)$")
