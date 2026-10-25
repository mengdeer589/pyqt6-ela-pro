"""贴底跟随 / 回到底部 / 交互 resize 延迟重排方法组（从 ``ElaChatView`` 拆出）。"""

from __future__ import annotations


from typing import Optional

from PyQt6.QtWidgets import (
    QScrollBar,
)

from .view_metrics import (
    _BOTTOM_MARGIN,
    _FLOAT_MARGIN,
    _FOLLOW_HOLD_MS,
    _JUMP_MIN_DISTANCE,
    _SUSPEND_MARGIN_VIEWPORTS,
)


class _ViewScrollMixin:
    """方法组 mixin：状态由 ``ElaChatView.__init__`` 建立。"""

    def _atBottom(self) -> bool:
        bar = self._scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - _BOTTOM_MARGIN

    def _on_scrolled(self, _value: int) -> None:
        self._stick = self._atBottom()
        self._update_jump_button()
        if self._virtual_list_mode:
            if not self._virtual_window_timer.isActive():
                self._virtual_window_timer.start(0)
            return
        if self._shell_placeholders:
            # 滚动到占位区域时立刻填充，不等 100ms 的查看器挂起周期
            self._suspension_timer.start(0)
        self._schedule_suspension_update()
        if self._shell_placeholders and not self._suspension_enabled:
            bar = self._scroll.verticalScrollBar()
            top = bar.value()
            viewport = self._scroll.viewport().height()
            self._materialize_visible_placeholder(
                top, top + viewport, viewport * _SUSPEND_MARGIN_VIEWPORTS
            )
        self._maybe_request_older()

    def _on_jump_clicked(self) -> None:
        self.scrollToBottom()

    def _update_jump_button(self) -> None:
        visible = bool(self._messages) and self._distance_from_bottom() > (
            self._jump_distance()
        )
        self._jump_button.setVisible(visible)
        if visible:
            self._position_jump_button()

    def _distance_from_bottom(self) -> int:
        bar = self._scroll.verticalScrollBar()
        return int(bar.maximum() - bar.value())

    def _jump_distance(self) -> int:
        if self._jump_threshold is not None:
            return int(self._jump_threshold)
        return max(_JUMP_MIN_DISTANCE, self._scroll.viewport().height())

    def setJumpThreshold(self, distance: int) -> None:
        """设置「回到底部」显示阈值（像素；``None`` 恢复默认动态阈值）。"""
        self._jump_threshold = None if distance is None else max(0, int(distance))
        self._update_jump_button()

    def jumpThreshold(self) -> Optional[int]:
        """获取「回到底部」显示阈值（``None`` 表示默认动态阈值）。"""
        return self._jump_threshold

    def _position_jump_button(self) -> None:
        margin = _FLOAT_MARGIN
        self._jump_button.move(
            max(0, self.width() - self._jump_button.width() - margin),
            max(0, self.height() - self._jump_button.height() - margin),
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        # resizeEvent 投递时布局链通常已经把内容排到新宽度（super() 前后读
        # viewport()/_content 都是新宽），所以冻结优先用「当前内容宽」；只有布局
        # 还没跟上时才退回 oldSize 推算。拿 oldSize 无条件冻结会把已经排好的
        # 内容拉回旧宽，多出两趟重排 + 一段旧宽闪现。
        self._freeze_before_resize(event)
        super().resizeEvent(event)
        self._position_jump_button()
        self._on_view_resized(event.size().width())

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if self._virtual_list_mode:
            self._virtual_window_timer.start(0)
        self._schedule_suspension_update()

    def setResizeReflowDeferred(
        self,
        on: bool = True,
        minMessages: Optional[int] = None,
        delayMs: Optional[int] = None,
        minParts: Optional[int] = None,
    ) -> None:
        """设置交互 resize 是否延迟重排（默认开启）。

        拖动窗口期间把消息内容宽度冻结在起始宽度，避免全部 Markdown
        查看器逐帧文本 reflow；停手 ``delayMs`` 毫秒后统一按新宽度重排
        （贴底时自动回到最新消息）。

        :param on: 是否启用
        :param minMessages: 触发延迟重排的最小消息数（缺省 50，小会话实时重排）
        :param delayMs: 停手后统一重排的延迟（毫秒，缺省 120）
        :param minParts: 触发延迟重排的最小分段数（缺省 200；工具卡 / 正文多
            但消息少的历史会话同样需要延迟）
        """
        self._resize_reflow_deferred = bool(on)
        if minMessages is not None:
            self._resize_reflow_min = max(0, int(minMessages))
        if minParts is not None:
            self._resize_reflow_min_parts = max(0, int(minParts))
        if delayMs is not None:
            self._resize_reflow_delay = max(0, int(delayMs))
        if not self._resize_reflow_deferred:
            self._resize_reflow_timer.stop()
            self._release_resize_reflow()

    def resizeReflowDeferred(self) -> bool:
        """是否启用交互 resize 延迟重排。"""
        return self._resize_reflow_deferred

    def _should_defer_resize(self) -> bool:
        """内容量是否达到延迟重排阈值（消息数**或**分段数）。"""
        if self.count() >= self._resize_reflow_min:
            return True
        if self._resize_reflow_min_parts <= 0:
            return False
        parts = sum(len(message.parts) for message in self._messages)
        return parts >= self._resize_reflow_min_parts

    def _freeze_before_resize(self, event) -> None:
        """在 ``QScrollArea`` 处理 resize 之前冻结内容宽（避免逐帧重排）。

        resize 事件到达时布局链**通常已经**按新宽排过内容（Qt 在投递事件前
        完成父布局激活）。此时若还按 ``oldSize`` 推算冻结值，会把内容从新宽
        拉回旧宽（一次多余重排 + 一帧旧宽），解冻时再拉回来（第二次）。
        所以优先钉住当前内容宽；只有布局没跟上时才用旧控件宽推算。
        """
        if not self._resize_reflow_deferred or self._resize_frozen_width > 0:
            return
        if event.size().width() == event.oldSize().width():
            return  # 仅高度变化
        if not self._should_defer_resize():
            return
        viewport_width = self._scroll.viewport().width()
        current = self._content.width()
        if current > 0 and current == viewport_width:
            frozen = current
        else:
            old_width = event.oldSize().width()
            if old_width <= 0:
                return
            chrome = self.width() - viewport_width
            frozen = old_width - max(0, chrome)
        if frozen > 0:
            self._resize_frozen_width = frozen
            self._content.setFixedWidth(frozen)

    def _on_view_resized(self, width: int) -> None:
        """视图尺寸变化：拖动期间冻结内容宽度，停手后统一重排。"""
        if not self._resize_reflow_deferred:
            return
        if width <= 0 or not self._should_defer_resize():
            return
        if width == self._resize_width and not self._resize_reflow_timer.isActive():
            return  # 仅高度变化，无需 reflow
        if self._resize_frozen_width <= 0:
            # 首帧旧宽不可用（如 show 前）时的兜底：按当前内容宽冻结
            frozen = self._content.width()
            if frozen > 0:
                self._resize_frozen_width = frozen
                self._content.setFixedWidth(frozen)
        self._resize_width = width
        self._resize_reflow_timer.start(self._resize_reflow_delay)

    def _release_resize_reflow(self) -> None:
        """解除宽度冻结并按新宽度一次性重排。"""
        if self._resize_frozen_width <= 0:
            return
        viewport = self._scroll.viewport()
        viewport.setUpdatesEnabled(False)
        try:
            self._resize_frozen_width = 0
            self._content.setMinimumWidth(0)
            self._content.setMaximumWidth(16777215)
            self._content.updateGeometry()
            if not self._stick:
                bar = self._scroll.verticalScrollBar()
                self._pending_anchor = (bar.value(), bar.maximum())
            self._refresh_shell_heights()
            self._content_layout.activate()
            # 冻结期间内容宽度可能已与视口脱节（ElaScrollBar 占 10px，出现/消失会改变视口
            # 宽度），而 setWidgetResizable 只在滚动区自身 resize 时才重算 —— 不显式拉回，
            # 内容会溢出视口被右侧裁掉。
            self._sync_content_width()
            if self._virtual_list_mode:
                for messageId, message in self._message_index.items():
                    if messageId not in self._bubbles:
                        self._virtual_heights[messageId] = self._estimate_shell_height(
                            message
                        )
                self._virtual_prefix_dirty = True
                self._refresh_virtual_window()
            if self._stick:
                self._scroll_to_bottom()
            self._update_jump_button()
            self._schedule_suspension_update()
        finally:
            viewport.setUpdatesEnabled(True)
            viewport.update()

    def _sync_content_width(self) -> None:
        """把内容宽度对齐视口（滚动区自身不 resize 时需要显式调用）。"""
        viewport_width = self._scroll.viewport().width()
        if viewport_width > 0 and self._content.width() != viewport_width:
            self._content.resize(viewport_width, self._content.height())

    def _follow_bottom(self) -> None:
        """内容变化后跟随底部（用户已上滚 / 批量加载中不打扰）。"""
        if self._batch_depth > 0:
            return
        if self._stick and not self._follow_hold and not self._follow_timer.isActive():
            self._follow_timer.start(0)

    def _scroll_to_bottom_if_sticky(self) -> None:
        if not self._stick or self._follow_hold:
            self._update_jump_button()
            return
        self._scroll_to_bottom()

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        """滚动范围变化（Markdown / 工具卡展开等异步重排）时保持贴底。

        正在展开 / 收起工具卡时消费本次变化并延长暂停窗口（视口不动，避免跳动）；
        其余情况（流式输出、异步渲染）贴底时只对齐一次，不轮询。
        懒加载插入更早消息后，按记下的锚点补偿滚动位置（保持阅读位置稳定）。
        """
        if self._follow_hold:
            self._hold_timer.start(_FOLLOW_HOLD_MS)
            return
        pending = self._pending_anchor
        if pending is not None and not self._stick:
            self._pending_anchor = None
            top, old_max = pending
            delta = maximum - old_max
            if delta:
                # 物化可能让内容变高（懒加载插入）也可能变矮（超长消息窗口化），
                # 两个方向都要按锚点补偿，否则滚动位置会跳。
                self._scroll.verticalScrollBar().setValue(max(0, top + delta))
            self._schedule_suspension_update()
            return
        self._pending_anchor = None
        if self._stick:
            self._scroll_to_bottom()
        self._schedule_suspension_update()

    def holdFollow(self, hold: bool = True) -> None:
        """暂停 / 恢复贴底跟随（展开收起工具卡等交互期间使用）。

        ``hold=True`` 后 ``_FOLLOW_HOLD_MS`` 毫秒自动恢复，期间滚动范围变化
        不会带动视口，避免消息区跳动。
        """
        self._follow_hold = bool(hold)
        if self._follow_hold:
            self._hold_timer.start(_FOLLOW_HOLD_MS)
        else:
            self._hold_timer.stop()

    def followHeld(self) -> bool:
        """当前是否处于贴底跟随暂停状态。"""
        return self._follow_hold

    def _release_follow_hold(self) -> None:
        self._follow_hold = False

    def _on_tool_toggled(self) -> None:
        """工具卡展开 / 收起：暂停跟随，保持视口位置不变。"""
        self.holdFollow(True)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def scrollToBottom(self) -> None:
        """滚动到底部并恢复自动跟随。"""
        self._stick = True
        self._scroll_to_bottom()
        self._update_jump_button()

    def setStickToBottom(self, on: bool) -> None:
        """设置是否自动跟随底部。"""
        self._stick = bool(on)
        if self._stick:
            self.scrollToBottom()

    def stickToBottom(self) -> bool:
        """是否处于自动跟随底部状态。"""
        return self._stick

    def setScrollBarPolicy(self, policy) -> None:
        """设置垂直滚动条策略（默认 :attr:`Qt.ScrollBarPolicy.ScrollBarAsNeeded`）。

        :param policy: ``Qt.ScrollBarPolicy`` 成员。``ScrollBarAsNeeded``
            仅在内容溢出时显示（默认）；``ScrollBarAlwaysOn`` 常显；
            ``ScrollBarAlwaysOff`` 彻底隐藏 —— 注意此时只能滚轮 / 键盘滚动，
            没有可拖动的把手。

        滚动条本身是 ``ElaScrollBar``（Ela 自绘：静止 2.4px 细柄，悬停展开
        成 6px 带上下箭头），可拖动、点击绝对定位。手动拖动会把
        :meth:`stickToBottom` 置 ``False``（复用既有的 ``valueChanged`` 逻辑）。
        """
        self._scroll.setVerticalScrollBarPolicy(policy)
        # ElaScrollBar 静止占 10px：策略变化会让视口宽度变化，内容要跟着拉回
        self._sync_content_width()
        self._update_jump_button()

    def scrollBarPolicy(self):
        """获取垂直滚动条策略（:meth:`setScrollBarPolicy` 的逆操作）。"""
        return self._scroll.verticalScrollBarPolicy()

    def scrollBar(self) -> QScrollBar:
        """获取垂直滚动条控件（``ElaScrollBar``）。

        用于宿主做策略之外的调节，例如 ``setIsAnimation(True)`` 让内容增长
        时范围平滑过渡、``setSpeedLimit(...)`` 改滚轮步进上限。
        """
        return self._scroll.verticalScrollBar()
