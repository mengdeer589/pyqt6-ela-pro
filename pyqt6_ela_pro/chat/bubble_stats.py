"""气泡用量徽标 / 展示模式 / 底部停靠方法组。"""

from __future__ import annotations

from .bubble_shared import _STATS_MODES


from typing import Optional
from uuid import uuid4

from .._internal import is_deleted


from .blocks import (
    StatsBadge,
)
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
)


class _BubbleStatsMixin:
    """方法组 mixin：状态由 ``ElaChatBubble.__init__`` 建立。"""

    def statsBadge(self) -> Optional[StatsBadge]:
        """获取当前展示的用量徽标（无则 ``None``；``"none"`` 模式恒为 ``None``）。"""
        if self._stats_mode == "none":
            return None
        for part in reversed(self._parts):
            if part.kind != ElaChatPartKindType.Stats:
                continue
            widget = self._part_widgets.get(part.id)
            if isinstance(widget, StatsBadge):
                return widget
        return None

    def setStatsMode(self, mode: str) -> None:
        """设置用量徽标展示模式（立即生效；非法值回落 ``"footer"``）。

        ``"footer"``：一个整轮汇总徽标（各步求和）；``"steps"``：每步各自一个
        徽标；``"none"``：不显示，耗时回退到底部 meta 文本。每步原始用量始终
        保留在 ``parts`` 中。
        """
        self._stats_mode = mode if mode in _STATS_MODES else "footer"
        self._apply_stats_mode()
        self._sync_stats_duration()

    def statsMode(self) -> str:
        """获取用量徽标展示模式。"""
        return self._stats_mode

    def _apply_stats_mode(self) -> None:
        """按当前模式显隐 / 刷新各步骤用量徽标（不改 ``parts`` 原始数据）。

        流式回合内一律不摆徽标（数字未落定且会反复跳动）；历史恢复时按模式
        按需建 ``StatsBadge``，footer 每条消息只建最后一个。
        """
        stats_parts = [
            part
            for part in self._parts
            if part.kind == ElaChatPartKindType.Stats and part.stats is not None
        ]
        if not stats_parts:
            return
        if self._stats_mode == "none" or self._status == ElaChatStatusType.Streaming:
            for part in stats_parts:
                widget = self._part_widgets.get(part.id)
                if isinstance(widget, StatsBadge) and not is_deleted(widget):
                    widget.hide()
            return
        if self._stats_mode == "footer":
            visible_parts = stats_parts[-1:]
        else:
            visible_parts = stats_parts
        visible_ids = {part.id for part in visible_parts}
        for part in stats_parts:
            if part.id in visible_ids:
                continue
            widget = self._part_widgets.get(part.id)
            if isinstance(widget, StatsBadge) and not is_deleted(widget):
                widget.hide()
        for part in visible_parts:
            badge = self._ensure_stats_badge(part)
            badge.show()
        if self._stats_mode == "footer":
            last_part = stats_parts[-1]
            last_badge = self._ensure_stats_badge(last_part)
            merged = ElaChatStats.merge(part.stats for part in stats_parts)
            last_badge.setStats(merged if merged is not None else last_part.stats)
        else:
            for part in stats_parts:
                self._ensure_stats_badge(part).setStats(part.stats)
        # 判据是消息状态而不是 ``_stream_ended``：``setParts`` / ``setStatus``
        # 收尾都不经过 ``endStream``，拿历史标志会把恢复出的汇总徽标留在时间线里。
        if self._status != ElaChatStatusType.Streaming:
            self._dock_step_stats_to_footer()

    def _ensure_stats_badge(self, part: ElaChatPart) -> StatsBadge:
        """按需创建 / 复用某个用量分段的徽标（历史恢复延迟建控件）。"""
        widget = self._part_widgets.get(part.id)
        if isinstance(widget, StatsBadge) and not is_deleted(widget):
            return widget
        badge = StatsBadge(self._parts_container or self._content or self)
        self._part_widgets[part.id] = badge
        if self._parts_layout is not None:
            self._parts_layout.insertWidget(self._part_layout_index(part.id), badge)
        else:
            badge.setParent(self._parts_container or self._content or self)
        return badge

    def _sync_stats_duration(self) -> None:
        """把端到端耗时同步到最后一个用量徽标的悬浮提示。"""
        badge = self.statsBadge()
        if badge is None:
            self._meta.setDuration(self._duration_ms)
            return
        badge.setMessageDuration(self._duration_ms)
        self._meta.setDuration(0)

    def setStepStats(
        self, stats: Optional[ElaChatStats], partId: Optional[str] = None
    ) -> None:
        """设置当前步骤的用量统计（``None`` 移除当前步骤记录）。

        每步原始用量记录为 ``parts`` 中的 ``Stats`` 分段（不汇总），展示由
        :meth:`setStatsMode` 决定。``partId`` 由 :meth:`setParts` 传入时保留原 id。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        self._ensure_parts_materialized()
        if partId is not None:
            # 恢复路径：明确指定分段 id，不再复用当前步骤的用量段
            self._current_stats_id = partId
        if stats is None:
            if self._current_stats_id is not None:
                partId = self._current_stats_id
                self._current_stats_id = None
                self._drop_part(partId)
                if not self._stats_batch:
                    self._apply_stats_mode()
                    self._sync_stats_duration()
            return
        part = self._find_part(self._current_stats_id)
        if part is None:
            partId = partId or uuid4().hex[:12]
            badge = None
            if not self._stats_batch:
                # 历史回放期只登记数据，可见徽标由 _apply_stats_mode 按需创建
                badge = StatsBadge(self._parts_container or self._content or self)
                badge._setStats(stats, deferShow=False)
            self._append_part(
                ElaChatPart(
                    id=partId,
                    kind=ElaChatPartKindType.Stats,
                    status=ElaChatStatusType.Done,
                    stats=stats,
                    step=self._step_index,
                ),
                badge,
            )
            self._current_stats_id = partId
        else:
            self._replace_part(self._current_stats_id, part.withStats(stats))
            widget = self._part_widgets.get(self._current_stats_id)
            if isinstance(widget, StatsBadge):
                widget.setStats(stats)
        if self._stats_batch:
            return
        self._apply_stats_mode()
        self._sync_stats_duration()

    def stats(self) -> Optional[ElaChatStats]:
        """获取整轮用量汇总（各步求和；无记录返回 ``None``）。"""
        return ElaChatStats.merge(
            part.stats
            for part in self._parts
            if part.kind == ElaChatPartKindType.Stats and part.stats is not None
        )

    def _dock_step_stats_to_footer(self) -> None:
        """把展示中的用量徽标停靠到底部行（停靠是独占的，换目标前先归位）。"""
        if self._stats_layout is None or self._stats_mode == "none":
            return
        target = None
        for part in reversed(self._parts):
            if part.kind == ElaChatPartKindType.Stats:
                target = part.id
                break
        if target is None:
            return
        widget = self._part_widgets.get(target)
        if widget is None or is_deleted(widget):
            return
        if widget.parentWidget() is self._stats_host:
            return
        self._undock_step_stats(target)
        index = (
            self._parts_layout.indexOf(widget) if self._parts_layout is not None else -1
        )
        if self._parts_layout is not None:
            self._parts_layout.removeWidget(widget)
        else:
            widget.setParent(self._stats_host)
        self._stats_layout.addWidget(widget)
        self._docked_stats = (target, index)

    def _undock_step_stats(self, nextTarget: Optional[str] = None) -> None:
        """把已停靠的徽标放回时间线（``nextTarget`` 是自己时不摘）。"""
        docked = self._docked_stats
        self._docked_stats = None
        if docked is None:
            return
        partId, index = docked
        if partId == nextTarget:
            return
        widget = self._part_widgets.get(partId)
        if widget is None or is_deleted(widget):
            return
        if widget.parentWidget() is not self._stats_host:
            return
        self._stats_layout.removeWidget(widget)
        if self._parts_layout is None:
            return
        if not any(part.id == partId for part in self._parts):
            return
        if index < 0 or index > self._parts_layout.count():
            self._parts_layout.addWidget(widget)
        else:
            self._parts_layout.insertWidget(index, widget)
