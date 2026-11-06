"""terminal_view.ansi：ANSI 模型与解析器。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import NamedTuple, Optional

from PyQt6.QtGui import QColor

from .theme import _BASIC_KEYS, _BRIGHT_KEYS


#: 单个残缺转义序列的保留上限（超出即丢弃，防脏数据撑爆缓冲）
_MAX_PENDING = 64

#: 256 色立方体的 6 档灰度
_CUBE_STEPS = (0, 95, 135, 175, 215, 255)

#: dim 效果向背景混合的比例
_DIM_RATIO = 0.45

_ZERO = 0

#: ``CSI J`` / ``CSI K`` 参数缺省值
_DEFAULT_CSI_PARAM = 0

#: ``CSI C`` / ``CSI D`` 的缺省步进
_DEFAULT_CSI_STEP = 1


class AnsiColor(NamedTuple):
    """一个 ANSI 颜色值（尚未解析成具体颜色）。
    ``kind`` 取 ``"basic"``（0-15）/ ``"indexed"``（0-255）/ ``"rgb"``；``value``
    在前两者是色号，``"rgb"`` 时是 ``0xRRGGBB``。
    """

    kind: str
    value: int


@dataclass(frozen=True)
class TerminalStyle:
    """一段文本的字符样式（不可变，解析器用 ``dataclasses.replace`` 更新）。"""

    fg: Optional[AnsiColor] = None
    bg: Optional[AnsiColor] = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    inverse: bool = False


@dataclass
class TerminalSpan:
    """同一行内一段同样式文本。"""

    text: str
    style: TerminalStyle = TerminalStyle()


class TerminalLine:
    """一行终端输出（由若干 :class:`TerminalSpan` 组成）。"""

    __slots__ = ("spans", "_text")

    def __init__(self, spans: list) -> None:
        self.spans = spans
        self._text: Optional[str] = None

    @property
    def text(self) -> str:
        """纯文本（不含任何转义序列），供过滤 / 导出使用。"""
        if self._text is None:
            self._text = "".join(span.text for span in self.spans)
        return self._text

    def __repr__(self) -> str:
        return f"TerminalLine({self.text!r})"


class AnsiParser:
    """增量 ANSI 解析器（纯字符串处理，不依赖 Qt，可脱离 GUI 单测）。

    按块喂入，未闭合的 ``ESC[`` 残留在内部缓冲等下一片；残留超过 64 字符丢弃。
    """

    #: 需要按字符逐个处理的控制字符
    _C0 = "\r\n\t\b\x07\x0b\x0c"

    def __init__(self) -> None:
        self._style = TerminalStyle()
        self._spans: list = []
        self._pending = ""
        self._cursor = 0
        self._line_len = 0
        self._pending_cr = False
        self._clear_all = False

    def feed(self, chunk: str) -> list:
        """喂入一段原始文本（可含任意半截转义序列），返回**本次收口**的完整行列表；
        未换行则为空。
        """
        if not chunk:
            return []
        data = self._pending + chunk
        self._pending = ""
        data, self._pending = self._split_incomplete(data)

        out: list = []
        index, size = 0, len(data)
        while index < size:
            char = data[index]
            if char == "\x1b":
                index += self._read_escape(data, index, out)
                continue
            if char in self._C0:
                self._control(char, out)
                index += 1
                continue
            end = index
            while end < size and data[end] != "\x1b" and data[end] not in self._C0:
                end += 1
            self._write(data[index:end])
            index = end
        return out

    def flush(self) -> list:
        """收尾：把未换行的残余内容作为最后一行吐出（无内容则空列表）。"""
        return [self._take_line()] if self._spans else []

    def pendingLine(self) -> Optional[TerminalLine]:  # noqa: N802 (Qt 命名)
        """还没收口的那一行（**不消费**；没有则 ``None``）。

        与 :meth:`flush` 的区别就是不消费：终端停在 ``Password:`` 这种
        等输入的状态时，那行既没被 ``\\n`` 收口、也不该被收走 —— 真实
        终端就把它显示在光标处。view 层用它把「当前行」实时画出来。
        """
        if not self._spans:
            return None
        return TerminalLine(list(self._spans))

    def reset(self) -> None:
        """清空全部状态（样式、行缓冲、残缺序列）。"""
        self._style = TerminalStyle()
        self._spans = []
        self._pending = ""
        self._cursor = _ZERO
        self._line_len = _ZERO
        self._pending_cr = False
        self._clear_all = False

    def takeClear(self) -> bool:  # noqa: N802 (Qt 命名)
        """取出并复位「整屏清空」标记（``CSI 2J`` / ``CSI 3J``）。"""
        value = self._clear_all
        self._clear_all = False
        return value

    def currentStyle(self) -> TerminalStyle:
        """当前生效的 SGR 样式。"""
        return self._style

    def _split_incomplete(self, data: str) -> tuple:
        """把尾部未闭合的转义序列切出来留给下一片，返回 ``(待处理数据, 残留序列)``；
        残留超长时丢弃那个 ``ESC``。
        """
        index = data.rfind("\x1b")
        if index < 0:
            return data, ""
        tail = data[index:]
        if self._is_complete_escape(tail):
            return data, ""
        if len(tail) > _MAX_PENDING:
            # 脏数据：整个残缺序列当普通文本吐掉（不丢 ESC，否则后面
            # 的内容会跟着一起被吞）
            return data[:index] + tail[1:], ""
        return data[:index], tail

    @classmethod
    def _is_complete_escape(cls, tail: str) -> bool:
        """判断以 ``ESC`` 开头的那段是否已经是一个完整转义序列。"""
        nxt = tail[1:2]
        if not nxt:
            return False
        if nxt == "]":
            # OSC 以 BEL 或 ST（ESC \）收尾
            return any(cls._has_terminator(tail, item) for item in ("\x07", "\x1b\\"))
        if nxt in "PX^_":
            return cls._has_terminator(tail, "\x1b\\")
        if nxt in "[9":
            return cls._csi_end(tail) is not None
        if nxt in "()*+-./":
            return len(tail) >= 3
        if nxt in "@ABCDEFGHJKLMPSTXZ`":  # 合法两字节序列
            return True
        # 简单两字节序列（ESC 7 / ESC c / ESC = …）或落单 ESC：立即可消费
        return True

    @staticmethod
    def _has_terminator(tail: str, terminator: str) -> bool:
        return tail.find(terminator, 2) >= 0

    @staticmethod
    def _csi_end(tail: str) -> Optional[int]:
        """返回 ``CSI`` 末字节下标，不完整返回 ``None``。"""
        index = 2
        size = len(tail)
        while index < size and "0" <= tail[index] <= "?":
            index += 1
        while index < size and " " <= tail[index] <= "/":
            index += 1
        if index < size and "@" <= tail[index] <= "~":
            return index
        return None

    def _read_escape(self, data: str, start: int, out: list) -> int:
        """解析 ``data[start]`` 处的转义序列，返回已消费的字符数。"""
        nxt = data[start + 1 : start + 2]
        if nxt == "]":  # OSC ... BEL / ST
            return _skip_string(data, start, ("\x07", "\x1b\\"))
        if nxt in "PX^_":  # DCS / SOS / PM / APC ... ST
            return _skip_string(data, start, ("\x1b\\",))
        if nxt in "[9":  # CSI（含 9 私有前缀）
            end = self._csi_end(data[start:])
            if end is None:
                # 不完整：整段丢弃（_split_incomplete 已保证片尾不会走到这里）
                return len(data) - start
            self._handle_csi(data[start + 2 : start + end], data[start + end], out)
            return end + 1
        if nxt in "()*+-./":  # 字符集选择：ESC ( B
            return 3
        if "@" <= nxt <= "Z" or nxt in "\\-_":  # ESC 7 / ESC c / ESC = …
            return 2
        # 落单 / 未知 ESC：只丢 ESC 本身。**不能顺手吃掉后一个字符** ——
        # 分片边界上会出现「上一片残留 ESC + 新片以 ESC 开头」（ESC ESC [ …），
        # 吃掉就会把后面的 CSI 整段当普通文本渲染出来。
        return 1

    def _handle_csi(self, params: str, final: str, out: list) -> None:
        if final == "m":
            # SGR 只改属性，不动光标 —— 不能清掉 \\r 的重绘标记，
            # 否则 "\\r + 颜色码 + 文本" 这种极常见组合会失效
            self._apply_sgr(params)
        elif final == "K":
            self._pending_cr = False
            self._erase_in_line(_first_param(params))
        elif final == "J":
            self._pending_cr = False
            self._erase_in_display(_first_param(params))
        elif final == "C":
            # 光标移动必须清掉 \r 的「整行重绘」标记：移动后是逐格覆盖，不是整行重写。
            # C/D/G 若保留标记，"PROGRESS 50%" + \r + ESC[2C + "DONE" 会被整行擦掉。
            self._pending_cr = False
            self._cursor += max(_DEFAULT_CSI_STEP, _first_param(params, 1))
        elif final == "D":
            self._pending_cr = False
            self._cursor = max(
                0, self._cursor - max(_DEFAULT_CSI_STEP, _first_param(params, 1))
            )
        elif final in ("G", "`"):
            # ``CSI 1G`` is equivalent to going back to the first column, but
            # does **not** erase -- that is exactly the difference from \\r
            self._pending_cr = False
            self._cursor = max(0, _first_param(params, 1) - 1)

    def _apply_sgr(self, params: str) -> None:
        """应用 ``SGR``（选择图形 rendition）参数串。"""
        values = _parse_params(params) or [_DEFAULT_CSI_PARAM]
        style = self._style
        index = 0
        while index < len(values):
            code = values[index]
            if code == _ZERO:
                style = TerminalStyle()
            elif code == 1:
                style = replace(style, bold=True)
            elif code == 2:
                style = replace(style, dim=True)
            elif code == 3:
                style = replace(style, italic=True)
            elif code == 4:
                style = replace(style, underline=True)
            elif code == 7:
                style = replace(style, inverse=True)
            elif code == 9:
                style = replace(style, strike=True)
            elif code == 22:
                style = replace(style, bold=False, dim=False)
            elif code == 23:
                style = replace(style, italic=False)
            elif code == 24:
                style = replace(style, underline=False)
            elif code == 27:
                style = replace(style, inverse=False)
            elif code == 29:
                style = replace(style, strike=False)
            elif code == 39:
                style = replace(style, fg=None)
            elif code == 49:
                style = replace(style, bg=None)
            elif 30 <= code <= 37:
                style = replace(style, fg=AnsiColor("basic", code - 30))
            elif 90 <= code <= 97:
                style = replace(style, fg=AnsiColor("basic", code - 90 + 8))
            elif 40 <= code <= 47:
                style = replace(style, bg=AnsiColor("basic", code - 40))
            elif 100 <= code <= 107:
                style = replace(style, bg=AnsiColor("basic", code - 100 + 8))
            elif code in (38, 48):
                color, step = _extended_color(values, index)
                if color is None:
                    step = 1
                elif code == 38:
                    style = replace(style, fg=color)
                else:
                    style = replace(style, bg=color)
                index += step - 1
            index += 1
        self._style = style

    def _erase_in_line(self, mode: int) -> None:
        """``CSI K``：清到行尾 / 清到行首 / 清整行。"""
        if mode == 0:
            # 光标到行尾：光标本身不动
            self._cut(self._cursor)
        elif mode == 1:
            # 行首到光标（**含光标那一格**）：清成空格，光标不动
            _, tail = _split_spans(self._spans, self._cursor + 1)
            self._spans = [TerminalSpan(" " * (self._cursor + 1), self._style)]
            if tail:
                self._spans.extend(tail)
            self._line_len = _spans_length(self._spans)
        elif mode == 2:
            self._spans = []
            self._cursor = _ZERO
            self._line_len = _ZERO

    def _erase_in_display(self, mode: int) -> None:
        """``CSI J``。
        滚动缓冲模型下「光标到末尾」= 当前行之后本来就没有内容，``0`` / ``1``
        视作空操作；``2`` / ``3`` 才是真正的整屏清空。
        """
        if mode in (2, 3):
            self._clear_all = True
            self._spans = []
            self._cursor = _ZERO
            self._line_len = _ZERO

    def _control(self, char: str, out: list) -> None:
        if char == "\r":
            # 只标记「下一笔是整行重绘」，不擦内容（紧跟的 \n 是 CRLF，应保留内容收行）。
            # 但光标必须在这里归零：\r 是光标移动，擦除发生在下一笔写入时。
            self._pending_cr = True
            self._cursor = _ZERO
        elif char == "\n":
            out.append(self._take_line())
        elif char == "\b":
            self._pending_cr = False
            self._cursor = max(0, self._cursor - 1)
        elif char == "\t":
            self._write(" " * (8 - self._cursor % 8))
        # BEL / VT / FF：无视觉意义，丢弃

    def _write(self, text: str) -> None:
        """按当前样式在光标处写入文本（逐格覆盖，行尾不足则补空格）。"""
        if not text:
            return
        if self._pending_cr:
            # \r 之后的第一笔 = 整行重绘
            self._pending_cr = False
            self._spans = []
            self._cursor = _ZERO
            self._line_len = _ZERO
        # 光标可能落在行尾之外（CSI C / D / G 移动过），补空格占位
        if self._cursor > self._line_len:
            gap = self._cursor - self._line_len
            self._merge_span(" " * gap, self._style)
            self._line_len = self._cursor
        self._overwrite(self._cursor, text, self._style)
        self._cursor += len(text)
        self._line_len = max(self._line_len, self._cursor)

    def _overwrite(self, pos: int, text: str, style: TerminalStyle) -> None:
        """在字符偏移 ``pos`` 处覆盖写入 ``text``，行尾多余部分保持不变。

        与「截断」相反：光标移动（``CSI C/D/G``、``\\b``）只是把笔挪到别处，
        覆盖只应改写笔下那几格，后面的内容必须留着。整行丢弃只发生在 ``\\r``
        重绘路径上。
        """
        head, rest = _split_spans(self._spans, pos)
        _, tail = _split_spans(rest, len(text))  # 丢弃笔下那几格
        self._spans = head
        self._merge_span(text, style)
        if tail:
            self._spans.extend(tail)
        self._line_len = pos + len(text) + _spans_length(tail)

    def _merge_span(self, text: str, style: TerminalStyle) -> None:
        """追加 span；与末尾同样式则合并，避免高碎片数。
        没有这一步，一行 200 段同色的输出就会变成 200 个 span —— 过滤、导出、
        渲染全要按 span 遍历，内存也翻倍。
        """
        if not text:
            return
        if self._spans and self._spans[-1].style == style:
            last = self._spans[-1]
            self._spans[-1] = TerminalSpan(last.text + text, style)
        else:
            self._spans.append(TerminalSpan(text, style))

    def _cut(self, pos: int) -> list:
        """在字符偏移 ``pos`` 处截断当前行，返回被切下的后半段。"""
        head, tail = _split_spans(self._spans, pos)
        self._spans = head
        self._line_len = _spans_length(head)
        return tail

    def _take_line(self) -> TerminalLine:
        self._pending_cr = False
        self._cursor = _ZERO
        self._line_len = _ZERO
        line = TerminalLine(self._spans)
        self._spans = []
        return line


def _spans_length(spans: list) -> int:
    """span 列表的总字符数。"""
    return sum(len(span.text) for span in spans)


def _split_spans(spans: list, pos: int) -> tuple:
    """在字符偏移 ``pos`` 处切分 span 列表，返回 ``(前段, 后段)``；``pos`` 落在某个
    span 中间时该 span 被切成两半。
    """
    head: list = []
    tail: list = []
    rest = max(0, pos)
    for span in spans:
        size = len(span.text)
        if rest >= size:
            head.append(span)
            rest -= size
        else:
            if rest > 0:
                head.append(TerminalSpan(span.text[:rest], span.style))
            if span.text[rest:]:
                tail.append(TerminalSpan(span.text[rest:], span.style))
            rest = _ZERO
    return head, tail


def _skip_string(data: str, start: int, terminators: tuple) -> int:
    """跳过字符串序列（OSC / DCS），返回已消费字符数。

    取各终止符里最早出现的一个；都没有则视为序列延伸到片尾。
    """
    size = len(data)
    best = size
    for terminator in terminators:
        index = data.find(terminator, start + 2)
        if index < 0:
            continue
        end = index + len(terminator)
        if end < best:
            best = end
    return best - start


def _parse_params(params: str) -> list:
    """把 CSI 参数串解析成整数列表（空参数按 0，非法项也按 0）。"""
    if not params:
        return []
    out = []
    for part in params.split(";"):
        part = part.strip()
        if part[:1] in ("?", "<", "=", ">"):
            part = part[1:]
        out.append(int(part) if part.lstrip("+-").isdigit() else 0)
    return out


def _first_param(params: str, default: int = _DEFAULT_CSI_PARAM) -> int:
    """取 CSI 的第一个参数（缺省值由 ``default`` 给）。"""
    values = _parse_params(params)
    return values[0] if values else default


def _extended_color(values: list, index: int) -> tuple:
    """解析 ``38/48;5;N`` 与 ``38/48;2;R;G;B``，返回 ``(颜色, 消耗的参数个数)``；
    格式不认识时颜色为 ``None``、步进为 1。
    """
    mode = values[index + 1] if index + 1 < len(values) else _ZERO
    if mode == 5 and index + 2 < len(values):
        return AnsiColor("indexed", _clamp_byte(values[index + 2])), 3
    if mode == 2 and index + 4 < len(values):
        red = _clamp_byte(values[index + 2])
        green = _clamp_byte(values[index + 3])
        blue = _clamp_byte(values[index + 4])
        return AnsiColor("rgb", (red << 16) | (green << 8) | blue), 5
    return None, 1


def _clamp_byte(value: int) -> int:
    """颜色分量夹到 0-255（超界值按上限算，而不是取模回绕）。"""
    return max(0, min(255, value))


def _blend(a: QColor, b: QColor, ratio: float) -> QColor:
    """按比例混合两种颜色（``ratio`` 为 ``b`` 的占比，0-1）。"""
    ratio = max(0.0, min(1.0, float(ratio)))
    return QColor(
        round(a.red() + (b.red() - a.red()) * ratio),
        round(a.green() + (b.green() - a.green()) * ratio),
        round(a.blue() + (b.blue() - a.blue()) * ratio),
    )


def _indexed_key(index: int) -> str:
    """色号 → 调色板键（0-7 基础色，8-15 亮色）。"""
    keys = _BASIC_KEYS if index < 8 else _BRIGHT_KEYS
    return keys[index % 8]


def _indexed_rgb(index: int) -> Optional[QColor]:
    """256 色号 → 颜色（0-15 交给调色板，16-231 立方体，232-255 灰阶）。"""
    if index < 16 or index > 255:
        return None
    if index < 232:
        n = index - 16
        return QColor(
            _CUBE_STEPS[(n // 36) % 6],
            _CUBE_STEPS[(n // 6) % 6],
            _CUBE_STEPS[n % 6],
        )
    level = 8 + (index - 232) * 10
    return QColor(level, level, level)
