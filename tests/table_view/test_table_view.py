"""Tests for table_view module: ElaDataTable, ElaRowColorDelegate."""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.table_view import (
    TABLE_MIN_SECTION_SIZE,
    TABLE_ROW_MIN_HEIGHT,
    TABLE_THREAD_QUIT_TIMEOUT,
    ElaDataTable,
    ElaRowColorDelegate,
    _LoadThread,
)


class TestElaRowColorDelegate:
    """Test cases for ElaRowColorDelegate."""

    def test_initialization(self):
        """Test delegate initializes with empty colors dict."""
        delegate = ElaRowColorDelegate()
        assert delegate._row_colors == {}
        delegate.deleteLater()

    def test_set_row_color(self):
        """Test setRowColor stores color for row."""
        delegate = ElaRowColorDelegate()
        color = QColor(255, 0, 0)
        delegate.setRowColor(0, color)

        assert 0 in delegate._row_colors
        assert delegate._row_colors[0] == color

        delegate.deleteLater()

    def test_set_row_color_multiple_rows(self):
        """Test setRowColor works for multiple rows."""
        delegate = ElaRowColorDelegate()
        delegate.setRowColor(0, QColor(255, 0, 0))
        delegate.setRowColor(5, QColor(0, 255, 0))
        delegate.setRowColor(10, QColor(0, 0, 255))

        assert len(delegate._row_colors) == 3
        delegate.deleteLater()

    def test_clear_all_colors(self):
        """Test clearAllColors removes all colors."""
        delegate = ElaRowColorDelegate()
        delegate.setRowColor(0, QColor(255, 0, 0))
        delegate.setRowColor(1, QColor(0, 255, 0))
        delegate.clearAllColors()

        assert len(delegate._row_colors) == 0
        delegate.deleteLater()

    def test_constants(self):
        """Test table constants are defined correctly."""
        assert TABLE_MIN_SECTION_SIZE == 60
        assert TABLE_ROW_MIN_HEIGHT == 46


class TestLoadThread:
    """Test cases for _LoadThread."""

    def test_initialization(self):
        """Test load thread initializes with rows."""
        thread = _LoadThread(rows=[["a", "b"], ["c", "d"]])
        assert thread._rows == [["a", "b"], ["c", "d"]]
        assert thread._isCanceled is False

    def test_cancel(self):
        """Test cancel sets isCanceled flag."""
        thread = _LoadThread(rows=[["a"]])
        thread.cancel()
        assert thread._isCanceled is True

    def test_run_emits_finished_when_not_canceled(self):
        """Test run emits finished signal with rows."""
        thread = _LoadThread(rows=[["a", "b"], ["c", "d"]])

        result = []
        thread.finished.connect(lambda r: result.extend(r))

        thread.run()

        assert len(result) == 2
        assert result == [["a", "b"], ["c", "d"]]

    def test_run_does_not_emit_when_canceled(self):
        """Test run does not emit finished when canceled."""
        thread = _LoadThread(rows=[["a", "b"]])
        thread.cancel()

        emitted = []
        thread.finished.connect(lambda r: emitted.append(True))

        thread.run()

        assert len(emitted) == 0


class TestElaDataTable:
    """Test cases for ElaDataTable class."""

    def test_loading_thread_timeout_constant(self):
        """Test TABLE_THREAD_QUIT_TIMEOUT is defined."""

        assert TABLE_THREAD_QUIT_TIMEOUT == 1000

    def test_delete_later_disconnects_section_clicked(self):
        """Test deleteLater disconnects sectionClicked signal without error."""

        table = ElaDataTable()
        table.deleteLater()  # should not raise TypeError when disconnecting

    def test_set_column_widths_by_header_name(self):
        """Test string header keys resolve to columns."""

        table = ElaDataTable()
        table.setTableData([["A", "B"], [1, 2], [3, 4]])

        table.setColumnWidths({"A": 120})

        assert table.columnWidth(0) == 120
        table.deleteLater()

    def test_apply_column_widths_with_header_name_on_show(self):
        """Regression: tableViewShow must not pass str keys to setColumnWidth."""

        table = ElaDataTable()
        table.setTableData([["A", "B"], [1, 2], [3, 4]])
        table.setColumnWidths({"A": 140, "不存在的列": 200})

        table.show()
        table.tableViewShow.emit()
        QApplication.processEvents()

        assert table.columnWidth(0) == 140
        table.close()
        table.deleteLater()

    def test_resolve_column_unknown_name_returns_none(self):
        """Test _resolve_column returns None for unmatched header name."""

        table = ElaDataTable()
        table.setTableData([["A", "B"], [1, 2]])

        assert table._resolve_column("A") == 0
        assert table._resolve_column(1) == 1
        assert table._resolve_column("missing") is None
        table.deleteLater()
