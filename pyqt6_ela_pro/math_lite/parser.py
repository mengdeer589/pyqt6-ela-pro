"""math_lite.parser：ASCII 数学语法解析与文本辅助。"""

from __future__ import annotations

import math
import re
from typing import Optional

from PyQt6.QtGui import QColor

from .preprocess import _column_align_from_spec, _read_balanced
from .tables import (
    _ACCENTS,
    _ALIGN_ENVS,
    _ALPHABETS,
    _BIG_DELIM_SCALES,
    _BIG_OPS,
    _CANCEL_KINDS,
    _COLOR_NAMES,
    _DELIMS,
    _FUNCTIONS,
    _LIMIT_OPERATORS,
    _MATRIX_ENVS,
    _NOT_COMBOS,
    _SPACES,
    _SYMBOLS,
    _TEXT_ESCAPES,
    _TEXT_SPACE_RE,
    _TEXT_STYLES,
)


class _ParseError(Exception):
    """公式语法不受支持。"""


class _Node:
    """AST 节点基类。"""


class _Sym(_Node):
    def __init__(self, text: str, italic: bool = True):
        self.text = text
        self.italic = italic


class _Text(_Node):
    def __init__(self, text: str, italic: bool = False, bold: bool = False):
        self.text = text
        self.italic = italic
        self.bold = bold


class _Row(_Node):
    def __init__(self, items: list):
        self.items = items


class _Frac(_Node):
    def __init__(self, num: _Node, den: _Node):
        self.num = num
        self.den = den


class _Sqrt(_Node):
    def __init__(self, body: _Node, index: Optional[_Node] = None):
        self.body = body
        self.index = index


class _Script(_Node):
    def __init__(self, base: _Node, sup: Optional[_Node], sub: Optional[_Node]):
        self.base = base
        self.sup = sup
        self.sub = sub


class _BigOp(_Node):
    def __init__(self, text: str, stack: bool = True, scale: float = 1.35):
        self.text = text
        self.stack = stack
        self.scale = scale


class _Delim(_Node):
    def __init__(self, left: str, body: _Node, right: str):
        self.left = left
        self.body = body
        self.right = right


class _Matrix(_Node):
    def __init__(
        self,
        rows: list,
        kind: str,
        column_align: Optional[list] = None,
        hlines: Optional[set] = None,
    ):
        self.rows = rows
        self.kind = kind
        self.column_align = column_align
        self.hlines = hlines or set()


class _Binom(_Node):
    def __init__(self, num: _Node, den: _Node):
        self.num = num
        self.den = den


class _Accent(_Node):
    def __init__(self, kind: str, body: _Node):
        self.kind = kind
        self.body = body


class _Space(_Node):
    def __init__(self, em: float):
        self.em = em


class _Styled(_Node):
    def __init__(
        self,
        body: _Node,
        italic: bool,
        bold: bool,
        family: Optional[str] = None,
    ):
        self.body = body
        self.italic = italic
        self.bold = bold
        self.family = family


class _Tag(_Node):
    """``\\tag`` / ``\\tag*``：公式编号（``star`` 为真时不加括号）。"""

    def __init__(self, text: str, star: bool = False):
        self.text = text
        self.star = star


class _Boxed(_Node):
    """``\\boxed``：带边框的公式。"""

    def __init__(self, body: _Node):
        self.body = body


class _Framed(_Node):
    """``\\fbox`` / ``\\colorbox``：边框或底色。"""

    def __init__(self, kind: str, body: _Node, color: str = ""):
        self.kind = kind
        self.body = body
        self.color = color


class _XArrow(_Node):
    """``\\xrightarrow`` / ``\\xleftarrow``：可伸缩箭头 + 上下标签。"""

    def __init__(
        self,
        direction: str,
        above: Optional[_Node],
        below: Optional[_Node],
    ):
        self.direction = direction
        self.above = above
        self.below = below


class _Brace(_Node):
    """``\\overbrace`` / ``\\underbrace``：水平花括号。"""

    def __init__(self, over: bool, body: _Node):
        self.over = over
        self.body = body


class _Stacked(_Node):
    """``\\overset`` / ``\\underset`` / ``\\stackrel``：上下叠放。"""

    def __init__(
        self,
        top: Optional[_Node],
        base: _Node,
        bottom: Optional[_Node],
    ):
        self.top = top
        self.base = base
        self.bottom = bottom


class _ScaledDelim(_Node):
    """``\\big`` 系列：按比例放大的定界符。"""

    def __init__(self, text: str, scale: float, role: str = ""):
        self.text = text
        self.scale = scale
        self.role = role


class _MiddleDelim(_Node):
    """``\\middle``：在 ``\\left...\\right`` 内按行高自动缩放。"""

    def __init__(self, text: str):
        self.text = text


class _Phantom(_Node):
    """``\\phantom`` 系列：占位但不绘制。"""

    def __init__(self, body: _Node, kind: str):
        self.body = body
        self.kind = kind


class _HSpace(_Node):
    """``\\hspace{2em}`` / ``\\kern``：物理维度间距（构建期按字号换算）。"""

    def __init__(self, raw: str):
        self.raw = raw


class _Color(_Node):
    """显式着色（``\\textcolor`` 或 ``\\color`` 作用域）。"""

    def __init__(self, body: _Node, color: str):
        self.body = body
        self.color = color


class _ColorMark(_Node):
    """``\\color{...}`` 开关：解析后转为后续内容的 ``_Color`` 包裹。"""

    def __init__(self, color: str):
        self.color = color


class _Cancel(_Node):
    """``\\cancel`` / ``\\bcancel`` / ``\\xcancel`` / ``\\sout``：删除线。"""

    def __init__(self, kind: str, body: _Node):
        self.kind = kind
        self.body = body


class _Pmod(_Node):
    """``\\pmod{n}``：``(mod n)``。"""

    def __init__(self, body: _Node):
        self.body = body


def _apply_color_marks(items: list) -> list:
    """把 ``\\color`` 开关转换为对后续原子的 ``_Color`` 包裹（组内作用域）。"""
    result: list = []
    current: Optional[str] = None
    for item in items:
        if isinstance(item, _ColorMark):
            current = item.color
            continue
        result.append(_Color(item, current) if current else item)
    return result


def _unescape_text(raw: str) -> str:
    """``\\text{}`` 内的转义序列还原为字面字符。"""
    return re.sub(
        r"\\([%&#_${}\\ ])",
        lambda match: _TEXT_ESCAPES.get(match.group(1), match.group(0)),
        raw,
    )


def _normalize_text(raw: str) -> str:
    """文本模式内容：还原转义并折叠连续空白。"""
    return _TEXT_SPACE_RE.sub(" ", _unescape_text(raw))


def _parse_color(raw: str) -> Optional[QColor]:
    """颜色名 / ``#RRGGBB`` → ``QColor``（无法解析返回 ``None``）。"""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("#"):
        color = QColor(text)
        return color if color.isValid() else None
    hex_value = _COLOR_NAMES.get(text.lower())
    if hex_value is None:
        color = QColor(text)
        return color if color.isValid() else None
    return QColor(hex_value)


def _dimension_em(raw: str, size: float) -> float:
    """物理维度（``2em`` / ``3pt`` / ``1cm``）→ em 值（无法解析返回 0）。

    解析必须线性：带尾锚的多段可回溯正则在长输入上是 O(n²)，会按住 GUI 线程。
    """
    text = (raw or "").strip()
    if not text:
        return 0.0
    # 单位段 = 结尾连续的 ASCII 字母（允许内部空格）
    i = len(text)
    while i > 0 and text[i - 1].isalpha():
        i -= 1
    unit = text[i:].strip().lower()
    number = text[:i].strip()
    if not number:
        return 0.0
    # 贪心吃掉 ``[+-]? digits [. digits]``（允许 ``1.2.3`` 这种畸形输入，
    # 由 float() 抛 ValueError —— 调用方已兜）
    j = 0
    n = len(number)
    if n and number[j] in "+-":
        j += 1
    seen_digit = False
    while j < n and number[j].isdigit():
        j += 1
        seen_digit = True
    if j < n and number[j] == ".":
        j += 1
        while j < n and number[j].isdigit():
            j += 1
            seen_digit = True
    if not seen_digit or j != n:
        return 0.0
    value = float(number)
    if not math.isfinite(value):
        # ``float("1"×400)`` 是 inf 而非异常 —— 由输出层的 isfinite 兜底拒收，
        # 这里先归零，语义上「解析不出可用尺寸」更贴切。
        return 0.0
    unit = unit or "em"
    if unit == "em":
        return value
    if unit == "ex":
        return value * 0.5
    if unit == "mu":
        return value / 18.0
    if unit in ("pt", "px"):
        # 96dpi 下 1pt = 4/3px；em = px / (size * 4/3)
        px = value * (4.0 / 3.0) if unit == "pt" else value
        return px / max(size * 4.0 / 3.0, 1.0)
    if unit == "cm":
        return value * 28.3465 / max(size, 1.0)
    if unit == "mm":
        return value * 2.83465 / max(size, 1.0)
    if unit == "in":
        return value * 72.0 / max(size, 1.0)
    return 0.0


class _Parser:
    def __init__(self, source: str, tolerant: bool = False):
        self.s = source
        self.i = 0
        self.tolerant = tolerant

    def _peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def _startswith(self, token: str) -> bool:
        return self.s.startswith(token, self.i)

    def _match_command_word(self, name: str) -> bool:
        """``name``（含反斜杠）匹配且其后不再跟字母。"""
        if not self.s.startswith(name, self.i):
            return False
        end = self.i + len(name)
        return end >= len(self.s) or not self.s[end].isalpha()

    def _skip_spaces(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t\n":
            self.i += 1

    def parse(self) -> _Node:
        rows = [[self._row(stop=None, top_level=True)]]
        while True:
            self._skip_spaces()
            if self._startswith("\\\\"):
                self.i += 2
                rows.append([self._row(stop=None, top_level=True)])
                continue
            break
        self._skip_spaces()
        if self.i < len(self.s):
            raise _ParseError(f"unexpected {self.s[self.i]!r} at {self.i}")
        if len(rows) == 1:
            return rows[0][0]
        return _Matrix(rows, "gather")

    def _row(self, stop, matrix_stops: bool = False, top_level: bool = False) -> _Node:
        items = []
        while self.i < len(self.s):
            if stop == "}" and self.s[self.i] == "}":
                break
            if stop == "right" and self._startswith(r"\right"):
                break
            if top_level and self._startswith("\\\\"):
                break
            if matrix_stops and (
                self._peek() == "&"
                or self._startswith(r"\\")
                or self._startswith(r"\end")
            ):
                break
            atom = self._atom_with_scripts()
            if atom is None:
                break
            items.append(atom)
        return _Row(_apply_color_marks(items))

    def _group(self) -> _Node:
        if self._peek() != "{":
            raise _ParseError("expected {")
        self.i += 1
        row = self._row(stop="}")
        if self._peek() != "}":
            raise _ParseError("expected }")
        self.i += 1
        return row

    def _raw_group(self) -> str:
        # TeX 里控制词后的空白是词尾分隔符（``\text {x}`` 与 ``\text{x}``
        # 等价），而模型输出 / MinerU 转写常带这个空格。命令参数都走本函数，
        # 统一在这里跳过一次。
        self._skip_spaces()
        if self._peek() != "{":
            raise _ParseError("expected {")
        self.i += 1
        depth = 1
        start = self.i
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    result = self.s[start : self.i]
                    self.i += 1
                    return result
            self.i += 1
        raise _ParseError("unclosed {")

    def _atom_with_scripts(self):
        self._skip_spaces()
        base = self._atom()
        if base is not None:
            # \limits / \nolimits 位于大算子与上下标之间
            while True:
                self._skip_spaces()
                if self._match_command_word(r"\limits"):
                    self.i += len(r"\limits")
                    if isinstance(base, _BigOp):
                        base.stack = True
                    continue
                if self._match_command_word(r"\nolimits"):
                    self.i += len(r"\nolimits")
                    if isinstance(base, _BigOp):
                        base.stack = False
                    continue
                break
        sup = sub = None
        if base is None and self._peek() in ("^", "_"):
            base = _Sym("", italic=False)
        if base is None:
            return None
        while True:
            self._skip_spaces()
            c = self._peek()
            if c not in ("^", "_"):
                break
            self.i += 1
            arg = self._script_arg()
            if c == "^":
                sup = arg
            else:
                sub = arg
        if sup is not None or sub is not None:
            return _Script(base, sup, sub)
        return base

    def _script_arg(self) -> _Node:
        self._skip_spaces()
        if self._peek() == "{":
            return self._group()
        if self._peek() == "\\":
            return self._command()
        return self._atom() or _Sym("", italic=False)

    def _atom(self):
        c = self._peek()
        if not c:
            return None
        if c in ("^", "_"):
            # 上下标标记交给 _atom_with_scripts 处理（不消费）
            return None
        if c == "{":
            return self._group()
        if c == "\\":
            return self._command()
        self.i += 1
        if c.isalpha():
            return _Sym(c, italic=True)
        # ASCII 字形 → 数学字形（连字符减号、撇号导数、星号、波浪空格）
        if c == "-":
            return _Text("\u2212", italic=False)
        if c == "'":
            return _Text("\u2032", italic=False)
        if c == "*":
            return _Text("\u2217", italic=False)
        if c == "~":
            return _Space(0.5)
        return _Text(c, italic=False)

    def _command(self):
        assert self._peek() == "\\"
        start = self.i
        self.i += 1
        if self._peek().isalpha():
            while self.i < len(self.s) and self.s[self.i].isalpha():
                self.i += 1
            name = self.s[start : self.i]
        else:
            name = self.s[start : self.i + 1]
            self.i += 1

        if name in (r"\frac", r"\dfrac", r"\tfrac", r"\cfrac"):
            num = self._script_arg()
            den = self._script_arg()
            return _Frac(num, den)
        if name == r"\genfrac":
            left = self._raw_group()
            right = self._raw_group()
            if self._peek() == "{":
                self._raw_group()
            if self._peek() == "{":
                self._raw_group()
            num = self._script_arg()
            den = self._script_arg()
            frac = _Frac(num, den)
            if left.strip() or right.strip():
                return _Delim(
                    _DELIMS.get(left.strip(), left.strip()),
                    frac,
                    _DELIMS.get(right.strip(), right.strip()),
                )
            return frac
        if name == r"\sqrt":
            index = None
            self._skip_spaces()
            if self._peek() == "[":
                end = self.s.find("]", self.i)
                if end == -1:
                    raise _ParseError("unclosed [")
                saved = self.s[self.i + 1 : end]
                self.i = end + 1
                index = _Parser(saved, tolerant=self.tolerant).parse()
            body = self._script_arg()
            return _Sqrt(body, index)
        if name in _ACCENTS:
            return _Accent(_ACCENTS[name], self._script_arg())
        if name in (r"\binom", r"\dbinom", r"\tbinom"):
            return _Binom(self._script_arg(), self._script_arg())
        if name in _ALPHABETS:
            raw = self._raw_group()
            table = _ALPHABETS[name]
            return _Text("".join(table.get(ch, ch) for ch in raw), italic=False)
        if name == r"\begin":
            env = self._raw_group().strip()
            self._skip_optional_bracket()
            kind = "aligned" if env in _ALIGN_ENVS else env
            if env == "array":
                spec = self._raw_group()
                return self._parse_matrix(
                    env, kind="array", column_align=_column_align_from_spec(spec)
                )
            if env in ("alignat", "alignat*"):
                self._skip_spaces()
                if self._peek() == "{":
                    self._raw_group()
            if env in _MATRIX_ENVS:
                return self._parse_matrix(env, kind=kind)
            if self.tolerant:
                return self._parse_matrix(env, kind=env)
            raise _ParseError(f"unsupported environment {env!r}")
        if name == r"\substack":
            return self._parse_substack()
        if name in _SPACES:
            return _Space(_SPACES[name])
        if name in _BIG_OPS:
            char, stack, scale = _BIG_OPS[name]
            return _BigOp(char, stack, scale)
        if name[1:] in _LIMIT_OPERATORS:
            return _BigOp(name[1:], True, 1.0)
        if name == r"\operatorname":
            star = False
            self._skip_spaces()
            if self._peek() == "*":
                star = True
                self.i += 1
            raw = self._raw_group()
            if star:
                return _BigOp(_normalize_text(raw), True, 1.0)
            return _Text(_normalize_text(raw), italic=False)
        if name == r"\tag":
            star = False
            self._skip_spaces()
            if self._peek() == "*":
                star = True
                self.i += 1
            return _Tag(_normalize_text(self._raw_group()).strip(), star)
        if name == r"\boxed":
            return _Boxed(self._script_arg())
        if name in (r"\underline", r"\underbar"):
            return _Accent("underline", self._script_arg())
        if name in (r"\overbrace", r"\underbrace"):
            return _Brace(name == r"\overbrace", self._script_arg())
        if name in (r"\xrightarrow", r"\xleftarrow"):
            direction = "right" if name == r"\xrightarrow" else "left"
            below = None
            self._skip_spaces()
            if self._peek() == "[":
                end = self.s.find("]", self.i)
                if end != -1:
                    label = self.s[self.i + 1 : end]
                    self.i = end + 1
                    if label.strip():
                        below = _Parser(label, tolerant=True).parse()
            above = self._script_arg()
            return _XArrow(direction, above, below)
        if name in (r"\overset", r"\underset", r"\stackrel"):
            first = self._script_arg()
            second = self._script_arg()
            if name == r"\underset":
                return _Stacked(None, second, first)
            return _Stacked(first, second, None)
        if name == r"\pmod":
            return _Pmod(self._script_arg())
        if name == r"\mod":
            return _Text("mod", italic=False)
        if name in _CANCEL_KINDS:
            return _Cancel(_CANCEL_KINDS[name], self._script_arg())
        if name in (r"\phantom", r"\hphantom", r"\vphantom"):
            kind = {
                r"\phantom": "full",
                r"\hphantom": "h",
                r"\vphantom": "v",
            }[name]
            return _Phantom(self._script_arg(), kind)
        if name == r"\mathstrut":
            return _Phantom(_Text("|", italic=False), "v")
        if name in (r"\hspace", r"\kern", r"\mkern", r"\mskip"):
            if self._peek() == "*":
                self.i += 1
            self._skip_spaces()
            if self._peek() == "{":
                raw, self.i = _read_balanced(self.s, self.i)
            else:
                match = re.match(r"[+-]?[\d.]+[a-zA-Z]*", self.s[self.i :])
                raw = match.group(0) if match else ""
                self.i += len(raw)
            return _HSpace(raw)
        if name == r"\textcolor":
            color = self._raw_group()
            return _Color(self._script_arg(), color)
        if name == r"\color":
            return _ColorMark(self._raw_group())
        if name in (r"\colorbox", r"\fbox"):
            if name == r"\fbox":
                return _Framed("fbox", self._script_arg())
            color = self._raw_group()
            return _Framed("colorbox", self._script_arg(), color)
        if name == r"\not":
            return self._parse_not()
        if name == r"\middle":
            return _MiddleDelim(self._read_delim())
        if name in _BIG_DELIM_SCALES:
            return _ScaledDelim(self._read_delim(), _BIG_DELIM_SCALES[name])
        if name in (r"\bigl", r"\bigr", r"\bigm", r"\big"):
            return _ScaledDelim(
                self._read_delim(), _BIG_DELIM_SCALES[r"\big"], name[1:][-1]
            )
        if name in (r"\Bigl", r"\Bigr", r"\Bigm", r"\Big"):
            return _ScaledDelim(
                self._read_delim(), _BIG_DELIM_SCALES[r"\Big"], name[1:][-1]
            )
        if name in (r"\biggl", r"\biggr", r"\biggm", r"\bigg"):
            return _ScaledDelim(
                self._read_delim(), _BIG_DELIM_SCALES[r"\bigg"], name[1:][-1]
            )
        if name in (r"\Biggl", r"\Biggr", r"\Biggm", r"\Bigg"):
            return _ScaledDelim(
                self._read_delim(), _BIG_DELIM_SCALES[r"\Bigg"], name[1:][-1]
            )
        if name in (
            r"\displaystyle",
            r"\textstyle",
            r"\scriptstyle",
            r"\scriptscriptstyle",
        ):
            return _Space(0.0)
        if name in _TEXT_STYLES:
            raw = self._raw_group()
            italic, bold, family = _TEXT_STYLES[name]
            return _Styled(
                _Text(_normalize_text(raw), italic=False),
                italic=italic,
                bold=bold,
                family=family,
            )
        if name == r"\left":
            left = self._read_delim()
            body = self._row(stop="right")
            if not self._startswith(r"\right"):
                raise _ParseError("missing \\right")
            self.i += len(r"\right")
            right = self._read_delim()
            return _Delim(left, body, right)
        if name == r"\right":
            raise _ParseError("unexpected \\right")
        if name[1:] in _FUNCTIONS:
            return _Text(name[1:], italic=False)
        if name in _SYMBOLS:
            return _Text(_SYMBOLS[name], italic=False)
        if name.startswith("\\") and len(name) == 2 and name[1] in "\\{}":
            return _Text(name[1], italic=False)
        if self.tolerant:
            return _Text(name, italic=False)
        raise _ParseError(f"unsupported command {name!r}")

    def _parse_not(self) -> _Node:
        """``\\not``：优先查常见组合表，否则叠加斜线。"""
        atom = self._atom_with_scripts()
        if atom is None:
            return _Text("̸", italic=False)
        text = _atom_text(atom)
        negated = _NOT_COMBOS.get(text)
        if negated is not None:
            return _Text(negated, italic=False)
        return _Cancel("cancel", atom)

    def _skip_optional_bracket(self) -> None:
        """跳过 ``\\begin{aligned}[t]`` 的位置参数。"""
        self._skip_spaces()
        if self._peek() == "[":
            end = self.s.find("]", self.i)
            if end != -1:
                self.i = end + 1

    def _parse_matrix(
        self,
        env: str,
        kind: Optional[str] = None,
        column_align: Optional[list] = None,
    ) -> _Node:
        """解析 ``\\begin{env} ... \\end{env}``（``&`` 分列、``\\\\`` 分行）。"""
        rows: list[list] = []
        current: list = []
        hlines: set = set()
        while True:
            self._skip_spaces()
            if self._match_command_word(r"\hline"):
                self.i += len(r"\hline")
                hlines.add(len(rows))
                continue
            if self._match_command_word(r"\cline"):
                self.i += len(r"\cline")
                self._skip_spaces()
                if self._peek() == "{":
                    _, self.i = _read_balanced(self.s, self.i)
                continue
            current.append(self._row(stop=None, matrix_stops=True))
            self._skip_spaces()
            if self._startswith(r"\\"):
                self.i += 2
                rows.append(current)
                current = []
                continue
            if self._peek() == "&":
                self.i += 1
                continue
            if self._startswith(r"\end"):
                self.i += len(r"\end")
                self._skip_spaces()
                if self._raw_group().strip() != env:
                    raise _ParseError("mismatched \\end")
                rows.append(current)
                break
            raise _ParseError(f"unexpected token in {env!r}")
        return _Matrix(rows, kind or env, column_align, hlines)

    def _parse_substack(self) -> _Node:
        """解析 ``\\substack{a \\\\ b}``（多行下标）。"""
        self._skip_spaces()
        if self._peek() != "{":
            raise _ParseError("expected { after \\substack")
        self.i += 1
        rows: list[list] = []
        current: list = []
        while True:
            current.append(self._row(stop="}", matrix_stops=True))
            self._skip_spaces()
            if self._startswith(r"\\"):
                self.i += 2
                rows.append(current)
                current = []
                continue
            if self._peek() == "}":
                self.i += 1
                rows.append(current)
                break
            raise _ParseError("unexpected token in \\substack")
        return _Matrix(rows, "substack")

    def _read_delim(self) -> str:
        self._skip_spaces()
        if self._peek() == "\\":
            start = self.i
            self.i += 1
            if self._peek().isalpha():
                while self.i < len(self.s) and self.s[self.i].isalpha():
                    self.i += 1
            elif self.i < len(self.s):
                self.i += 1
            token = self.s[start : self.i]
        else:
            token = self._peek()
            self.i += 1
        if token not in _DELIMS:
            if self.tolerant:
                return token[1:] if token.startswith("\\") else token
            raise _ParseError(f"unsupported delimiter {token!r}")
        return _DELIMS[token]


def _atom_text(node: _Node) -> str:
    """取原子用于间距判定的文本（脚本 / 算子取基符）。"""
    if isinstance(node, (_Sym, _Text)):
        return node.text
    if isinstance(node, _BigOp):
        return node.text
    if isinstance(node, _Script):
        return _atom_text(node.base)
    if isinstance(node, _Delim):
        return node.left or node.right
    if isinstance(node, _Color):
        return _atom_text(node.body)
    if isinstance(node, _Styled):
        return _atom_text(node.body)
    if isinstance(node, _Stacked):
        return _atom_text(node.base)
    if isinstance(node, _Accent):
        return _atom_text(node.body)
    if isinstance(node, _ScaledDelim):
        return node.text
    if isinstance(node, _MiddleDelim):
        return node.text
    if isinstance(node, _Tag):
        return ""
    return ""
