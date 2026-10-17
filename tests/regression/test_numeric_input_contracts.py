from __future__ import annotations

import pytest

from pyqt6_ela_pro.table_view import ElaDataTable
from pyqt6_ela_pro.terminal_view import (
    _MAX_FONT_SIZE,
    _MAX_LINES_CAP,
    _MIN_FONT_SIZE,
    ElaTerminalView,
)

NON_FINITE = [float("inf"), float("-inf"), float("nan")]


class TestTerminalNumericInputs:
    def test_font_size_clamps_normally(self, make):
        view = make(ElaTerminalView)
        view.setFontSize(1)
        assert view.fontSize() == _MIN_FONT_SIZE
        view.setFontSize(9999)
        assert view.fontSize() == _MAX_FONT_SIZE
        view.setFontSize(14)
        assert view.fontSize() == 14

    @pytest.mark.parametrize("bad", NON_FINITE)
    def test_font_size_survives_non_finite(self, make, bad):
        """inf/-inf 照常夹到上/下限；nan 保持原值。都不抛。"""
        view = make(ElaTerminalView)
        view.setFontSize(14)
        view.setFontSize(bad)
        assert view.fontSize() in (_MIN_FONT_SIZE, _MAX_FONT_SIZE, 14)

    def test_font_size_infinity_clamps_to_max(self, make):
        view = make(ElaTerminalView)
        view.setFontSize(float("inf"))
        assert view.fontSize() == _MAX_FONT_SIZE
        view.setFontSize(float("-inf"))
        assert view.fontSize() == _MIN_FONT_SIZE

    def test_font_size_nan_keeps_current(self, make):
        view = make(ElaTerminalView)
        view.setFontSize(17)
        view.setFontSize(float("nan"))
        assert view.fontSize() == 17

    def test_max_lines_clamps_normally(self, make):
        view = make(ElaTerminalView)
        view.setMaxLines(-5)
        assert view.maxLines() == 0, "负数应夹到 0（= 不限）"
        view.setMaxLines(3.7)
        assert view.maxLines() == 3, "浮点应取整"

    @pytest.mark.parametrize(
        ("bad", "want"),
        [
            (float("inf"), _MAX_LINES_CAP),
            (float("nan"), _MAX_LINES_CAP),
            (float("-inf"), 0),  # 负无穷夹到下界 0（= 不限）
        ],
    )
    def test_max_lines_survives_non_finite(self, make, bad, want):
        view = make(ElaTerminalView)
        view.setMaxLines(bad)
        assert view.maxLines() == want

    @pytest.mark.parametrize(
        ("bad", "want"),
        [
            (float("inf"), _MAX_LINES_CAP),
            (float("nan"), _MAX_LINES_CAP),
            (float("-inf"), 0),
        ],
    )
    def test_constructor_survives_non_finite_max_lines(self, make, bad, want):
        view = make(ElaTerminalView, maxLines=bad)
        assert view.maxLines() == want

    def test_max_lines_zero_means_unlimited(self, make):
        view = make(ElaTerminalView, maxLines=0)
        assert view.maxLines() == 0
        for i in range(200):
            view.appendLine(f"line {i}")
        assert view.lineCount() == 200, "0 应表示不限，200 行都得留着"


class TestTableColumnWidthInputs:
    @pytest.fixture
    def table(self, make):
        widget = make(ElaDataTable)
        widget.setTableData([["a", "b"], ["1", "2"]])
        return widget

    @pytest.mark.parametrize(
        ("given", "want"),
        [(120.5, 120), (120.4, 120), (0, 0), (99, 99), (99_999, 10_000), ("150", 150)],
    )
    def test_set_column_width_rounds(self, table, given, want):
        table.setColumnWidth(0, given)
        assert table._columnWidths[0] == want

    @pytest.mark.parametrize("bad", NON_FINITE)
    def test_set_column_width_survives_non_finite(self, table, bad):
        table.setColumnWidth(0, bad)
        assert table._columnWidths[0] == 100

    def test_set_column_widths_rounds_all(self, table):
        table.setColumnWidths({0: 88.8, 1: 66})
        assert table._columnWidths[0] == 88
        assert table._columnWidths[1] == 66

    def test_set_column_widths_by_column_name(self, table):
        table.setColumnWidths({"a": 77})
        assert table._columnWidths["a"] == 77

    def test_width_actually_reaches_the_view(self, table):
        """不只是记账 —— 真的落到 QTableView 上。"""
        table.setColumnWidth(0, 123.9)
        assert table.columnWidth(0) == 123
