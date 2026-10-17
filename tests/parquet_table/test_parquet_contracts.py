"""``ElaParquetTable`` 的数据装载 / 读失败 / 外观契约回归（需要 polars）。

钉的四条：

1. **polars 读失败必须降级而不是崩** —— ``goToPage`` / ``_on_cell_clicked``
   直接挂在 ``currentPageChanged`` / ``clicked`` 上，PyQt5 槽内未捕获异常
   = 进程直接终止、**无 traceback**。文件被移走 / 截断只在 ``.collect()``
   时暴露。
2. **``loadData`` 先读成功再改状态** —— 原先先把 ``_lf`` 赋值再
   ``collect()``，失败后进入「总数是旧的、数据源是新的」的不一致态。
3. **信息栏 5 种语义色必须真的显示** —— 裸 ``ElaText`` 的
   ``paintEvent`` 会把 palette 重置回主题色，五种色一个都不显示。
4. **外部列名 / 数值不按富文本解析** —— 它们来自 parquet 文件。
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("polars")

import polars as pl  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QWidget  # noqa: E402

from pyqt6_ela_pro.parquet_table import ElaParquetTable  # noqa: E402

ROWS = 137


@pytest.fixture
def parquet_file(tmp_path):
    path = tmp_path / "sample.parquet"
    pl.DataFrame(
        {
            "id": list(range(ROWS)),
            "name": [f"row{i}" for i in range(ROWS)],
            "score": [i * 1.5 for i in range(ROWS)],
        }
    ).write_parquet(path)
    return path


@pytest.fixture
def table(make, qapp, parquet_file):
    widget = make(ElaParquetTable, parquet_path=str(parquet_file), page_size=50)
    widget.show()
    qapp.processEvents()
    return widget


class TestPaging:
    def test_loads_all_rows(self, table):
        assert table.totalRows() == ROWS
        assert table.totalPages() == 3
        assert table.pageSize() == 50

    def test_first_page_row_numbers_start_at_one(self, table):
        assert table._table.model().verticalHeaderItem(0).text() == "1"

    def test_second_page_offsets_row_numbers(self, table):
        table.nextPage()
        assert table.currentPage() == 2
        assert table._table.model().verticalHeaderItem(0).text() == "51"

    def test_out_of_range_page_is_clamped(self, table):
        table.goToPage(999)
        assert table.currentPage() == table.totalPages()
        table.goToPage(-5)
        assert table.currentPage() == 1

    def test_page_size_clamps_to_range(self, make, parquet_file):
        widget = make(ElaParquetTable, parquet_path=str(parquet_file), page_size=10_000)
        assert widget.pageSize() == 5000
        small = make(ElaParquetTable, parquet_path=str(parquet_file), page_size=1)
        assert small.pageSize() == 50


class TestReadFailureIsContained:
    """P0：这些路径都在 Qt 槽里，抛出去就是进程终止。"""

    def test_paging_after_file_moved_emits_error(self, table, qapp, tmp_path):
        errors: list[str] = []
        table.errorOccurred.connect(errors.append)
        os.rename(table._parquet_path, tmp_path / "moved.parquet")
        table.goToPage(2)
        qapp.processEvents()
        assert errors, "读失败没有发errorOccurred"
        assert "读取 Parquet 文件失败" in errors[0]

    def test_cell_click_after_file_moved_survives(self, table, qapp, tmp_path):
        os.rename(table._parquet_path, tmp_path / "moved.parquet")
        table._on_cell_clicked(table._table.model().index(0, 2))
        qapp.processEvents()

    def test_column_stats_read_failure_does_not_crash(self, table, qapp, tmp_path):
        os.rename(table._parquet_path, tmp_path / "moved.parquet")
        table._column_stats_cache.clear()  # 强制走整列 collect
        table._on_cell_clicked(table._table.model().index(0, 2))
        qapp.processEvents()

    def test_loadData_broken_file_keeps_previous_state(self, table, tmp_path):
        broken = tmp_path / "broken.parquet"
        broken.write_bytes(b"PAR1this-is-not-a-parquet-file")
        before_rows = table.totalRows()
        before_page = table.currentPage()
        with pytest.raises(Exception):  # noqa: B017, PT011
            table.loadData(str(broken))
        # 先读成功再改状态：失败后仍是原来那份数据
        assert table.totalRows() == before_rows
        assert table.currentPage() == before_page
        assert table._parquet_path.endswith("sample.parquet")

    def test_loadData_truncated_file_keeps_previous_state(self, table, tmp_path):
        with open(table._parquet_path, "rb") as handle:
            head = handle.read(200)
        trunc = tmp_path / "trunc.parquet"
        trunc.write_bytes(head)
        with pytest.raises(Exception):  # noqa: B017, PT011
            table.loadData(str(trunc))
        assert table._parquet_path.endswith("sample.parquet")
        assert table.totalRows() == ROWS

    def test_missing_file_raises_file_not_found(self, make, tmp_path):
        with pytest.raises(FileNotFoundError):
            make(ElaParquetTable, parquet_path=str(tmp_path / "nope.parquet"))


class TestColumnStats:
    def test_numeric_column_stats(self, table, qapp):
        table._on_cell_clicked(table._table.model().index(0, 2))  # score
        qapp.processEvents()
        info = table._info_bar
        assert str(info._min_val) == "0.0"
        assert str(info._max_val) == str((ROWS - 1) * 1.5)

    def test_non_numeric_column_has_no_stats(self, table, qapp):
        table._on_cell_clicked(table._table.model().index(0, 1))  # name
        qapp.processEvents()
        # 断言打在**标签文本**上而不是 ``_min_val`` 字段：``clear_info()`` 只
        # 重置显示、不动背后的字段（那是私有的、无人读）
        assert table._info_bar._min_label.text() == "最小值: -"
        assert table._info_bar._col_label.text() == "列: -"

    def test_stats_are_cached_per_column(self, table, qapp):
        idx = table._table.model().index(0, 2)
        table._on_cell_clicked(idx)
        qapp.processEvents()
        assert "score" in table._column_stats_cache
        cached = table._column_stats_cache["score"]
        table._on_cell_clicked(idx)
        qapp.processEvents()
        assert table._column_stats_cache["score"] == cached


class TestInfoBarAppearance:
    LABELS = (
        "_col_label",
        "_col_index_label",
        "_min_label",
        "_max_label",
        "_last_label",
    )

    def test_five_labels_get_distinct_colors(self, table):
        # 读 textColor()（意图色）而不是 palette()：ColorText 是**绘制前**才把
        # palette 自愈回显式色，绘制之外读到的是陈旧值
        colors = {
            getattr(table._info_bar, name).textColor().name() for name in self.LABELS
        }
        assert len(colors) == 5, f"5 种语义色应各不相同，实得 {colors}"

    def test_colors_are_valid(self, table):
        for name in self.LABELS:
            color = getattr(table._info_bar, name).textColor()
            assert color is not None and color.isValid(), name

    def test_font_size_is_explicitly_set(self, table):
        # 不设就是 ElaText 默认的 28px（实测），整条信息栏比例会崩
        for name in self.LABELS:
            label = getattr(table._info_bar, name)
            assert label.font().pixelSize() == 12, name


class TestUntrustedColumnNames:
    @pytest.fixture
    def evil_table(self, make, qapp, tmp_path):
        path = tmp_path / "evil.parquet"
        pl.DataFrame({"<b>col</b>": [1, 2, 3], "x": [4, 5, 6]}).write_parquet(path)
        widget = make(ElaParquetTable, parquet_path=str(path))
        widget.show()
        qapp.processEvents()
        return widget

    def test_markup_column_name_shown_literally(self, evil_table, qapp):
        evil_table._on_cell_clicked(evil_table._table.model().index(0, 0))
        qapp.processEvents()
        assert "<b>col</b>" in evil_table._info_bar._col_label.text()

    def test_labels_are_plain_text(self, evil_table):
        # AutoText 会走 mightBeRichText()：列名叫 <b>x</b> 的文件会被真解析
        for name in TestInfoBarAppearance.LABELS:
            label = getattr(evil_table._info_bar, name)
            assert label.textFormat() == Qt.TextFormat.PlainText, name


class TestConstructorSignature:
    def test_parent_is_first_positional(self, make, qapp, parquet_file):
        # 构造参数必须是 (parent, ...)。原签名是
        # (parquet_path, page_size, show_row_index, parent)，于是
        # ``ElaParquetTable(some_widget)`` 会把 widget 当路径 -> str() ->
        # is_file() False -> 抛 **FileNotFoundError**（而不是 TypeError），
        # 排查成本很高。
        parent = make(QWidget)
        widget = make(ElaParquetTable, parent, str(parquet_file))
        assert widget.parent() is parent
        assert widget.totalRows() == ROWS

    def test_keyword_form(self, make, parquet_file):
        widget = make(ElaParquetTable, parquet_path=str(parquet_file))
        assert widget.totalRows() == ROWS
