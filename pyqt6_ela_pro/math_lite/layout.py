"""math_lite.layout."""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from .parser import (
    _Accent,
    _BigOp,
    _Binom,
    _Boxed,
    _Brace,
    _Cancel,
    _Color,
    _Delim,
    _Frac,
    _Framed,
    _HSpace,
    _Matrix,
    _MiddleDelim,
    _Node,
    _ParseError,
    _Phantom,
    _Pmod,
    _Row,
    _ScaledDelim,
    _Script,
    _Space,
    _Sqrt,
    _Stacked,
    _Styled,
    _Sym,
    _Tag,
    _Text,
    _XArrow,
    _atom_text,
    _dimension_em,
    _parse_color,
)
from .tables import _ALIGN_ENVS, _MATRIX_DELIMS


_MATH_FONT_NAMES = ("Cambria Math", "STIX Two Math", "Latin Modern Math")

_FALLBACK_FONT_NAMES = ("Times New Roman", "Georgia", "DejaVu Serif")

_FAMILIES: Optional[list] = None

_USE_MATH_ITALIC = False

_REF_METRICS: dict = {}

_MATH_ITALIC_MAP = {
    **{chr(ord("A") + i): chr(0x1D434 + i) for i in range(26)},
    **{chr(ord("a") + i): chr(0x210E if i == 7 else 0x1D44E + i) for i in range(26)},
}

_MATH_ITALIC_GREEK = "αβγδεζηθικλμνξοπρςστυφχψω"


def _math_families() -> list:
    """选择数学字体族（优先含数学斜体码位的字族）。"""
    families = set(QFontDatabase.families())
    for name in _MATH_FONT_NAMES:
        if name in families:
            return [name]
    for name in _FALLBACK_FONT_NAMES:
        if name in families:
            return [name]
    return []


def _font(
    size: float,
    italic: bool = False,
    bold: bool = False,
    family: Optional[str] = None,
) -> QFont:
    """公式排版字体（``family``：``"mono"`` / ``"sans"`` / 缺省数学字体）。

    各字体族列表**刻意保留多族回退**：数学字形与 ``\\text{中文}`` 的 CJK 覆盖
    只能二选一，单族化会砸掉一边；公式只渲染一次成图、非逐帧文本路径，Win7
    多族慢 shaping 的影响面最小 —— 与终端 / 查看器 / 图表 / chat 的单族化策略
    不同源（见「下游项目反馈bug.md」§3）。
    """
    global _FAMILIES, _USE_MATH_ITALIC
    if _FAMILIES is None:
        _FAMILIES = _math_families()
        _USE_MATH_ITALIC = bool(_FAMILIES) and _FAMILIES[0] in _MATH_FONT_NAMES
    font = QFont()
    if family == "mono":
        font.setFamilies(["Consolas", "Courier New", "DejaVu Sans Mono"])
    elif family == "sans":
        font.setFamilies(["Microsoft YaHei UI", "Segoe UI", "Arial"])
    elif _FAMILIES:
        # 数学字体缺少 CJK 字形：按序回退系统无衬线字体（``\text{中文}`` 可读）
        font.setFamilies(
            [_FAMILIES[0], "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"]
        )
    font.setPointSizeF(size)
    font.setItalic(italic)
    font.setBold(bold)
    return font


def _reference_metrics(size: float) -> tuple:
    """字号 → (大写字母上伸、下伸) 参考度量（紧凑，按字号缓存）。
    Cambria Math 等数学字体的 ``ascent``/``descent`` 为堆叠公式设计，
    行高极大（12pt 时约 50/39），不能用于排版；这里用字形紧包围盒
    """
    key = round(float(size), 2)
    cached = _REF_METRICS.get(key)
    if cached is not None:
        return cached
    fm = QFontMetricsF(_font(key))
    ascent = -fm.tightBoundingRect("H").top()
    descent = max(
        fm.tightBoundingRect("y").bottom(),
        fm.tightBoundingRect("p").bottom(),
    )
    if not math.isfinite(ascent) or ascent <= 0:
        ascent = key * 4.0 / 3.0 * 0.7
    if not math.isfinite(descent) or descent < 0:
        descent = 0.0
    _REF_METRICS[key] = (ascent, descent)
    return _REF_METRICS[key]


_REF_HEIGHTS: dict = {}


def _reference_heights(size: float) -> tuple:
    """字号 → (x-height, 大写高度)。
    上下标偏移按字体度量分档（x-height / cap-height），而不是逐字形紧包围盒，
    否则 `a`/`c` 的墨迹差 1px 就会让上标不在同一水平线。
    """
    key = round(float(size), 2)
    cached = _REF_HEIGHTS.get(key)
    if cached is not None:
        return cached
    fm = QFontMetricsF(_font(key))
    x_height = -fm.tightBoundingRect("x").top()
    cap_height = -fm.tightBoundingRect("H").top()
    if not math.isfinite(x_height) or x_height <= 0:
        x_height = key * 4.0 / 3.0 * 0.45
    if not math.isfinite(cap_height) or cap_height <= 0:
        cap_height = key * 4.0 / 3.0 * 0.7
    _REF_HEIGHTS[key] = (x_height, cap_height)
    return _REF_HEIGHTS[key]


def _math_italic_text(text: str) -> str:
    """ASCII 字母 / 小写希腊字母 → Unicode 数学斜体码位（不支持时原样）。"""
    if not _USE_MATH_ITALIC:
        return text
    return "".join(_MATH_ITALIC_MAP.get(ch, ch) for ch in text)


class _Box:
    w = 0.0
    h = 0.0
    a = 0.0
    d = 0.0

    def paint(
        self, painter: QPainter, x: float, base: float
    ) -> None:  # pragma: no cover
        raise NotImplementedError


class _GlyphBox(_Box):
    def __init__(
        self,
        text: str,
        size: float,
        italic: bool = False,
        bold: bool = False,
        family: Optional[str] = None,
    ):
        self.font = _font(size, italic, bold, family)
        self.color: Optional[QColor] = None
        # 变量斜体：数学字体使用 Unicode 数学斜体码位，普通字体用字形斜体
        if italic and family is None and _USE_MATH_ITALIC and not bold:
            text = _math_italic_text(text)
        self.text = text
        fm = QFontMetricsF(self.font)
        self.w = fm.horizontalAdvance(text) if text else 0.0
        cap, _ = _reference_metrics(size)
        if text and text.strip():
            tight = fm.tightBoundingRect(text)
            self.a = max(-tight.top(), 0.0)
            self.d = max(tight.bottom(), 0.0)
            if self.a <= 0:
                self.a = cap
        else:
            self.a = cap
            self.d = 0.0
        self.h = self.a + self.d
        # 上下标高度档位：同类字形共用同一度量，保证上标水平线一致
        x_height, cap_height = _reference_heights(size)
        if self.a <= x_height * 1.1:
            self.nucleus = x_height
        elif self.a <= cap_height * 1.1:
            self.nucleus = cap_height
        else:
            self.nucleus = self.a

    def paint(self, painter, x, base):
        if not self.text:
            return
        painter.setFont(self.font)
        if self.color is not None:
            painter.setPen(QPen(self.color))
        painter.drawText(QPointF(x, base), self.text)


class _RowBox(_Box):
    def __init__(self, boxes: list):
        self.boxes = boxes
        self.a = max((b.a for b in boxes), default=0.0)
        self.d = max((b.d for b in boxes), default=0.0)
        self.w = sum(b.w for b in boxes)
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        cx = x
        for box in self.boxes:
            box.paint(painter, cx, base)
            cx += box.w


class _SpaceBox(_Box):
    def __init__(self, em: float, size: float):
        self.w = max(0.0, em * size * 4.0 / 3.0)

    def paint(self, painter, x, base):
        return


class _TaggedBox(_Box):
    """正文 + 右侧公式编号（编号与正文同基线，间隔固定 ``2em``）。"""

    def __init__(self, body: _Box, tag: _Box, size: float):
        self.body = body
        self.tag = tag
        # ``_SpaceBox`` 的换算：1em = 4/3 pt
        self.gap = max(size * 8.0 / 3.0, 12.0)
        self.w = body.w + self.gap + tag.w
        self.a = max(body.a, tag.a)
        self.d = max(body.d, tag.d)
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        self.body.paint(painter, x, base)
        self.tag.paint(painter, x + self.w - self.tag.w, base)


class _FractionBox(_Box):
    def __init__(self, num: _Box, den: _Box, size: float):
        self.num = num
        self.den = den
        self.pad = max(1.2, size * 0.16)
        self.gap = max(1.6, size * 0.26)
        self.rule = max(0.6, size * 0.06)
        self.w = max(num.w, den.w) + 2 * self.pad
        self.a = num.h + self.gap + self.rule / 2
        self.d = den.h + self.gap + self.rule / 2
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        num_x = x + (self.w - self.num.w) / 2
        den_x = x + (self.w - self.den.w) / 2
        num_base = base - self.rule / 2 - self.gap - self.num.d
        den_base = base + self.rule / 2 + self.gap + self.den.a
        self.num.paint(painter, num_x, num_base)
        self.den.paint(painter, den_x, den_base)
        pen = painter.pen()
        painter.setPen(QPen(pen.color(), self.rule))
        y = base - self.rule / 2
        painter.drawLine(QPointF(x, y), QPointF(x + self.w, y))


class _ScriptBox(_Box):
    def __init__(
        self,
        base: _Box,
        sup: Optional[_Box],
        sub: Optional[_Box],
        size: float,
        pad_em: float = 0.1,
    ):
        self.base = base
        self.sup = sup
        self.sub = sub
        em = size * 4.0 / 3.0
        gap = max(1.0, em * 0.1)
        self.pad = max(0.8, size * pad_em)
        # 上标基线上移量：按基体"高度档位"（x-height / cap-height / 实际墨迹）+
        # gap；同类字形共用档位，保证 a²、c² 等上标在同一水平线，∫ 等超高基体贴顶
        nucleus = getattr(base, "nucleus", base.a)
        self.sup_shift = (nucleus + gap + sup.d) if sup is not None else 0.0
        # 下标基线下移量：使下标墨迹顶边低于基体下伸 + gap，避免与基体重叠
        self.sub_shift = (base.d + gap + sub.a) if sub is not None else 0.0
        script_w = max(
            sup.w if sup else 0.0,
            sub.w if sub else 0.0,
        )
        self.w = base.w + (script_w + self.pad if script_w else 0.0)
        sup_a = (self.sup_shift + sup.a) if sup else 0.0
        sub_d = (self.sub_shift + sub.d) if sub else 0.0
        self.a = max(base.a, sup_a)
        self.d = max(base.d, sub_d)
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        self.base.paint(painter, x, base)
        sx = x + self.base.w + self.pad
        if self.sup is not None:
            self.sup.paint(painter, sx, base - self.sup_shift)
        if self.sub is not None:
            self.sub.paint(painter, sx, base + self.sub_shift)


class _BigOpBox(_Box):
    def __init__(
        self,
        text: str,
        sup: Optional[_Box],
        sub: Optional[_Box],
        size: float,
        scale: float = 1.35,
    ):
        self.op = _GlyphBox(text, size * scale)
        self.sup = sup
        self.sub = sub
        self.gap = max(1.2, size * 0.2)
        self.w = max(self.op.w, sup.w if sup else 0.0, sub.w if sub else 0.0)
        self.a = self.op.a + ((self.gap + sup.d + sup.a) if sup else 0.0)
        self.d = self.op.d + ((self.gap + sub.a + sub.d) if sub else 0.0)
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        cx = x + (self.w - self.op.w) / 2
        self.op.paint(painter, cx, base)
        if self.sup is not None:
            sx = x + (self.w - self.sup.w) / 2
            self.sup.paint(painter, sx, base - self.op.a - self.gap - self.sup.d)
        if self.sub is not None:
            sx = x + (self.w - self.sub.w) / 2
            self.sub.paint(painter, sx, base + self.op.d + self.gap + self.sub.a)


class _SqrtBox(_Box):
    def __init__(self, body: _Box, index: Optional[_Box], size: float):
        self.body = body
        self.index = index
        self.pad = max(1.0, size * 0.1)
        self.hook = max(3.0, size * 0.6)
        self.w = self.hook + body.w + self.pad
        self.a = body.a + self.hook * 0.5 + self.pad
        self.d = body.d + self.pad * 0.5
        self.h = self.a + self.d
        self.size = size

    def paint(self, painter, x, base):
        body_x = x + self.hook + self.pad
        self.body.paint(painter, body_x, base)
        top = base - self.body.a - self.pad * 0.5
        bottom = base + self.body.d + self.pad * 0.4
        pen = painter.pen()
        width = max(0.7, self.size * 0.07)
        painter.setPen(QPen(pen.color(), width))
        painter.drawLine(
            QPointF(x + self.hook, top),
            QPointF(x + self.hook + self.body.w + self.pad, top),
        )
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(x, top + self.body.h * 0.45),
                    QPointF(x + self.hook * 0.35, bottom),
                    QPointF(x + self.hook, top),
                ]
            )
        )
        if self.index is not None:
            self.index.paint(painter, x, base - self.body.a - self.pad * 0.5)


class _DelimBox(_Box):
    def __init__(self, left: str, body: _Box, right: str, size: float):
        self.body = body
        target = body.h + size * 0.35
        self.left = self._make_glyph(left, target, size)
        self.right = self._make_glyph(right, target, size)
        self.w = self.left.w + body.w + self.right.w
        center = (body.d - body.a) / 2.0
        half = max(self.left.h, self.right.h) / 2.0 if (left or right) else 0.0
        self.a = max(body.a, half - center)
        self.d = max(body.d, half + center)
        self.h = self.a + self.d

    @staticmethod
    def _make_glyph(text: str, target: float, size: float) -> _Box:
        if not text:
            return _SpaceBox(0.0, size)
        box = _GlyphBox(text, size)
        if box.h <= 0:
            return box
        scale = target / box.h
        return _GlyphBox(text, size * scale)

    def paint(self, painter, x, base):
        center = (self.body.d - self.body.a) / 2.0
        if self.left.w:
            self.left.paint(painter, x, base + center + self.left.a - self.left.h / 2)
            x += self.left.w
        self.body.paint(painter, x, base)
        x += self.body.w
        if self.right.w:
            self.right.paint(
                painter, x, base + center + self.right.a - self.right.h / 2
            )


class _MatrixBox(_Box):
    """矩阵 / cases / align / array：等距网格 + 可缩放定界符（支持逐列对齐）。"""

    def __init__(
        self,
        rows: list,
        kind: str,
        size: float,
        column_align: Optional[list] = None,
        hlines: Optional[set] = None,
    ):
        self.kind = kind
        self.rows = rows
        self.hlines = set(hlines) if hlines else set()
        self.column_align = list(column_align) if column_align else []
        self.cols = max((len(row) for row in rows), default=0)
        self.col_widths = [0.0] * self.cols
        self.row_metrics = []
        for row in rows:
            for column, cell in enumerate(row):
                self.col_widths[column] = max(self.col_widths[column], cell.w)
            row_a = max((cell.a for cell in row), default=0.0)
            row_d = max((cell.d for cell in row), default=0.0)
            self.row_metrics.append((row_a, row_d))
        if kind == "substack":
            self.col_gap = size * 0.4
            self.row_gap = size * 0.28
        elif kind == "smallmatrix":
            self.col_gap = size * 0.35
            self.row_gap = size * 0.25
        elif kind in ("aligned",) or kind in _ALIGN_ENVS:
            self.col_gap = size * 0.35
            self.row_gap = size * 0.75
        elif kind in ("gather", "gathered", "multline", "multline*") or kind in (
            "equation",
            "equation*",
            "displaymath",
            "math",
            "gather*",
        ):
            self.col_gap = size * 0.5
            self.row_gap = size * 0.8
        elif kind in ("cases", "cases*", "dcases", "rcases"):
            self.col_gap = size * 0.6
            self.row_gap = size * 0.45
        else:
            self.col_gap = size * 0.85
            self.row_gap = size * 0.65
        self.body_w = sum(self.col_widths) + self.col_gap * max(self.cols - 1, 0)
        body_h = sum(a + d for a, d in self.row_metrics) + self.row_gap * max(
            len(rows) - 1, 0
        )
        # 矩阵整体以数学轴为中心
        axis = size * 0.25
        self.body_a = body_h / 2.0 + axis
        self.body_d = max(body_h - self.body_a, 0.0)
        left, right = _MATRIX_DELIMS.get(kind, ("", ""))
        target = body_h + size * 0.3
        self.left = _DelimBox._make_glyph(left, target, size)
        self.right = _DelimBox._make_glyph(right, target, size)
        self.w = self.left.w + self.body_w + self.right.w
        half = max(self.left.h, self.right.h) / 2.0 if (left or right) else 0.0
        self.a = max(self.body_a, half)
        self.d = max(self.body_d, half)
        self.h = self.a + self.d

    def _align_offset(self, column: int, width: float, cell_w: float) -> float:
        if column < len(self.column_align):
            align = self.column_align[column]
        elif self.kind in ("cases", "cases*", "dcases", "rcases"):
            align = "l"
        else:
            align = "c"
        if align == "l":
            return 0.0
        if align == "r":
            return width - cell_w
        return (width - cell_w) / 2.0

    def _delim_baseline(self, glyph: _Box, base: float) -> float:
        center = (self.body_d - self.body_a) / 2.0
        return base + center + glyph.a - glyph.h / 2.0

    def paint(self, painter, x, base):
        if self.left.w:
            self.left.paint(painter, x, self._delim_baseline(self.left, base))
            x += self.left.w
        top = base - self.body_a
        pen = painter.pen()
        if self.hlines:
            painter.setPen(QPen(pen.color(), max(0.7, pen.widthF())))
        for row_index, row in enumerate(self.rows):
            row_a, row_d = self.row_metrics[row_index]
            row_base = top + row_a
            if row_index in self.hlines:
                line_y = row_base - row_a - self.row_gap / 2.0
                painter.drawLine(QPointF(x, line_y), QPointF(x + self.body_w, line_y))
            cx = x
            for column in range(self.cols):
                cell = row[column] if column < len(row) else None
                width = self.col_widths[column]
                if cell is not None:
                    offset = self._align_offset(column, width, cell.w)
                    cell.paint(painter, cx + offset, row_base)
                cx += width + self.col_gap
            top += row_a + row_d + self.row_gap
        if len(self.rows) in self.hlines:
            line_y = top - self.row_gap / 2.0
            painter.drawLine(QPointF(x, line_y), QPointF(x + self.body_w, line_y))
        if self.right.w:
            self.right.paint(
                painter, x + self.body_w, self._delim_baseline(self.right, base)
            )


class _BinomBox(_Box):
    """组合数 \\binom：上下堆叠（无横线）+ 圆括号。"""

    def __init__(self, num: _Box, den: _Box, size: float):
        self.num = num
        self.den = den
        self.pad = max(1.0, size * 0.14)
        self.gap = max(0.8, size * 0.1)
        body_w = max(num.w, den.w) + 2 * self.pad
        self.a = num.h + self.gap
        self.d = den.h + self.gap
        target = self.a + self.d
        self.left = _DelimBox._make_glyph("(", target, size)
        self.right = _DelimBox._make_glyph(")", target, size)
        self.w = self.left.w + body_w + self.right.w
        self.h = self.a + self.d

    def _delim_baseline(self, glyph: _Box, base: float) -> float:
        center = (self.d - self.a) / 2.0
        return base + center + glyph.a - glyph.h / 2.0

    def paint(self, painter, x, base):
        if self.left.w:
            self.left.paint(painter, x, self._delim_baseline(self.left, base))
            x += self.left.w
        body_w = self.w - self.left.w - self.right.w
        self.num.paint(
            painter, x + (body_w - self.num.w) / 2.0, base - self.gap - self.num.d
        )
        self.den.paint(
            painter, x + (body_w - self.den.w) / 2.0, base + self.gap + self.den.a
        )
        if self.right.w:
            self.right.paint(
                painter, x + body_w, self._delim_baseline(self.right, base)
            )


class _AccentBox(_Box):
    """重音 / 下划线 / 箭头等修饰。"""

    def __init__(self, kind: str, body: _Box, size: float):
        self.kind = kind
        self.body = body
        self.size = size
        self.pad = max(1.0, size * 0.12)
        self.w = max(body.w, size * 0.6)
        extra = size * (0.18 if kind == "vec" else 0.14)
        if kind == "underline":
            self.a = body.a
            self.d = body.d + self.pad + extra
        else:
            self.a = body.a + self.pad + extra
            self.d = body.d
        self.h = self.a + self.d

    def _line_width(self) -> float:
        return max(0.7, self.size * 0.06)

    def paint(self, painter, x, base):
        self.body.paint(painter, x, base)
        pen = painter.pen()
        painter.setPen(QPen(pen.color(), self._line_width()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.kind == "underline":
            y = base + self.body.d + self.pad * 0.8
            painter.drawLine(QPointF(x, y), QPointF(x + self.w, y))
            return
        top = base - self.body.a - self.pad * 0.6
        mid = x + self.w / 2
        if self.kind in ("bar", "overline"):
            painter.drawLine(QPointF(x, top), QPointF(x + self.w, top))
        elif self.kind == "vec":
            painter.drawLine(
                QPointF(x + 0.05 * self.size, top),
                QPointF(x + self.w - 0.05 * self.size, top),
            )
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(x + self.w - 0.18 * self.size, top - 0.06 * self.size),
                        QPointF(x + self.w - 0.05 * self.size, top),
                        QPointF(x + self.w - 0.18 * self.size, top + 0.06 * self.size),
                    ]
                )
            )
        elif self.kind in ("hat", "tilde"):
            spread = 0.15 if self.kind == "hat" else 0.08
            height = 0.05 if self.kind == "hat" else 0.07
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(x + self.w * spread, top + 0.04 * self.size),
                        QPointF(mid, top - height * self.size),
                        QPointF(x + self.w * (1 - spread), top + 0.04 * self.size),
                    ]
                )
            )
        elif self.kind in ("acute", "grave"):
            sign = 1 if self.kind == "acute" else -1
            painter.drawLine(
                QPointF(mid - sign * 0.08 * self.size, top + 0.05 * self.size),
                QPointF(mid + sign * 0.08 * self.size, top - 0.05 * self.size),
            )
        elif self.kind == "breve":
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(x + self.w * 0.2, top - 0.03 * self.size),
                        QPointF(mid, top + 0.05 * self.size),
                        QPointF(x + self.w * 0.8, top - 0.03 * self.size),
                    ]
                )
            )
        elif self.kind == "check":
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(x + self.w * 0.2, top + 0.05 * self.size),
                        QPointF(mid, top - 0.05 * self.size),
                        QPointF(x + self.w * 0.8, top + 0.05 * self.size),
                    ]
                )
            )
        elif self.kind == "ring":
            r = max(0.8, self.size * 0.06)
            painter.drawEllipse(QPointF(mid, top), r, r)
        elif self.kind in (
            "overrightarrow",
            "overleftarrow",
            "overleftrightarrow",
        ):
            self._paint_over_arrow(painter, x, top, pen.color())
        else:  # dot / ddot
            r = max(0.8, self.size * 0.055)
            painter.setBrush(pen.color())
            cx = mid
            painter.drawEllipse(QPointF(cx, top), r, r)
            if self.kind == "ddot":
                painter.drawEllipse(QPointF(cx - r * 2.5, top), r, r)
                painter.drawEllipse(QPointF(cx + r * 2.5, top), r, r)

    def _paint_over_arrow(self, painter, x, top, color):
        painter.setPen(QPen(color, self._line_width()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        head = self.size * 0.16
        y = top
        if self.kind in ("overrightarrow", "overleftrightarrow"):
            painter.drawLine(QPointF(x, y), QPointF(x + self.w, y))
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(x + self.w - head, y - head * 0.6),
                        QPointF(x + self.w, y),
                        QPointF(x + self.w - head, y + head * 0.6),
                    ]
                )
            )
        if self.kind in ("overleftarrow", "overleftrightarrow"):
            painter.drawLine(QPointF(x, y), QPointF(x + self.w, y))
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(x + head, y - head * 0.6),
                        QPointF(x, y),
                        QPointF(x + head, y + head * 0.6),
                    ]
                )
            )


class _BoxedBox(_Box):
    """``\\boxed``：细边框包裹。"""

    def __init__(self, body: _Box, size: float):
        self.body = body
        self.pad = max(1.5, size * 0.28)
        self.line = max(0.7, size * 0.055)
        self.w = body.w + 2 * self.pad
        self.a = body.a + self.pad
        self.d = body.d + self.pad
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        self.body.paint(painter, x + self.pad, base)
        pen = painter.pen()
        painter.setPen(QPen(pen.color(), self.line))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(
            QRectF(x, base - self.a, self.w, self.h),
        )


class _FramedBox(_Box):
    """``\\fbox``（边框）/ ``\\colorbox``（底色）。"""

    def __init__(self, kind: str, body: _Box, size: float, color: QColor = None):
        self.kind = kind
        self.body = body
        self.color = color
        self.pad = max(2.0, size * 0.3)
        self.line = max(0.7, size * 0.055)
        self.w = body.w + 2 * self.pad
        self.a = body.a + self.pad
        self.d = body.d + self.pad
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        rect = QRectF(x, base - self.a, self.w, self.h)
        pen = painter.pen()
        if self.kind == "colorbox" and self.color is not None:
            painter.fillRect(rect, self.color)
        else:
            painter.setPen(QPen(pen.color(), self.line))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
        self.body.paint(painter, x + self.pad, base)


class _StackedBox(_Box):
    """``\\overset`` / ``\\underset`` / ``\\stackrel`` / 花括号标签。"""

    def __init__(
        self,
        base: _Box,
        above: Optional[_Box],
        below: Optional[_Box],
        size: float,
    ):
        self.base = base
        self.above = above
        self.below = below
        self.gap = max(0.8, size * 0.12)
        self.w = max(
            base.w,
            above.w if above else 0.0,
            below.w if below else 0.0,
        )
        self.a = base.a + ((above.h + self.gap) if above else 0.0)
        self.d = base.d + ((below.h + self.gap) if below else 0.0)
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        self.base.paint(painter, x + (self.w - self.base.w) / 2, base)
        if self.above is not None:
            self.above.paint(
                painter,
                x + (self.w - self.above.w) / 2,
                base - self.base.a - self.gap - self.above.d,
            )
        if self.below is not None:
            self.below.paint(
                painter,
                x + (self.w - self.below.w) / 2,
                base + self.base.d + self.gap + self.below.a,
            )


def _brace_path(
    path: QPainterPath,
    x: float,
    y: float,
    width: float,
    height: float,
    over: bool,
) -> None:
    """水平花括号：``over=True`` 时尖角朝上。"""
    direction = -1.0 if over else 1.0
    cusp = y + direction * height
    path.moveTo(x, y)
    path.cubicTo(
        x + width * 0.08,
        cusp,
        x + width * 0.42,
        y,
        x + width * 0.5,
        cusp,
    )
    path.cubicTo(
        x + width * 0.58,
        y,
        x + width * 0.92,
        cusp,
        x + width,
        y,
    )


class _BraceBox(_Box):
    """``\\overbrace`` / ``\\underbrace``：水平花括号。"""

    def __init__(self, over: bool, body: _Box, size: float):
        self.over = over
        self.body = body
        self.size = size
        self.height = max(2.5, size * 0.4)
        self.margin = max(1.0, size * 0.12)
        self.w = body.w
        self.a = body.a + (self.height + self.margin if over else 0.0)
        self.d = body.d + (self.height + self.margin if not over else 0.0)
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        self.body.paint(painter, x, base)
        pen = painter.pen()
        path = QPainterPath()
        if self.over:
            y = base - self.body.a - self.margin
        else:
            y = base + self.body.d + self.margin
        _brace_path(path, x, y, self.w, self.height, self.over)
        painter.setPen(QPen(pen.color(), max(0.7, self.size * 0.06)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class _XArrowBox(_Box):
    """``\\xrightarrow`` / ``\\xleftarrow``：可伸缩箭头 + 可选上下标签。"""

    def __init__(
        self,
        direction: str,
        above: Optional[_Box],
        below: Optional[_Box],
        size: float,
    ):
        self.direction = direction
        self.above = above
        self.below = below
        self.size = size
        self.gap = max(0.8, size * 0.12)
        min_len = size * 2.2
        label_w = max(
            above.w if above else 0.0,
            below.w if below else 0.0,
        )
        self.w = max(min_len, label_w + size * 0.8)
        self.arrow_a = max(0.35 * size, 0.0)
        self.a = self.arrow_a + ((above.h + self.gap) if above else 0.0)
        self.d = (below.h + self.gap) if below else 0.0
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        pen = painter.pen()
        width = max(0.7, self.size * 0.06)
        painter.setPen(QPen(pen.color(), width))
        y = base - self.arrow_a
        left, right = x, x + self.w
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        head = self.size * 0.18
        if self.direction == "right":
            tip = right
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(tip - head, y - head * 0.6),
                        QPointF(tip, y),
                        QPointF(tip - head, y + head * 0.6),
                    ]
                )
            )
        else:
            tip = left
            painter.drawPolyline(
                QPolygonF(
                    [
                        QPointF(tip + head, y - head * 0.6),
                        QPointF(tip, y),
                        QPointF(tip + head, y + head * 0.6),
                    ]
                )
            )
        if self.above is not None:
            self.above.paint(
                painter,
                x + (self.w - self.above.w) / 2,
                y - self.gap - self.above.d,
            )
        if self.below is not None:
            self.below.paint(
                painter,
                x + (self.w - self.below.w) / 2,
                y + self.gap + self.below.a,
            )


class _PhantomBox(_Box):
    """``\\phantom`` 系列：占位但不绘制。"""

    def __init__(self, body: _Box, kind: str):
        self.body = body
        self.kind = kind
        if kind == "full":
            self.w, self.a, self.d = body.w, body.a, body.d
        elif kind == "h":
            self.w, self.a, self.d = body.w, 0.0, 0.0
        else:
            self.w, self.a, self.d = 0.0, body.a, body.d
        self.h = self.a + self.d

    def paint(self, painter, x, base):
        return


class _ColorBox(_Box):
    """显式着色：子盒改用指定画笔颜色绘制。"""

    def __init__(self, body: _Box, color: QColor):
        self.body = body
        self.color = color
        self.w, self.a, self.d, self.h = body.w, body.a, body.d, body.h

    def paint(self, painter, x, base):
        pen = painter.pen()
        painter.setPen(QPen(self.color))
        self.body.paint(painter, x, base)
        painter.setPen(pen)


class _CancelBox(_Box):
    """``\\cancel`` 系列：删除线 / 斜线。"""

    def __init__(self, kind: str, body: _Box, size: float):
        self.kind = kind
        self.body = body
        self.line = max(0.7, size * 0.06)
        self.w, self.a, self.d, self.h = body.w, body.a, body.d, body.h

    def paint(self, painter, x, base):
        self.body.paint(painter, x, base)
        pen = painter.pen()
        painter.setPen(QPen(pen.color(), self.line))
        top = base - self.a
        bottom = base + self.d
        if self.kind in ("cancel", "xcancel"):
            painter.drawLine(QPointF(x, bottom), QPointF(x + self.w, top))
        if self.kind in ("bcancel", "xcancel"):
            painter.drawLine(QPointF(x, top), QPointF(x + self.w, bottom))
        if self.kind == "sout":
            middle = base - (self.a - self.d) / 2
            painter.drawLine(QPointF(x, middle), QPointF(x + self.w, middle))


class _MiddleBox(_Box):
    """``\\middle``：占位符，构建 ``_Row`` 时按行高替换为缩放定界符。"""

    def __init__(self, text: str, size: float):
        self.text = text
        self.size = size
        self.w = self.a = self.d = self.h = 0.0

    def resized(self, target: float, base_box: _Box) -> _Box:
        glyph = _GlyphBox(self.text, self.size)
        if glyph.h <= 0:
            return glyph
        return _GlyphBox(self.text, self.size * max(target / glyph.h, 1.0))


_RELATION_ATOMS = set("=<>≤≥≠≈≡∼≃∝∈∉⊂⊆⊃⊇→←↔⇒⇐⇔↦∥⊥")

_BINARY_ATOMS = set("+−-×÷·⋅∗±∓∪∩∖⊕⊗")

_UNARY_ATOMS = set("+−-")

_PUNCT_ATOMS = set(",;")

_OPEN_DELIMS = set("([{⟨")

_RELATION_SPACE = 5.0 / 18.0

_BINARY_SPACE = 4.0 / 18.0

_PUNCT_SPACE = 3.0 / 18.0


def _build_tag(tag: _Tag, size: float) -> _Box:
    """公式编号：按正文文本直立绘制，``\\tag*`` 不补括号。"""
    text = tag.text
    if not text:
        return _SpaceBox(0.0, size)
    if not tag.star:
        text = f"({text})"
    return _GlyphBox(text, size)


def _build(
    node: _Node,
    size: float,
    italic: bool = False,
    bold: bool = False,
    depth: int = 0,
    family: Optional[str] = None,
) -> _Box:
    if isinstance(node, _Sym):
        return _GlyphBox(
            node.text,
            size,
            italic=node.italic or italic,
            bold=bold,
            family=family,
        )
    if isinstance(node, _Text):
        return _GlyphBox(
            node.text,
            size,
            italic=node.italic or italic,
            bold=node.bold or bold,
            family=family,
        )
    if isinstance(node, _Styled):
        return _build(
            node.body,
            size,
            node.italic,
            node.bold,
            depth,
            node.family or family,
        )
    if isinstance(node, _Space):
        return _SpaceBox(node.em, size)
    if isinstance(node, _HSpace):
        return _SpaceBox(_dimension_em(node.raw, size), size)
    if isinstance(node, _Row):
        boxes: list = []
        previous = ""
        tag: Optional[_Tag] = None
        for item in node.items:
            if isinstance(item, _Tag):
                tag = item
                continue
            text = _atom_text(item)
            before = after = 0.0
            if text in _RELATION_ATOMS:
                before = after = _RELATION_SPACE
            elif text in _BINARY_ATOMS:
                unary = text in _UNARY_ATOMS and (
                    not previous
                    or previous in _OPEN_DELIMS
                    or previous in _RELATION_ATOMS
                    or previous in _BINARY_ATOMS
                    or previous in _PUNCT_ATOMS
                )
                if not unary:
                    before = after = _BINARY_SPACE
            elif text in _PUNCT_ATOMS:
                after = _PUNCT_SPACE
            if before > 0:
                boxes.append(_SpaceBox(before, size))
            boxes.append(_build(item, size, italic, bold, depth, family))
            if after > 0:
                boxes.append(_SpaceBox(after, size))
            previous = text
        middles = [
            (index, box)
            for index, box in enumerate(boxes)
            if isinstance(box, _MiddleBox)
        ]
        if middles:
            others_a = max(
                (box.a for box in boxes if not isinstance(box, _MiddleBox)),
                default=0.0,
            )
            others_d = max(
                (box.d for box in boxes if not isinstance(box, _MiddleBox)),
                default=0.0,
            )
            target = others_a + others_d + size * 0.25
            for index, box in middles:
                boxes[index] = box.resized(target, box)
        row = _RowBox(boxes)
        if tag is not None:
            return _TaggedBox(row, _build_tag(tag, size), size)
        return row
    if isinstance(node, _Frac):
        script = max(size * (0.9 if depth == 0 else 0.75), 4.0)
        return _FractionBox(
            _build(node.num, script, italic, bold, depth + 1, family),
            _build(node.den, script, italic, bold, depth + 1, family),
            size,
        )
    if isinstance(node, _Sqrt):
        script = max(size * (0.7 if depth == 0 else 0.55), 4.0)
        index = (
            _build(node.index, script, italic, bold, depth + 1, family)
            if node.index is not None
            else None
        )
        return _SqrtBox(
            _build(node.body, size, italic, bold, depth, family), index, size
        )
    if isinstance(node, _Script):
        script = max(size * (0.7 if depth == 0 else 0.55), 4.0)
        base = _build(node.base, size, italic, bold, depth, family)
        sup = (
            _build(node.sup, script, italic, bold, depth + 1, family)
            if node.sup is not None
            else None
        )
        sub = (
            _build(node.sub, script, italic, bold, depth + 1, family)
            if node.sub is not None
            else None
        )
        if isinstance(node.base, _BigOp):
            if node.base.stack:
                return _BigOpBox(node.base.text, sup, sub, size, node.base.scale)
            side_op = _BigOpBox(node.base.text, None, None, size, node.base.scale)
            return _RowBox(
                [
                    _ScriptBox(side_op, sup, sub, size, pad_em=0.35),
                    _SpaceBox(0.15, size),
                ]
            )
        if isinstance(node.base, (_Brace, _Accent)):
            return _StackedBox(base, sup, sub, size)
        return _ScriptBox(base, sup, sub, size)
    if isinstance(node, _BigOp):
        return _BigOpBox(node.text, None, None, size, node.scale)
    if isinstance(node, _Delim):
        return _DelimBox(
            node.left,
            _build(node.body, size, italic, bold, depth, family),
            node.right,
            size,
        )
    if isinstance(node, _Accent):
        return _AccentBox(
            node.kind,
            _build(node.body, size, italic, bold, depth, family),
            size,
        )
    if isinstance(node, _Brace):
        return _BraceBox(
            node.over,
            _build(node.body, size, italic, bold, depth, family),
            size,
        )
    if isinstance(node, _Stacked):
        script = max(size * 0.7, 4.0)
        return _StackedBox(
            _build(node.base, size, italic, bold, depth, family),
            _build(node.top, script, italic, bold, depth + 1, family)
            if node.top is not None
            else None,
            _build(node.bottom, script, italic, bold, depth + 1, family)
            if node.bottom is not None
            else None,
            size,
        )
    if isinstance(node, _XArrow):
        script = max(size * 0.7, 4.0)
        return _XArrowBox(
            node.direction,
            _build(node.above, script, italic, bold, depth + 1, family)
            if node.above is not None
            else None,
            _build(node.below, script, italic, bold, depth + 1, family)
            if node.below is not None
            else None,
            size,
        )
    if isinstance(node, _Boxed):
        return _BoxedBox(_build(node.body, size, italic, bold, depth, family), size)
    if isinstance(node, _Framed):
        color = _parse_color(node.color)
        kind = "colorbox" if (node.kind == "colorbox" and color) else "fbox"
        return _FramedBox(
            kind,
            _build(node.body, size, italic, bold, depth, family),
            size,
            color,
        )
    if isinstance(node, _Phantom):
        return _PhantomBox(
            _build(node.body, size, italic, bold, depth, family), node.kind
        )
    if isinstance(node, _Color):
        color = _parse_color(node.color)
        body = _build(node.body, size, italic, bold, depth, family)
        if color is None:
            return body
        return _ColorBox(body, color)
    if isinstance(node, _Cancel):
        return _CancelBox(
            node.kind,
            _build(node.body, size, italic, bold, depth, family),
            size,
        )
    if isinstance(node, _Pmod):
        inner = _build(node.body, max(size * 0.9, 4.0), italic, bold, depth + 1)
        return _RowBox(
            [
                _SpaceBox(0.5, size),
                _GlyphBox("(mod ", size, family=family),
                inner,
                _GlyphBox(")", size, family=family),
            ]
        )
    if isinstance(node, _ScaledDelim):
        return _GlyphBox(node.text, size * node.scale, family=family)
    if isinstance(node, _MiddleDelim):
        return _MiddleBox(node.text, size)
    if isinstance(node, _Matrix):
        cell_size = size * 0.85 if node.kind == "smallmatrix" else size
        rows = [
            [_build(cell, cell_size, italic, bold, depth + 1, family) for cell in row]
            for row in node.rows
        ]
        column_align = node.column_align
        if node.kind in _ALIGN_ENVS and not column_align:
            # align/aligned：奇数列右对齐、偶数列左对齐（TeX 语义）
            columns = max((len(row) for row in node.rows), default=0)
            column_align = ["r" if index % 2 == 0 else "l" for index in range(columns)]
        return _MatrixBox(rows, node.kind, size, column_align, node.hlines)
    if isinstance(node, _Binom):
        script = max(size * 0.8, 4.0)
        return _BinomBox(
            _build(node.num, script, italic, bold, depth + 1, family),
            _build(node.den, script, italic, bold, depth + 1, family),
            size,
        )
    if isinstance(node, _Tag):
        return _build_tag(node, size)
    raise _ParseError(f"unsupported node {type(node).__name__}")


_MATH_ITALIC_MAP.update(
    {ch: chr(0x1D6FC + i) for i, ch in enumerate(_MATH_ITALIC_GREEK)}
)
