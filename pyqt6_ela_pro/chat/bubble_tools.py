"""气泡工具调用 / 每步面板方法组（从 ``ElaChatBubble`` 拆出）。"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional
from uuid import uuid4


from .blocks import (
    CONTEXT_TOOLS,
    SHELL_TOOLS,
    ContextToolGroupCard,
    ToolCallCard,
    ToolGroupPanel,
    toolDefaultOpen,
    toolSubtitleParts,
)
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
)
from .renderers import toolRendererGroupable, toolRendererSubtitle


class _BubbleToolsMixin:
    """方法组 mixin：状态由 ``ElaChatBubble.__init__`` 建立。"""

    def _ensure_tools(self) -> ToolGroupPanel:
        """确保当前步骤存在工具面板（无则创建），返回该面板。"""
        if self._current_tool_panel is None:
            panel = ToolGroupPanel(self._parts_container or self._content or self)
            panel.toggled.connect(self._on_tool_card_toggled)
            self._panels.append(panel)
            self._panel_steps[id(panel)] = self._step_index
            self._panel_calls[id(panel)] = set()
            if self._parts_layout is not None:
                self._parts_layout.addWidget(panel)
            self._current_tool_panel = panel
        return self._current_tool_panel

    def toolPanel(self) -> Optional[ToolGroupPanel]:
        """获取当前步骤的工具面板（无工具时返回 ``None``）。"""
        if self._current_tool_panel is not None:
            return self._current_tool_panel
        return self._panels[-1] if self._panels else None

    def toolPanels(self) -> list:
        """获取全部步骤的工具面板（按创建顺序）。"""
        return list(self._panels)

    def _panel_for_call(self, callId: str) -> Optional[ToolGroupPanel]:
        for panel in self._panels:
            if callId in self._panel_calls.get(id(panel), ()):
                return panel
        return self._current_tool_panel

    def setToolGrouping(self, on: bool) -> None:
        """设置是否把连续上下文工具（read/glob/grep/list）合并为分组卡。"""
        self._tool_grouping = bool(on)

    def setToolDefaultOpen(self, policy) -> None:
        """注入「哪些工具卡默认展开」的策略。

        ``policy(toolName, arguments, ok) -> bool``，仅在**新建**工具卡时被调用；
        已存在的卡片不受影响（否则会把用户手动折叠的卡片弹开）。

        为什么做成可注入的纯函数而不是硬编码：「shell 要不要默认展开」「纯删除
        要不要折叠」都是**宿主的产品决策**，与工具语义强相关。库默认只保留一条
        与领域无关且普遍正确的规则（失败时展开），其余交给宿主。编码 agent 场景
        可直接用 :func:`~pyqt6_ela_pro.chat.blocks.toolDefaultOpenCoding`。

        :param policy: 可调用对象；传 ``None`` 恢复库默认
        """
        self._tool_open_policy = policy if callable(policy) else toolDefaultOpen

    def _tool_default_open(self, name: str, arguments, ok: bool) -> bool:
        """按当前策略求「默认展开」；宿主策略抛异常时回落库默认。"""
        try:
            return bool(self._tool_open_policy(name, arguments, ok))
        except Exception:
            return bool(toolDefaultOpen(name, arguments, ok))

    def toolGrouping(self) -> bool:
        """是否启用上下文工具分组。"""
        return self._tool_grouping

    def addToolCall(
        self,
        name: str,
        arguments: str = "",
        toolCallId: Optional[str] = None,
        *,
        tool_call: Optional[ElaChatToolCall] = None,
    ) -> str:
        """添加一个工具调用，返回调用 id（上下文工具自动归组）。

        ``tool_call`` 由恢复路径传入**已完成**的快照：卡片构造时就带上结果与
        最终状态，省掉「先建卡再 setResult」的第二次头部同步。
        """
        if self._role != ElaChatRoleType.Assistant:
            return ""
        self._ensure_parts_materialized()
        self._mark_generation_started()
        callId = (
            toolCallId
            or (tool_call.id if tool_call is not None else "")
            or uuid4().hex[:12]
        )
        if toolCallId and toolCallId in self._tool_cards:
            # 同一调用 id 重复上报（参数分片等）：更新参数不追加重复分段
            card = self._tool_cards[toolCallId]
            if isinstance(card, ContextToolGroupCard):
                card.updateArguments(toolCallId, arguments or "")
            else:
                card.setArguments(arguments or "")
            part = self._find_part(toolCallId)
            if part is not None:
                self._replace_part(
                    toolCallId, part.withToolCall(card.toolCall(toolCallId))
                )
            return toolCallId
        call = tool_call or ElaChatToolCall(
            id=callId, name=name, arguments=arguments or ""
        )
        if not call.id:
            # 存储里缺 ``tool_call.id`` 的旧数据：用刚分配的 call id 补齐。
            # 不补的话卡片按空 id 登记，回填结果时按生成 id 找不到同一条调用，
            # 上下文分组卡会把整个 tool_call 换成 None（数据丢失）。
            call = replace(call, id=callId)
        name = call.name
        arguments = call.arguments
        panel = self._ensure_tools()
        container = panel.toolContainer()
        key = (name or "").lower()
        is_context = key in CONTEXT_TOOLS
        failed = call.status == ElaChatToolStatusType.Error
        # 宿主给上下文工具注册了渲染器 -> 默认退出分组：分组卡只画一行汇总
        # 摘要，会把渲染器整个绕过（那宿主注册它就毫无意义）。
        groupable = toolRendererGroupable(name)
        if is_context and not groupable:
            self._finish_tool_group()
        if is_context and self._tool_grouping and groupable:
            if self._group_card is None:
                # 分组卡同样走展开策略：策略问的是「这次探索要不要默认摊开」，
                # 上下文工具合并后单卡就是整个分组的代表，只对单调用问一次、
                # 却不管分组，会让同一策略在两条路径上表现不一致。
                self._group_card = ContextToolGroupCard(
                    container,
                    defaultOpen=self._tool_default_open(name, arguments, not failed),
                )
                self._group_card.toggled.connect(self._on_tool_card_toggled)
                panel.toolLayout().addWidget(self._group_card)
            self._group_card.addToolCall(call)
            card = self._group_card
        else:
            card = ToolCallCard(
                parent=container,
                tool_call=call,
                # shell 类工具的 pending 期间允许展开（命令与输出是多行文本）；
                # 清单与默认展开策略共用 blocks.SHELL_TOOLS，别各写一份。
                allowOpenWhilePending=key in SHELL_TOOLS,
                # 建卡时结果还没到，ok 传 True（不是失败）；失败展开由
                # ToolCallCard.setResult(ok=False) 单独处理。传 False 会被
                # 策略读成「已失败」-> 每张卡都自动展开。
                defaultOpen=self._tool_default_open(
                    call.name, call.arguments, not failed
                ),
            )
            card.setMessageId(self._message_id)
            card.toggled.connect(self._on_tool_card_toggled)
            panel.toolLayout().addWidget(card)
        self._tool_cards[callId] = card
        self._panel_calls[id(panel)].add(callId)
        self._parts.append(
            ElaChatPart(
                id=callId,
                kind=ElaChatPartKindType.Tool,
                status=(
                    ElaChatStatusType.Done
                    if call.status in ElaChatToolStatusType.Settled
                    else ElaChatStatusType.Streaming
                ),
                tool_call=call,
                step=self._step_index,
            )
        )
        self._part_widgets[callId] = card
        self._move_step_stats_to_end(self._step_index)
        if self._bulk_build:
            # 回放期间只登记；收尾统一 show + 刷新摘要，避免每个工具都触发
            # 一次面板 show / 全量 parts 扫描（bug #17）。
            self._bulk_panels.add(panel)
        else:
            panel.show()
            self._sync_tool_panel(panel)
        return callId

    def _on_tool_card_toggled(self, _checked: bool = False) -> None:
        self.toolToggled.emit()

    def _finish_tool_group(self) -> None:
        if self._group_card is not None:
            self._group_card.finish()
            self._group_card = None

    def _toolPanelSummary(self, calls) -> str:
        """折叠面板的一行摘要：单调用显示「工具 · 关键参数」，多调用显示名称计数。"""
        calls = [call for call in calls if call is not None]
        if not calls:
            return ""
        if len(calls) == 1:
            call = calls[0]
            name = call.name or "工具"
            subtitle = ""
            try:
                _key, subtitle = toolRendererSubtitle(name, call.arguments)
                if not subtitle:
                    _key, subtitle = toolSubtitleParts(call.arguments)
            except Exception:
                subtitle = ""
            subtitle = " ".join(str(subtitle or "").split())
            if len(subtitle) > 72:
                subtitle = subtitle[:71] + "…"
            text = f"{name} · {subtitle}" if subtitle else name
            if call.status == ElaChatToolStatusType.Error:
                text += " · 失败"
            return text
        counts = {}
        order = []
        failed = 0
        for call in calls:
            name = call.name or "工具"
            if name not in counts:
                order.append(name)
                counts[name] = 0
            counts[name] += 1
            if call.status == ElaChatToolStatusType.Error:
                failed += 1
        parts = [
            f"{name}×{counts[name]}" if counts[name] > 1 else name for name in order[:4]
        ]
        if len(order) > 4:
            parts.append("…")
        if failed:
            parts.append(f"失败{failed}")
        return " · ".join(parts)

    def _sync_tool_panel(self, panel: Optional[ToolGroupPanel] = None) -> None:
        """按分段状态刷新指定面板（缺省当前面板）的标题与运行指示。"""
        panel = panel or self._current_tool_panel
        if panel is None:
            return
        step = self._panel_steps.get(id(panel), self._step_index)
        calls = [
            part.tool_call
            for part in self._parts
            if part.kind == ElaChatPartKindType.Tool
            and part.step == step
            and part.tool_call is not None
        ]
        total = len(calls)
        done = sum(1 for call in calls if call.status in ElaChatToolStatusType.Settled)
        key = (
            total,
            tuple(call.id for call in calls),
            sum(1 for call in calls if call.status == ElaChatToolStatusType.Error),
        )
        if key == getattr(panel, "_summary_key", None):
            # 结果落定（running -> done）不改摘要，跳过参数 JSON 解析
            panel.setCounts(done, total)
        else:
            panel._summary_key = key
            panel.setCounts(done, total, summary=self._toolPanelSummary(calls))

    def setToolCallResult(self, toolCallId: str, result: str, ok: bool = True) -> None:
        """更新指定工具调用的结果。"""
        if self._parts_deferred or (
            self._parts_windowed and toolCallId not in self._tool_cards
        ):
            part = self._find_part(toolCallId)
            if part is not None and part.tool_call is not None:
                status = (
                    ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error
                )
                call = part.tool_call.withResult(result or "", status)
                self._replace_part(toolCallId, part.withToolCall(call))
            return
        card = self._tool_cards.get(toolCallId)
        if card is None:
            return
        card.updateResult(toolCallId, result, ok=ok)
        part = self._find_part(toolCallId)
        if part is not None:
            self._replace_part(toolCallId, part.withToolCall(card.toolCall(toolCallId)))
        self._sync_tool_panel(self._panel_for_call(toolCallId))

    def toolCall(self, toolCallId: str) -> Optional[ElaChatToolCall]:
        """按 id 获取工具调用快照。"""
        card = self._tool_cards.get(toolCallId)
        if card is not None:
            return card.toolCall(toolCallId)
        part = self._find_part(toolCallId)
        return part.tool_call if part is not None else None

    def toolCalls(self) -> list:
        """获取全部工具调用快照（按添加顺序）。"""
        return [
            part.tool_call
            for part in self._parts
            if part.kind == ElaChatPartKindType.Tool and part.tool_call is not None
        ]

    def toolCallCount(self) -> int:
        """工具调用数量。"""
        return sum(1 for part in self._parts if part.kind == ElaChatPartKindType.Tool)

    def clearToolCalls(self) -> None:
        """移除全部工具调用卡片与各步骤外层面板。"""
        self._remove_parts({ElaChatPartKindType.Tool})
        self._tool_cards.clear()
        self._group_card = None
        self._panel_calls.clear()
        for panel in self._panels:
            panel.hide()
            panel.setParent(None)
            panel.deleteLater()
        self._panels = []
        self._panel_steps.clear()
        self._current_tool_panel = None
