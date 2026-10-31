"""会话内搜索（``ElaChatView`` 方法组）。"""

from __future__ import annotations

from typing import Optional

from ..ela_markdown_viewer import ElaMarkdownViewer
from .message import ElaChatPartKindType, ElaChatRoleType
from .search import SEARCH_HIT_LIMIT, ElaChatSearchBar, ElaChatSearchHit


class _ViewSearchMixin:
    """方法组 mixin：状态由 ``ElaChatView.__init__`` 建立。"""

    def searchText(self, text: str, caseSensitive: bool = False) -> int:
        """搜索会话正文（助手 Text 分段 + 用户文本），返回命中数（上限 500）。"""
        query = str(text or "")
        self._search_query = query
        self._search_case = bool(caseSensitive)
        self._search_hits = []
        self._search_index = -1
        self._clear_search_highlights()
        if not query:
            self._sync_search_bar()
            return 0
        needle = query if caseSensitive else query.lower()
        for message in self.messages():
            if message.role == ElaChatRoleType.Assistant:
                for part in message.parts:
                    if part.kind != ElaChatPartKindType.Text or not part.text:
                        continue
                    haystack = part.text if caseSensitive else part.text.lower()
                    start = 0
                    occurrence = 0
                    while True:
                        at = haystack.find(needle, start)
                        if at < 0:
                            break
                        self._search_hits.append(
                            ElaChatSearchHit(
                                message_id=message.id,
                                part_id=part.id,
                                occurrence=occurrence,
                                snippet=part.text[
                                    max(0, at - 20) : at + len(query) + 20
                                ],
                            )
                        )
                        occurrence += 1
                        start = at + max(1, len(query))
                        if len(self._search_hits) >= SEARCH_HIT_LIMIT:
                            break
                    if len(self._search_hits) >= SEARCH_HIT_LIMIT:
                        break
            elif message.role == ElaChatRoleType.User and message.text:
                haystack = message.text if caseSensitive else message.text.lower()
                start = 0
                occurrence = 0
                while True:
                    at = haystack.find(needle, start)
                    if at < 0:
                        break
                    self._search_hits.append(
                        ElaChatSearchHit(
                            message_id=message.id,
                            part_id="",
                            occurrence=occurrence,
                            snippet=message.text[
                                max(0, at - 20) : at + len(query) + 20
                            ],
                            user=True,
                        )
                    )
                    occurrence += 1
                    start = at + max(1, len(query))
                    if len(self._search_hits) >= SEARCH_HIT_LIMIT:
                        break
            if len(self._search_hits) >= SEARCH_HIT_LIMIT:
                break
        if self._search_hits:
            self._goto_search_hit(0)
        else:
            self._sync_search_bar()
        return len(self._search_hits)

    def searchNext(self) -> bool:
        """跳到下一个命中（循环）。"""
        if not self._search_hits:
            return False
        return self._goto_search_hit((self._search_index + 1) % len(self._search_hits))

    def searchPrev(self) -> bool:
        """跳到上一个命中（循环）。"""
        if not self._search_hits:
            return False
        return self._goto_search_hit((self._search_index - 1) % len(self._search_hits))

    def clearSearch(self) -> None:
        """清除查询与全部高亮。"""
        self._search_query = ""
        self._search_hits = []
        self._search_index = -1
        self._clear_search_highlights()
        self._sync_search_bar()

    def searchHits(self) -> list:
        """获取命中快照。"""
        return list(self._search_hits)

    def searchIndex(self) -> int:
        """当前命中下标（无命中 ``-1``）。"""
        return self._search_index

    def searchBar(self) -> Optional[ElaChatSearchBar]:
        """获取搜索条（未创建返回 ``None``）。"""
        return getattr(self, "_search_bar", None)

    def showSearchBar(self, text: str = "") -> ElaChatSearchBar:
        """显示搜索条并聚焦；可选预填查询。"""
        bar = self._ensure_search_bar()
        bar.show()
        if text:
            bar.setQuery(text)
            self.searchText(text)
        bar.focusEditor()
        return bar

    def hideSearchBar(self) -> None:
        """隐藏搜索条并清除高亮。"""
        bar = getattr(self, "_search_bar", None)
        if bar is not None:
            bar.closeBar()
        self.clearSearch()

    # -- 内部 --------------------------------------------------------------

    def _ensure_search_bar(self) -> ElaChatSearchBar:
        bar = getattr(self, "_search_bar", None)
        if bar is not None:
            return bar
        bar = ElaChatSearchBar(self)
        bar.queryChanged.connect(self.searchText)
        bar.nextRequested.connect(self.searchNext)
        bar.prevRequested.connect(self.searchPrev)
        bar.closed.connect(self.clearSearch)
        layout = self.layout()
        if layout is not None:
            layout.insertWidget(0, bar)
        self._search_bar = bar
        return bar

    def _sync_search_bar(self) -> None:
        bar = getattr(self, "_search_bar", None)
        if bar is not None:
            bar.setState(len(self._search_hits), self._search_index)

    def _clear_search_highlights(self) -> None:
        for bubble in list(self._bubbles.values()):
            if bubble is None:
                continue
            for widget in getattr(bubble, "_part_widgets", {}).values():
                if isinstance(widget, ElaMarkdownViewer):
                    widget.clearSearch()

    def _goto_search_hit(self, index: int) -> bool:
        if not self._search_hits:
            return False
        index = max(0, min(int(index), len(self._search_hits) - 1))
        hit = self._search_hits[index]
        self._search_index = index
        self.scrollToMessage(hit.message_id)
        bubble = self._bubbles.get(hit.message_id)
        if bubble is not None and hit.part_id:
            widget = bubble._part_widgets.get(hit.part_id)
            if isinstance(widget, ElaMarkdownViewer):
                count = widget.searchText(self._search_query, self._search_case)
                for _ in range(max(0, hit.occurrence)):
                    widget.findNext(False)
                if count == 0:
                    self._search_index = index
        self._sync_search_bar()
        return True
