"""Tests for parquet_table module: ElaParquetTable, ElaInfoBarWidget."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pyqt6_ela_pro import parquet_table
from pyqt6_ela_pro.parquet_table import (
    INFO_BAR_HEIGHT,
    INFO_BAR_SPACING,
    ElaInfoBarWidget,
)


class TestConstants:
    """Test cases for module constants."""

    def test_info_bar_height(self):
        """Test INFO_BAR_HEIGHT is 40."""
        assert INFO_BAR_HEIGHT == 40

    def test_info_bar_spacing(self):
        """Test INFO_BAR_SPACING is 10."""
        assert INFO_BAR_SPACING == 10


class TestElaInfoBarWidget:
    """Test cases for ElaInfoBarWidget class."""

    def test_initialization(self):
        """Test info bar initializes correctly."""
        bar = ElaInfoBarWidget()

        assert bar._col_name == ""
        assert bar._col_index == 0
        assert bar._min_val == ""
        assert bar._max_val == ""
        assert bar._last_val == ""

        bar.deleteLater()

    def test_fixed_height_is_info_bar_height(self):
        """Test info bar has fixed height of INFO_BAR_HEIGHT."""
        bar = ElaInfoBarWidget()

        assert bar.height() == INFO_BAR_HEIGHT

        bar.deleteLater()

    def test_update_info(self):
        """Test update_info updates all values."""
        bar = ElaInfoBarWidget()

        bar.update_info("年龄", 2, "18", "100", "50")

        assert bar._col_name == "年龄"
        assert bar._col_index == 2
        assert bar._min_val == "18"
        assert bar._max_val == "100"
        assert bar._last_val == "50"

        bar.deleteLater()

    def test_clear_info(self):
        """Test clear_info updates label text."""
        bar = ElaInfoBarWidget()
        bar.update_info("年龄", 2, "18", "100", "50")

        bar.clear_info()

        assert "列" in bar._col_label.text()

        bar.deleteLater()


class TestElaParquetTableImport:
    """Test cases for ElaParquetTable import behavior."""

    def test_polars_not_installed_raises_import_error(self):
        """Test ElaParquetTable raises ImportError when polars is not available."""

        original_pl = getattr(parquet_table, "pl", None)
        parquet_table.pl = None

        try:
            with pytest.raises(ImportError, match="polars"):
                parquet_table.ElaParquetTable.__init__(
                    parquet_table.ElaParquetTable.__new__(
                        parquet_table.ElaParquetTable
                    ),
                    "test.parquet",
                )
        finally:
            if original_pl is not None:
                parquet_table.pl = original_pl

    def test_file_not_found_raises_error(self):
        """Test loadData raises FileNotFoundError for missing file."""

        original_pl = getattr(parquet_table, "pl", None)
        mock_pl = MagicMock()
        parquet_table.pl = mock_pl

        try:
            table = parquet_table.ElaParquetTable()
            with pytest.raises(FileNotFoundError):
                table.loadData("nonexistent_file.parquet")
        finally:
            if original_pl is not None:
                parquet_table.pl = original_pl
            else:
                parquet_table.pl = None
