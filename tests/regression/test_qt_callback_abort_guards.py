"""回归测试：Qt 回调内异常导致的静默进程终止（0xC0000409）。

这些 bug 的共同特征是「异常穿出 Qt 回调边界 → 整个进程 abort、无 traceback」。
一旦在 pytest 主进程里复现，会把整个测试会话一起杀掉（表现为无输出、退出码
0xC0000409），因此每个用例都在**独立子进程**中运行并断言退出码。

覆盖：
- ``ElaDialogBase`` / ``ElaMessageDialog`` 缺 parent（底层 ElaContentDialog
  无条件解引用 parent）
- ``ElaButton.setSvgIcon`` 图标名拼错 / 图标包缺失 / SVG 语法错时，
  ``getSvgData`` 的 ``KeyError`` / ``QSvgRenderer`` 的解析失败不得穿出 ``paintEvent``
- ``ElaChartWidget`` 的 ``title`` / ``legend`` ``fontSize`` 传非数值
- ``charts.axes.niceTicks`` 在 ``vmax - vmin`` 溢出为 inf 时的 ``OverflowError``
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QWidget

#: 0xC0000409（PyQt 回调未捕获异常）/ 0xC0000005（访问冲突）等致命退出码
from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts.axes import niceTicks
from pyqt6_ela_pro.charts.core import _opt_float
from pyqt6_ela_pro.dialog_base import ElaDialogBase
from pyqt6_ela_pro.message_dialog import ElaMessageDialog
from pyqt6_ela_pro.ela_button import ElaButton
from pyqt6_ela_pro.svg_icon import svg_icon_loader

_ABORT_CODES = {
    0xC0000409,  # STATUS_STACK_BUFFER_OVERRUN —— PyQt 回调异常
    0xC0000005,  # STATUS_ACCESS_VIOLATION
    3221226505,  # 0xC0000409 有符号形式
    3221225477,  # 0xC0000005 有符号形式
}

_PRELUDE = textwrap.dedent(
    """
    import sys, warnings
    sys.path.insert(0, ".")
    warnings.filterwarnings("ignore")
    from PyQt6.QtWidgets import QApplication, QWidget
    from PyQt6.QtCore import Qt
    app = QApplication([])
    import pyqt6_ela_pro as P
    from PyQt6ElaWidgetTools import eApp
    eApp.init()
    """
)


def _run(body: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """在独立子进程里执行 ``body``，返回 CompletedProcess。"""
    return subprocess.run(
        [sys.executable, "-c", _PRELUDE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(Path(__file__).resolve().parents[2]),
    )


def _assert_no_abort(label: str, result: subprocess.CompletedProcess) -> None:
    assert result.returncode not in _ABORT_CODES, (
        f"{label}: 进程被静默终止（rc={result.returncode:#x}）。"
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


class TestDialogParentContract:
    """``ElaContentDialog`` 的 C++ 构造函数解引用 parent，必须由 Python 侧拦截。"""

    def test_dialog_base_without_parent_raises_instead_of_aborting(self, qapp):

        host = QWidget()
        with pytest.raises(ValueError, match="parent"):
            ElaDialogBase()
        host.deleteLater()

    def test_message_dialog_without_parent_raises(self, qapp):

        with pytest.raises(ValueError, match="parent"):
            ElaMessageDialog(title="t", message="m")

    def test_message_dialog_with_parent_works(self, qapp):

        host = QWidget()
        dlg = ElaMessageDialog(title="t", message="m", parent=host)
        assert dlg is not None
        dlg.deleteLater()
        host.deleteLater()
        qapp.processEvents()

    def test_subprocess_no_abort_on_missing_parent(self):
        result = _run(
            """
            from pyqt6_ela_pro.dialog_base import ElaDialogBase
            from pyqt6_ela_pro.message_dialog import ElaMessageDialog
            for factory in (ElaDialogBase, lambda: ElaMessageDialog(title="t", message="m")):
                try:
                    factory()
                except ValueError:
                    pass
            print("OK")
            """
        )
        _assert_no_abort("ElaDialogBase(parent=None)", result)
        assert "OK" in result.stdout, result.stderr


class TestSvgIconPaintSafety:
    """图标名拼错 / 图标包缺失 / SVG 语法错时都不能把异常抛进 paintEvent。"""

    def test_unknown_icon_name_paints(self, qapp, recwarn):

        for source in ("definitely-not-an-icon", "<svg><<<未闭合", ""):
            button = ElaButton("x", parent=None)
            button.setSvgIcon(source)
            button.resize(120, 40)
            button.show()
            qapp.processEvents()
            button.repaint()
            button.grab()  # 强制走 paintEvent
            button.deleteLater()
        qapp.processEvents()

    def test_loader_has_icon(self, qapp):

        loader = svg_icon_loader()
        assert loader.hasIcon("definitely-not-an-icon") is False

    def test_missing_icon_name_warns_instead_of_silent(self, qapp):
        """找不到图标名必须 warn —— 静默少一个图标，用户会去查图标名。"""
        button = ElaButton("x")
        with pytest.warns(RuntimeWarning, match="图标名"):
            assert button.setSvgIcon("definitely-not-an-icon") is False

    def test_subprocess_no_abort_on_bad_icon(self):
        result = _run(
            """
            from pyqt6_ela_pro import ElaButton
            b = ElaButton("x")
            b.setSvgIcon("definitely-not-an-icon")
            b.resize(120, 40); b.show()
            for _ in range(10): app.processEvents()
            b.repaint(); b.grab()
            print("OK")
            """
        )
        _assert_no_abort("ElaButton.setSvgIcon(bad icon)", result)
        assert "OK" in result.stdout, result.stderr


class TestChartFontSizeRobustness:
    """``title`` / ``legend`` 的 ``fontSize`` 传 CSS 值不能崩在 paintEvent。"""

    @pytest.mark.parametrize(
        "option",
        [
            {"title": {"text": "hi", "textStyle": {"fontSize": "14px"}}},
            {"title": {"text": "hi", "textStyle": {"fontSize": None}}},
            {"title": {"text": "a", "subtext": "b", "subtextStyle": {"fontSize": "x"}}},
            {"legend": {"textStyle": {"fontSize": "12px"}}},
        ],
    )
    def test_non_numeric_font_size_renders(self, qapp, option):

        chart = ElaChartWidget()
        chart.resize(400, 300)
        chart.show()
        merged = {"series": [{"type": "line", "data": [1, 2]}], **option}
        chart.setOption(merged, notMerge=True)
        for _ in range(8):
            qapp.processEvents()
        chart.repaint()
        chart.grab()
        chart.deleteLater()
        qapp.processEvents()

    def test_opt_float_falls_back(self):

        assert _opt_float("14px", 12) == 12
        assert _opt_float(None, 12) == 12
        assert _opt_float(float("nan"), 12) == 12
        assert _opt_float(float("inf"), 12) == 12
        assert _opt_float(20, 12) == 20
        assert _opt_float("16", 12) == 16

    def test_subprocess_no_abort_on_bad_font_size(self):
        result = _run(
            """
            from pyqt6_ela_pro import ElaChartWidget
            c = ElaChartWidget(); c.resize(400, 300); c.show()
            c.setOption({"title": {"text": "hi", "textStyle": {"fontSize": "14px"}},
                         "series": [{"type": "line", "data": [1, 2]}]}, notMerge=True)
            for _ in range(10): app.processEvents()
            c.repaint(); c.grab()
            print("OK")
            """
        )
        _assert_no_abort("chart title fontSize=14px", result)
        assert "OK" in result.stdout, result.stderr


class TestNiceTicksOverflow:
    """``vmax - vmin`` 溢出会让 math.floor(inf) 抛 OverflowError。"""

    @pytest.mark.parametrize(
        "vmin,vmax", [(1e308, -1e308), (1.7e308, -1.7e308), (1e308, -1e308)]
    )
    def test_extreme_span_is_finite(self, vmin, vmax):

        lo, hi, ticks = niceTicks(vmin, vmax)
        assert all(t == t and abs(t) != float("inf") for t in ticks)
        assert lo <= hi

    def test_huge_data_does_not_crash_set_option(self, qapp):

        chart = ElaChartWidget()
        chart.resize(400, 300)
        chart.show()
        chart.setOption(
            {"series": [{"type": "line", "data": [1e308, -1e308]}]}, notMerge=True
        )
        for _ in range(8):
            qapp.processEvents()
        chart.repaint()
        chart.grab()
        chart.deleteLater()
        qapp.processEvents()

    def test_normal_ranges_unchanged(self):

        lo, hi, ticks = niceTicks(0.0, 10.0)
        assert (lo, hi) == (0.0, 10.0)
        assert len(ticks) >= 2
