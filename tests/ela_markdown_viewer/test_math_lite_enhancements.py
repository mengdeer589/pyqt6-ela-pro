"""Tests for math_lite matrix / binom / alphabet enhancements."""

from __future__ import annotations

from PyQt6.QtGui import QColor

from pyqt6_ela_pro.math_lite import render_formula
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

COLOR = QColor("#202020")


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
