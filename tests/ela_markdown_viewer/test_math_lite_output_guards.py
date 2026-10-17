"""``math_lite`` 的输出层健壮性回归。

这个模块的契约是「不支持时返回 ``None``」——**每一级**都有兜底
（``preprocess`` / ``parse`` / ``build`` / ``paint``），所以调用方永远不会
见到异常。这三条守的就是那个「唯一没有 try 的输出级」，以及两处会让
GUI 线程卡死的病态输入。

实测过的三个原始故障：

* ``x\\hspace{100000000em}x`` → ``OverflowError`` 穿出 ``render_formula``；
  在流式路径上它顺着 ``_stream_timer.timeout`` 冲出 Qt 回调 =
  **0xC0000409 零traceback 终止**；
* ``\\hspace{10000000em}`` → ``QImage`` 返回 null 而本函数**把它当成功交
  出去**，调用方的 ``if image is None`` 降级分支因此被绕过；
* ``\\hspace{1000000em}`` → **真实分配 3.1 GiB** 缓冲；
* ``\\zzz`` + 400 层花括号 → ``RecursionError`` 从容错重试分支穿出；
* ``_dimension_em`` 的正则在长输入上是 O(n²)，单个公式按住 GUI 十秒。
"""

from __future__ import annotations

import sys
import time

import pytest
from PyQt6.QtGui import QColor, QImage

from pyqt6_ela_pro.math_lite import _dimension_em, render_formula

COLOR = QColor("#202020")


def _render(latex: str, pt: float = 12.0) -> QImage | None:
    return render_formula(latex, COLOR, pt)


class TestOutputLayerGuards:
    @pytest.mark.parametrize(
        ("latex", "why"),
        [
            ("x\\hspace{100000000em}x", "box.w * _SS 越过 INT_MAX"),
            ("x\\hspace{114000000em}x", "同上的另一个取值"),
            ("x\\hspace{1000000000em}x", "更大"),
            ("\\hspace{" + "1" * 400 + "}", "float() 得到 inf"),
            ("x\\kern{99999999em}x", "\\kern 走同一分支"),
        ],
    )
    def test_huge_dimension_returns_none_not_raise(self, latex, why):
        # 原实现在这里抛 OverflowError。pytest 里能看见是因为它穿出了
        # render_formula；在真实流式路径上它会冲出 QTimer 槽 = 进程终止。
        assert _render(latex) is None, why

    def test_intermediate_band_returns_none(self):
        # 这一带 QImage 返回 null 而不抛异常 —— 更隐蔽：函数**把它当成功**
        # 返回，调用方的 ``if image is None`` 降级被绕过，最终 setWidth(0.0)
        assert _render("x\\hspace{10000000em}x") is None
        assert _render("x\\hspace{50000000em}x") is None

    def test_moderate_huge_allocation_is_rejected(self):
        # 32MB×100 = 3.1 GiB 真实分配；不设上限时这一档是真分配出来的
        assert _render("x\\hspace{1000000em}x") is None

    def test_never_returns_null_image(self):
        """返回的 QImage 必须非null —— null 等于「成功但没内容」。"""
        for latex in (
            "x",
            "x^2",
            "\\frac{a}{b}",
            "x\\hspace{2em}x",
            "x\\hspace{10000000em}x",
        ):
            image = _render(latex)
            if image is not None:
                assert not image.isNull(), f"{latex!r} 返回了 null QImage 当成功"

    def test_normal_formulas_still_render(self):
        for latex in ("x", "x^2", "\\frac{a}{b}", "x\\hspace{2em}x", "\\sqrt{2}"):
            image = _render(latex)
            assert image is not None, f"{latex!r} 正常公式被误拒了"
            assert image.width() > 0 and image.height() > 0

    def test_malformed_dimension_does_not_crash(self):
        # 畸形实参按「0 宽度」处理：这一段不占空间，其余内容照常渲染。
        # 关键是**不抛异常**（float("1.2.3") 的 ValueError 由调用方兜住）。
        assert _dimension_em("1.2.3", 12.0) == 0.0
        image = _render("x\\hspace{1.2.3}x")
        assert image is not None and not image.isNull()

    def test_bare_marker_with_no_content_is_none(self):
        # 裸 ``\\hspace{...}``（后面没内容）本来就返回 None；
        # 带内容才走 box 布局 —— 两个形状都要守住
        assert _render("\\hspace{100000000em}") is None
        assert _render("x\\hspace{100000000em}x") is None


class TestTolerantFallbackEscapes:
    @pytest.mark.parametrize("depth", [400, 800, 1600])
    def test_deep_nesting_with_unknown_command_returns_none(self, depth):
        # 严格解析因浅层未知命令失败 → 进容错重试 → 容错路径深递归爆栈。
        # 原先三层重试只 catch _ParseError，RecursionError 从上一层穿出。
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(1000)
        try:
            latex = "\\zzz " + "{" * depth + "x" + "}" * depth
            assert _render(latex) is None
        finally:
            sys.setrecursionlimit(old_limit)

    def test_deep_nesting_without_unknown_command_still_contained(self):
        # 对照组：纯深嵌套原先就被最外层的 except Exception 兜住
        assert _render("{" * 800 + "x" + "}" * 800) is None


class TestDimensionParsingIsLinear:
    def test_isfinite_and_zero(self):
        assert _dimension_em("", 12.0) == 0.0
        assert _dimension_em("   ", 12.0) == 0.0
        assert _dimension_em("abc", 12.0) == 0.0
        assert _dimension_em("2em", 12.0) == 2.0
        assert _dimension_em("2 em", 12.0) == 2.0
        assert _dimension_em("-1.5em", 12.0) == -1.5
        # float 溢出成 inf 时归零（由输出层的 isfinite 兜底拒收）
        assert _dimension_em("1" * 400, 12.0) == 0.0

    def test_known_units(self):
        # em = 1 个字号宽度。12pt 字号下 1em = 16px，所以：
        # 3ex = 1.5em、18mu = 1em、1pt = 1.333px = 0.0833em
        assert _dimension_em("3ex", 12.0) == pytest.approx(1.5)
        assert _dimension_em("18mu", 12.0) == pytest.approx(1.0)
        assert _dimension_em("1pt", 12.0) == pytest.approx(1.0 / 12.0)
        assert _dimension_em("1px", 12.0) == pytest.approx(0.0625)
        assert _dimension_em("1cm", 12.0) > 0
        assert _dimension_em("1mm", 12.0) > 0
        assert _dimension_em("1in", 12.0) > 0
        assert _dimension_em("10bogus", 12.0) == 0.0
        # 无单位时按 em
        assert _dimension_em("2", 12.0) == 2.0

    def test_malformed_numbers_return_zero(self):
        for raw in ("1.2.3", "em", "+", "-", ".", "1..2", "1 2 em"):
            assert _dimension_em(raw, 12.0) == 0.0, raw

    def test_long_argument_is_linear(self):
        # 原正则是 ``\s*([+-]?[\d.]+)\s*([a-zA-Z]*)\s*$``：三个可回溯量词
        # 相邻又带尾锚。**尾部那个 ``@`` 是二次回溯的触发点** —— 它让 ``$``
        # 永远匹配不上，引擎于是从中间 ``\s*`` 的每个回溯位置重试。实测
        # N 从 10k 翻到 60k，耗时 282ms -> 1135ms -> 4517ms -> 10223ms。
        #（不带尾杂字符时旧正则本来就快，所以这个 ``@`` 不能省。）
        timings = []
        for n in (10_000, 20_000, 40_000, 60_000):
            raw = "1" + " " * n + "a" * n + "@"
            t0 = time.perf_counter()
            _dimension_em(raw, 12.0)
            timings.append(time.perf_counter() - t0)
        # 线性：每翻倍≈2x；二次：每翻倍≈4x
        for prev, cur in zip(timings, timings[1:]):
            assert cur < max(prev * 3.0, 0.05), timings

    def test_long_argument_in_full_render(self):
        # 整条渲染路径（含解析 + 布局）也不得是二次的
        timings = []
        for n in (10_000, 20_000, 40_000):
            latex = "\\hspace{1" + " " * n + "a" * n + "@}"
            t0 = time.perf_counter()
            _render(latex)
            timings.append(time.perf_counter() - t0)
        for prev, cur in zip(timings, timings[1:]):
            assert cur < max(prev * 3.0, 0.05), timings
