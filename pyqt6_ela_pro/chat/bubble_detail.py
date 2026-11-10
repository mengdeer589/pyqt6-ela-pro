"""气泡的时间线密度 / 披露状态方法组（``pyqt6_ela_pro.chat``）。"""

from __future__ import annotations

from typing import Optional

from .blocks._helpers import toolKindOf
from .message import (
    ElaChatPartKindType,
    ElaChatToolKindType,
    ElaChatToolStatusType,
)
from .timeline_detail import (
    DEFAULT_TIMELINE_DETAIL,
    ElaChatTimelineDetail,
    coerceTimelineDetail,
)


class _BubbleDetailMixin:
    """密度设置与逐 part 披露状态；状态由 ``ElaChatBubble.__init__`` 建立。"""

    def setTimelineDetail(self, detail) -> None:
        """设置时间线密度并立即作用到已存在分段。"""
        self._timeline_detail = coerceTimelineDetail(detail)
        self.applyTimelineDetail()

    def timelineDetail(self) -> ElaChatTimelineDetail:
        """获取当前时间线密度（未设置返回默认值）。"""
        return self._timeline_detail or DEFAULT_TIMELINE_DETAIL

    def applyTimelineDetail(self) -> None:
        """把当前密度作用到全部分段控件（不重建文档）。"""
        for part in list(self._parts):
            self._apply_part_visibility(part.id)
        self._refresh_tool_panels()
        row = self._thinking_row
        if row is None:
            return
        if self.timelineDetail().thinking.hidden:
            row.end()
        elif self._current_reasoning_id is not None and row.isHidden():
            row.resume()

    def setPartExpanded(self, partId: str, opened: bool) -> None:
        """设置某个分段的展开状态（覆盖全局密度默认值）。"""
        if not partId:
            return
        self._disclosure[str(partId)] = bool(opened)
        self._apply_part_visibility(str(partId))

    def partExpanded(self, partId: str) -> Optional[bool]:
        """读取某个分段的手动披露状态（未手动设置返回 ``None``）。"""
        return self._disclosure.get(str(partId))

    def clearPartExpanded(self, partId: Optional[str] = None) -> None:
        """清除披露状态（``None`` 清空全部）。"""
        if partId is None:
            self._disclosure.clear()
        else:
            self._disclosure.pop(str(partId), None)

    def _part_section_name(self, part) -> Optional[str]:
        kind = getattr(part, "kind", "")
        if kind == ElaChatPartKindType.Reasoning:
            return "thinking"
        if kind == ElaChatPartKindType.Notice:
            return "notices"
        if kind == ElaChatPartKindType.Tool:
            call = getattr(part, "tool_call", None)
            tool_kind = toolKindOf(call)
            if tool_kind == ElaChatToolKindType.Subagent:
                return "subagents"
            if tool_kind == ElaChatToolKindType.Execute:
                return "shell"
            if tool_kind in (
                ElaChatToolKindType.Edit,
                ElaChatToolKindType.Delete,
                ElaChatToolKindType.Move,
            ):
                return "edit"
            return "tools"
        return None

    def _is_part_hidden(self, part) -> bool:
        section = self._part_section_name(part)
        if section is None:
            return False
        return self.timelineDetail().section(section).hidden

    def _apply_part_visibility(self, partId: str) -> None:
        part = self._find_part(partId)
        widget = self._part_widgets.get(partId)
        if part is None or widget is None:
            return
        call = getattr(part, "tool_call", None)
        if call is not None and getattr(call, "parent_id", ""):
            # 子代理子调用挂在父卡里，显隐由父卡统一控制。
            return
        section_name = self._part_section_name(part)
        if section_name is None:
            return
        section = self.timelineDetail().section(section_name)
        if section.hidden:
            widget.setVisible(False)
            return
        widget.setVisible(True)
        opened = self._disclosure.get(str(partId))
        if opened is None:
            opened = section.expanded
        setter = getattr(widget, "setOpenedSilently", None)
        if callable(setter):
            setter(bool(opened))
        else:
            setter = getattr(widget, "setOpened", None)
            if callable(setter):
                setter(bool(opened))

    def _refresh_tool_panels(self) -> None:
        for panel in list(self._panels):
            calls = list(self._panel_calls.get(id(panel), ()))
            visible = [callId for callId in calls if not self._is_call_hidden(callId)]
            completed = 0
            for callId in visible:
                part = self._find_part(callId)
                call = getattr(part, "tool_call", None) if part is not None else None
                if call is not None and call.status in ElaChatToolStatusType.Settled:
                    completed += 1
            if not visible:
                panel.setVisible(False)
                continue
            panel.setVisible(True)
            try:
                panel.setCounts(completed, len(visible))
            except Exception:
                pass
            self._sync_tool_panel(panel)

    def _is_call_hidden(self, callId: str) -> bool:
        part = self._find_part(callId)
        return bool(part is not None and self._is_part_hidden(part))
