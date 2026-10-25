"""插话回执与上下文压缩分段方法组。"""

from __future__ import annotations


from typing import Optional
from uuid import uuid4


from .blocks import (
    CompactionSeparator,
    SteerNotice,
)
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatStatusType,
)


class _BubbleMiscMixin:
    """方法组 mixin：状态由 ``ElaChatBubble.__init__`` 建立。"""

    def addSteerNotice(self, text: str, partId: Optional[str] = None) -> str:
        """追加一条插话回执，返回分段 id。

        **刻意不插一条用户消息** —— 助手消息正在流式输出，中途插一条用户
        气泡视觉上很怪。回执行留在同一条助手消息内，语义是「插话已送达」。
        """
        self._ensure_parts_materialized()
        self._mark_generation_started()
        partId = partId or uuid4().hex[:12]
        widget = SteerNotice(self._parts_container or self._content or self)
        widget.setText(text or "")
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Synthetic,
            text=text or "",
            status=ElaChatStatusType.Done,
            step=self._step_index,
        )
        self._append_part(part, widget)
        return partId

    def beginCompaction(
        self, reason: str = "auto", partId: Optional[str] = None
    ) -> str:
        """开始一次上下文压缩，返回分段 id。

        **库不实现压缩算法** —— 摘要怎么来、压哪段、什么时候压都由宿主决定
        （依赖 provider 侧的能力）。本方法只在时间线上如实表达「这里发生过
        一次压缩」，并把摘要接上。

        ``reason`` **只进 journal 原始事件**（宿主诊断用），时间线卡片不展示它。
        """
        self._ensure_parts_materialized()
        self._mark_generation_started()
        partId = partId or uuid4().hex[:12]
        widget = CompactionSeparator(self._parts_container or self._content or self)
        widget.setCompactionStatus(ElaChatStatusType.Streaming)
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Compaction,
            status=ElaChatStatusType.Streaming,
            step=self._step_index,
        )
        self._append_part(part, widget)
        return partId

    def appendCompactionSummary(self, partId: str, chunk: str) -> None:
        """追加压缩摘要（流式）。"""
        if not partId or not chunk:
            return
        part = self._find_part(partId)
        if part is None or part.kind != ElaChatPartKindType.Compaction:
            return
        self._replace_part(partId, part.withText(part.text + chunk))
        widget = self._part_widgets.get(partId)
        if isinstance(widget, CompactionSeparator):
            widget.setSummary(part.text + chunk)

    def endCompaction(
        self, partId: str, status: str = ElaChatStatusType.Done, historyCount: int = 0
    ) -> None:
        """结束压缩（``status`` 非 Done 时视为失败，摘要就地落定）。"""
        if not partId:
            return
        part = self._find_part(partId)
        if part is None or part.kind != ElaChatPartKindType.Compaction:
            return
        self._materialize_part(partId)
        self._replace_part(partId, part.withStatus(status))
        widget = self._part_widgets.get(partId)
        if isinstance(widget, CompactionSeparator):
            widget.setSummary(part.text)
            widget.setHistoryCount(historyCount)
            widget.setCompactionStatus(status)
