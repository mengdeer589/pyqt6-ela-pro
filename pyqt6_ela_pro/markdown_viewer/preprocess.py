"""Markdown 预处理：折叠 / 脚注 / 标注 / 任务标记 / 锚点。"""

from __future__ import annotations

import re
from html import escape as _html_escape
from html.entities import html5 as _HTML5_ENTITIES
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
)
from PyQt6ElaWidgetTools import ElaThemeType

from .._content_colors import calloutColors
from .html_guard import guard_unpaired_html
from .syntax import (
    _DETAILS_CLOSE_RE,
    _DETAILS_OPEN_RE,
    _FOOTNOTE_DEF_RE,
    _SUMMARY_RE,
    _clamp_pos,
    _fence_close,
    _fence_open,
    _is_indented_code_line,
    _strip_code_container_prefix,
)
from .themes import _QUOTE_LEFT_MARGIN
from .tokens import (
    _CALLOUT_RAIL_PROPERTY,
    _CALLOUT_TOKEN_PREFIX,
    _CODE_TOKEN_PREFIX,
    _CODE_TOKEN_SUFFIX,
    _FOLD_END_TOKEN_PREFIX,
    _FOLD_TOKEN_PREFIX,
    _FOOTNOTE_DEF_PREFIX,
    _FOOTNOTE_REF_PREFIX,
    _INLINE_CODE_TOKEN_PREFIX,
    _MARK_TOKEN_PREFIX,
    _MERMAID_TOKEN_PREFIX,
    _PROTECT_TOKEN_PREFIX,
    _TOC_TOKEN,
    merge_anchor_format,
)


_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")

_DEFAULT_REASONING_TAG = "think"

_DEFAULT_REASONING_LABEL = "思考过程"

_TASK_LIST_RE = re.compile(
    r"^((?:[ \t]*>[ \t]?)*[ \t]*(?:[-+*]|\d+[.)])[ \t]+)\[([ xX])\][ \t]?"
)

_EMPTY_ALT_IMAGE_RE = re.compile(r"!\[\](?=[\(\[])")

_SUB_RE = re.compile(r"(?<![\d~])~([0-9A-Za-z]+)~(?!~)")

_SUP_RE = re.compile(r"(?<!\^)\^([0-9A-Za-z]+)\^(?!\^)")

_LONE_TILDE_RE = re.compile(r"(?<!\\)(?<!~)~(?!~)")

_MARK_RE = re.compile(r"==([^=\s](?:[^=]*[^=\s])?)==")

_MARK_RICH_RE = re.compile(r"==([^=\s](?:.*?[^=\s])?)==")

_MARK_SPECIAL_CHARS = ("[", "]", "`", "~", "<", ">")

_EMOJI_RE = re.compile(r":([a-z0-9_+-]+):")

_NAMED_ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]+);")

_NUMERIC_WS_ENTITY_RE = re.compile(
    r"&#(?:0*9|0*10|0*13|x0*9|x0*10|x0*13);", re.IGNORECASE
)

_ENTITY_SKIP = frozenset({"amp", "apos", "gt", "lt", "nbsp", "quot"})

_EMOJI_MAP = {
    "smile": "😄",
    "grin": "😁",
    "joy": "😂",
    "rofl": "🤣",
    "wink": "😉",
    "blush": "😊",
    "heart": "❤️",
    "broken_heart": "💔",
    "thumbsup": "👍",
    "+1": "👍",
    "thumbsdown": "👎",
    "-1": "👎",
    "ok_hand": "👌",
    "clap": "👏",
    "pray": "🙏",
    "muscle": "💪",
    "wave": "👋",
    "point_right": "👉",
    "point_left": "👈",
    "eyes": "👀",
    "thinking": "🤔",
    "sweat_smile": "😅",
    "cry": "😢",
    "sob": "😭",
    "angry": "😠",
    "rage": "😡",
    "scream": "😱",
    "sunglasses": "😎",
    "star": "⭐",
    "star2": "🌟",
    "sparkles": "✨",
    "fire": "🔥",
    "rocket": "🚀",
    "tada": "🎉",
    "balloon": "🎈",
    "gift": "🎁",
    "trophy": "🏆",
    "medal": "🏅",
    "warning": "⚠️",
    "check": "✅",
    "heavy_check_mark": "✔️",
    "x": "❌",
    "cross_mark": "❌",
    "question": "❓",
    "no_entry": "⛔",
    "bulb": "💡",
    "book": "📖",
    "books": "📚",
    "pencil": "📝",
    "gear": "⚙️",
    "wrench": "🔧",
    "hammer": "🔨",
    "bug": "🐛",
    "zap": "⚡",
    "boom": "💥",
    "100": "💯",
    "clock": "🕐",
    "hourglass": "⏳",
    "calendar": "📅",
    "pushpin": "📌",
    "paperclip": "📎",
    "link": "🔗",
    "lock": "🔒",
    "key": "🔑",
    "mag": "🔍",
    "chart": "📈",
    "package": "📦",
    "computer": "💻",
    "phone": "📱",
    "email": "📧",
    "speech_balloon": "💬",
    "arrow_right": "➡️",
    "arrow_left": "⬅️",
    "arrow_up": "⬆️",
    "arrow_down": "⬇️",
    "information_source": "ℹ️",
    "heavy_plus_sign": "➕",
    "heavy_minus_sign": "➖",
}

_CALLOUT_RE = re.compile(
    r"^>[ \t]*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*$", re.IGNORECASE
)

_CALLOUT_LABELS = {
    "note": "提示",
    "tip": "技巧",
    "important": "重要",
    "warning": "警告",
    "caution": "注意",
}

_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]\s]+)\]")

_TOC_LINE_RE = re.compile(r"^\[toc\]$", re.IGNORECASE)

_DETAILS_INLINE_RE = re.compile(
    r"^<details>\s*<summary>(.*?)</summary>(.*?)</details>\s*$", re.IGNORECASE
)

_DETAILS_SUMMARY_OPEN_RE = re.compile(
    r"^<details(?P<attrs>\s[^>]*)?>\s*<summary>(.*?)</summary>\s*$",
    re.IGNORECASE,
)

_EMPTY_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]*#*[ \t]*$")

_EMPTY_LIST_ITEM_RE = re.compile(r"^((?:[ \t]*>[ \t]?)*[ \t]*(?:[-+*]|\d+[.)])[ \t]*)$")

_BARE_URL_RE = re.compile(
    r"(?:https?://|ftp://|mailto:|xmpp:|www\.)[^\s<>]+", re.IGNORECASE
)

_LINK_LABEL_RE = re.compile(r"\[([^\]]*)\]\(")

_TABLE_DELIM_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")

_IMAGE_LINK_RE = re.compile(
    r"\[!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)\]"
    r"\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)"
)


def _image_link_html(match: re.Match) -> str:
    """纯图片链接 → HTML：Qt 对 Markdown 图片 label 不保留外链 anchor。"""
    alt, src, img_title, href, link_title = match.groups()
    if any(char in src + href for char in '<>"\n'):
        return match.group(0)
    parts = [
        f'<a href="{_html_escape(href, quote=True)}"',
        f' title="{_html_escape(link_title, quote=True)}"' if link_title else "",
        ">",
        f'<img src="{_html_escape(src, quote=True)}"',
        f' alt="{_html_escape(alt, quote=True)}"' if alt else "",
        f' title="{_html_escape(img_title, quote=True)}"' if img_title else "",
        "></a>",
    ]
    return "".join(parts)


def _trim_url_tail(url: str) -> str:
    """去掉裸 URL 末尾的句读 / 不成对右括号（GFM autolink 的常见裁剪）。"""
    while url:
        char = url[-1]
        if char in ".,;:!?":
            url = url[:-1]
            continue
        if char in ")]}":
            opener = {")": "(", "]": "[", "}": "{"}[char]
            if url.count(char) > url.count(opener):
                url = url[:-1]
                continue
        break
    return url


def _split_url_tail(url: str) -> tuple[str, str]:
    """在第一个不成对右括号处截断（``(business))+ok`` → ``(business)``）。"""
    depth = 0
    for index, char in enumerate(url):
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                return _trim_url_tail(url[:index]), url[index:]
            depth -= 1
    trimmed = _trim_url_tail(url)
    return trimmed, url[len(trimmed) :]


def _label_ranges(segment: str) -> list[tuple[int, int]]:
    """当前片段里 Markdown 链接 label 的字符区间（不含方括号）。"""
    return [
        (match.start(1), match.end(1)) for match in _LINK_LABEL_RE.finditer(segment)
    ]


def _table_row_flags(lines: list[str]) -> list[bool]:
    """标记表格块内的行（表头 / 分隔行 / 数据行）。"""
    flags = [False] * len(lines)
    index = 0
    while index < len(lines):
        if "|" not in lines[index] or not _TABLE_DELIM_RE.match(lines[index]):
            index += 1
            continue
        flags[index] = True
        cursor = index - 1
        while cursor >= 0 and lines[cursor].strip() and "|" in lines[cursor]:
            flags[cursor] = True
            cursor -= 1
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].strip() and "|" in lines[cursor]:
            flags[cursor] = True
            cursor += 1
        index = cursor
    return flags


def _decode_named_entities(segment: str) -> str:
    """补 Qt 缺失的 HTML5 命名实体；XML 五件套与 nbsp 留给导入器。"""

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name.lower() in _ENTITY_SKIP:
            return match.group(0)
        if _is_escaped(segment, match.start()):
            return match.group(0)
        value = _HTML5_ENTITIES.get(f"{name};")
        # 只补 Qt 缺的非 ASCII 字符；ASCII 标点/字母交给导入器，
        # 避免 &LT; 重新造出真实标签。
        if value is None or value.isascii() or "\n" in value or "\r" in value:
            return match.group(0)
        return value

    segment = _NUMERIC_WS_ENTITY_RE.sub(" ", segment)
    return _NAMED_ENTITY_RE.sub(replace, segment)


def _is_escaped(text: str, index: int) -> bool:
    count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        count += 1
        cursor -= 1
    return count % 2 == 1


def _details_is_open(attrs: Optional[str]) -> bool:
    return (
        bool(attrs)
        and re.search(r"(?:^|\s)open(?:\s|=|$)", attrs, re.IGNORECASE) is not None
    )


def _is_footnote_continuation(line: str) -> bool:
    """脚注续行：剥掉 ``>`` 后仍有 4 空格 / tab（列表标记也算续行）。"""
    stripped = re.sub(r"^(?:[ \t]*>[ \t]?)+", "", line)
    return stripped.startswith("\t") or stripped.startswith("    ")


def _escape_label_url(url: str) -> str:
    """打断 label 内裸 URL 的 autolink，避免它抢走外层链接的 href。"""
    if url.lower().startswith("www."):
        return url[:3] + "\\" + url[3:]
    scheme = re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", url)
    if scheme is not None:
        colon = scheme.end() - 1
        return url[:colon] + "\\" + url[colon:]
    return url


def _front_matter_end(lines: list[str]) -> Optional[tuple[int, str]]:
    """首行 front matter 定界符且有闭合行时返回 ``(闭合行号, 语言)``。"""
    if not lines:
        return None
    opening = lines[0].lstrip("\ufeff").strip()
    if opening == "---":
        closers, language = ("---", "..."), "yaml"
    elif opening == "+++":
        closers, language = ("+++",), "toml"
    else:
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() in closers:
            if index <= 1:
                return None
            body = lines[1:index]
            if not _looks_like_front_matter(body, language):
                return None
            return index, language
    return None


def _looks_like_front_matter(lines: list[str], language: str) -> bool:
    """避免把「首尾都是 ``---`` 的普通正文」误判成 front matter。"""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if language == "toml":
            if "=" in stripped or stripped.startswith("["):
                return True
            continue
        if re.match(r"^[A-Za-z_][\w.-]*\s*:(?!//)", stripped):
            return True
        if stripped.startswith(("- ", "{", "[", "...")):
            return True
    return False


class _MarkdownPreprocessMixin:
    @staticmethod
    def _collect_footnote_defs(lines: list[str]) -> tuple[list, set]:
        """收集围栏之外的脚注定义行，返回 ``[(id, text)]`` 与定义行号集合。"""
        defs: list[tuple[str, str]] = []
        indices: set[int] = set()
        seen: set[str] = set()
        fence: Optional[str] = None
        fence_prefix = ""
        index = 0
        while index < len(lines):
            line = lines[index]
            if fence is not None:
                if _fence_close(line, fence, fence_prefix):
                    fence = None
                    fence_prefix = ""
                index += 1
                continue
            opened, _lang, prefix = _fence_open(line)
            if opened:
                fence = opened
                fence_prefix = prefix
                index += 1
                continue
            if _is_indented_code_line(line):
                index += 1
                continue
            match = _FOOTNOTE_DEF_RE.match(line)
            if match is None:
                index += 1
                continue
            fid = match.group(1)
            parts = [match.group(2).strip()]
            indices.add(index)
            cursor = index + 1
            while cursor < len(lines):
                following = lines[cursor]
                if not following.strip():
                    lookahead = cursor + 1
                    while lookahead < len(lines) and not lines[lookahead].strip():
                        lookahead += 1
                    if lookahead < len(lines) and _is_footnote_continuation(
                        lines[lookahead]
                    ):
                        parts.append("")
                        cursor = lookahead
                        continue
                    break
                if not _is_footnote_continuation(following):
                    break
                parts.append(following.strip())
                indices.add(cursor)
                cursor += 1
            body = " ".join(part for part in parts if part).strip()
            if fid not in seen:
                seen.add(fid)
                defs.append((fid, body))
            index = cursor
        return defs, indices

    def _extract_folds(self, lines: list[str]) -> tuple[list[str], list[dict]]:
        """扫描可折叠块（推理标签 / ``<details>``）并替换为占位符行。

        - 围栏代码块内的标签不处理；
        - 未闭合的块标记 ``pending``（流式期间标签显示"思考中…"）；
        - 内容行原样保留（渲染后按展开状态隐藏或展示）。

        返回 ``(改写后的行, [(kind, label, pending)])``。
        """
        result: list[str] = []
        folds: list[dict] = []
        tag = (self._reasoning_tag or "").strip()
        open_re = (
            re.compile(rf"^<{re.escape(tag)}>\s*$", re.IGNORECASE) if tag else None
        )
        close_re = (
            re.compile(rf"^</{re.escape(tag)}>\s*$", re.IGNORECASE) if tag else None
        )
        fence: Optional[str] = None
        fence_prefix = ""
        index = 0
        i = 0
        total = len(lines)
        index_map: list[int] = []

        def append(text: str, raw_index: int) -> None:
            result.append(text)
            index_map.append(raw_index)

        def append_fold(
            start: int, end: int, meta: dict, closed: bool, anchor: int
        ) -> None:
            nonlocal index
            if result and result[-1].strip():
                append("", anchor)
            append(f"{_FOLD_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", anchor)
            append("", anchor)
            for raw in range(start, end):
                append(lines[raw], raw)
            if closed:
                append("", anchor)
                append(f"{_FOLD_END_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", anchor)
                append("", anchor)
            folds.append(meta)
            index += 1

        while i < total:
            stripped = lines[i].strip()
            if fence is not None:
                if _fence_close(lines[i], fence, fence_prefix):
                    fence = None
                    fence_prefix = ""
                append(lines[i], i)
                i += 1
                continue
            opened, _lang, prefix = _fence_open(lines[i])
            if opened:
                fence = opened
                fence_prefix = prefix
                append(lines[i], i)
                i += 1
                continue
            if _is_indented_code_line(lines[i]):
                append(lines[i], i)
                i += 1
                continue
            inline_details = _DETAILS_INLINE_RE.match(stripped)
            if inline_details is not None:
                label = inline_details.group(1).strip() or "详情"
                body = inline_details.group(2).strip()
                if result and result[-1].strip():
                    append("", i)
                append(f"{_FOLD_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", i)
                append("", i)
                if body:
                    append(body, i)
                append("", i)
                append(f"{_FOLD_END_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", i)
                append("", i)
                folds.append({"kind": "details", "label": label, "pending": False})
                index += 1
                i += 1
                continue
            if open_re is not None and open_re.match(stripped):
                j = i + 1
                while j < total and not close_re.match(lines[j].strip()):
                    j += 1
                closed = j < total
                append_fold(
                    i + 1,
                    j,
                    {
                        "kind": "reasoning",
                        "label": self._reasoning_label if closed else "思考中…",
                        "pending": not closed,
                    },
                    closed,
                    i,
                )
                i = j + 1 if closed else total
                continue
            summary_open = _DETAILS_SUMMARY_OPEN_RE.match(stripped)
            details_open = _DETAILS_OPEN_RE.match(stripped)
            if details_open or summary_open is not None:
                depth = 1
                attrs = (
                    summary_open.group("attrs")
                    if summary_open is not None
                    else details_open.group("attrs")
                )
                is_open = _details_is_open(attrs)
                fold_index = index
                label = summary_open.group(2).strip() if summary_open else "详情"
                content_start = i + 1
                if summary_open is None and content_start < total:
                    summary = _SUMMARY_RE.match(lines[content_start].strip())
                    if summary:
                        label = summary.group(1).strip() or label
                        content_start += 1
                k = content_start
                while k < total and depth > 0:
                    inner = lines[k].strip()
                    if (
                        _DETAILS_OPEN_RE.match(inner)
                        or _DETAILS_SUMMARY_OPEN_RE.match(inner)
                        or _DETAILS_INLINE_RE.match(inner)
                    ):
                        depth += 1
                    elif _DETAILS_CLOSE_RE.match(inner):
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                closed = depth == 0
                append_fold(
                    content_start,
                    k if closed else total,
                    {
                        "kind": "details",
                        "label": label,
                        "pending": not closed,
                        "open": is_open,
                    },
                    closed,
                    i,
                )
                if is_open and fold_index not in self._collapsed_folds:
                    self._expanded_folds.add(fold_index)
                i = k + 1 if closed else total
                continue
            append(lines[i], i)
            i += 1
        return result, folds, index_map

    def _preprocess(self, text: str) -> str:
        """预处理 Markdown 源文。
        围栏代码 / 脚注 / Callout / [toc] / 折叠块替换为占位符，任务列表换成 ■/□，
        行内代码 / 上下标 / 高亮 / emoji 在此展开。
        """
        raw_lines = text.split("\n")
        # 首行 frontmatter 会被 Qt 的 Markdown 导入器整块吞掉；转成对应
        # 语言围栏保留原文，只替换两行定界符，源码行号不漂。
        if self._front_matter_mode == "fence":
            meta = _front_matter_end(raw_lines)
            if meta is not None:
                end, language = meta
                content = "\n".join(raw_lines[1:end])
                max_run = max((len(m) for m in re.findall(r"`+", content)), default=0)
                fence = "`" * max(3, max_run + 1)
                raw_lines[0] = f"{fence}{language}"
                raw_lines[end] = fence
            elif raw_lines and raw_lines[0].lstrip("\ufeff").strip() == "---":
                # Qt 会把首行 --- + 后续 --- 整块当 front matter 吞掉；
                # 不是 YAML 时换成等价的分隔线，保住正文。
                raw_lines[0] = "***"
        lines, folds, index_map = self._extract_folds(raw_lines)
        table_rows = _table_row_flags(lines)
        fn_defs, fn_def_lines = self._collect_footnote_defs(raw_lines)
        defined = {fid for fid, _ in fn_defs}
        #: 脚注首次引用顺序（编号按引用顺序而不是定义顺序）
        ref_order: list[str] = []

        out: list[str] = []
        inline_codes: list[str] = []
        #: 与 ``inline_codes`` 一一对应的占位符 token（``transform_line`` 里
        #: 本就为文档生成了同一串，顺手存下来 —— ``_apply_inline_code_formats``
        #: 不必再逐条重建 f-string）
        inline_tokens: list[str] = []
        #: 行内转换要跳过的片段（链接目标 / 裸 URL / HTML 标签）
        protected: list[str] = []
        link_dest_re = re.compile(r"\]\(([^)\n]*)\)")
        angle_autolink_re = re.compile(r"<(?:https?|ftp)://[^>\s]+>", re.IGNORECASE)
        tag_re = re.compile(r"<[^>\n]+>")

        def protect_span(span: str) -> str:
            token = f"{_PROTECT_TOKEN_PREFIX}{len(protected)}{_CODE_TOKEN_SUFFIX}"
            protected.append(span)
            return token

        def protect_inline(segment: str) -> str:
            if not segment:
                return segment
            # 图片链接先转成 HTML：Qt 不会给「纯图片 label」的图片片段挂 anchor
            segment = _IMAGE_LINK_RE.sub(lambda match: _image_link_html(match), segment)
            # 链接目标只保护 (...) 内部；label 仍参与加粗 / 斜体等转换
            segment = link_dest_re.sub(
                lambda match: "](" + protect_span(match.group(1)) + ")", segment
            )
            segment = angle_autolink_re.sub(
                lambda match: protect_span(match.group(0)), segment
            )
            segment = tag_re.sub(lambda match: protect_span(match.group(0)), segment)
            labels = _label_ranges(segment)

            def protect_bare_url(match):
                raw = match.group(0)
                start = match.start()
                label_end = next(
                    (right for left, right in labels if left <= start < right),
                    None,
                )
                if label_end is not None:
                    # label 内的 URL 交给外层链接；转义起点阻止它自己变成 autolink。
                    # 只保护 label 里的 URL 部分，别吃掉收尾的 == / ** / ]。
                    limit = min(len(raw), max(0, label_end - start))
                    url_part = raw[:limit]
                    tail = raw[limit:]
                    for marker in ("**", "__", "==", "~~", "*", "_", "~"):
                        if url_part.endswith(marker):
                            url_part = url_part[: -len(marker)]
                            tail = marker + tail
                            break
                    return (
                        protect_span(_escape_label_url(url_part).replace("~", "\\~"))
                        + tail
                    )
                if "](" in raw:
                    return protect_span(raw.replace("~", "\\~"))
                url, tail = _split_url_tail(raw)
                if not url:
                    return raw
                lowered = url.lower()
                if lowered.startswith(("http://", "https://", "ftp://")):
                    return protect_span(f"<{url}>") + tail
                if lowered.startswith(("mailto:", "xmpp:")):
                    href = _html_escape(url, quote=True)
                    return protect_span(f'<a href="{href}">{href}</a>') + tail
                if lowered.startswith("www.") and not any(
                    char in url for char in "[]<>\"'"
                ):
                    label = _escape_label_url(url).replace("*", "\\*")
                    return protect_span(f"[{label}](<http://{url}>)") + tail
                return protect_span(raw.replace("~", "\\~"))

            return _BARE_URL_RE.sub(protect_bare_url, segment)

        fenced_blocks: list[tuple[str, str]] = []
        fenced_source_lines: list[tuple[int, int]] = []
        mermaid_blocks: list[str] = []
        marks: list[str] = []
        callouts: list[str] = []
        tasks: list[tuple[int, bool]] = []
        fence: Optional[str] = None
        fence_lang = ""
        fence_prefix = ""
        fence_start = 0
        buffer: list[str] = []

        def emit_closed_fence(
            lang: str, code: str, start_line: int, end_line: int, prefix: str
        ) -> None:
            """闭合围栏：mermaid 且启用渲染时产出 Mermaid 占位符，否则代码卡片。"""
            if lang == "mermaid" and code.strip() and self._mermaid_enabled():
                mermaid_blocks.append(code)
                out.append(
                    prefix + f"{_MERMAID_TOKEN_PREFIX}{len(mermaid_blocks) - 1}"
                    f"{_CODE_TOKEN_SUFFIX}"
                )
                return
            token = f"{_CODE_TOKEN_PREFIX}{len(fenced_blocks)}{_CODE_TOKEN_SUFFIX}"
            fenced_blocks.append((lang, code, True))
            fenced_source_lines.append((start_line, end_line))
            out.append(prefix + token)

        def transform(segment: str) -> str:
            # 每个 sub 先做触发字符检查再进正则：正则固定开销远贵于 in 的 C 级扫描，
            # 正文命中率 <0.5%；各触发串都是对应正则的必要前置，跳过行为逐字节一致。
            if not segment:
                return segment

            if "&" in segment:
                segment = _decode_named_entities(segment)

            # 空 alt 图片补一个空格，否则 Qt 导入器整张丢弃（见正则注释）
            if "![" in segment:
                segment = _EMPTY_ALT_IMAGE_RE.sub("![ ]", segment)

            if "[^" in segment:

                def replace_ref(match):
                    fid = match.group(1)
                    if fid not in defined:
                        return match.group(0)
                    if fid not in ref_order:
                        ref_order.append(fid)
                    return f"{_FOOTNOTE_REF_PREFIX}{fid}{_CODE_TOKEN_SUFFIX}"

                # 脚注引用先替换为占位符，避免 ``^`` 被上标规则误配
                segment = _FOOTNOTE_REF_RE.sub(replace_ref, segment)

            if "~" in segment:
                segment = _SUB_RE.sub(lambda m: f"<sub>{m.group(1)}</sub>", segment)
                # 剩余的单波浪号转义为 ``\~``：否则 Qt 导入器会把「1~23、45~67」
                # 这类范围值配对成下标并吞掉 ``~``（见 _LONE_TILDE_RE）
                segment = _LONE_TILDE_RE.sub(r"\\~", segment)

            if "^" in segment:
                segment = _SUP_RE.sub(lambda m: f"<sup>{m.group(1)}</sup>", segment)

            if "==" in segment:

                def replace_mark(match):
                    content = match.group(1)
                    if "\ue000" in content or any(
                        ch in content for ch in _MARK_SPECIAL_CHARS
                    ):
                        return match.group(0)
                    marks.append(content)
                    return f"{_MARK_TOKEN_PREFIX}{len(marks) - 1}{_CODE_TOKEN_SUFFIX}"

                segment = _MARK_RE.sub(replace_mark, segment)

            if segment.count(":") >= 2:
                # emoji 短代码至少要两个冒号（``:smile:``）；只有一个冒号的
                # 段落（时间 / 键值对）占正文绝大多数，省掉一次正则
                segment = _EMOJI_RE.sub(
                    lambda m: _EMOJI_MAP.get(m.group(1).lower(), m.group(0)), segment
                )
            return segment

        def extract_rich_marks(line: str) -> str:
            """提取含行内代码 / 链接的高亮：内容交给 QTextDocumentFragment 渲染。"""
            if "==" not in line:
                return line
            skip_spans = [
                (match.start(), match.end()) for match in _INLINE_CODE_RE.finditer(line)
            ]
            for pattern in (link_dest_re, angle_autolink_re, tag_re):
                skip_spans.extend(
                    (match.start(), match.end()) for match in pattern.finditer(line)
                )

            def replace(match: re.Match) -> str:
                content = match.group(1)
                if not ("`" in content or "[" in content):
                    return match.group(0)
                if "<" in content or ">" in content:
                    return match.group(0)
                if any(start < match.start() < end for start, end in skip_spans):
                    return match.group(0)
                marks.append(content)
                return f"{_MARK_TOKEN_PREFIX}{len(marks) - 1}{_CODE_TOKEN_SUFFIX}"

            return _MARK_RICH_RE.sub(replace, line)

        def transform_line(line: str, in_table: bool = False) -> str:
            """行内语法转换（行内代码换成唯一占位符，文本另存）。"""
            line = extract_rich_marks(line)
            # 没有反引号的行直接走纯文本转换：``_INLINE_CODE_RE.finditer``
            # 每行都要起一次正则引擎（命中率低的文档是纯开销）
            if "`" not in line:
                return transform(protect_inline(line))
            pieces: list[str] = []
            last = 0
            for match in _INLINE_CODE_RE.finditer(line):
                pieces.append(transform(protect_inline(line[last : match.start()])))
                # 换成唯一占位符而不是把原文留在文档里：按文本 find 反推位置时，
                # 同一串文本更早出现过就会整体错位。占位符含私有区字符，零碰撞。
                token = (
                    f"{_INLINE_CODE_TOKEN_PREFIX}{len(inline_codes)}"
                    f"{_CODE_TOKEN_SUFFIX}"
                )
                code_text = match.group(2)
                if in_table:
                    code_text = code_text.replace("\\|", "|")
                inline_codes.append(code_text)
                inline_tokens.append(token)
                pieces.append(token)
                last = match.end()
            pieces.append(transform(protect_inline(line[last:])))
            return "".join(pieces)

        for line_no, line in enumerate(lines):
            raw_index = index_map[line_no]
            stripped = line.strip()
            if fence is not None:
                if _fence_close(line, fence, fence_prefix):
                    emit_closed_fence(
                        fence_lang,
                        "\n".join(buffer),
                        fence_start,
                        raw_index + 1,
                        fence_prefix,
                    )
                    fence = None
                    fence_lang = ""
                    fence_prefix = ""
                    buffer = []
                else:
                    buffer.append(_strip_code_container_prefix(line, fence_prefix))
                continue

            if raw_index in fn_def_lines:
                # 定义行抽取到文末；正文以空行占位避免段落粘连
                out.append("")
                continue

            opened, opened_lang, opened_prefix = _fence_open(line)
            if opened:
                fence = opened
                fence_lang = opened_lang
                fence_prefix = opened_prefix
                fence_start = raw_index
                continue

            if _is_indented_code_line(line):
                out.append(line)
                continue

            empty_heading = _EMPTY_HEADING_RE.match(line)
            if empty_heading is not None:
                line = f"{empty_heading.group(1)} \u200b"
            else:
                empty_item = _EMPTY_LIST_ITEM_RE.match(line)
                if empty_item is not None:
                    line = f"{empty_item.group(1).rstrip()} \u200b"

            callout = _CALLOUT_RE.match(stripped)
            if callout is not None:
                callouts.append(callout.group(1).lower())
                out.append(
                    f"> {_CALLOUT_TOKEN_PREFIX}{len(callouts) - 1}{_CODE_TOKEN_SUFFIX}"
                )
                following = (
                    lines[line_no + 1].lstrip("> ").strip()
                    if line_no + 1 < len(lines)
                    else ""
                )
                if following.startswith("|"):
                    out.append(">")
                continue

            if _TOC_LINE_RE.match(stripped):
                out.append(_TOC_TOKEN)
                continue

            def replace_task(match, line_index=raw_index):
                checked = match.group(2).lower() == "x"
                tasks.append((line_index, checked))
                marker = "■" if checked else "□"
                return f"{match.group(1)}[{marker}](#elatask-{len(tasks) - 1})"

            line = _TASK_LIST_RE.sub(replace_task, line)
            out.append(
                transform_line(
                    line, table_rows[line_no] if line_no < len(table_rows) else False
                )
            )

        if fence is not None:
            # 未闭合围栏：同样按代码块渲染（GitHub 语义），流式期间体验更好
            token = f"{_CODE_TOKEN_PREFIX}{len(fenced_blocks)}{_CODE_TOKEN_SUFFIX}"
            fenced_blocks.append((fence_lang, "\n".join(buffer), False))
            fenced_source_lines.append((fence_start, len(raw_lines)))
            out.append(fence_prefix + token)

        if fn_defs:
            by_id = dict(fn_defs)
            seen_refs = set(ref_order)
            ordered_defs = [(fid, by_id[fid]) for fid in ref_order if fid in by_id]
            ordered_defs.extend(
                (fid, body) for fid, body in fn_defs if fid not in seen_refs
            )
        else:
            ordered_defs = []
        if ordered_defs:
            out.append("")
            out.append("---")
            out.append("")
            for index, (fid, body) in enumerate(ordered_defs, start=1):
                out.append(
                    f"{_FOOTNOTE_DEF_PREFIX}{index}{_CODE_TOKEN_SUFFIX} [{index}] {body}"
                )
                out.append("")

        self._inline_codes = inline_codes
        self._inline_code_tokens = inline_tokens
        self._fenced_blocks = fenced_blocks
        self._fenced_source_lines = fenced_source_lines
        self._mark_texts = marks
        self._footnote_defs = ordered_defs
        self._callout_types = callouts
        self._task_items = tasks
        self._mermaid_blocks = mermaid_blocks
        self._fold_blocks = folds
        text = "\n".join(out)
        # 逆序还原：裸 URL / angle autolink 的 span 可能包住更早的链接目标 token
        for index in range(len(protected) - 1, -1, -1):
            text = text.replace(
                f"{_PROTECT_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", protected[index]
            )
        return guard_unpaired_html(text)

    def _replace_mark_tokens(self, document: QTextDocument) -> None:
        """把 ``==高亮==`` 占位符替换为带主题背景色的文本。"""
        if not self._mark_texts:
            return
        fmt = QTextCharFormat()
        fmt.setBackground(QBrush(self._mark_bg))
        entries = [
            (f"{_MARK_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", content)
            for index, content in enumerate(self._mark_texts)
        ]

        def replace(found: QTextCursor, content: str) -> None:
            original = found.charFormat()
            found.removeSelectedText()
            start = found.position()
            if any(char in content for char in "*_`["):
                found.insertFragment(QTextDocumentFragment.fromMarkdown(content))
            else:
                found.insertText(content)
            end = found.position()
            range_fmt = fmt
            if original.isAnchor():
                range_fmt = QTextCharFormat(fmt)
                merge_anchor_format(range_fmt, original)
            if end > start:
                cursor = QTextCursor(found.document())
                cursor.setPosition(start)
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(range_fmt)

        self._replace_tokens_in_order(document, entries, replace)

    def _replace_footnote_refs(self, document: QTextDocument) -> None:
        """把脚注引用占位符替换为上标编号链接（``[n](#fn-id)``）。
        每个脚注的首次引用处同时附加 ``fnref-id`` 锚点，供定义区编号回跳。
        同一脚注可被引用多次，所以每个 id 用自己的搜索游标循环（id 数量少，
        """
        if not self._footnote_defs:
            return
        anchored: set[str] = set()
        for index, (fid, _body) in enumerate(self._footnote_defs, start=1):
            token = f"{_FOOTNOTE_REF_PREFIX}{fid}{_CODE_TOKEN_SUFFIX}"
            search = QTextCursor(document)
            while True:
                found = document.find(token, search)
                if found.isNull():
                    break
                fmt = QTextCharFormat()
                fmt.setAnchor(True)
                fmt.setAnchorHref(f"#fn-{fid}")
                if fid not in anchored:
                    fmt.setAnchorNames([f"fnref-{fid}"])
                    anchored.add(fid)
                fmt.setVerticalAlignment(
                    QTextCharFormat.VerticalAlignment.AlignSuperScript
                )
                fmt.setForeground(self._link_color)
                found.removeSelectedText()
                found.insertText(f"[{index}]", fmt)
                search.setPosition(found.position())

    def _apply_footnote_defs(self, document: QTextDocument) -> None:
        """给文末脚注定义块设置锚点（``fn-id``）并着色编号。"""
        if not self._footnote_defs:
            return
        entries = [
            (f"{_FOOTNOTE_DEF_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", (index, fid))
            for index, (fid, _body) in enumerate(self._footnote_defs, start=1)
        ]

        def replace(found: QTextCursor, data) -> None:
            index, fid = data
            found.removeSelectedText()
            if found.block().text().startswith(" "):
                found.deleteChar()
            block = found.block()
            block_format = block.blockFormat()
            block_format.setTopMargin(2)
            block_format.setBottomMargin(2)
            found.setBlockFormat(block_format)

            number = document.find(f"[{index}]", block.position())
            if (
                not number.isNull()
                and number.block() == block
                and number.selectionEnd() <= block.position() + block.length()
            ):
                number_fmt = QTextCharFormat()
                number_fmt.setAnchor(True)
                number_fmt.setAnchorHref(f"#fnref-{fid}")
                number_fmt.setForeground(self._link_color)
                number.mergeCharFormat(number_fmt)

            anchor_fmt = QTextCharFormat()
            anchor_fmt.setAnchor(True)
            anchor_fmt.setAnchorNames([f"fn-{fid}"])
            cursor = QTextCursor(document)
            cursor.setPosition(block.position())
            cursor.setPosition(
                _clamp_pos(document, block.position() + max(block.length() - 1, 0)),
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.mergeCharFormat(anchor_fmt)

        self._replace_tokens_in_order(document, entries, replace)

    @staticmethod
    def _slugify(text: str, used: dict) -> str:
        """标题文本 → GitHub 风格锚点（保留 CJK，去标点，重名追加序号）。"""
        slug = re.sub(r"elamath[0-9a-f]+z\d+q", "", text).strip().lower()
        slug = re.sub(r"[^\w\u4e00-\u9fff -]+", "", slug)
        slug = re.sub(r"[\s-]+", "-", slug).strip("-")
        if not slug:
            slug = "section"
        base = slug
        index = 1
        while slug in used:
            slug = f"{base}-{index}"
            index += 1
        used[slug] = True
        return slug

    def _apply_heading_anchors(self, document: QTextDocument) -> None:
        """给标题块附加锚点名称，并记录标题列表（供目录生成）。"""
        self._headings = []
        used: dict = {}
        block = document.begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level > 0:
                text = re.sub(r"elamath[0-9a-f]+z\d+q", "", block.text()).strip()
                slug = self._slugify(text, used)
                fmt = QTextCharFormat()
                fmt.setAnchor(True)
                fmt.setAnchorNames([slug])
                cursor = QTextCursor(document)
                cursor.setPosition(block.position())
                cursor.setPosition(
                    _clamp_pos(document, block.position() + max(block.length() - 1, 0)),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.mergeCharFormat(fmt)
                self._headings.append((level, text, slug))
            block = block.next()

    def _replace_toc_token(self, document: QTextDocument) -> None:
        """把 ``[toc]`` 占位符替换为标题链接列表（多个 ``[toc]`` 逐个处理）。"""
        while True:
            found = document.find(_TOC_TOKEN)
            if found.isNull():
                return
            cursor = QTextCursor(found)
            cursor.removeSelectedText()
            if not self._headings:
                continue
            for index, (level, text, slug) in enumerate(self._headings):
                if index > 0:
                    cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
                indent = "  " * max(level - 1, 0)
                if indent:
                    cursor.insertText(indent)
                cursor.insertText("• ")
                link_fmt = QTextCharFormat()
                link_fmt.setAnchor(True)
                link_fmt.setAnchorHref(f"#{slug}")
                link_fmt.setForeground(self._link_color)
                cursor.insertText(text or slug, link_fmt)

    def _apply_folds(self, document: QTextDocument) -> None:
        """把折叠占位符替换为可点击标签，并按展开状态隐藏/展示内容。
        调用点必须在 ``setMarkdown`` 的编辑块**之外**（``_render_into`` 里
        单独成段）：折叠区间可能含表格单元块，帧树未物化时删它们会改坏
        """
        if not self._fold_blocks:
            return
        start_search = QTextCursor(document)
        end_search = QTextCursor(document)
        for index, fold in enumerate(self._fold_blocks):
            start_token = f"{_FOLD_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}"
            end_token = f"{_FOLD_END_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}"
            found = document.find(start_token, start_search)
            if found.isNull():
                continue
            expanded = index in self._expanded_folds
            label = fold.get("label") or ""
            # U+25B8/25BE（▸/▾）不在雅黑 cmap → Win7 逐字形 fallback 毒化；
            # +/- 与任务标记同口径，选 CJK 字体覆盖得到的字形（bug #20）。
            marker = "−" if expanded else "+"
            fmt = QTextCharFormat()
            fmt.setForeground(self._muted_color)
            fmt.setFontItalic(True)
            fmt.setAnchor(True)
            fmt.setAnchorHref(f"#elafold-{index}")
            found.removeSelectedText()
            start = found.position()
            found.insertText(f"{marker} ", fmt)
            if label and "<" not in label:
                found.insertFragment(QTextDocumentFragment.fromMarkdown(label))
            elif label:
                found.insertText(label, fmt)
            end = found.position()
            block = found.block()
            iterator = block.begin()
            ranges: list[tuple[int, int]] = []
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    position = fragment.position()
                    stop = position + fragment.length()
                    if (
                        position >= start
                        and stop <= end
                        and not fragment.charFormat().isAnchor()
                    ):
                        ranges.append((position, stop))
                iterator += 1
            edit = QTextCursor(document)
            for position, stop in ranges:
                edit.setPosition(position)
                edit.setPosition(stop, QTextCursor.MoveMode.KeepAnchor)
                edit.mergeCharFormat(fmt)
            start_search.setPosition(found.position())
            label_block = document.findBlock(max(found.position() - 1, 0))
            if not label_block.isValid():
                continue
            end_found = document.find(end_token, end_search)
            if not end_found.isNull():
                end_search.setPosition(end_found.position())
            end_number = (
                end_found.block().blockNumber()
                if not end_found.isNull()
                else document.blockCount() - 1
            )
            if expanded:
                block = label_block.next()
                while block.isValid() and block.blockNumber() < end_number:
                    self._style_fold_block(document, block)
                    block = block.next()
                if not end_found.isNull():
                    self._delete_blocks(document, end_number, end_number)
            else:
                self._delete_blocks(document, label_block.blockNumber() + 1, end_number)

    @staticmethod
    def _delete_blocks(document: QTextDocument, first: int, last: int) -> None:
        """按块号区间删除块（从后往前，避免块号失效）。"""
        for number in range(last, first - 1, -1):
            block = document.findBlockByNumber(number)
            if not block.isValid():
                continue
            cursor = QTextCursor(document)
            cursor.setPosition(block.position())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()

    def _style_fold_block(self, document: QTextDocument, block) -> None:
        """展开的折叠内容：左缩进 + 次级文字色。"""
        block_format = block.blockFormat()
        block_format.setLeftMargin(block_format.leftMargin() + 12)
        cursor = QTextCursor(document)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(block_format)
        # 先收集再改写：mergeCharFormat 会让片段迭代器失效。
        spans = []
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and (
                fragment.charFormat().foreground().style() == Qt.BrushStyle.NoBrush
            ):
                spans.append((fragment.position(), fragment.length()))
            iterator += 1
        if not spans:
            return
        fmt = QTextCharFormat()
        fmt.setForeground(self._muted_color)
        edit = QTextCursor(document)
        for position, length in spans:
            edit.setPosition(position)
            edit.setPosition(
                _clamp_pos(document, position + length),
                QTextCursor.MoveMode.KeepAnchor,
            )
            edit.mergeCharFormat(fmt)

    def _style_callouts(self, document: QTextDocument) -> None:
        """Callout：标记行替换为标签，整段引用块加中性淡底。"""
        if not self._callout_types:
            return
        background = QBrush(self._callout_bg)
        colors = calloutColors(
            ElaThemeType.ThemeMode.Dark
            if self._is_dark_theme
            else ElaThemeType.ThemeMode.Light,
            self._callout_bg,
        )
        entries = [
            (f"{_CALLOUT_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", kind)
            for index, kind in enumerate(self._callout_types)
        ]

        def replace(found: QTextCursor, kind: str) -> None:
            label = _CALLOUT_LABELS.get(kind, kind)
            if kind == "warning":
                color = QColor(colors["warning"])
            elif kind == "caution":
                color = QColor(colors["caution"])
            else:
                color = self._link_color
            label_fmt = QTextCharFormat()
            label_fmt.setFontWeight(QFont.Weight.DemiBold)
            label_fmt.setForeground(color)

            found.removeSelectedText()
            first_number = found.blockNumber()
            on_empty_line = found.atBlockEnd()
            found.insertText(label, label_fmt)
            if not on_empty_line:
                found.insertBlock(QTextBlockFormat(), QTextCharFormat())

            block = document.findBlockByNumber(first_number)
            while block.isValid():
                block_format = block.blockFormat()
                if block_format.leftMargin() < _QUOTE_LEFT_MARGIN:
                    break
                block_format.setBackground(background)
                # Callout 语义色左竖线，由自绘统一绘制
                block_format.setProperty(_CALLOUT_RAIL_PROPERTY, color.name())
                cursor = QTextCursor(document)
                cursor.setPosition(block.position())
                cursor.setBlockFormat(block_format)
                block = block.next()

        self._replace_tokens_in_order(document, entries, replace)

    def setReasoningTag(self, tag: Optional[str]) -> None:
        """推理块标签名（默认 ``"think"``，即 `` ... `` 语法）；``None`` 关闭折叠，
        标签内容按原文渲染。
        """
        self._reasoning_tag = tag
        if self._source:
            self._render()

    def reasoningTag(self) -> Optional[str]:
        """获取当前推理块标签名。"""
        return self._reasoning_tag

    def setReasoningLabel(self, label: str) -> None:
        """设置推理块折叠标签文案（默认"思考过程"）。"""
        self._reasoning_label = label or _DEFAULT_REASONING_LABEL
        if self._source:
            self._render()

    def reasoningLabel(self) -> str:
        """获取推理块折叠标签文案。"""
        return self._reasoning_label

    def setFrontMatterMode(self, mode: str) -> None:
        """首行 frontmatter 处理方式：``"fence"``（默认，保留为 YAML 代码块）
        或 ``"strip"``（交给 Qt 原生剥离）。
        """
        value = str(mode or "").strip().lower()
        if value not in ("fence", "strip"):
            raise ValueError("frontMatterMode 只支持 'fence' / 'strip'")
        if value == self._front_matter_mode:
            return
        self._front_matter_mode = value
        if self._source:
            self._render()

    def frontMatterMode(self) -> str:
        """获取首行 frontmatter 处理方式。"""
        return self._front_matter_mode
