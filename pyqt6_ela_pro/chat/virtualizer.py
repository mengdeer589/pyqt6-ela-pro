"""聊天视图的虚拟化 / 懒加载 / 视口挂起协调器。"""

from __future__ import annotations

import bisect
import time
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from .._internal import is_deleted
from .bubble import ElaChatBubble
from .message import ElaChatMessage, ElaChatRoleType
from .view_metrics import (
    _LAZY_PAGE_SIZE,
    _LAZY_TRIGGER_VIEWPORTS,
    _MESSAGE_SPACING,
    _SUSPEND_INTERVAL_MS,
    _SUSPEND_MARGIN_VIEWPORTS,
    _VIRTUAL_MATERIALIZE_BUDGET,
    _VIRTUAL_MATERIALIZE_BUDGET_MS,
    _VIRTUAL_WINDOW_MARGIN_RATIOS,
)
from .view_parts import DeferredPlaceholder


class ChatVirtualizer:
    """把虚拟列表 / 壳占位 / 视口挂起的行为从 ``ElaChatView`` 中拆出来。"""

    def __init__(self, view) -> None:
        self._view = view

    def _disable_virtual_list(self) -> None:
        """退出 spacer 模式：物化全部消息并移除上下占位。"""
        for messageId in list(self._view._message_index):
            if messageId not in self._view._bubbles:
                self._view._materialize_virtual_bubble(messageId)
        for spacer in (
            self._view._virtual_top_spacer,
            self._view._virtual_bottom_spacer,
        ):
            if spacer is not None:
                self._view._content_layout.removeWidget(spacer)
                spacer.hide()
                spacer.setParent(None)
                spacer.deleteLater()
        self._view._virtual_top_spacer = None
        self._view._virtual_bottom_spacer = None
        self._view._virtual_list_mode = False
        self._view._virtual_window_timer.stop()
        self._view._virtual_bubble_ids = list(self._view._message_index)
        self._view._virtual_prefix_dirty = True

    def _virtual_height(self, messageId: int) -> int:
        """消息当前在布局中的高度（气泡实测 / 缓存估算）。"""
        bubble = self._view._bubbles.get(messageId)
        if bubble is not None:
            height = bubble.height()
            if height > 0:
                return height
        placeholder = self._view._shell_placeholders.get(messageId)
        if placeholder is not None and not is_deleted(placeholder):
            return placeholder.height()
        height = self._view._virtual_heights.get(messageId)
        if height is not None:
            return height
        message = self._view._message_index.get(messageId)
        if message is None:
            return 0
        height = self._view._estimate_shell_height(message)
        self._view._virtual_heights[messageId] = height
        return height

    def _ensure_virtual_prefix(self) -> None:
        """重建「消息起点」前缀（含 20px 间距），供可见区间二分。"""
        if not self._view._virtual_prefix_dirty and len(
            self._view._virtual_order
        ) == len(self._view._messages):
            return
        if self._view._virtual_order_dirty or len(self._view._virtual_order) != len(
            self._view._messages
        ):
            order = []
            index_by_id = {}
            for index, message in enumerate(self._view._messages):
                order.append(message.id)
                index_by_id[message.id] = index
            self._view._virtual_order = order
            self._view._virtual_index = index_by_id
            self._view._virtual_order_dirty = False
        order = self._view._virtual_order
        prefix = []
        total = 0
        for index, messageId in enumerate(order):
            if index:
                total += _MESSAGE_SPACING
            prefix.append(total)
            total += self._view._virtual_height(messageId)
        prefix.append(total)
        self._view._virtual_prefix = prefix
        self._view._virtual_prefix_dirty = False

    def _init_virtual_spacers(self) -> None:
        """超长历史进入 spacer 虚拟列表：内容区只保留上下两个占位。"""
        if self._view._virtual_top_spacer is not None:
            return
        top = DeferredPlaceholder(self._view._content)
        top.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top.setFixedHeight(0)
        self._view._content_layout.insertWidget(0, top)
        bottom = DeferredPlaceholder(self._view._content)
        bottom.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        bottom.setFixedHeight(0)
        self._view._content_layout.insertWidget(
            max(0, self._view._content_layout.count() - 1), bottom
        )
        self._view._virtual_top_spacer = top
        self._view._virtual_bottom_spacer = bottom

    def _materialize_virtual_bubble(self, messageId: int) -> Optional[ElaChatBubble]:
        """在 spacer 列表里物化一条消息（插到正确的可见顺序位置）。"""
        message = self._view._message_index.get(messageId)
        if message is None or messageId in self._view._bubbles:
            return self._view._bubbles.get(messageId)
        order_pos = self._view._virtual_index.get(messageId, 0)
        position = 0
        for existing in self._view._virtual_bubble_ids:
            if self._view._virtual_index.get(existing, 0) > order_pos:
                break
            position += 1
        deferred = message.role == ElaChatRoleType.Assistant and bool(
            message.text or message.parts
        )
        bubble = self._view._build_bubble(
            messageId,
            message.role,
            "" if message.parts else message.text,
            False,
            deferred,
            insert_index=1 + position,
            identity=(message.agent, message.model, message.model_variant),
            mentions=message.mentions,
        )
        self._view._virtual_bubble_ids.insert(position, messageId)
        if message.parts:
            if self._view._virtual_parts_enabled:
                bubble.setPartsDeferred(message.parts)
            else:
                bubble.setParts(message.parts)
        elif deferred:
            bubble.setRenderDeferred(True)
            bubble.setText(message.text)
        self._view._apply_message_fields(messageId, message)
        self._view._sync_parts(messageId)
        bubble.materializeParts()
        bubble.setRenderDeferred(False)
        bubble.flushRender()
        self._view._content_layout.activate()
        height = bubble.height()
        if height <= 0:
            height = self._view._estimate_shell_height(message)
        self._view._virtual_heights[messageId] = max(40, height)
        self._view._virtual_prefix_dirty = True
        return bubble

    def _dematerialize_virtual_bubble(self, messageId: int) -> None:
        """从 spacer 列表移除一条已物化消息（保留实测高度）。

        在途回合 / 待答审批 / 用户手动展开的区块**不回收**：销毁气泡会丢掉
        未落定分片与交互状态（与 ``_dematerialize_shell`` 同一组守卫）。
        """
        bubble = self._view._bubbles.get(messageId)
        if bubble is None:
            return
        if (
            bubble.isStreaming()
            or bubble.pendingPermissions()
            or bubble.hasExpandedSections()
        ):
            return
        self._flush_dirty_before_destroy(messageId, bubble)
        self._view._bubbles.pop(messageId, None)
        height = bubble.height()
        if height > 0:
            self._view._virtual_heights[messageId] = max(40, height)
        if messageId in self._view._virtual_bubble_ids:
            self._view._virtual_bubble_ids.remove(messageId)
        bubble.hide()
        self._view._content_layout.removeWidget(bubble)
        bubble.setParent(None)
        bubble.deleteLater()
        self._view._dirty_syncs.discard(messageId)
        self._view._suspended_ids.discard(messageId)
        self._view._drop_message_guards(messageId)
        self._view._virtual_prefix_dirty = True

    def _flush_dirty_before_destroy(self, messageId: int, bubble) -> None:
        """销毁气泡前结算它的未同步分段（否则 ``_dirty_syncs`` 一丢弃就丢数据）。"""
        if messageId not in self._view._dirty_syncs:
            return
        message = self._view._message_index.get(messageId)
        if message is None or self._view._is_legacy_derived(message):
            return
        self._view._update_snapshot(
            messageId, lambda current: current.withParts(bubble.parts())
        )

    def _scroll_to_virtual_message(self, messageId: int) -> bool:
        """把 spacer 列表滚到指定消息，并按新视口物化。"""
        if not self._view._virtual_list_mode:
            return False
        self._view._ensure_virtual_prefix()
        index = self._view._virtual_index.get(messageId)
        if index is None:
            return False
        viewport = max(1, self._view._scroll.viewport().height())
        start = self._view._virtual_prefix[index]
        self._view._stick = False
        self._view._virtual_pending_top = max(0, start - viewport // 3)
        self._view._scroll.verticalScrollBar().setValue(self._view._virtual_pending_top)
        self._view._refresh_virtual_window()
        # 目标消息必须本次物化：分帧预算可能把它排到下一帧，而
        # 「scrollToMessage 之后 bubble(id) 立即可用」是公开契约。
        if messageId not in self._view._bubbles:
            self._view._materialize_virtual_bubble(messageId)
        return True

    def _refresh_virtual_window(self, at_bottom: bool = False) -> None:
        """按视口重排 spacer 虚拟列表：只保留视口附近的消息气泡。"""
        if not self._view._virtual_list_mode or self._view._virtual_refreshing:
            return
        if self._view._batch_depth > 0:
            return
        if not self._view._messages:
            return
        self._view._init_virtual_spacers()
        if (
            self._view._virtual_top_spacer is None
            or self._view._virtual_bottom_spacer is None
        ):
            return
        self._view._virtual_refreshing = True
        try:
            for messageId in list(self._view._virtual_bubble_ids):
                bubble = self._view._bubbles.get(messageId)
                if bubble is not None and bubble.height() > 0:
                    self._view._virtual_heights[messageId] = bubble.height()
            self._view._virtual_prefix_dirty = True
            self._view._ensure_virtual_prefix()
            count = len(self._view._virtual_order)
            if count <= 0:
                return
            viewport = max(1, self._view._scroll.viewport().height())
            bar = self._view._scroll.verticalScrollBar()
            total = self._view._virtual_prefix[-1]
            if self._view._virtual_pending_top is not None:
                top = self._view._virtual_pending_top
            elif at_bottom or self._view._stick:
                top = max(0, total - viewport)
            else:
                top = bar.value()
            bottom = top + viewport
            margin = viewport * _VIRTUAL_WINDOW_MARGIN_RATIOS
            first = max(
                0, bisect.bisect_right(self._view._virtual_prefix, top - margin) - 1
            )
            last = min(
                count - 1,
                bisect.bisect_right(self._view._virtual_prefix, bottom + margin) - 1,
            )
            if last < first:
                first = last
            offset = top - self._view._virtual_prefix[first]
            core_first = max(
                first, bisect.bisect_right(self._view._virtual_prefix, top) - 1
            )
            core_last = min(
                last, bisect.bisect_right(self._view._virtual_prefix, bottom) - 1
            )
            if core_last < core_first:
                core_first = core_last = first
            wanted = set(self._view._virtual_order[first : last + 1])
            for messageId in list(self._view._virtual_bubble_ids):
                if messageId not in wanted:
                    self._view._dematerialize_virtual_bubble(messageId)
            # 物化段必须**连续**：spacer 列表没有逐条占位，中间留洞会让后面的
            # 气泡整体上移（内容错位）。一次滚动步只铺 `_VIRTUAL_MATERIALIZE_BUDGET`
            # 条（每条约 7ms：建壳 + 查看器 + Markdown 渲染），先把视口区间铺满，
            # 再向余量窗口两侧交替扩；没铺完的下一帧继续（spacer 撑住高度，不跳）。
            materialized = sorted(
                index
                for index in (
                    self._view._virtual_index.get(messageId, -1)
                    for messageId in self._view._virtual_bubble_ids
                )
                if index >= 0
            )
            if materialized:
                mat_first, mat_last = materialized[0], materialized[-1]
            else:
                mat_first, mat_last = core_first, core_first - 1
            if mat_last < core_first or mat_first > core_last:
                # 与视口不相交（跳转）：整段重铺，避免把两段之间的洞留下
                for messageId in list(self._view._virtual_bubble_ids):
                    self._view._dematerialize_virtual_bubble(messageId)
                mat_first, mat_last = core_first, core_first - 1
            budget = _VIRTUAL_MATERIALIZE_BUDGET
            deadline = time.perf_counter() + _VIRTUAL_MATERIALIZE_BUDGET_MS / 1000.0
            timed_out = False

            def _materialize(candidate: int) -> bool:
                nonlocal budget, timed_out
                bubble = self._view._materialize_virtual_bubble(
                    self._view._virtual_order[candidate]
                )
                if bubble is None:
                    return False
                budget -= 1
                if time.perf_counter() >= deadline:
                    timed_out = True
                return True

            while budget > 0 and not timed_out and mat_first > core_first:
                candidate = mat_first - 1
                if not _materialize(candidate):
                    break
                mat_first = candidate
            while budget > 0 and not timed_out and mat_last < core_last:
                candidate = mat_last + 1
                if not _materialize(candidate):
                    break
                mat_last = candidate
            while (
                budget > 0 and not timed_out and (mat_first > first or mat_last < last)
            ):
                if mat_first > first:
                    candidate = mat_first - 1
                    if not _materialize(candidate):
                        break
                    mat_first = candidate
                if budget > 0 and not timed_out and mat_last < last:
                    candidate = mat_last + 1
                    if not _materialize(candidate):
                        break
                    mat_last = candidate
            if (budget <= 0 or timed_out) and (mat_first > first or mat_last < last):
                # 条数 / 时间预算用完但窗口还没铺满：下一帧继续（没铺满时不会
                # 连发，避免物化失败时变成 0ms 空转）
                self._view._virtual_window_timer.start(0)
            for messageId in list(self._view._virtual_bubble_ids):
                bubble = self._view._bubbles.get(messageId)
                if bubble is not None and bubble.height() > 0:
                    self._view._virtual_heights[messageId] = bubble.height()
            self._view._virtual_prefix_dirty = True
            self._view._ensure_virtual_prefix()
            total = self._view._virtual_prefix[-1]
            visible = [
                self._view._virtual_order[i]
                for i in range(mat_first, mat_last + 1)
                if self._view._virtual_order[i] in self._view._bubbles
            ]
            visible_sum = sum(
                self._view._virtual_heights.get(messageId, 0) for messageId in visible
            )
            top_height = (
                max(0, self._view._virtual_prefix[mat_first] - _MESSAGE_SPACING)
                if mat_first > 0
                else 0
            )
            used = top_height
            if visible:
                used += (
                    _MESSAGE_SPACING
                    + visible_sum
                    + _MESSAGE_SPACING * (len(visible) - 1)
                    + _MESSAGE_SPACING
                )
            bottom_height = max(0, total - used)
            self._view._virtual_top_spacer.setFixedHeight(top_height)
            self._view._virtual_bottom_spacer.setFixedHeight(bottom_height)
            self._view._content_layout.activate()
            if self._view._virtual_pending_top is not None:
                target = self._view._virtual_pending_top
                self._view._virtual_pending_top = None
                bar.setValue(max(0, min(target, max(0, total - viewport))))
            elif self._view._stick or at_bottom:
                self._view._scroll_to_bottom()
            else:
                new_top = self._view._virtual_prefix[first] + offset
                bar.setValue(max(0, min(new_top, max(0, total - viewport))))
        finally:
            self._view._virtual_refreshing = False

    def _add_shell_placeholder(self, message: ElaChatMessage) -> QWidget:
        """为未建壳消息插一个等高占位控件。"""
        placeholder = DeferredPlaceholder(self._view._content)
        placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        placeholder.setFixedHeight(self._view._estimate_shell_height(message))
        self._view._content_layout.insertWidget(
            self._view._content_layout.count() - 1, placeholder
        )
        self._view._shell_placeholders[message.id] = placeholder
        self._view._virtual_prefix_dirty = True
        return placeholder

    def _refresh_shell_heights(self) -> None:
        """宽度变化后按新宽度重算占位高度。"""
        if not self._view._shell_placeholders:
            return
        messages = self._view._message_index
        for messageId, placeholder in self._view._shell_placeholders.items():
            message = messages.get(messageId)
            if message is None or is_deleted(placeholder):
                continue
            placeholder.setFixedHeight(self._view._estimate_shell_height(message))
        self._view._virtual_prefix_dirty = True

    def _materialize_shell(self, messageId: int) -> Optional[ElaChatBubble]:
        """把占位消息换成真实气泡（分段仍可延迟物化）。"""
        bubble = self._view._bubbles.get(messageId)
        if bubble is not None:
            return bubble
        if self._view._virtual_list_mode:
            self._view._scroll_to_virtual_message(messageId)
            return self._view._bubbles.get(messageId)
        placeholder = self._view._shell_placeholders.pop(messageId, None)
        message = self._view._message_index.get(messageId)
        if message is None:
            return None
        index = (
            self._view._content_layout.indexOf(placeholder)
            if placeholder is not None
            else -1
        )
        deferred = message.role == ElaChatRoleType.Assistant and bool(
            message.text or message.parts
        )
        bubble = self._view._build_bubble(
            messageId,
            message.role,
            "" if message.parts else message.text,
            False,
            deferred,
            insert_index=index,
            identity=(message.agent, message.model, message.model_variant),
            mentions=message.mentions,
        )
        if placeholder is not None:
            self._view._content_layout.removeWidget(placeholder)
            placeholder.deleteLater()
        if message.parts:
            if self._view._virtual_parts_enabled:
                bubble.setPartsDeferred(message.parts)
            else:
                bubble.setParts(message.parts)
        elif deferred:
            bubble.setRenderDeferred(True)
            bubble.setText(message.text)
        self._view._apply_message_fields(messageId, message)
        self._view._sync_parts(messageId)
        self._view._virtual_prefix_dirty = True
        if messageId in self._view._lazy_ids:
            self._view._lazy_ids.remove(messageId)
        return bubble

    def _schedule_lazy_fill(self) -> None:
        """内容还填不满一屏时继续渲染更早的消息（否则没有滚动条可以上滚）。"""
        if (
            not self._view._lazy_ids
            or self._view._loading_older
            or self._view._batch_depth > 0
        ):
            return
        bar = self._view._scroll.verticalScrollBar()
        viewport = max(1, self._view._scroll.viewport().height())
        if bar.maximum() <= viewport and not self._view._lazy_timer.isActive():
            # 稍等一拍：批量收尾后的布局/滚动范围可能还没落地
            self._view._lazy_timer.start(30)

    def _maybe_request_older(self) -> None:
        """滚到接近顶部时预渲染更早的一页消息（合并到 0ms 定时器）。"""
        if (
            not self._view._lazy_ids
            or self._view._loading_older
            or self._view._batch_depth > 0
        ):
            return
        bar = self._view._scroll.verticalScrollBar()
        viewport = max(1, self._view._scroll.viewport().height())
        if bar.value() <= viewport * _LAZY_TRIGGER_VIEWPORTS:
            if not self._view._lazy_timer.isActive():
                self._view._lazy_timer.start(0)

    def _load_older_page(self) -> None:
        """渲染一页更早的懒加载消息，并保持当前阅读位置。"""
        if (
            not self._view._lazy_ids
            or self._view._loading_older
            or self._view._batch_depth > 0
        ):
            return
        self._view._loading_older = True
        try:
            bar = self._view._scroll.verticalScrollBar()
            rendered = 0
            while self._view._lazy_ids and rendered < _LAZY_PAGE_SIZE:
                messageId = self._view._lazy_ids.pop()
                bubble = self._view._materialize_shell(messageId)
                if bubble is None:
                    continue
                if not bubble.renderDeferred() and not bubble.partsDeferred():
                    continue
                bubble.materializeParts()
                bubble.setRenderDeferred(False)
                bubble.flushRender()
                self._view._sync_parts(messageId)
                rendered += 1
            if not rendered:
                return
            if self._view._stick:
                self._view._pending_anchor = None
                self._view._content_layout.activate()
                self._view._scroll_to_bottom()
            else:
                # 渲染后的高度要等本轮布局落地才可信：记下锚点，rangeChanged 时补偿
                self._view._pending_anchor = (bar.value(), bar.maximum())
                self._view._content_layout.activate()
            self._view._schedule_suspension_update()
        finally:
            self._view._loading_older = False
        self._view._schedule_lazy_fill()

    def _schedule_suspension_update(self) -> None:
        """合并短时间内的多次滚动 / 布局变化，按间隔更新挂起状态。"""
        if (
            not self._view._suspension_enabled
            or self._view._suspension_timer.isActive()
        ):
            return
        self._view._suspension_timer.start(_SUSPEND_INTERVAL_MS)

    def _update_suspension(self) -> None:
        """按当前视口范围挂起 / 恢复消息查看器。"""
        if self._view._virtual_list_mode:
            return
        if (
            not self._view._suspension_enabled
            or self._view.count() < self._view._suspension_min
            or not self._view.isVisible()
        ):
            self._view._restore_all_suspended()
            return
        if self._view._resize_frozen_width > 0:
            return  # 拖动 resize 期间几何未定，停手后统一更新
        bar = self._view._scroll.verticalScrollBar()
        top = bar.value()
        viewport = self._view._scroll.viewport().height()
        bottom = top + viewport
        margin = viewport * _SUSPEND_MARGIN_VIEWPORTS
        # **先快照全部几何，再统一应用**：挂起 / 恢复会改变兄弟气泡的 y（内容变矮 /
        # 变高），边判边改会让后面几条基于过期坐标判定 —— 表现为状态来回震荡、
        # 「最远那条」偶发没被挂起（计时相关，难复现）。
        snapshot = []
        for messageId, bubble in self._view._bubbles.items():
            if bubble.role() != ElaChatRoleType.Assistant or bubble.renderDeferred():
                continue
            if bubble.isStreaming():
                continue
            snapshot.append((messageId, bubble.y(), bubble.height()))
        for messageId, y, height in snapshot:
            in_range = (y + height >= top - margin) and (y <= bottom + margin)
            suspended = messageId in self._view._suspended_ids
            if in_range and suspended:
                self._view._restore_message_viewers(messageId)
            elif not in_range:
                if self._view._shell_recycling and self._view._dematerialize_shell(
                    messageId
                ):
                    continue
                if not suspended:
                    self._view._suspend_message_viewers(messageId)
        if self._view._shell_placeholders:
            self._view._materialize_visible_placeholder(top, bottom, margin)

    def _suspend_message_viewers(self, messageId: int) -> None:
        bubble = self._view._bubbles.get(messageId)
        if bubble is None or bubble.viewersSuspended():
            return
        bubble.setViewersSuspended(True)
        if not bubble.viewersSuspended():
            return
        self._view._suspended_ids.add(messageId)
        self._view._drop_message_guards(messageId)

    def _dematerialize_shell(self, messageId: int) -> bool:
        """把远处已物化消息收回等高占位（保留 parts 数据与消息快照）。"""
        bubble = self._view._bubbles.get(messageId)
        if bubble is None or bubble.isStreaming() or bubble.pendingPermissions():
            return False
        if bubble.hasExpandedSections():
            return False
        message = self._view._message_index.get(messageId)
        self._flush_dirty_before_destroy(messageId, bubble)
        height = bubble.height()
        if height <= 0 and message is not None:
            height = self._view._estimate_shell_height(message)
        placeholder = DeferredPlaceholder(self._view._content)
        placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        placeholder.setFixedHeight(max(40, height))
        index = self._view._content_layout.indexOf(bubble)
        if index >= 0:
            self._view._content_layout.insertWidget(index, placeholder)
        else:
            self._view._content_layout.insertWidget(
                self._view._content_layout.count() - 1, placeholder
            )
        self._view._content_layout.removeWidget(bubble)
        bubble.hide()
        bubble.setParent(None)
        bubble.deleteLater()
        self._view._bubbles.pop(messageId, None)
        self._view._shell_placeholders[messageId] = placeholder
        self._view._virtual_prefix_dirty = True
        self._view._dirty_syncs.discard(messageId)
        self._view._suspended_ids.discard(messageId)
        self._view._drop_message_guards(messageId)
        if messageId in self._view._lazy_ids:
            self._view._lazy_ids.remove(messageId)
        try:
            self._view._render_queue.remove(messageId)
        except ValueError:
            pass
        return True

    def _materialize_visible_placeholder(
        self, top: int, bottom: int, margin: float
    ) -> None:
        """每次挂起更新物化**一个**视口内的占位消息（时间片，避免成批建卡）。"""
        if not self._view._shell_placeholders or self._view._batch_depth > 0:
            return
        if self._view._resize_frozen_width > 0:
            return
        self._view._ensure_virtual_prefix()
        if not self._view._virtual_order:
            return
        start = top - margin
        end = bottom + margin
        lo = max(0, bisect.bisect_right(self._view._virtual_prefix, start) - 1)
        hi = min(
            len(self._view._virtual_order),
            bisect.bisect_right(self._view._virtual_prefix, end),
        )
        deadline = time.perf_counter() + 0.006
        materialized = 0
        above = False
        if not self._view._stick:
            for index in range(lo, hi):
                placeholder = self._view._shell_placeholders.get(
                    self._view._virtual_order[index]
                )
                if (
                    placeholder is not None
                    and not is_deleted(placeholder)
                    and placeholder.y() + placeholder.height() <= top
                ):
                    above = True
                    break
            if above:
                bar = self._view._scroll.verticalScrollBar()
                self._view._pending_anchor = (bar.value(), bar.maximum())
        for index in range(lo, hi):
            messageId = self._view._virtual_order[index]
            placeholder = self._view._shell_placeholders.get(messageId)
            if placeholder is None or is_deleted(placeholder):
                continue
            y = placeholder.y()
            height = placeholder.height()
            if not ((y + height >= top - margin) and (y <= bottom + margin)):
                continue
            bubble = self._view._materialize_shell(messageId)
            if bubble is None:
                continue
            bubble.materializeParts()
            bubble.setRenderDeferred(False)
            bubble.flushRender()
            self._view._sync_parts(messageId)
            self._view._content_layout.activate()
            materialized += 1
            if time.perf_counter() >= deadline:
                break
        if not materialized:
            # 前缀估算与真实几何偏差时的兜底：只扫到第一个命中的占位
            for messageId, placeholder in self._view._shell_placeholders.items():
                if is_deleted(placeholder):
                    continue
                y = placeholder.y()
                height = placeholder.height()
                if not ((y + height >= top - margin) and (y <= bottom + margin)):
                    continue
                bubble = self._view._materialize_shell(messageId)
                if bubble is not None:
                    bubble.materializeParts()
                    bubble.setRenderDeferred(False)
                    bubble.flushRender()
                    self._view._sync_parts(messageId)
                    self._view._content_layout.activate()
                    materialized = 1
                break
        if materialized and self._view._shell_placeholders:
            # 填满视口：16ms 后再补下一批，避免滚动事件被 0ms 定时器持续抢占
            self._view._suspension_timer.start(16)

    def _restore_message_viewers(self, messageId: int) -> None:
        bubble = self._view._bubbles.get(messageId)
        self._view._suspended_ids.discard(messageId)
        if bubble is None:
            return
        bar = self._view._scroll.verticalScrollBar()
        top = bar.value()
        before = bubble.height()
        bubble.setViewersSuspended(False)
        self._view._content_layout.activate()
        if self._view._stick:
            self._view._scroll_to_bottom()
            return
        after = bubble.height()
        if after != before and bubble.y() + after <= top:
            # 恢复点在视口上方：补偿高度差，保持阅读位置稳定
            bar.setValue(top + (after - before))

    def _restore_all_suspended(self) -> None:
        for messageId in list(self._view._suspended_ids):
            self._view._restore_message_viewers(messageId)
