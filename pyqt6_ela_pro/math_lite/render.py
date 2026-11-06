"""math_lite.render：公式绘制、缓存与行内公式提取。"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen

from .layout import _build
from .parser import _ParseError, _Parser
from .preprocess import (
    _collect_macros,
    _expand_macros,
    _repair_delimiters,
    preprocess_latex,
)
from .tables import _CACHE_CAP, _FAILED, _MATH_ENVS, _MAX_DIM, _MAX_PIXELS, _SS


_CACHE: "OrderedDict[tuple, object]" = OrderedDict()


def clear_cache() -> None:
    """清空公式渲染缓存（主题切换等场景可调用）。"""
    _CACHE.clear()


def set_cache_capacity(capacity: int) -> None:
    """设置公式渲染缓存容量（含失败哨兵；``<= 0`` 时清空并停止缓存）。"""
    global _CACHE_CAP
    _CACHE_CAP = max(0, int(capacity))
    while len(_CACHE) > _CACHE_CAP:
        _CACHE.popitem(last=False)


def _render(
    latex: str, color: QColor, pt: float, display: bool, report: Optional[dict] = None
) -> Optional[QImage]:
    """渲染实现：严格解析失败后进入容错解析（未知命令字面显示）。

    容错解析仍因结构性错误失败时，尝试自动配平 ``\\left`` / ``\\right``
    后重试（``report["repaired"]`` 标记）。
    """
    try:
        source = preprocess_latex(latex)
    except Exception:
        return None
    degraded = False
    repaired = False
    node = None
    try:
        node = _Parser(source, tolerant=False).parse()
    except _ParseError:
        degraded = True
        # 三层重试的每一层都必须自己写全 ``except Exception``：兄弟处理块不接
        # 兄弟块抛出的异常，容错路径的 RecursionError 会穿出去。对外契约是不支持时
        # 返回 None。
        try:
            node = _Parser(source, tolerant=True).parse()
        except _ParseError:
            source, repaired = _repair_delimiters(source)
            if not repaired:
                return None
            try:
                node = _Parser(source, tolerant=True).parse()
            except Exception:
                return None
        except Exception:
            return None
    except Exception:
        return None
    if node is None:
        return None
    try:
        box = _build(node, pt)
    except _ParseError:
        return None
    except Exception:
        return None
    if box.w <= 0 or box.h <= 0:
        return None
    if not (math.isfinite(box.w) and math.isfinite(box.h)):
        # ``\hspace{1e400}`` 会让 ``box.w`` 变成 inf，下面 ``int(inf)`` 抛
        # OverflowError；这是输出级唯一没有 try 兜底的位置，异常冲出 Qt 回调 =
        # 0xC0000409。
        return None
    pad = max(1.0, pt * 0.2)
    width = int(box.w + 2 * pad) + 1
    height = int(box.h + 2 * pad) + 1
    # 尺寸上限：``box.w`` 只有下界没有上界，``\hspace`` 数值直接进宽度；
    # 超过上限按「不支持」返回 None，走调用方既有的降级路径。
    if width > _MAX_DIM or height > _MAX_DIM:
        return None
    if (width * _SS) * (height * _SS) > _MAX_PIXELS:
        return None
    image = QImage(width * _SS, height * _SS, QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull():
        # 分配失败（尺寸超出平台上限）同样是「渲染不出来」，不能当成功返回
        return None
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.scale(_SS, _SS)
        painter.setPen(QPen(color))
        box.paint(painter, pad, pad + box.a)
    finally:
        painter.end()
    image.setDevicePixelRatio(_SS)
    if report is not None:
        report["degraded"] = degraded
        report["repaired"] = repaired
    return image


def render_formula(
    latex: str,
    color: QColor,
    pt: float,
    display: bool = False,
    report: Optional[dict] = None,
) -> Optional[QImage]:
    """渲染公式为透明底 QImage（2x 超采样）；不支持时返回 ``None``。

    对不支持的 LaTeX 命令采用**容错渲染**（命令字面显示）；结构性错误
    （定界符不闭合、``\\end`` 不匹配等）会先尝试自动修复（``\\left`` /
    ``\\right`` 配平），修复仍失败才返回 ``None``。

    ``latex`` 不含 ``$``；``pt`` 是字号（pt），块级公式的放大由调用方决定；
    ``display`` 只影响缓存键（尺寸由 ``pt`` 决定）。传入 ``report`` 字典会填入
    ``{"degraded": bool, "repaired": bool}``（走过容错路径 / 定界符被自动配平）。
    """
    key = (latex, color.name(), round(float(pt), 2), bool(display))
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        if cached is _FAILED:
            return None
        image, degraded, repaired = cached
        if report is not None:
            report["degraded"] = degraded
            report["repaired"] = repaired
        return image
    local_report: dict = {}
    image = _render(latex, color, float(pt), bool(display), local_report)
    degraded = local_report.get("degraded", False)
    repaired = local_report.get("repaired", False)
    if report is not None:
        report["degraded"] = degraded
        report["repaired"] = repaired
    _CACHE[key] = (image, degraded, repaired) if image else _FAILED
    while len(_CACHE) > _CACHE_CAP:
        _CACHE.popitem(last=False)
    return image


_MATH_SPECIAL_RE = re.compile(r"[`$\\]")


def _scan_inline_math(line: str, maths: list, mark: str) -> str:
    """扫描一行内的行内公式（``$...$`` / ``\\(...\\)`` / 同行 ``$$...$$``）。

    反引号行内代码段原样保留；``\\$`` 视为转义。``$`` 配对遵循 Pandoc
    规则（开 ``$`` 后非空白，闭 ``$`` 前非空白且其后非数字），降低货币
    写法（如「$5 与 $10」）误判率。``mark`` 为实例级占位模板。

    没有 ``$`` / ``\\`` 的行整行原样返回；其余按**特殊字符**跳着扫
    （逐字符 Python 循环实测 117KB 要 12ms，正文里公式极少）。
    """
    if "$" not in line and "\\" not in line:
        return line
    result = []
    i, n = 0, len(line)
    while i < n:
        match = _MATH_SPECIAL_RE.search(line, i)
        if match is None:
            result.append(line[i:])
            break
        start = match.start()
        if start > i:
            result.append(line[i:start])
            i = start
        c = line[i]
        if c == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            ticks = line[i:j]
            end = line.find(ticks, j)
            if end == -1:
                result.append(line[i:])
                return "".join(result)
            result.append(line[i : end + len(ticks)])
            i = end + len(ticks)
            continue
        if c == "\\" and i + 1 < n and line[i + 1] == "$":
            result.append("\\$")
            i += 2
            continue
        if c == "\\" and i + 1 < n and line[i + 1] in "([":
            close = "\\)" if line[i + 1] == "(" else "\\]"
            end = line.find(close, i + 2)
            if end != -1:
                maths.append((line[i + 2 : end], close == "\\]"))
                result.append(mark.format(len(maths) - 1))
                i = end + 2
                continue
            result.append(c)
            i += 1
            continue
        if line.startswith("$$", i):
            end = line.find("$$", i + 2)
            if end != -1:
                maths.append((line[i + 2 : end], True))
                result.append(mark.format(len(maths) - 1))
                i = end + 2
                continue
            result.append("$$")
            i += 2
            continue
        if c == "$" and i + 1 < n and not line[i + 1].isspace():
            matched = False
            j = i + 1
            while True:
                end = line.find("$", j)
                if end == -1:
                    break
                if line[end - 1].isspace() or (end + 1 < n and line[end + 1].isdigit()):
                    j = end + 1
                    continue
                maths.append((line[i + 1 : end], False))
                result.append(mark.format(len(maths) - 1))
                i = end + 1
                matched = True
                break
            if matched:
                continue
            result.append("$")
            i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


def extract_math(text: str, mark: str, macros: Optional[dict] = None):
    """从 Markdown 源文中提取数学公式并替换为占位标记。

    返回 ``(处理后的文本, [(latex, display), ...])``；代码围栏内不提取，多行
    ``$$`` / ``\\[`` / ``\\begin{...}`` 按块级处理。未闭合的块级公式不吞内容。

    :param text: Markdown 源文
    :param mark: 公式占位模板（``{}`` 为序号位）
    :param macros: 可选的文档级宏表
    """
    maths: list = []
    text, macros = _collect_macros(text, macros)
    lines = text.split("\n")
    out = []
    in_fence = False
    fence_mark = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if in_fence:
            out.append(line)
            if stripped.startswith(fence_mark) and not stripped.strip(fence_mark[0]):
                in_fence = False
            i += 1
            continue
        fence_open = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_open:
            in_fence = True
            fence_mark = fence_open.group(1)
            out.append(line)
            i += 1
            continue
        closer = None
        env_m = re.match(r"\\begin\{(\w+\*?)\}\s*$", stripped)
        if stripped in ("$$", "\\["):
            closer = stripped if stripped == "$$" else "\\]"
        elif env_m and env_m.group(1).rstrip("*") in _MATH_ENVS:
            closer = "\\end{" + env_m.group(1) + "}"
        if closer is not None:
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != closer:
                body.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
                latex = "\n".join(body).strip()
                if closer.startswith("\\end"):
                    env_name = env_m.group(1)
                    latex = f"\\begin{{{env_name}}}{latex}\\end{{{env_name}}}"
                if latex:
                    maths.append((latex, True))
                    out.append("")
                    out.append(mark.format(len(maths) - 1))
                    out.append("")
                continue
            out.append(_scan_inline_math(line, maths, mark))
            for b in body:
                out.append(_scan_inline_math(b, maths, mark))
            continue
        out.append(_scan_inline_math(line, maths, mark))
        i += 1
    maths = [(_expand_macros(latex, macros), display) for latex, display in maths]
    return "\n".join(out), maths
