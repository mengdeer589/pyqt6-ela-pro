# -*- coding: utf-8 -*-
"""LaTeX 数学公式轻量渲染（零依赖）。

参考 InstructionX_UIKit 的公式方案（占位标记提取 + 资源嵌入 + LRU 缓存），
但**不引入 matplotlib**：本模块把常见 LaTeX 数学子集解析为盒模型，用
``QPainter`` 绘制为透明底 ``QImage``（2x 超采样，高 DPI 清晰）。

支持范围：

- 希腊字母（大小写）与常用符号：``\\infty \\pm \\times \\leq \\in \\to`` 等，
  以及长尾箭头 / 变体符号（``\\mid \\implies \\iff \\rightleftharpoons`` 等）；
- 上下标：``x^2`` / ``x_i`` / ``x_i^{n+1}``；
- 分数：``\\frac`` / ``\\dfrac`` / ``\\tfrac`` / ``\\cfrac`` / ``\\genfrac``；
  根式：``\\sqrt`` / ``\\sqrt[n]``；
- 大型算子带上限：``\\sum`` / ``\\prod`` / ``\\int`` / ``\\oint`` / ``\\lim``，
  极限算子 ``\\max \\min \\sup \\inf \\det \\gcd \\limsup \\liminf`` 自动堆叠
  （``\\limits`` / ``\\nolimits`` 可覆盖）；
- 直立函数名：``\\sin \\cos \\log \\ln \\exp`` 等；``\\operatorname*`` 极限算子；
- 框线与修饰：``\\boxed`` / ``\\underline`` / ``\\overbrace`` / ``\\underbrace`` /
  ``\\overrightarrow`` 等重音 / ``\\overset`` / ``\\underset`` / ``\\xrightarrow``；
- 字体与颜色：``\\text \\mathrm \\mathbf \\boldsymbol \\bm \\textbf \\texttt`` 等、
  ``\\textcolor`` / ``\\color``（基础色名与 ``#RRGGBB``）、``\\cancel`` 系列；
- 公式编号：``\\tag`` / ``\\tag*``（编号右对齐在公式末尾，``\\tag*`` 不补括号）；
- 矩阵环境：``\\begin{matrix/pmatrix/bmatrix/Bmatrix/vmatrix/Vmatrix/cases}``
  （``&`` 分列、``\\\\`` 分行）；多行对齐 ``align`` / ``aligned`` / ``gather`` /
  ``multline`` / ``split`` / ``alignat`` / ``flalign``（``&`` 对齐位）、
  ``smallmatrix`` / ``dcases`` / ``rcases``、``array``（``{lcr}`` 列格式、
  ``\\hline``）、多行下标 ``\\substack``；组合数 ``\\binom``；
  字母表 ``\\mathbb`` / ``\\mathcal`` / ``\\mathfrak``；
- 定界符：``\\left( \\right)``、``\\big`` 系列、``\\middle``、``\\lfloor`` 等；
- 宏：``\\newcommand`` / ``\\def`` / ``\\DeclareMathOperator``（含参数）；
- 间距 / 占位：``\\quad`` / ``\\hspace{2em}`` / ``\\phantom`` 系列。

排版风格对齐 KaTeX：优先 Cambria Math 并用 Unicode 数学斜体码位渲染变量
（不可用时回退 Times 系字形斜体）；采用紧凑字形度量（数学字体的行高为
堆叠公式设计，不可直接使用）；TeX 风格原子间距（关系 / 二元运算符 / 标点）、
脚本分级缩放（0.7 / 0.55）、大算子 display 尺寸与上下限布局。

**容错渲染**：未知命令按字面文本渲染（``report["degraded"]`` 标记）；
``\\left`` / ``\\right`` 不闭合时自动配平后重试（``report["repaired"]``
标记），修复仍失败（括号不闭合、``\\end`` 不匹配等）才返回 ``None``，
调用方回退为源码文本显示。

用法::

    processed, maths = extract_math(source, "elamath0z{}q")
    img = render_formula(latex, color, pt, display=False)   # QImage | None
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QPolygonF,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)

__all__ = [
    "extract_math",
    "render_formula",
    "clear_cache",
    "set_cache_capacity",
    "MATH_ENVS",
]

#: 超采样倍率（QTextDocument 尊重 QImage 的 devicePixelRatio）
_SS = 2
#: LRU 缓存容量（含失败哨兵）
_CACHE_CAP = 256
_FAILED = object()

#: 单边像素上限。公式是文档内嵌内容，单边超过这个量级早已超出任何视口 ——
#: 而 ``box.w`` 只有下界没有上界（``\hspace`` 的数值参数直接进 ``box.w``，
#: ``_SpaceBox`` 只对负值 ``max(0.0, ...)``）。实测不设限时
#: ``x\hspace{1000000em}x`` 会真实分配 3.1 GiB 缓冲，
#: ``10000000em`` 让 QImage 返回 null 而被当成功交出去。
#: 取 20000 是为了给「超宽的长公式」留足余量，同时把最坏分配压到
#: ``_MAX_PIXELS`` 之下。
_MAX_DIM = 20000
#: 总像素上限（ARGB32 = 4 字节/像素，20k×20k ≈ 1.6 GiB 太离谱）。
#: 6400 万像素 ≈ 256 MiB 缓冲，已远超任何真实公式（典型公式不到 10 万像素）。
_MAX_PIXELS = 64_000_000

#: 宏展开后的字符数上限（``\def\a{\a\a\a}`` 这类自引用宏每轮 ×3，
#: 只限轮数会指数爆炸，实测 20 轮后 3.5e9 字符把 GUI 线程彻底卡死）
_MACRO_EXPANSION_LIMIT = 200_000

#: 多行块级公式环境（``\begin{...}`` 形式）
_MATH_ENVS = (
    "equation",
    "equation*",
    "align",
    "align*",
    "aligned",
    "aligned*",
    "gather",
    "gather*",
    "gathered",
    "multline",
    "multline*",
    "displaymath",
    "math",
    "split",
    "alignat",
    "alignat*",
    "flalign",
    "flalign*",
    "matrix",
    "pmatrix",
    "bmatrix",
    "Bmatrix",
    "vmatrix",
    "Vmatrix",
    "cases",
    "cases*",
    "dcases",
    "rcases",
    "smallmatrix",
)

#: 公开别名（供流式稳定边界扫描复用）
MATH_ENVS = _MATH_ENVS

# --------------------------------------------------------------------- 符号表
_SYMBOLS = {
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\varepsilon": "ε",
    r"\zeta": "ζ",
    r"\eta": "η",
    r"\theta": "θ",
    r"\vartheta": "ϑ",
    r"\iota": "ι",
    r"\kappa": "κ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\nu": "ν",
    r"\xi": "ξ",
    r"\pi": "π",
    r"\varpi": "ϖ",
    r"\rho": "ρ",
    r"\varrho": "ϱ",
    r"\sigma": "σ",
    r"\varsigma": "ς",
    r"\tau": "τ",
    r"\upsilon": "υ",
    r"\phi": "φ",
    r"\varphi": "φ",
    r"\chi": "χ",
    r"\psi": "ψ",
    r"\omega": "ω",
    r"\Gamma": "Γ",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Xi": "Ξ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Upsilon": "Υ",
    r"\Phi": "Φ",
    r"\Psi": "Ψ",
    r"\Omega": "Ω",
    r"\pm": "±",
    r"\mp": "∓",
    r"\times": "×",
    r"\div": "÷",
    r"\cdot": "·",
    r"\ast": "∗",
    r"\star": "⋆",
    r"\circ": "∘",
    r"\bullet": "•",
    r"\leq": "≤",
    r"\le": "≤",
    r"\geq": "≥",
    r"\ge": "≥",
    r"\neq": "≠",
    r"\ne": "≠",
    r"\approx": "≈",
    r"\equiv": "≡",
    r"\sim": "∼",
    r"\simeq": "≃",
    r"\propto": "∝",
    r"\cong": "≅",
    r"\in": "∈",
    r"\notin": "∉",
    r"\ni": "∋",
    r"\not\\in": "∉",
    r"\subset": "⊂",
    r"\subseteq": "⊆",
    r"\supset": "⊃",
    r"\supseteq": "⊇",
    r"\cup": "∪",
    r"\cap": "∩",
    r"\setminus": "∖",
    r"\otimes": "⊗",
    r"\oplus": "⊕",
    r"\odot": "⊙",
    r"\wedge": "∧",
    r"\vee": "∨",
    r"\emptyset": "∅",
    r"\varnothing": "∅",
    r"\forall": "∀",
    r"\exists": "∃",
    r"\nexists": "∄",
    r"\partial": "∂",
    r"\nabla": "∇",
    r"\infty": "∞",
    r"\angle": "∠",
    r"\perp": "⊥",
    r"\parallel": "∥",
    r"\therefore": "∴",
    r"\because": "∵",
    r"\rightarrow": "→",
    r"\to": "→",
    r"\leftarrow": "←",
    r"\gets": "←",
    r"\leftrightarrow": "↔",
    r"\Rightarrow": "⇒",
    r"\Leftarrow": "⇐",
    r"\Leftrightarrow": "⇔",
    r"\mapsto": "↦",
    r"\hookrightarrow": "↪",
    r"\uparrow": "↑",
    r"\downarrow": "↓",
    r"\updownarrow": "↕",
    r"\dots": "…",
    r"\ldots": "…",
    r"\cdots": "⋯",
    r"\vdots": "⋮",
    r"\ddots": "⋱",
    r"\prime": "′",
    r"\%": "%",
    r"\&": "&",
    r"\#": "#",
    r"\_": "_",
    r"\langle": "⟨",
    r"\rangle": "⟩",
    r"\|": "‖",
}

#: 扩充符号（P1 兼容性批次：长尾箭头 / 变体符号 / 特殊字母等）
_SYMBOLS.update(
    {
        r"\ell": "ℓ",
        r"\hbar": "ℏ",
        r"\imath": "ı",
        r"\jmath": "ȷ",
        r"\Re": "ℜ",
        r"\Im": "ℑ",
        r"\wp": "℘",
        r"\aleph": "ℵ",
        r"\beth": "ℶ",
        r"\gimel": "ℷ",
        r"\daleth": "ℸ",
        r"\mho": "℧",
        r"\eth": "ð",
        r"\neg": "¬",
        r"\lnot": "¬",
        r"\land": "∧",
        r"\lor": "∨",
        r"\veebar": "⊻",
        r"\barwedge": "⊼",
        r"\curlyvee": "⋎",
        r"\curlywedge": "⋏",
        r"\sqcup": "⊔",
        r"\sqcap": "⊓",
        r"\uplus": "⊎",
        r"\wr": "≀",
        r"\amalg": "⨿",
        r"\diamond": "⋄",
        r"\triangle": "△",
        r"\triangledown": "▽",
        r"\triangleleft": "◁",
        r"\triangleright": "▷",
        r"\bigtriangleup": "△",
        r"\bigtriangledown": "▽",
        r"\square": "□",
        r"\blacksquare": "■",
        r"\lozenge": "◊",
        r"\blacklozenge": "⧫",
        r"\bigstar": "★",
        r"\checkmark": "✓",
        r"\maltese": "✠",
        r"\top": "⊤",
        r"\bot": "⊥",
        r"\surd": "√",
        r"\flat": "♭",
        r"\natural": "♮",
        r"\sharp": "♯",
        r"\clubsuit": "♣",
        r"\diamondsuit": "♢",
        r"\heartsuit": "♡",
        r"\spadesuit": "♠",
        r"\dagger": "†",
        r"\ddagger": "‡",
        r"\dag": "†",
        r"\ddag": "‡",
        r"\S": "§",
        r"\P": "¶",
        r"\copyright": "©",
        r"\$": "$",
        r"\ll": "≪",
        r"\gg": "≫",
        r"\doteq": "≐",
        r"\doteqdot": "≑",
        r"\asymp": "≍",
        r"\bowtie": "⋈",
        r"\models": "⊨",
        r"\vdash": "⊢",
        r"\dashv": "⊣",
        r"\smile": "⌣",
        r"\frown": "⌢",
        r"\prec": "≺",
        r"\succ": "≻",
        r"\preceq": "⪯",
        r"\succeq": "⪰",
        r"\subsetneq": "⊊",
        r"\supsetneq": "⊋",
        r"\sqsubset": "⊏",
        r"\sqsupset": "⊐",
        r"\sqsubseteq": "⊑",
        r"\sqsupseteq": "⊒",
        r"\approxeq": "≊",
        r"\ncong": "≇",
        r"\triangleq": "≜",
        r"\circeq": "≗",
        r"\bumpeq": "≏",
        r"\between": "≬",
        r"\pitchfork": "⋔",
        r"\varpropto": "∝",
        r"\mid": "∣",
        r"\nmid": "∤",
        r"\colon": ":",
        r"\longrightarrow": "⟶",
        r"\longleftarrow": "⟵",
        r"\longleftrightarrow": "⟷",
        r"\Longrightarrow": "⟹",
        r"\Longleftarrow": "⟸",
        r"\Longleftrightarrow": "⟺",
        r"\longmapsto": "⟼",
        r"\implies": "⟹",
        r"\impliedby": "⟸",
        r"\iff": "⟺",
        r"\nearrow": "↗",
        r"\searrow": "↘",
        r"\swarrow": "↙",
        r"\nwarrow": "↖",
        r"\nrightarrow": "↛",
        r"\nleftarrow": "↚",
        r"\nRightarrow": "⇏",
        r"\nLeftarrow": "⇍",
        r"\nleftrightarrow": "↮",
        r"\rightsquigarrow": "⇝",
        r"\leadsto": "⇝",
        r"\rightrightarrows": "⇉",
        r"\leftleftarrows": "⇇",
        r"\upuparrows": "⇈",
        r"\downdownarrows": "⇊",
        r"\rightharpoonup": "⇀",
        r"\rightharpoondown": "⇁",
        r"\leftharpoonup": "↼",
        r"\leftharpoondown": "↽",
        r"\rightleftharpoons": "⇌",
        r"\curvearrowright": "↷",
        r"\curvearrowleft": "↶",
        r"\circlearrowright": "↻",
        r"\circlearrowleft": "↺",
        r"\hookleftarrow": "↩",
        r"\twoheadrightarrow": "↠",
        r"\twoheadleftarrow": "↞",
        r"\rightarrowtail": "↣",
        r"\leftarrowtail": "↢",
        r"\looparrowright": "↬",
        r"\looparrowleft": "↫",
        r"\multimap": "⊸",
        r"\dotsb": "⋯",
        r"\dotsc": "…",
        r"\dotsi": "⋯",
        r"\dotsm": "⋯",
        r"\dotso": "…",
        r"\iddots": "⋰",
        r"\bigsqcup": "⨆",
        r"\bigvee": "⋁",
        r"\bigwedge": "⋀",
        r"\bigodot": "⨀",
        r"\biguplus": "⨄",
        r"\vert": "|",
        r"\Vert": "‖",
        r"\lvert": "|",
        r"\rvert": "|",
        r"\lVert": "‖",
        r"\rVert": "‖",
        r"\lceil": "⌈",
        r"\rceil": "⌉",
        r"\lfloor": "⌊",
        r"\rfloor": "⌋",
        r"\lbrace": "{",
        r"\rbrace": "}",
        r"\lbrack": "[",
        r"\rbrack": "]",
        r"\lgroup": "(",
        r"\rgroup": ")",
        r"\backslash": "\\",
    }
)

#: 直立函数名
_FUNCTIONS = (
    "sin",
    "cos",
    "tan",
    "cot",
    "sec",
    "csc",
    "arcsin",
    "arccos",
    "arctan",
    "sinh",
    "cosh",
    "tanh",
    "log",
    "ln",
    "lg",
    "exp",
    "max",
    "min",
    "sup",
    "inf",
    "det",
    "dim",
    "gcd",
    "arg",
    "deg",
    "bmod",
    "operatorname",
)

#: 大型算子（渲染为放大符号，上下限堆叠；scale 接近 KaTeX display 字号）
_BIG_OPS = {
    r"\sum": ("∑", True, 1.7),
    r"\prod": ("∏", True, 1.7),
    r"\coprod": ("∐", True, 1.7),
    r"\int": ("∫", False, 2.0),
    r"\iint": ("∬", False, 2.0),
    r"\iiint": ("∭", False, 2.0),
    r"\oint": ("∮", False, 2.0),
    r"\bigcup": ("⋃", True, 1.7),
    r"\bigcap": ("⋂", True, 1.7),
    r"\bigoplus": ("⨁", True, 1.7),
    r"\bigotimes": ("⨂", True, 1.7),
}

#: 重音（base, kind）
_ACCENTS = {
    r"\vec": "vec",
    r"\hat": "hat",
    r"\widehat": "hat",
    r"\bar": "bar",
    r"\overline": "bar",
    r"\dot": "dot",
    r"\ddot": "ddot",
    r"\tilde": "tilde",
    r"\widetilde": "tilde",
    r"\acute": "acute",
    r"\grave": "grave",
    r"\breve": "breve",
    r"\check": "check",
    r"\mathring": "ring",
    r"\overrightarrow": "overrightarrow",
    r"\overleftarrow": "overleftarrow",
    r"\overleftrightarrow": "overleftrightarrow",
}

#: 间距命令 → em 倍数
_SPACES = {
    r"\,": 0.167,
    r"\:": 0.222,
    r"\;": 0.278,
    r"\!": -0.167,
    r"\quad": 1.0,
    r"\qquad": 2.0,
    r"\ ": 0.333,
}

_DELIMS = {
    "(": "(",
    ")": ")",
    "[": "[",
    "]": "]",
    "|": "|",
    r"\{": "{",
    r"\}": "}",
    r"\langle": "⟨",
    r"\rangle": "⟩",
    r"\|": "‖",
    ".": "",
    r"\lvert": "|",
    r"\rvert": "|",
    r"\vert": "|",
    r"\lVert": "‖",
    r"\rVert": "‖",
    r"\Vert": "‖",
    r"\lceil": "⌈",
    r"\rceil": "⌉",
    r"\lfloor": "⌊",
    r"\rfloor": "⌋",
    r"\lbrace": "{",
    r"\rbrace": "}",
    r"\lbrack": "[",
    r"\rbrack": "]",
    r"\lgroup": "(",
    r"\rgroup": ")",
    r"\backslash": "\\",
    r"\uparrow": "↑",
    r"\downarrow": "↓",
    r"\updownarrow": "↕",
    r"\Uparrow": "⇑",
    r"\Downarrow": "⇓",
    r"\Updownarrow": "⇕",
}

#: 矩阵类环境及其左右定界符
_MATRIX_ENVS = (
    "matrix",
    "pmatrix",
    "bmatrix",
    "Bmatrix",
    "vmatrix",
    "Vmatrix",
    "cases",
    "cases*",
    "dcases",
    "rcases",
    "smallmatrix",
    "align",
    "align*",
    "aligned",
    "aligned*",
    "gather",
    "gathered",
    "gather*",
    "multline",
    "multline*",
    "split",
    "alignat",
    "alignat*",
    "flalign",
    "flalign*",
    "equation",
    "equation*",
    "displaymath",
    "math",
)
_MATRIX_DELIMS = {
    "matrix": ("", ""),
    "pmatrix": ("(", ")"),
    "bmatrix": ("[", "]"),
    "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"),
    "Vmatrix": ("‖", "‖"),
    "cases": ("{", ""),
    "cases*": ("{", ""),
    "dcases": ("{", ""),
    "rcases": ("", "}"),
    "smallmatrix": ("", ""),
    "gather": ("", ""),
    "gathered": ("", ""),
    "gather*": ("", ""),
    "multline": ("", ""),
    "multline*": ("", ""),
    "split": ("", ""),
    "alignat": ("", ""),
    "alignat*": ("", ""),
    "flalign": ("", ""),
    "flalign*": ("", ""),
    "equation": ("", ""),
    "equation*": ("", ""),
    "displaymath": ("", ""),
    "math": ("", ""),
    "aligned": ("", ""),
    "array": ("", ""),
    "substack": ("", ""),
}

#: ``align`` 系环境：奇数列右对齐、偶数列左对齐（TeX 语义）
_ALIGN_ENVS = (
    "align",
    "aligned",
    "align*",
    "aligned*",
    "split",
    "alignat",
    "alignat*",
    "flalign",
    "flalign*",
)
#: 居中多行环境（``&`` 仅分列，不参与对齐）
_CENTER_ENVS = (
    "gather",
    "gathered",
    "gather*",
    "multline",
    "multline*",
    "equation",
    "equation*",
    "displaymath",
    "math",
)

#: ``\big`` 系列缩放倍率
_BIG_DELIM_SCALES = {
    r"\big": 1.2,
    r"\Big": 1.6,
    r"\bigg": 2.0,
    r"\Bigg": 2.4,
}

#: 极限算子（显示时上下限堆叠；与 KaTeX 的 limits 算子一致）
_LIMIT_OPERATORS = (
    "lim",
    "limsup",
    "liminf",
    "max",
    "min",
    "sup",
    "inf",
    "det",
    "gcd",
    "Pr",
    "argmax",
    "argmin",
)

#: ``\text`` 类命令 → (斜体, 粗体, 字体族)
_TEXT_STYLES = {
    r"\text": (False, False, None),
    r"\textrm": (False, False, None),
    r"\textnormal": (False, False, None),
    r"\textup": (False, False, None),
    r"\mathrm": (False, False, None),
    r"\mathnormal": (False, False, None),
    r"\mathbf": (False, True, None),
    r"\textbf": (False, True, None),
    r"\mathbfit": (True, True, None),
    r"\boldsymbol": (True, True, None),
    r"\bm": (True, True, None),
    r"\mathit": (True, False, None),
    r"\textit": (True, False, None),
    r"\textsl": (True, False, None),
    r"\mathsf": (False, False, "sans"),
    r"\textsf": (False, False, "sans"),
    r"\mathtt": (False, False, "mono"),
    r"\texttt": (False, False, "mono"),
}

#: ``\cancel`` 系列
_CANCEL_KINDS = {
    r"\cancel": "cancel",
    r"\bcancel": "bcancel",
    r"\xcancel": "xcancel",
    r"\sout": "sout",
}

#: 颜色名（KaTeX 基础色 + 常用扩展）
_COLOR_NAMES = {
    "black": "#000000",
    "white": "#ffffff",
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "cyan": "#00ffff",
    "magenta": "#ff00ff",
    "yellow": "#ffff00",
    "orange": "#ff8000",
    "gray": "#808080",
    "grey": "#808080",
    "purple": "#800080",
    "olive": "#808000",
    "teal": "#008080",
    "navy": "#000080",
    "maroon": "#800000",
    "lime": "#00ff00",
    "aqua": "#00ffff",
    "fuchsia": "#ff00ff",
    "silver": "#c0c0c0",
    "pink": "#ffc0cb",
    "brown": "#a52a2a",
}

#: ``\not`` 常见组合 → 取反后的单一 Unicode 字符
_NOT_COMBOS = {
    "=": "≠",
    "<": "≮",
    ">": "≯",
    "∈": "∉",
    "∋": "∌",
    "⊂": "⊄",
    "⊃": "⊅",
    "⊆": "⊈",
    "⊇": "⊉",
    "≡": "≢",
    "∼": "≁",
    "≃": "≄",
    "≈": "≉",
    "≅": "≇",
    "≤": "≰",
    "≥": "≱",
    "≺": "⊀",
    "≻": "⊁",
    "∃": "∄",
    "∥": "∦",
    "∣": "∤",
    "⊢": "⊬",
    "⊨": "⊭",
    "≍": "≭",
}


# ===================================================================== 预处理
#: ``\text{}`` 内的转义序列 → 字面字符
_TEXT_ESCAPES = {
    "%": "%",
    "&": "&",
    "#": "#",
    "_": "_",
    "$": "$",
    "{": "{",
    "}": "}",
    "\\": "\\",
    " ": " ",
}

#: ``\\[2pt]`` 行距参数（矩阵行尾）→ 还原为 ``\\``
_ROW_SPACING_RE = re.compile(r"\\\\\s*\[[^\]]*\]")
#: 编号 / 标签等在渲染时无意义的命令（直接移除）
_ENV_NOISE_RE = re.compile(r"\\(?:nonumber|notag|hfill|allowbreak)\b")
_LABEL_RE = re.compile(r"\\label\s*\{[^}]*\}")


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


#: 宏定义的触发串：整段文本一个都不含时无需扫描（见 ``_collect_macros``）
_MACRO_TRIGGERS = (r"\newcommand", r"\renewcommand", r"\DeclareMathOperator", r"\def")


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


#: ``\left`` / ``\right`` 定界符镜像表（自动配平用，键为源码中的原始定界符）
_DELIM_MIRRORS = {
    "(": ")",
    "[": "]",
    "{": r"\}",
    "|": "|",
    ".": ".",
    r"\{": r"\}",
    r"\}": r"\}",
    r"\|": r"\|",
    r"\langle": r"\rangle",
    r"\rangle": r"\rangle",
    r"\lvert": r"\rvert",
    r"\rvert": r"\rvert",
    r"\vert": r"\vert",
    r"\lVert": r"\rVert",
    r"\rVert": r"\rVert",
    r"\Vert": r"\Vert",
    r"\lceil": r"\rceil",
    r"\rceil": r"\rceil",
    r"\lfloor": r"\rfloor",
    r"\rfloor": r"\rfloor",
    r"\lbrace": r"\rbrace",
    r"\rbrace": r"\rbrace",
    r"\lbrack": r"\rbrack",
    r"\rbrack": r"\rbrack",
    r"\lgroup": r"\rgroup",
    r"\rgroup": r"\rgroup",
    r"\uparrow": r"\downarrow",
    r"\downarrow": r"\downarrow",
    r"\updownarrow": r"\updownarrow",
    r"\Uparrow": r"\Downarrow",
    r"\Downarrow": r"\Downarrow",
    r"\Updownarrow": r"\Updownarrow",
    r"\backslash": r"\backslash",
}

#: ``\left`` / ``\right`` 命令匹配（负向后瞻避免误伤 ``\leftarrow`` 系列，
#: 负向前瞻避免匹配 ``\\left`` 这种行分隔符后紧跟文本的情况）
_DELIM_CMD_RE = re.compile(r"(?<!\\)\\(left|right)(?![A-Za-z])")


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


def _alphabet_map(
    upper_base: int,
    overrides: dict,
    lower_base: Optional[int] = None,
    with_digits: bool = False,
) -> dict:
    """构造字母表映射（Unicode 数学字母，处理保留码位空洞）。"""
    mapping: dict = {}
    for index in range(26):
        char = chr(ord("A") + index)
        mapping[char] = chr(overrides.get(char, upper_base + index))
    if lower_base is not None:
        for index in range(26):
            char = chr(ord("a") + index)
            mapping[char] = chr(overrides.get(char, lower_base + index))
    if with_digits:
        for index in range(10):
            mapping[str(index)] = chr(0x1D7D8 + index)
    return mapping


#: 数学字母表命令 → Unicode 码位映射
_ALPHABETS = {
    r"\mathbb": _alphabet_map(
        0x1D538,
        {
            "C": 0x2102,
            "H": 0x210D,
            "N": 0x2115,
            "P": 0x2119,
            "Q": 0x211A,
            "R": 0x211D,
            "Z": 0x2124,
        },
        0x1D552,
        with_digits=True,
    ),
    r"\mathcal": _alphabet_map(
        0x1D49C,
        {
            "B": 0x212C,
            "E": 0x2130,
            "F": 0x2131,
            "H": 0x210B,
            "I": 0x2110,
            "L": 0x2112,
            "M": 0x2133,
            "R": 0x211B,
        },
        0x1D4B6,
    ),
    r"\mathfrak": _alphabet_map(
        0x1D504,
        {
            "C": 0x212D,
            "H": 0x210C,
            "I": 0x2111,
            "R": 0x211C,
            "Z": 0x2128,
        },
        0x1D51E,
    ),
}
_ALPHABETS[r"\mathcal"].update({"e": "\u212f", "g": "\u210a", "o": "\u2134"})


class _ParseError(Exception):
    """公式语法不受支持。"""


# ===================================================================== 解析
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


#: 文本模式里的空白串（TeX 把连续空白折叠成一个空格）
_TEXT_SPACE_RE = re.compile(r"[ \t\r\n\f]+")


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

    **解析必须线性**：原先的 ``r"\\s*([+-]?[\\d.]+)\\s*([a-zA-Z]*)\\s*$"`` 里
    三个可回溯量词相邻又带尾锚 ``$``，在「有数字段和单位段、没有收尾空格」的
    长输入上会从中间 ``\\s*`` 的每个回溯位置重试 → **O(n²)**。实测
    ``\\hspace{1} + 空格×N + a×N}`` 的 N 从 10k 翻到 60k，耗时
    282ms → 1135ms → 4517ms → 10223ms（干净的二次），单个公式就能把 GUI
    线程按住十秒。

    改成「单位段先行切出 + 数字段用贪心前缀」，两遍都线性，且对同样输入
    结果完全一致。
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

    # -- 基础 -------------------------------------------------------------
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

    # -- 原子与上下标 -------------------------------------------------------
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

    # -- 命令 -------------------------------------------------------------
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


# ===================================================================== 布局
#: 优先使用的数学字体（含 Unicode 数学斜体码位）；无数学字体时回退普通衬线
_MATH_FONT_NAMES = ("Cambria Math", "STIX Two Math", "Latin Modern Math")
_FALLBACK_FONT_NAMES = ("Times New Roman", "Georgia", "DejaVu Serif")

_FAMILIES: Optional[list] = None
#: 选中字体是否支持 Unicode 数学斜体码位
_USE_MATH_ITALIC = False
#: 字号 → (上伸参考高度, 下伸参考高度)
_REF_METRICS: dict = {}

#: ASCII 字母 → 数学斜体码位（h 用 ℎ U+210E，其余为保留码位之外的正序）
_MATH_ITALIC_MAP = {
    **{chr(ord("A") + i): chr(0x1D434 + i) for i in range(26)},
    **{chr(ord("a") + i): chr(0x210E if i == 7 else 0x1D44E + i) for i in range(26)},
}
#: 小写希腊字母 → 数学斜体码位（大写希腊保持直立，与 TeX 默认一致）
_MATH_ITALIC_GREEK = "αβγδεζηθικλμνξοπρςστυφχψω"
_MATH_ITALIC_MAP.update(
    {ch: chr(0x1D6FC + i) for i, ch in enumerate(_MATH_ITALIC_GREEK)}
)


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
    计算参考度量。
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


#: 字号 → (x-height, 大写高度)：上下标位置量化用（同类字形保持同一水平线）
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
        painter.drawPolyline(QPolygonF([
            QPointF(x, top + self.body.h * 0.45),
            QPointF(x + self.hook * 0.35, bottom),
            QPointF(x + self.hook, top),
        ]))
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
            painter.drawPolyline(QPolygonF([
                QPointF(x + self.w - 0.18 * self.size, top - 0.06 * self.size),
                QPointF(x + self.w - 0.05 * self.size, top),
                QPointF(x + self.w - 0.18 * self.size, top + 0.06 * self.size),
            ]))
        elif self.kind in ("hat", "tilde"):
            spread = 0.15 if self.kind == "hat" else 0.08
            height = 0.05 if self.kind == "hat" else 0.07
            painter.drawPolyline(QPolygonF([
                QPointF(x + self.w * spread, top + 0.04 * self.size),
                QPointF(mid, top - height * self.size),
                QPointF(x + self.w * (1 - spread), top + 0.04 * self.size),
            ]))
        elif self.kind in ("acute", "grave"):
            sign = 1 if self.kind == "acute" else -1
            painter.drawLine(
                QPointF(mid - sign * 0.08 * self.size, top + 0.05 * self.size),
                QPointF(mid + sign * 0.08 * self.size, top - 0.05 * self.size),
            )
        elif self.kind == "breve":
            painter.drawPolyline(QPolygonF([
                QPointF(x + self.w * 0.2, top - 0.03 * self.size),
                QPointF(mid, top + 0.05 * self.size),
                QPointF(x + self.w * 0.8, top - 0.03 * self.size),
            ]))
        elif self.kind == "check":
            painter.drawPolyline(QPolygonF([
                QPointF(x + self.w * 0.2, top + 0.05 * self.size),
                QPointF(mid, top - 0.05 * self.size),
                QPointF(x + self.w * 0.8, top + 0.05 * self.size),
            ]))
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
            painter.drawPolyline(QPolygonF([
                QPointF(x + self.w - head, y - head * 0.6),
                QPointF(x + self.w, y),
                QPointF(x + self.w - head, y + head * 0.6),
            ]))
        if self.kind in ("overleftarrow", "overleftrightarrow"):
            painter.drawLine(QPointF(x, y), QPointF(x + self.w, y))
            painter.drawPolyline(QPolygonF([
                QPointF(x + head, y - head * 0.6),
                QPointF(x, y),
                QPointF(x + head, y + head * 0.6),
            ]))


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
            painter.drawPolyline(QPolygonF([
                QPointF(tip - head, y - head * 0.6),
                QPointF(tip, y),
                QPointF(tip - head, y + head * 0.6),
            ]))
        else:
            tip = left
            painter.drawPolyline(QPolygonF([
                QPointF(tip + head, y - head * 0.6),
                QPointF(tip, y),
                QPointF(tip + head, y + head * 0.6),
            ]))
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


# ===================================================================== 构建
#: TeX 风格间距（em）：关系符两侧、二元运算符两侧、标点后
_RELATION_ATOMS = set("=<>≤≥≠≈≡∼≃∝∈∉⊂⊆⊃⊇→←↔⇒⇐⇔↦∥⊥")
_BINARY_ATOMS = set("+−-×÷·⋅∗±∓∪∩∖⊕⊗")
_UNARY_ATOMS = set("+−-")
_PUNCT_ATOMS = set(",;")
_OPEN_DELIMS = set("([{⟨")
_RELATION_SPACE = 5.0 / 18.0
_BINARY_SPACE = 4.0 / 18.0
_PUNCT_SPACE = 3.0 / 18.0


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


# ===================================================================== 渲染
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
        # **兄弟处理器不接兄弟块内抛出的异常**，所以这三层重试里每一层都
        # 必须自己写全 ``except Exception``：原先只接 ``_ParseError``，于是
        # 「严格解析因浅层未知命令失败 -> 进容错重试 -> 容错路径深递归爆栈」
        # 这条链上抛出的 ``RecursionError`` 会从上一层的处理块里穿出去，
        # 没人接。而 ``render_formula`` 的对外契约是「不支持时返回 None」。
        #
        # 实测阈值（recursionlimit=1000）：``\zzz`` + 400 层花括号即逃逸；
        # 不带未知命令的纯深嵌套反而被最外层的 ``except Exception`` 兜住
        # —— 因为严格解析先撞限，抛的正是 ``RecursionError``。只要先浅层
        # 失败进容错分支，就失守。
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
        # ``\hspace{1e400}`` 这类会让 ``_dimension_em`` 返回 inf，一路加进
        # ``box.w``。下面 ``int(inf)`` 抛OverflowError，而这一行**在模块里
        # 唯一没有 try 兜底的输出级**（preprocess / parse / build 三级都有），
        # 异常会顺着 ``_stream_timer.timeout -> _render_into -> _embed_math``
        # 冲出 Qt 回调 = **0xC0000409 零traceback 终止**。
        return None
    pad = max(1.0, pt * 0.2)
    width = int(box.w + 2 * pad) + 1
    height = int(box.h + 2 * pad) + 1
    # **尺寸上限**：``box.w`` 只有下界没有上界（``_SpaceBox`` 只对负值
    # ``max(0.0, ...)``），而 ``\hspace`` 的数值参数直接进 ``box.w``。实测
    # ``x\hspace{1000000em}x`` 会**真实分配 3.1 GiB** 缓冲，
    # ``10000000em`` 让 QImage 返回 null 而本函数把它当成功交出去 ——
    # 调用方的 ``if image is None`` 降级分支因此被绕过（``setWidth(0.0)``）。
    # 超过上限按「不支持」处理，走调用方既有的降级路径。
    if width > _MAX_DIM or height > _MAX_DIM:
        return None
    if width * height > _MAX_PIXELS:
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


# ===================================================================== 提取
#: 行内公式扫描的特殊字符（其余字符整段跳过，避免逐字符 Python 循环）
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

    返回 ``(处理后的文本, [(latex, display), ...])``；代码围栏内的内容
    不提取。多行 ``$$`` / ``\\[`` 块与 ``\\begin{...}`` 环境按块级公式
    处理（环境保留 ``&``/``\\\\`` 结构交给渲染器对齐）；文档中的
    ``\\newcommand`` / ``\\def`` 定义会被收集并按公式展开。未找到闭合符
    的块级公式**不吞内容**：开启行与中间行原样输出（行内公式仍可提取），
    与流式增量路径的降级显示语义一致。

    :param text: Markdown 源文
    :param mark: 公式占位模板（``{}`` 为序号位）
    :param macros: 可选的文档级宏表（外部预收集）
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
            if stripped.startswith(fence_mark):
                in_fence = False
            i += 1
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = True
            fence_mark = stripped[:3]
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
