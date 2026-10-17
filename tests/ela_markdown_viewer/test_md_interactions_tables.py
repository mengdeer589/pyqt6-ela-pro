"""Tests for ElaMarkdownViewer interaction details and table styling.

Covers: copy button focus policy, anchor history, table zebra and column widths.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QTextTable
from PyQt6.QtTest import QTest

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


def _tables(viewer: ElaMarkdownViewer) -> list:
    result = []
    stack = [viewer.document().rootFrame()]
    while stack:
        frame = stack.pop()
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                result.append(child)
            stack.append(child)
    result.sort(key=lambda t: t.firstPosition())
    return result


TABLE_SOURCE = "| A | B |\n|---|----|\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |\n"


class TestCopyButtonFocus:
    def test_copy_button_no_focus(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(420, 320)
        v.setMarkdown("```python\nx = 1\n```")
        v.show()
        qapp.processEvents()
        QTest.qWait(150)

        assert v._code_buttons
        for button in v._code_buttons:
            assert button.focusPolicy() == Qt.FocusPolicy.NoFocus
        v.close()
        v.deleteLater()


class TestAnchorHistory:
    SOURCE = "# 一\n\n" + "段落内容\n\n" * 40 + "# 二\n\n" + "更多内容\n\n" * 40

    def test_back_to_previous_anchor(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(360, 240)
        v.setMarkdown(self.SOURCE)
        v.show()
        qapp.processEvents()
        QTest.qWait(200)

        bar = v.textBrowser().verticalScrollBar()
        bar.setValue(0)
        v._on_anchor_clicked(QUrl("#二"))
        assert len(v._anchor_back_stack) == 1
        v._on_anchor_clicked(QUrl("#一"))
        assert len(v._anchor_back_stack) == 2

        assert v.backToPreviousAnchor() is True
        assert len(v._anchor_back_stack) == 1
        assert v.backToPreviousAnchor() is True
        assert v.backToPreviousAnchor() is False
        v.close()
        v.deleteLater()

    def test_clear_anchor_history(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        v._on_anchor_clicked(QUrl("#二"))
        v.clearAnchorHistory()
        assert v.backToPreviousAnchor() is False
        v.deleteLater()

    def test_control_anchors_not_recorded(self):
        v = ElaMarkdownViewer()
        v.setCodeBlockCollapseLines(2)
        v.setMarkdown("```python\n1\n2\n3\n4\n```")
        v._on_anchor_clicked(QUrl("#elacode-expand-0"))
        assert v._anchor_back_stack == []
        v.deleteLater()


class TestTableZebra:
    def test_zebra_disabled_by_default(self):
        v = ElaMarkdownViewer()
        v.setMarkdown(TABLE_SOURCE)
        table = _tables(v)[0]
        assert table.cellAt(2, 0).format().background().style() == Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_zebra_applies_to_even_data_rows(self):
        v = ElaMarkdownViewer()
        v.setTableZebra(True)
        v.setMarkdown(TABLE_SOURCE)
        table = _tables(v)[0]

        assert table.cellAt(1, 0).format().background().style() == Qt.BrushStyle.NoBrush
        striped = table.cellAt(2, 0).format().background()
        assert striped.style() != Qt.BrushStyle.NoBrush
        assert striped.color().name() == v._table_stripe_bg.name()
        assert table.cellAt(0, 0).format().background().color().name() == (
            v._table_header_bg.name()
        )
        v.deleteLater()

    def test_zebra_toggle_off(self):
        v = ElaMarkdownViewer()
        v.setTableZebra(True)
        v.setMarkdown(TABLE_SOURCE)
        v.setTableZebra(False)
        table = _tables(v)[0]
        assert table.cellAt(2, 0).format().background().style() == Qt.BrushStyle.NoBrush
        v.deleteLater()


class TestTableColumnWidths:
    def test_widths_applied(self):
        v = ElaMarkdownViewer()
        v.setTableColumnWidths([60, 40])
        v.setMarkdown(TABLE_SOURCE)
        table = _tables(v)[0]

        constraints = table.format().columnWidthConstraints()
        assert len(constraints) == 2
        assert abs(constraints[0].rawValue() - 60) < 0.01
        assert abs(constraints[1].rawValue() - 40) < 0.01
        assert v.tableColumnWidths() == [60.0, 40.0]
        v.deleteLater()

    def test_mismatched_count_ignored(self):
        v = ElaMarkdownViewer()
        v.setTableColumnWidths([20, 20, 20])
        v.setMarkdown(TABLE_SOURCE)
        table = _tables(v)[0]
        assert len(table.format().columnWidthConstraints()) in (0, 2)
        v.deleteLater()

    def test_none_resets(self):
        v = ElaMarkdownViewer()
        v.setTableColumnWidths([70, 30])
        v.setTableColumnWidths(None)
        v.setMarkdown(TABLE_SOURCE)
        table = _tables(v)[0]
        assert table.format().columnWidthConstraints() == []
        assert v.tableColumnWidths() is None
        v.deleteLater()

    def test_invalid_values_reset(self):
        v = ElaMarkdownViewer()
        v.setTableColumnWidths([0, 100])
        assert v.tableColumnWidths() is None
        v.deleteLater()
