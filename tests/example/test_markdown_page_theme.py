"""Markdown 示例页：阅读器正文 + ElaDrawer 设置面板。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaMarkdownViewer
from pyqt6_ela_pro.example.markdown_page import MarkdownPage


def test_reader_uses_single_full_page_viewer(qapp, make):
    page = make(MarkdownPage)
    viewers = page.findChildren(ElaMarkdownViewer)
    assert viewers == [page._reader_view]
    assert page._reader_view.document().blockCount() > 100
    assert page._settings_drawer is not None
    assert page._settings_drawer.contentWidget() is not None


def test_theme_combo_applies_to_all_viewers(qapp, make):
    page = make(MarkdownPage)
    viewers = page.findChildren(ElaMarkdownViewer)
    assert viewers

    combo = page._md_theme_combo
    for target in (
        "lark",
        "typo",
        "vue",
        "ayu",
        "solarized",
        "indigo",
        "paper",
        "github",
        "nord",
    ):
        combo.setCurrentIndex(combo.findText(target))
        qapp.processEvents()
        assert combo.currentText() == target
        assert all(viewer.markdownTheme() == target for viewer in viewers)


def test_drawer_toggles_line_numbers_and_collapse(qapp, make):
    page = make(MarkdownPage)
    viewer = page._reader_view

    assert not viewer.lineNumbersEnabled()
    page._line_numbers_switch.setIsToggled(True)
    qapp.processEvents()
    assert viewer.lineNumbersEnabled()

    assert viewer.codeBlockCollapseLines() == 0
    page._collapse_combo.setCurrentIndex(1)
    qapp.processEvents()
    assert viewer.codeBlockCollapseLines() == 12


def test_drawer_search_reports_matches(qapp, make):
    page = make(MarkdownPage)
    page._search_edit.setText("ElaMarkdownViewer")
    qapp.processEvents()
    assert "处" in page._search_count.text()
