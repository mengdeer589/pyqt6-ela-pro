"""Tests for math_lite LaTeX compatibility batch.

Covers: macro expansion, tolerant rendering, common commands / symbols,
environments, delimiters, limit operators, fonts / colors / spacing and
the viewer-level extraction changes.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QImage, QTextDocument

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer
from pyqt6_ela_pro.math_lite import _Parser, _atom_text, render_formula

COLOR = QColor("#202020")

CORPUS = [
    # 结构 / 框线
    r"\boxed{x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}}",
    r"\underline{x + y}",
    r"\fbox{x}",
    r"\colorbox{yellow}{x}",
    r"\cancel{x} \bcancel{y} \xcancel{z} \sout{w}",
    r"\overset{?}{=}",
    r"a \underset{n}{\sim} b",
    r"\stackrel{\text{def}}{=}",
    r"A \xrightarrow{f} B",
    r"A \xleftarrow[g]{} B",
    # 重音 / 花括号
    r"\overrightarrow{AB}",
    r"\overleftarrow{CD}",
    r"\overleftrightarrow{EF}",
    r"\widetilde{xyz}",
    r"\overbrace{a+b+c}^{n}",
    r"\underbrace{a+b+c}_{n}",
    r"\acute{a} \grave{b} \breve{c} \check{d} \mathring{e}",
    # 分式族 / 堆叠
    r"\cfrac{1}{1+\cfrac{1}{1+x}}",
    r"\genfrac{(}{)}{0}{}{a}{b}",
    # 符号
    r"\{x \mid x > 0\}",
    r"f\colon A \to B",
    r"a = b \implies c = d",
    r"a \iff b",
    r"a \impliedby b",
    r"a \not= b",
    r"x \not\in A",
    r"a \nmid b",
    r"a \le b \ge c",
    r"\ell, \hbar, \imath, \jmath, \Re, \Im, \wp, \aleph",
    r"\checkmark \square \blacksquare \dagger \S \P \$",
    r"a \rightleftharpoons b,\ x \rightharpoonup y",
    r"a \longrightarrow b \Longleftrightarrow c",
    r"\nearrow \searrow \swarrow \nwarrow",
    r"\bigsqcup \bigvee \bigwedge \bigodot",
    # 定界符
    r"\big( \frac{a}{b} \big)",
    r"\Bigl[ x \Bigr]",
    r"\bigg\{ x \bigg\}",
    r"\Bigg( y \Bigg)",
    r"\lvert x \rvert \lVert y \rVert",
    r"\lceil x \rceil \lfloor y \rfloor",
    r"\lbrace x \rbrace \lbrack y \rbrack",
    r"\left\{ x \middle| x > 0 \right\}",
    r"\left\lfloor x \right\rfloor",
    # 极限算子 / 大型算子
    r"\max_{x \in X} f(x)",
    r"\sup_{n} a_n",
    r"\limsup_{n \to \infty} a_n",
    r"\liminf_{n} a_n",
    r"\det_{A} B",
    r"\gcd(a, b)",
    r"\Pr_{X}[A]",
    r"\operatorname*{arg\,max}_{x} f(x)",
    r"\displaystyle \sum_{i=1}^n i",
    r"\sum\limits_{i=1}^n i",
    r"\int\limits_0^1 x\,dx",
    r"\sum_{\substack{i=1 \\ j=2}} x_{ij}",
    # 字体 / 文本
    r"\boldsymbol{\alpha} + \beta",
    r"\bm{v}",
    r"\textbf{hello}",
    r"\textit{x}",
    r"\texttt{code}",
    r"\textsf{sans}",
    r"\textnormal{abc}",
    r"\text{增长 50\% 与 A \& B}",
    r"\textcolor{red}{x}",
    r"\color{blue} x + y",
    # 间距 / 占位
    r"a \hspace{2em} b",
    r"a \kern{3pt} b",
    r"a \phantom{xxxx} b",
    r"a \hphantom{x} b",
    r"\vphantom{\int} x",
    r"\mathstrut x",
    # 环境
    r"\begin{gather} a = b \\ c = d \end{gather}",
    r"\begin{gathered} a = b \\ c = d \end{gathered}",
    r"\begin{multline} a = b \\ + c \end{multline}",
    r"\begin{split} a &= b \\ c &= d \end{split}",
    r"\begin{alignat}{2} x &= 1 & y &= 2 \end{alignat}",
    r"\begin{aligned}[t] x &= 1 \\ y &= 2 \end{aligned}",
    r"\begin{smallmatrix} a & b \\ c & d \end{smallmatrix}",
    r"\begin{dcases} x & x > 0 \\ -x & x < 0 \end{dcases}",
    r"\begin{rcases} x & x > 0 \\ -x & x < 0 \end{rcases}",
    r"\begin{cases*} x & x > 0 \\ -x & x < 0 \end{cases*}",
    r"\begin{equation} a = b \end{equation}",
    r"\begin{array}{cc} a & b \\ \hline c & d \end{array}",
    r"\begin{cases} x & x>0 \\[2pt] -x & x<0 \end{cases}",
    r"\begin{align} a &= b \nonumber \\ c &= d \end{align}",
    # 宏
    r"\newcommand{\R}{\mathbb{R}} \R^n",
    r"\def\E{\mathbb{E}} \E[X]",
    r"\newcommand{\norm}[1]{\left\|#1\right\|} \norm{v}",
    r"\DeclareMathOperator*{\argmax}{arg\,max} \argmax_x f(x)",
    # 公式编号
    r"a = b \tag{1}",
    r"a = b \tag {2}",
    r"a = b \tag*{A}",
    # 多行（无环境）
    r"a = b \\ c = d",
]


@pytest.mark.parametrize("latex", CORPUS)
def test_corpus_renders(latex):
    image = render_formula(latex, COLOR, 14.0, True)
    assert image is not None, latex


class TestTolerantRendering:
    def test_unknown_command_renders_literally(self):
        report = {}
        image = render_formula(r"x \foobar y", COLOR, 14.0, report=report)
        assert image is not None
        assert report["degraded"] is True

    def test_known_formula_not_degraded(self):
        report = {}
        image = render_formula(r"x^2 + \alpha", COLOR, 14.0, report=report)
        assert image is not None
        assert report["degraded"] is False
        assert report["repaired"] is False

    def test_unclosed_left_is_repaired(self):
        """缺 ``\\right`` 的定界符自动配平后仍可渲染。"""
        report = {}
        image = render_formula(r"\left( x", COLOR, 14.0, report=report)
        assert image is not None
        assert report["repaired"] is True

    def test_orphan_right_is_removed(self):
        """孤立 ``\\right`` 直接移除后渲染。"""
        report = {}
        image = render_formula(r"x \right) y", COLOR, 14.0, report=report)
        assert image is not None
        assert report["repaired"] is True

    def test_llm_formula_missing_right_renders(self):
        """大模型常产出缺 ``\\right`` 的公式：自动修复后正常渲染。"""
        source = (
            r"\rho \left( \frac{\partial}{\partial t} \left( e +"
            r" \frac{\mathbf{V}^2}{2} \right) + \nabla \cdot \left( \mathbf{V}"
            r" (e + \frac{p}{\rho} + \frac{\mathbf{V}^2}{2}) \right) = 0"
        )
        report = {}
        image = render_formula(source, COLOR, 12.0, True, report=report)
        assert image is not None
        assert report["repaired"] is True

    def test_valid_delimiters_not_repaired(self):
        report = {}
        image = render_formula(
            r"\left( a \left[ b \right] \right)", COLOR, 14.0, report=report
        )
        assert image is not None
        assert report["repaired"] is False
        # ``\leftarrow`` 不应被误认为 ``\left``
        report2 = {}
        arrow = render_formula(r"a \leftarrow b", COLOR, 14.0, report=report2)
        assert arrow is not None
        assert report2["repaired"] is False

    def test_unclosed_group_fails(self):
        assert render_formula(r"x^{", COLOR, 14.0) is None

    def test_malformed_display_math_has_no_render_issue(self, qapp):
        """viewer 层：修复后不再记录渲染问题，文档中无公式源码残留。"""
        viewer = ElaMarkdownViewer()
        viewer.setMarkdown("$$\n\\rho \\left( x + \\frac{a}{b} = 0\n$$")
        assert viewer.renderIssues() == []
        assert r"\rho" not in viewer.document().toPlainText()
        viewer.deleteLater()


class TestMacros:
    def test_newcommand_with_args(self):
        plain = render_formula(r"\left\|v\right\|", COLOR, 14.0)
        macro = render_formula(
            r"\newcommand{\norm}[1]{\left\|#1\right\|} \norm{v}", COLOR, 14.0
        )
        assert plain is not None and macro is not None
        assert abs(plain.width() - macro.width()) <= 1

    def test_def_expands(self):
        assert render_formula(r"\def\R{\mathbb{R}} \R", COLOR, 14.0) is not None

    def test_declare_math_operator(self):
        image = render_formula(
            r"\DeclareMathOperator*{\argmax}{arg\,max} \argmax_x f(x)",
            COLOR,
            14.0,
            True,
        )
        assert image is not None

    def test_viewer_document_level_macro(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown("\\newcommand{\\R}{\\mathbb{R}}\n\n公式 $\\R^n$ 结束")

        assert "R" not in v.document().toPlainText()
        images = _images(v)
        assert len(images) == 1
        v.deleteLater()


class TestEnvironments:
    def test_gather_two_rows_taller(self):
        one = render_formula(r"\begin{gather} a = b \end{gather}", COLOR, 14.0, True)
        two = render_formula(
            r"\begin{gather} a = b \\ c = d \end{gather}", COLOR, 14.0, True
        )
        assert one is not None and two is not None
        assert two.height() > one.height()

    def test_smallmatrix_smaller_than_matrix(self):
        small = render_formula(
            r"\begin{smallmatrix} a & b \\ c & d \end{smallmatrix}", COLOR, 14.0
        )
        normal = render_formula(
            r"\begin{matrix} a & b \\ c & d \end{matrix}", COLOR, 14.0
        )
        assert small is not None and normal is not None
        assert small.width() < normal.width()

    def test_aligned_position_argument(self):
        assert (
            render_formula(
                r"\begin{aligned}[t] x &= 1 \\ y &= 2 \end{aligned}", COLOR, 14.0
            )
            is not None
        )

    def test_hline_renders(self):
        assert (
            render_formula(
                r"\begin{array}{cc} a & b \\ \hline c & d \end{array}", COLOR, 14.0
            )
            is not None
        )

    def test_viewer_standalone_align_keeps_rows(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown("\\begin{align}\n a &= b \\\\ c &= d\n\\end{align}")

        text = v.document().toPlainText()
        assert "begin" not in text and "align" not in text
        images = _images(v)
        assert len(images) == 1
        assert images[0].height() / 2 > 30
        v.deleteLater()

    def test_viewer_standalone_cases_extracted(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown("\\begin{cases}\n x & x>0 \\\\ -x & x<0\n\\end{cases}")

        assert "cases" not in v.document().toPlainText()
        assert len(_images(v)) == 1
        v.deleteLater()


class TestStructures:
    def test_boxed_larger_than_bare(self):
        bare = render_formula(r"x^2", COLOR, 14.0)
        boxed = render_formula(r"\boxed{x^2}", COLOR, 14.0)
        assert bare is not None and boxed is not None
        assert boxed.width() > bare.width()
        assert boxed.height() > bare.height()

    def test_underbrace_label_grows_height(self):
        bare = render_formula(r"\underbrace{a+b}", COLOR, 14.0)
        labeled = render_formula(r"\underbrace{a+b}_{n}", COLOR, 14.0)
        assert bare is not None and labeled is not None
        assert labeled.height() > bare.height()

    def test_xrightarrow_label_grows_width(self):
        bare = render_formula(r"A \xrightarrow{} B", COLOR, 14.0)
        labeled = render_formula(r"A \xrightarrow{\text{long label}} B", COLOR, 14.0)
        assert bare is not None and labeled is not None
        assert labeled.width() > bare.width()

    def test_big_delim_larger_than_plain(self):
        plain = render_formula(r"(x)", COLOR, 14.0)
        big = render_formula(r"\Big(x\Big)", COLOR, 14.0)
        assert plain is not None and big is not None
        assert big.height() > plain.height()

    def test_limit_operator_stacks(self):
        side = render_formula(r"\max f", COLOR, 14.0)
        stacked = render_formula(r"\max_{x} f", COLOR, 14.0)
        assert side is not None and stacked is not None
        assert stacked.height() > side.height()

    def test_operatorname_star_stacks(self):
        side = render_formula(r"\operatorname{argmax} f", COLOR, 14.0)
        stacked = render_formula(r"\operatorname*{argmax}_{x} f", COLOR, 14.0)
        assert side is not None and stacked is not None
        assert stacked.height() > side.height()

    def test_nolimits_keeps_side_script(self):
        stacked = render_formula(r"\sum_{i} x", COLOR, 14.0)
        side = render_formula(r"\sum\nolimits_{i} x", COLOR, 14.0)
        assert stacked is not None and side is not None
        assert side.height() < stacked.height()

    def test_hphantom_width(self):
        plain = render_formula(r"a b", COLOR, 14.0)
        phantom = render_formula(r"a \hphantom{xxxx} b", COLOR, 14.0)
        assert plain is not None and phantom is not None
        assert phantom.width() > plain.width()

    def test_hspace_width(self):
        plain = render_formula(r"ab", COLOR, 14.0)
        spaced = render_formula(r"a \hspace{2em} b", COLOR, 14.0)
        assert plain is not None and spaced is not None
        assert spaced.width() > plain.width() + 20

    def test_top_level_row_break(self):
        one = render_formula(r"a = b", COLOR, 14.0)
        two = render_formula(r"a = b \\ c = d", COLOR, 14.0)
        assert one is not None and two is not None
        assert two.height() > one.height()


class TestAtomGlyphs:
    @staticmethod
    def _row_texts(latex: str) -> list:
        node = _Parser(latex).parse()
        return [_atom_text(item) for item in node.items]

    def test_ascii_minus_maps_to_math_minus(self):
        assert "−" in self._row_texts("a - b")

    def test_ascii_prime_maps_to_prime(self):
        assert "′" in self._row_texts("f'(x)")

    def test_ascii_star_maps_to_ast(self):
        assert "∗" in self._row_texts("a * b")

    def test_not_combos_use_single_glyph(self):
        assert "≠" in self._row_texts(r"a \not= b")
        assert "∉" in self._row_texts(r"x \not\in A")

    def test_text_escapes_unescaped(self):
        node = _Parser(r"\text{50\%}").parse()
        assert "".join(_atom_text(item) for item in node.items) == "50%"

    def test_text_space_runs_collapse(self):
        node = _Parser(r"\text{token   ids}").parse()
        assert "".join(_atom_text(item) for item in node.items) == "token ids"


class TestControlWordWhitespace:
    """控制词与参数花括号之间的空白（TeX 里是词尾分隔符）。"""

    @pytest.mark.parametrize(
        "latex",
        [
            r"\text { x }",
            r"\mathrm {x}",
            r"\mathbf {x}",
            r"\mathbb {R}",
            r"\operatorname {argmax}",
            r"\operatorname *{argmax}",
            r"\sqrt [3] {x}",
            r"\textcolor {red} {x}",
            r"\color {blue} x",
            r"\begin {matrix} a & b \\ c & d \end {matrix}",
            r"\genfrac {(} {)} {0} {} {a} {b}",
        ],
    )
    def test_space_before_group(self, latex):
        assert render_formula(latex, COLOR, 14.0) is not None

    def test_sqrt_optional_index_ignores_space(self):
        plain = render_formula(r"\sqrt[3]{x}", COLOR, 14.0)
        spaced = render_formula(r"\sqrt [3] {x}", COLOR, 14.0)
        assert plain is not None and spaced is not None
        assert spaced.size() == plain.size()

    def test_operatorname_star_ignores_space(self):
        plain = render_formula(r"\operatorname*{argmax}", COLOR, 14.0)
        spaced = render_formula(r"\operatorname *{argmax}", COLOR, 14.0)
        assert plain is not None and spaced is not None
        assert spaced.size() == plain.size()

    def test_mineru_spaced_text_formulas(self):
        """MinerU 转写的 ``\\text { token   ids }`` 曾整条渲染失败。"""
        for latex in MINERU_SPACED_FORMULAS:
            report = {}
            image = render_formula(latex, COLOR, 14.0, True, report=report)
            assert image is not None, latex
            assert report["degraded"] is False

    def test_viewer_renders_mineru_spaced_formulas(self, qapp):
        source = "\n\n".join(f"$$\n{latex}\n$$" for latex in MINERU_SPACED_FORMULAS)
        v = ElaMarkdownViewer()
        v.setMarkdown(source)

        assert v.renderIssues() == []
        assert len(_images(v)) == len(MINERU_SPACED_FORMULAS)
        text = v.document().toPlainText()
        assert "\\text" not in text and "\\mathrm" not in text
        v.deleteLater()


MINERU_SPACED_FORMULAS = [
    r"\text { token   ids } (W) = \{w _ {v _ {1}}, w _ {v _ {2}}, "
    r"\dots , w _ {v _ {n}} \}",
    r"\text { positional   ids } (B) = \{b _ {1}, b _ {2}, \dots , b _ {n} \}",
    r"\text { segment   ids } (G) = \{g _ {s e g _ {1}}, g _ {s e g _ {2}}, "
    r"\dots , g _ {s e g _ {n}} \}",
    r"\text { column   ids } (C) = \{c _ {c o l _ {1}}, c _ {c o l _ {2}}, "
    r"\dots , c _ {c o l _ {n}} \}",
    r"\mathrm{rowids} (R) = \{r _ {r o w _ {1}}, r _ {r o w _ {2}}, "
    r"\dots , r _ {r o w _ {n}} \}",
    r"\mathrm{rankids} (Z) = \left\{z _ {r a n k _ {1}}, z _ {r a n k _ {2}}, "
    r"\dots , z _ {r a n k _ {n}} \right\}",
]


class TestEquationTags:
    """``\\tag`` / ``\\tag*``：公式编号右对齐在公式末尾。"""

    def test_tag_not_degraded(self):
        report = {}
        image = render_formula(r"a = b \tag{1}", COLOR, 14.0, True, report=report)
        assert image is not None
        assert report["degraded"] is False

    def test_tag_widens_formula(self):
        plain = render_formula(r"a = b", COLOR, 14.0, True)
        tagged = render_formula(r"a = b \tag{1}", COLOR, 14.0, True)
        assert plain is not None and tagged is not None
        assert tagged.width() > plain.width() + 20

    def test_tag_star_omits_parentheses(self):
        starred = render_formula(r"a = b \tag*{A}", COLOR, 14.0, True)
        plain = render_formula(r"a = b \tag{A}", COLOR, 14.0, True)
        assert starred is not None and plain is not None
        assert starred.width() < plain.width()

    def test_tag_survives_space_before_group(self):
        report = {}
        image = render_formula(r"a = b \tag {1}", COLOR, 14.0, True, report=report)
        assert image is not None
        assert report["degraded"] is False

    def test_viewer_tag_not_left_as_source(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown("$$\nQ = H W ^ {Q}\tag{1}\n$$")

        assert v.renderIssues() == []
        assert len(_images(v)) == 1
        assert "\\tag" not in v.document().toPlainText()
        v.deleteLater()

    def test_viewer_mineru_tagged_formula(self, qapp):
        latex = (
            r"\operatorname{Attn} (H) = \operatorname{softmax} "
            r"(\frac {Q K ^ {\top}}{\sqrt {d _ {K}}}) V\tag{2}"
        )
        v = ElaMarkdownViewer()
        v.setMarkdown(f"$$\n{latex}\n$$")

        assert v.renderIssues() == []
        assert len(_images(v)) == 1
        v.deleteLater()


class TestViewerCompat:
    def test_tolerant_formula_records_issue(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown(r"公式 $x \foobar y$ 结束")

        assert len(_images(v)) == 1
        issues = v.renderIssues()
        assert any(kind == "math" for kind, _ in issues)
        v.deleteLater()

    def test_structural_error_keeps_source(self, qapp):
        """自动修复也处理不了的错误仍回退为源码文本。"""
        v = ElaMarkdownViewer()
        v.setMarkdown(r"公式 $x^{$ 结束")

        assert _images(v) == []
        assert "x^{" in v.document().toPlainText()
        assert any(kind == "math" for kind, _ in v.renderIssues())
        v.deleteLater()

    def test_missing_right_is_repaired_without_issue(self, qapp):
        """缺 ``\\right`` 的定界符修复后正常渲染，不记为渲染问题。"""
        v = ElaMarkdownViewer()
        v.setMarkdown(r"公式 $\left( x$ 结束")

        assert len(_images(v)) == 1
        assert v.renderIssues() == []
        v.deleteLater()

    def test_boxed_inline_renders(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown(r"结果 $\boxed{x^2}$ 结束")

        assert len(_images(v)) == 1
        assert v.renderIssues() == []
        v.deleteLater()


def _images(viewer: ElaMarkdownViewer) -> list:
    """收集文档中的公式 / 图片资源（返回 QImage 列表）。"""
    result = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                resource = viewer.document().resource(
                    QTextDocument.ResourceType.ImageResource,
                    QUrl(fragment.charFormat().toImageFormat().name()),
                )
                if isinstance(resource, QImage):
                    result.append(resource)
            iterator += 1
        block = block.next()
    return result


# ---------------------------------------------------------------------------
# 矩阵 / binom / 字母表 / 多行环境
# ---------------------------------------------------------------------------


def _render(latex: str):
    return render_formula(latex, COLOR, 14.0, True)


def _fragments(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                result.append(fragment)
            iterator += 1
        block = block.next()
    return result


class TestMathLiteMatrix:
    def test_pmatrix_renders(self):
        image = _render(r"\begin{pmatrix}a & b \\ c & d\end{pmatrix}")
        assert image is not None
        assert image.width() > 0 and image.height() > 0

    def test_matrix_grows_with_rows(self):
        one_row = _render(r"\begin{pmatrix}a & b\end{pmatrix}")
        two_rows = _render(r"\begin{pmatrix}a & b \\ c & d\end{pmatrix}")
        assert one_row is not None and two_rows is not None
        assert two_rows.height() > one_row.height()

    def test_delimiter_kinds(self):
        for env in ("bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "matrix"):
            image = _render(rf"\begin{{{env}}}1 & 2 \\ 3 & 4\end{{{env}}}")
            assert image is not None, env

    def test_cases_left_aligned(self):
        image = _render(r"\begin{cases} x & x > 0 \\ -x & x \le 0 \end{cases}")
        assert image is not None

    def test_mismatched_environment_none(self):
        assert _render(r"\begin{pmatrix}a & b\end{bmatrix}") is None

    def test_gather_renders_two_rows(self):
        one = _render(r"\begin{gather}a=b\end{gather}")
        two = _render(r"\begin{gather}a=b\\c=d\end{gather}")
        assert one is not None and two is not None
        assert two.height() > one.height()

    def test_nested_formula_in_cell(self):
        image = _render(r"\begin{pmatrix}\frac{1}{2} & \sqrt{x} \\ 0 & 1\end{pmatrix}")
        assert image is not None


class TestMathLiteBinomAndAlphabets:
    def test_binom(self):
        image = _render(r"\binom{n}{k}")
        assert image is not None
        assert image.width() > 0 and image.height() > 0

    def test_binom_variants(self):
        assert _render(r"\dbinom{n}{k}") is not None
        assert _render(r"\tbinom{n}{k}") is not None

    def test_mathbb(self):
        assert _render(r"\mathbb{R} \subset \mathbb{C}") is not None

    def test_mathcal_and_mathfrak(self):
        assert (
            _render(
                r"\mathcal{L}(A) \to \mathfrak{g}",
            )
            is not None
        )

    def test_mathbb_indicator_digit(self):
        assert _render(r"\mathbb{1}_{A}") is not None


class TestMathLiteAlignAndArray:
    def test_align_environment(self):
        image = _render(r"\begin{align} a &= b + c \\ d &= e \end{align}")
        assert image is not None
        assert image.width() > 0 and image.height() > 0

    def test_aligned_and_star(self):
        assert _render(r"\begin{aligned} x &= 1 \\ y &= 2 \end{aligned}") is not None
        assert _render(r"\begin{align*} a &= b \\ c &= d \end{align*}") is not None

    def test_align_renders_two_rows(self):
        one = _render(r"\begin{aligned} a &= b \end{aligned}")
        two = _render(r"\begin{aligned} a &= b \\ c &= d \end{aligned}")
        assert one is not None and two is not None
        assert two.height() > one.height()

    def test_substack(self):
        image = _render(r"\sum_{\substack{i=1 \\ j=2}} x_{ij}")
        assert image is not None
        assert image.height() > _render(r"\sum_{i=1} x_i").height()

    def test_array_with_column_spec(self):
        image = _render(r"\begin{array}{lcr} a & b & c \\ 1 & 2 & 3 \end{array}")
        assert image is not None

    def test_array_ignores_bars(self):
        assert _render(r"\begin{array}{l|c} a & b \\ c & d \end{array}") is not None

    def test_align_mismatched_end_none(self):
        assert _render(r"\begin{align} a &= b \end{aligned}") is None

    def test_nested_in_display_math(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("$$\\begin{aligned} x &= 1 \\\\ y &= 2 \\end{aligned}$$")

        assert "aligned" not in v.document().toPlainText()
        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert len(images) == 1
        v.deleteLater()


class TestViewerIntegration:
    def test_matrix_in_display_math(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("$$\\begin{pmatrix}1 & 0 \\\\ 0 & 1\\end{pmatrix}$$")

        text = v.document().toPlainText()
        assert "pmatrix" not in text
        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert len(images) == 1
        v.deleteLater()

    def test_binom_inline_math(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("组合数 $\\binom{n}{k}$ 结束")

        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert len(images) == 1
        assert "binom" not in v.document().toPlainText()
        v.deleteLater()
