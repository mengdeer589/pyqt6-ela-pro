"""会话内搜索（ElaChatSearchBar + view.searchText）。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatSearchBar,
    ElaChatView,
)
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


class TestSearch:
    def test_hits_and_navigation(self, qapp, make):
        view = make(ElaChatView)
        first = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(first)
        view.appendText(first, "alpha beta alpha")
        view.endText(first)
        view.endMessage(first)
        second = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(second)
        view.appendText(second, "alpha gamma")
        view.endText(second)
        view.endMessage(second)
        view.addMessage(ElaChatRoleType.User, "user alpha")
        assert view.searchText("alpha") == 4
        assert view.searchIndex() == 0
        assert view.searchNext()
        assert view.searchIndex() == 1
        assert view.searchPrev()
        assert view.searchIndex() == 0
        view.clearSearch()
        assert view.searchHits() == []
        assert view.searchIndex() == -1

    def test_case_sensitive(self, qapp, make):
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(mid)
        view.appendText(mid, "Alpha alpha")
        view.endText(mid)
        view.endMessage(mid)
        assert view.searchText("Alpha", caseSensitive=True) == 1
        assert view.searchText("Alpha", caseSensitive=False) == 2

    def test_search_bar_roundtrip(self, qapp, make):
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(mid)
        view.appendText(mid, "needle")
        view.endText(mid)
        view.endMessage(mid)
        bar = view.showSearchBar("needle")
        assert isinstance(bar, ElaChatSearchBar)
        assert not bar.isHidden()
        assert view.searchHits()
        view.hideSearchBar()
        assert bar.isHidden()
        assert view.searchHits() == []

    def test_search_clears_on_clear(self, qapp, make):
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(mid)
        view.appendText(mid, "needle")
        view.endText(mid)
        view.endMessage(mid)
        view.showSearchBar("needle")
        view.clear()
        assert view.searchHits() == []

    def test_hit_restores_suspended_viewer(self, qapp, make):
        view = make(ElaChatView)
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(mid)
        view.appendText(mid, "needle")
        view.endText(mid)
        view.endMessage(mid)
        bubble = view.bubble(mid)
        part_id = view.message(mid).parts[0].id
        bubble.setViewersSuspended(True)
        assert not isinstance(bubble._part_widgets[part_id], ElaMarkdownViewer)
        assert view.searchText("needle") == 1
        assert isinstance(bubble._part_widgets[part_id], ElaMarkdownViewer)

    def test_hit_expands_windowed_message(self, qapp, make):
        view = make(ElaChatView)
        view.resize(800, 500)
        view.show()
        qapp.processEvents()
        mid = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(mid)
        view.appendText(mid, "step 0 needle")
        view.endText(mid)
        for index in range(1, 25):
            view.beginStep(mid)
            view.beginText(mid)
            view.appendText(mid, f"step {index}")
            view.endText(mid)
        view.endMessage(mid)
        bubble = view.bubble(mid)
        bubble.setPartsDeferred(list(bubble.parts()))
        bubble.materializeParts()
        view._sync_parts(mid)
        view._flush_pending_syncs()
        early = [
            part.id
            for part in view.message(mid).parts
            if part.kind == ElaChatPartKindType.Text and "needle" in part.text
        ][0]
        assert bubble.partsWindowed()
        assert early not in bubble._part_widgets

        assert view.searchText("needle") == 1
        assert not bubble.partsWindowed()
        assert isinstance(bubble._part_widgets[early], ElaMarkdownViewer)
