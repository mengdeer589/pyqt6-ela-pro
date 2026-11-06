"""math_lite.preprocess：宏展开、转义与定界符修复。"""

from __future__ import annotations

import re
from typing import Optional

from .tables import (
    _DELIM_CMD_RE,
    _DELIM_MIRRORS,
    _ENV_NOISE_RE,
    _LABEL_RE,
    _MACRO_EXPANSION_LIMIT,
    _MACRO_TRIGGERS,
    _ROW_SPACING_RE,
)


def _skip_ws(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\n":
        index += 1
    return index


def _read_balanced(text: str, start: int) -> tuple[str, int]:
    """从 ``start``（指向 ``{``）读取平衡花括号内容，返回 ``(内容, 结束位置后一位)``；
    未闭合时返回剩余全部文本。
    """
    if start >= len(text) or text[start] != "{":
        return "", start
    depth = 0
    i = start
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    return text[start + 1 :], len(text)


def _parse_define(text: str, pos: int):
    """尝试解析 ``pos`` 处的宏定义。

    支持 ``\\newcommand`` / ``\\renewcommand`` / ``\\def`` /
    ``\\DeclareMathOperator``（含 ``*`` 星号形式；``\\newcommand`` 的
    可选默认参数 ``[default]`` 不支持）。返回
    ``(宏名, 参数个数, 展开体, 结束位置)``，无法识别返回 ``None``。
    """
    for prefix in (r"\newcommand", r"\renewcommand"):
        if text.startswith(prefix, pos):
            i = pos + len(prefix)
            if i < len(text) and text[i] == "*":
                i += 1
            i = _skip_ws(text, i)
            if i < len(text) and text[i] == "{":
                inner, i = _read_balanced(text, i)
                name = inner.strip()
            elif i < len(text) and text[i] == "\\":
                j = i + 1
                while j < len(text) and text[j].isalpha():
                    j += 1
                name = text[i:j]
                i = j
            else:
                return None
            if not name.startswith("\\"):
                return None
            i = _skip_ws(text, i)
            n_args = 0
            if i < len(text) and text[i] == "[":
                end = text.find("]", i)
                if end == -1:
                    return None
                spec = text[i + 1 : end].strip()
                if not spec.isdigit():
                    return None  # 可选默认参数：整体不识别（按字面保留）
                n_args = int(spec)
                i = end + 1
            i = _skip_ws(text, i)
            if i >= len(text) or text[i] != "{":
                return None
            body, end = _read_balanced(text, i)
            return name, n_args, body, end
    if text.startswith(r"\def", pos):
        i = pos + len(r"\def")
        if i < len(text) and text[i] == "*":
            i += 1
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] != "\\":
            return None
        j = i + 1
        while j < len(text) and text[j].isalpha():
            j += 1
        name = text[i:j]
        i = j
        params = ""
        while i < len(text) and text[i] == "#":
            params += text[i : i + 2]
            i += 2
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] != "{":
            return None
        body, end = _read_balanced(text, i)
        return name, len(re.findall(r"#\d", params)), body, end
    if text.startswith(r"\DeclareMathOperator", pos):
        i = pos + len(r"\DeclareMathOperator")
        star = False
        if i < len(text) and text[i] == "*":
            star = True
            i += 1
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] != "{":
            return None
        name, i = _read_balanced(text, i)
        name = name.strip()
        if not name.startswith("\\"):
            return None
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] != "{":
            return None
        label, end = _read_balanced(text, i)
        operator = r"\operatorname*" if star else r"\operatorname"
        return name, 0, f"{operator}{{{label}}}", end
    return None


def _collect_macros(text: str, macros: Optional[dict] = None) -> tuple[str, dict]:
    """收集文本中的宏定义并从正文移除定义段，返回 ``(移除后的文本, {宏名: (参数个数, 展开体)})``；
    传入的 ``macros`` 是文档级收集结果，优先级更低。

    先做触发串检查、再按 ``\\`` 跳着扫（都不命中时整段原样返回）：逐字符
    Python 循环实测 117KB 要 14ms，而正文里宏定义几乎不存在。
    """
    table: dict = dict(macros) if macros else {}
    if not any(trigger in text for trigger in _MACRO_TRIGGERS):
        return text, table
    out: list[str] = []
    total = len(text)
    i = 0
    while True:
        j = text.find("\\", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        i = j
        if (
            text.startswith(r"\newcommand", i)
            or text.startswith(r"\renewcommand", i)
            or text.startswith(r"\DeclareMathOperator", i)
            or (
                text.startswith(r"\def", i)
                and (i + 4 >= total or not text[i + 4].isalpha())
            )
        ):
            parsed = _parse_define(text, i)
            if parsed is not None:
                name, n_args, body, end = parsed
                table[name] = (n_args, body)
                i = end
                continue
        out.append("\\")
        i += 1
    return "".join(out), table


def _read_macro_arg(text: str, index: int) -> tuple[str, int]:
    """读取宏调用的一个参数（花括号组 / 单字符 / 命令）。"""
    index = _skip_ws(text, index)
    if index >= len(text):
        return "", index
    if text[index] == "{":
        return _read_balanced(text, index)
    if text[index] == "\\":
        j = index + 1
        if j < len(text) and text[j].isalpha():
            while j < len(text) and text[j].isalpha():
                j += 1
        elif j < len(text):
            j += 1
        return text[index:j], j
    return text[index], index + 1


def _expand_macros(text: str, macros: Optional[dict] = None) -> str:
    """展开 ``\\newcommand`` / ``\\def`` 定义的宏。

    最多 20 轮防循环，**并对展开后的长度设上限**：``\\def\\a{\\a\\a\\a}\\a`` 这类
    自引用宏每轮把文本放大 3 倍，光限制轮数并不管用 —— 20 轮后是 3^20 ≈ 3.5e9
    字符，GUI 线程会直接卡死（实测 >200s 未返回）。超过上限即停止展开并原样返回。
    """
    text, table = _collect_macros(text, macros)
    if not table:
        return text
    for _ in range(20):
        out: list[str] = []
        size = 0
        i = 0
        changed = False
        overflow = False
        total = len(text)
        while i < total:
            char = text[i]
            if char == "\\" and i + 1 < total and text[i + 1].isalpha():
                j = i + 1
                while j < total and text[j].isalpha():
                    j += 1
                name = text[i:j]
                entry = table.get(name)
                if entry is None:
                    piece = name
                    i = j
                else:
                    n_args, body = entry
                    args: list[str] = []
                    cursor = j
                    for _arg in range(n_args):
                        arg, cursor = _read_macro_arg(text, cursor)
                        args.append(arg)
                    piece = body
                    for idx, arg in enumerate(args, 1):
                        piece = piece.replace(f"#{idx}", arg)
                    i = cursor
                    changed = True
            else:
                piece = char
                i += 1
            out.append(piece)
            # 按**字符数**而非条目数设限：宏体可能很长，只数条目会成倍超标
            size += len(piece)
            if size > _MACRO_EXPANSION_LIMIT:
                overflow = True
                break
        text = "".join(out)
        if not changed or overflow:
            break
    return text


def _strip_env_noise(source: str) -> str:
    """移除行距参数与编号 / 标签等渲染噪音。"""
    source = _ROW_SPACING_RE.sub(r"\\\\", source)
    source = _ENV_NOISE_RE.sub("", source)
    return _LABEL_RE.sub("", source)


def preprocess_latex(source: str, macros: Optional[dict] = None) -> str:
    """公式预处理：宏展开 + 环境噪音清理。"""
    return _strip_env_noise(_expand_macros(source, macros))


def _read_raw_delim(source: str, pos: int) -> tuple[int, str]:
    r"""读取 ``\left`` / ``\right`` 后的原始定界符 token（返回起止下标）。"""
    n = len(source)
    while pos < n and source[pos].isspace():
        pos += 1
    start = pos
    if pos < n and source[pos] == "\\":
        pos += 1
        if pos < n and source[pos].isalpha():
            while pos < n and source[pos].isalpha():
                pos += 1
        elif pos < n:
            pos += 1
    elif pos < n:
        pos += 1
    return start, source[start:pos]


def _repair_delimiters(source: str) -> tuple[str, bool]:
    """自动配平 ``\\left`` / ``\\right``（LLM 生成公式常见缺闭合）。

    - 多余的 ``\\left<定界符>``：在公式末尾补配对镜像（未知定界符用
      ``\\right.`` 不可见闭合）；
    - 孤立的 ``\\right<定界符>``：直接移除。

    :return: (修复后的源码, 是否有改动)
    """
    stack: list[str] = []
    edits: list[tuple[int, int]] = []  # 待删除的孤立 \right 区间
    for match in _DELIM_CMD_RE.finditer(source):
        token_start, token = _read_raw_delim(source, match.end())
        if match.group(1) == "left":
            stack.append(token)
        elif stack:
            stack.pop()
        else:
            edits.append((match.start(), token_start + len(token)))
    if not stack and not edits:
        return source, False

    result = source
    for start, end in reversed(edits):
        result = result[:start] + result[end:]
    if stack:
        suffix = "".join(
            r"\right" + _DELIM_MIRRORS.get(token, ".") for token in reversed(stack)
        )
        result = result.rstrip() + " " + suffix
    return result, True


def _column_align_from_spec(spec: str) -> list:
    """``array`` 列格式 ``{lcr|...}`` → 对齐序列（忽略竖线）。"""
    return [char for char in spec if char in "lcr"]
