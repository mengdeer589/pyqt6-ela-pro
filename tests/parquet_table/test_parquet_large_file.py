import pytest

pytest.importorskip("polars")

import os  # noqa: E402

import polars as pl  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402

from pyqt6_ela_pro.parquet_table import ElaParquetTable  # noqa: E402

_HORIZONTAL = Qt.Orientation.Horizontal

ROWS = 200_000
#: 强制切出 20 个 row group —— 聚合必须跨组归并才对
ROW_GROUP_SIZE = 10_000
PAGE = 5000


@pytest.fixture(scope="module")
def big_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("big") / "big.parquet"
    # 用 LazyFrame.select 而不是 DataFrame({...: expr}) —— polars 的 DataFrame
    # 构造器不接受 Expr（只认 list[Expr]），直接塞会 TypeError
    df = (
        pl.LazyFrame(schema={"id": pl.Int64, "amount": pl.Float64, "label": pl.String})
        .select(
            pl.int_range(0, ROWS, dtype=pl.Int64).alias("id"),
            # 有意「非单调 + 跨零 + 重复值 + 负数」：min/max 只有真正归并全部
            # row group 才对得上；含负数还能抓住「只扫了前几组」
            (
                ((pl.int_range(0, ROWS, dtype=pl.Int64) * 7919) % 100_003).cast(
                    pl.Float64
                )
                - 50_000.0
            ).alias("amount"),
            # 字符串列：用来验「非数值列不出统计」
            (pl.int_range(0, ROWS, dtype=pl.Int64) % 97).cast(pl.String).alias("label"),
        )
        .collect()
    )
    df.write_parquet(path, row_group_size=ROW_GROUP_SIZE)
    return path


@pytest.fixture
def big_table(make, qapp, big_file):
    widget = make(ElaParquetTable, parquet_path=str(big_file), page_size=PAGE)
    widget.show()
    qapp.processEvents()
    return widget


class TestLargeFileLayout:
    def test_fixture_is_complete_and_multi_group(self, big_file):
        """守卫：数据可完整读回（少写一组min/max 就会偏）。"""
        assert pl.scan_parquet(big_file).select(pl.len()).collect().item() == ROWS
        assert pl.read_parquet_metadata(big_file)  # footer 可读

    def test_row_count_and_pages(self, big_table):
        assert big_table.totalRows() == ROWS
        assert big_table.totalPages() == ROWS // PAGE
        assert big_table.pageSize() == PAGE

    def test_first_page_contains_the_first_rows(self, big_table):
        model = big_table._table.model()
        assert model.rowCount() == PAGE
        assert model.item(0, 0).text() == "0"
        assert model.item(PAGE - 1, 0).text() == str(PAGE - 1)

    def test_paging_never_repeats_or_skips(self, big_table):
        """逐页取第一列拼起来必须恰好是 0..ROWS-1（无重复、无跳行）。"""
        seen: list[int] = []
        for page in range(1, big_table.totalPages() + 1):
            big_table.goToPage(page)
            model = big_table._table.model()
            seen.extend(int(model.item(r, 0).text()) for r in range(model.rowCount()))
        assert len(seen) == ROWS
        assert seen == list(range(ROWS)), "分页出现重复或跳行"

    def test_row_index_labels_match_page_offset(self, big_table):
        big_table.goToPage(3)
        model = big_table._table.model()
        assert model.verticalHeaderItem(0).text() == str(2 * PAGE + 1)
        assert model.verticalHeaderItem(model.rowCount() - 1).text() == str(3 * PAGE)

    def test_clamping_lands_on_real_pages(self, big_table):
        big_table.goToPage(10**9)
        assert big_table.currentPage() == big_table.totalPages()
        big_table.goToPage(-1)
        assert big_table.currentPage() == 1


class TestLargeFileColumnStats:
    """核心：min/max 必须跨**全部** row group 归并。"""

    def test_matches_full_column_truth(self, big_table, big_file, qapp):
        expected = (
            pl.read_parquet(big_file)
            .select(
                pl.col("amount").min().alias("min"),
                pl.col("amount").max().alias("max"),
                pl.col("amount").last().alias("last"),
            )
            .to_dicts()[0]
        )
        big_table._column_stats_cache.clear()
        big_table._on_cell_clicked(big_table._table.model().index(0, 1))
        qapp.processEvents()
        info = big_table._info_bar
        assert float(info._min_val) == pytest.approx(expected["min"])
        assert float(info._max_val) == pytest.approx(expected["max"])
        assert float(info._last_val) == pytest.approx(expected["last"])

    def test_min_is_negative_so_partial_scan_would_be_caught(self, big_table, qapp):
        """amount 含负数：若实现只扫了前几个 row group，min 必然偏大。"""
        truth = None
        big_table._column_stats_cache.clear()
        big_table._on_cell_clicked(big_table._table.model().index(0, 1))
        qapp.processEvents()
        truth = float(big_table._info_bar._min_val)
        assert truth < 0, "amount 列含负数；min 为非负说明只扫了部分 row group"

    def test_stats_are_reused_on_second_click(self, big_table, qapp):
        """缓存命中：值不变，且**不再触碰 polars**（用计数哨兵验，不看耗时）。"""
        model = big_table._table.model()
        big_table._column_stats_cache.clear()
        big_table._on_cell_clicked(model.index(0, 1))
        qapp.processEvents()
        assert "amount" in big_table._column_stats_cache
        first = dict(big_table._column_stats_cache["amount"])

        calls: list[str] = []
        real = big_table._compute_column_stats

        def counting(name: str):
            calls.append(name)
            return real(name)

        big_table._compute_column_stats = counting  # type: ignore[method-assign]
        try:
            big_table._on_cell_clicked(model.index(0, 1))
            qapp.processEvents()
        finally:
            del big_table._compute_column_stats  # type: ignore[attr-defined]
        assert calls == [], "缓存命中却仍重算了统计"
        assert big_table._column_stats_cache["amount"] == first

    def test_string_column_has_no_stats(self, big_table, qapp):
        model = big_table._table.model()
        assert model.headerData(2, _HORIZONTAL) == "label"
        big_table._column_stats_cache.clear()
        big_table._on_cell_clicked(model.index(0, 2))
        qapp.processEvents()
        assert big_table._column_stats_cache == {}, "字符串列不该出统计"
        assert big_table._info_bar._min_label.text() == "最小值: -"

    def test_int_column_does_have_stats(self, big_table, qapp):
        big_table._column_stats_cache.clear()
        big_table._on_cell_clicked(big_table._table.model().index(0, 0))  # id
        qapp.processEvents()
        assert "id" in big_table._column_stats_cache
        assert float(big_table._info_bar._min_val) == 0.0
        assert float(big_table._info_bar._max_val) == float(ROWS - 1)


class TestLargeFileStateHandling:
    def test_reload_same_file_resets_cache_and_page(self, big_table, big_file, qapp):
        big_table._on_cell_clicked(big_table._table.model().index(0, 1))
        qapp.processEvents()
        assert big_table._column_stats_cache
        big_table.goToPage(5)
        big_table.loadData(str(big_file))
        qapp.processEvents()
        assert big_table._column_stats_cache == {}, "重载后统计缓存必须清空"
        assert big_table.currentPage() == 1

    def test_same_column_name_in_another_file_is_recomputed(self, make, qapp, tmp_path):
        """统计缓存**按列名**存 —— 换文件后同名列必须重算，否则显示别人的值。"""
        a = tmp_path / "a.parquet"
        b = tmp_path / "b.parquet"
        pl.DataFrame({"v": [1.0, 2.0, 3.0]}).write_parquet(a)
        pl.DataFrame({"v": [-100.0, 0.0, 100.0]}).write_parquet(b)
        table = make(ElaParquetTable, parquet_path=str(a))
        table.show()
        qapp.processEvents()
        table._on_cell_clicked(table._table.model().index(0, 0))
        qapp.processEvents()
        assert float(table._info_bar._min_val) == 1.0
        table.loadData(str(b))
        qapp.processEvents()
        table._on_cell_clicked(table._table.model().index(0, 0))
        qapp.processEvents()
        assert float(table._info_bar._min_val) == -100.0, (
            "同名列沿用了上一个文件的统计缓存"
        )

    def test_read_failure_still_contained_on_big_file(self, big_table, qapp, tmp_path):
        errors: list[str] = []
        big_table.errorOccurred.connect(errors.append)
        os.rename(big_table._parquet_path, tmp_path / "gone.parquet")
        big_table._column_stats_cache.clear()
        big_table.goToPage(2)
        big_table._on_cell_clicked(big_table._table.model().index(0, 1))
        qapp.processEvents()
        assert errors, "大文件路径上的读失败没被兜住"
        assert "读取 Parquet 文件失败" in errors[0]
