"""``ElaDataTable`` 的数据装载 / 排序契约回归。

这里钉的三条都是「无任何报错、结果却错」那一类：

1. 同步 :meth:`setTableData` 必须取消在途的 :meth:`setTableDataAsync`；
2. ``nan`` / ``inf`` 不能让排序静默变成空操作；
3. 字典格式的列长不一致必须报错（相邻形状，一并钉住）。
"""

from __future__ import annotations

import time

import pytest
from PyQt6.QtCore import Qt

from pyqt6_ela_pro.table_view import ElaDataTable


def _column(table: ElaDataTable, col: int = 0) -> list[str]:
    model = table.model()
    return [model.item(row, col).text() for row in range(model.rowCount())]


def _settle(qapp, timeout: float = 2.0) -> None:
    """等后台加载线程有机会跑完（它靠 queued signal 回主线程）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


class TestSyncCancelsPendingAsync:
    """同步填的数据不能被几秒前的异步结果整个顶掉。"""

    def test_sync_data_survives_pending_async(self, make, qapp):
        table = make(ElaDataTable)
        table.setTableData([["sync", "col"], ["SYNC", "1"]])
        table.setTableDataAsync(
            [["async", "col"]] + [[f"ASYNC{i}", str(i)] for i in range(20000)]
        )
        # 异步刚起、还没回来 —— 这时同步再填一次
        table.setTableData([["sync", "col"], ["SYNC", "1"]])
        assert _column(table) == ["SYNC"]

        _settle(qapp)
        assert _column(table) == ["SYNC"], "在途的异步加载把同步数据顶掉了"
        assert table.model().rowCount() == 1

    def test_retire_thread_is_called(self, make, qapp, monkeypatch):
        table = make(ElaDataTable)
        calls: list[object] = []
        original = table._retire_thread
        monkeypatch.setattr(
            table,
            "_retire_thread",
            lambda thread: calls.append(thread) or original(thread),
        )
        table.setTableDataAsync([["a", "b"], ["1", "2"]])
        table.setTableData([["a", "b"], ["9", "9"]])
        assert len(calls) == 1, "同步路径没有调用 _retire_thread"
        _settle(qapp, 0.3)


class TestNumericSorting:
    """NaN / inf 与空值同等对待：排在末尾，且不破坏其余行的全序。"""

    def test_nan_does_not_break_order(self, make):
        table = make(ElaDataTable)
        table.setTableData([["n"], ["3"], ["NaN"], ["1"]])
        table._sort_numeric(0, Qt.SortOrder.AscendingOrder)
        assert _column(table) == ["1", "3", "NaN"]

    @pytest.mark.parametrize(
        ("raw", "why"),
        [
            ("NaN", "float('NaN') 能成功解析"),
            ("nan", "小写"),
            ("inf", "正无穷"),
            ("-inf", "负无穷"),
            ("1e999", "float 溢出成 inf"),
        ],
    )
    def test_non_finite_values_go_last(self, make, raw, why):
        table = make(ElaDataTable)
        table.setTableData([["n"], [raw], ["2"], ["1"]])
        table._sort_numeric(0, Qt.SortOrder.AscendingOrder)
        assert _column(table) == ["1", "2", raw], f"{raw} 应排到末尾（{why}）"

    def test_descending_also_keeps_order(self, make):
        table = make(ElaDataTable)
        table.setTableData([["n"], ["1"], ["NaN"], ["3"], ["2"]])
        table._sort_numeric(0, Qt.SortOrder.DescendingOrder)
        assert _column(table) == ["3", "2", "1", "NaN"]

    def test_is_numeric_rejects_non_finite(self, make):
        table = make(ElaDataTable)
        for text in ("NaN", "nan", "inf", "-inf", "1e999"):
            assert table._is_numeric(text) is False, text
        for text in ("1", "-2.5", "1,234", " 7 "):
            assert table._is_numeric(text) is True, text


class TestDataShapeValidation:
    def test_dict_with_ragged_columns_raises(self, make):
        table = make(ElaDataTable)
        with pytest.raises(ValueError):
            table.setTableData({"a": [1, 2, 3], "b": [1, 2]})

    def test_empty_input_is_noop(self, make):
        table = make(ElaDataTable)
        table.setTableData([["a", "b"], ["1", "2"]])
        table.setTableData([])
        assert _column(table, 0) == ["1"]
