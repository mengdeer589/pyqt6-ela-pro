"""插话回执与上下文压缩分段方法组。"""

from __future__ import annotations


from typing import Optional
from uuid import uuid4


from .._internal import is_deleted
from ._changes import ElaChatTurnChanges, changesFromParts
from .blocks import (
    CompactionSeparator,
    ElaChatNotice,
    PlanPanel,
    SteerNotice,
    TurnChangesRow,
)
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPlan,
    ElaChatRoleType,
    ElaChatStatusType,
)


class _BubbleMiscMixin:
    """方法组 mixin：状态由 ``ElaChatBubble.__init__`` 建立。"""

    def addNotice(
        self,
        noticeType: str,
        text: str = "",
        detail: str = "",
        partId: Optional[str] = None,
    ) -> str:
        """追加一条时间线通知（模型 / agent / 目录切换、中断等），返回分段 id。"""
        self._ensure_parts_materialized()
        partId = partId or uuid4().hex[:12]
        widget = ElaChatNotice(
            noticeType,
            text,
            detail,
            self._parts_container or self._content or self,
        )
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Notice,
            text=text or "",
            status=ElaChatStatusType.Done,
            notice_type=noticeType or "",
            detail=detail or "",
            step=self._step_index,
        )
        self._append_part(part, widget)
        self._apply_part_visibility(partId)
        return partId

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

    def setPlan(
        self,
        plan,
        partId: Optional[str] = None,
    ) -> str:
        """插入 / 更新一张计划卡，返回分段 id。

        ``partId`` 为空时复用消息里最后一张计划卡（反复上报不会堆一摞卡）；
        传新 id 可显式新建。计划内容不并入 ``message.text``。
        """
        if self._role != ElaChatRoleType.Assistant:
            return ""
        self._ensure_parts_materialized()
        self._mark_generation_started()
        value = ElaChatPlan.coerce(plan)
        if value is None:
            return ""
        if partId is None:
            for part in reversed(self._parts):
                if part.kind == ElaChatPartKindType.Plan:
                    partId = part.id
                    break
        partId = partId or uuid4().hex[:12]
        part = self._find_part(partId)
        if part is not None and part.kind == ElaChatPartKindType.Plan:
            self._replace_part(partId, part.withPlan(value))
            widget = self._part_widgets.get(partId)
            if isinstance(widget, PlanPanel):
                widget.setPlan(value)
            return partId
        widget = PlanPanel(self._parts_container or self._content or self, plan=value)
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Plan,
            status=ElaChatStatusType.Done,
            plan=value,
            step=self._step_index,
        )
        self._append_part(part, widget)
        return partId

    def plan(self) -> Optional[ElaChatPlan]:
        """获取最后一张计划卡的快照（无则 ``None``）。"""
        part = self.planPart()
        return part.plan if part is not None else None

    def planPart(self) -> Optional[ElaChatPart]:
        """获取最后一个计划分段（无则 ``None``）。"""
        for part in reversed(self._parts):
            if part.kind == ElaChatPartKindType.Plan:
                return part
        return None

    def clearPlan(self) -> None:
        """移除全部计划卡。"""
        self._remove_parts({ElaChatPartKindType.Plan})

    def turnChanges(self) -> ElaChatTurnChanges:
        """获取当前回合的文件变更汇总（从工具 metadata 派生）。"""
        return changesFromParts(self._parts)

    def setChangeSummaryEnabled(self, on: bool) -> None:
        """设置是否在回合末显示文件变更汇总（默认开）。"""
        self._change_summary_enabled = bool(on)
        self._sync_changes_row()

    def changeSummaryEnabled(self) -> bool:
        """回合末是否显示文件变更汇总。"""
        return self._change_summary_enabled

    def _sync_changes_row(self) -> None:
        """按状态 / 变更数据显隐汇总行；流式期间不显示（避免计数跳动）。"""
        host = self._changes_host
        if host is None:
            return
        if (
            not self._change_summary_enabled
            or self._role != ElaChatRoleType.Assistant
            or self._status == ElaChatStatusType.Streaming
            or self._parts_deferred
        ):
            host.hide()
            return
        changes = self.turnChanges()
        if changes.isEmpty():
            host.hide()
            return
        row = self._changes_row
        if row is None or is_deleted(row):
            row = TurnChangesRow(host)
            host.layout().addWidget(row)
            self._changes_row = row
        row.setChanges(changes)
        host.show()
        if not row.isVisible():
            row.show()

    def beginCompaction(
        self,
        reason: str = "auto",
        partId: Optional[str] = None,
        *,
        queued: bool = False,
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
        status = ElaChatStatusType.Queued if queued else ElaChatStatusType.Streaming
        widget = CompactionSeparator(self._parts_container or self._content or self)
        widget.setCompactionStatus(status)
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Compaction,
            status=status,
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
        self,
        partId: str,
        status: str = ElaChatStatusType.Done,
        historyCount: int = 0,
        *,
        stats=None,
    ) -> None:
        """结束压缩（``status`` 非 Done 时视为失败 / 取消，摘要就地落定）。"""
        if not partId:
            return
        part = self._find_part(partId)
        if part is None or part.kind != ElaChatPartKindType.Compaction:
            return
        self._materialize_part(partId)
        part = part.withStatus(status).withHistoryCount(historyCount)
        if stats is not None:
            part = part.withStats(stats)
        self._replace_part(partId, part)
        widget = self._part_widgets.get(partId)
        if isinstance(widget, CompactionSeparator):
            widget.setSummary(part.text)
            widget.setHistoryCount(historyCount)
            widget.setCompactionStatus(status)
            widget.setStats(stats)
