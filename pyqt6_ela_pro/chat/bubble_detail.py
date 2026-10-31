"""气泡的时间线密度 / 披露状态方法组（``pyqt6_ela_pro.chat``）。"""

from __future__ import annotations

from typing import Optional

from .blocks._helpers import SHELL_TOOLS, _WRITE_TOOLS
from .message import ElaChatPartKindType, ElaChatToolStatusType
from .timeline_detail import (
    DEFAULT_TIMELINE_DETAIL,
    ElaChatTimelineDetail,
    coerceTimelineDetail,
)

#: 编辑类工具（与 blocks._helpers._WRITE_TOOLS 同口径，额外补 patch）
_EDIT_TOOLS = frozenset({"edit", "write", "patch", "apply_patch"})
#: 子代理类工具
_SUBAGENT_TOOLS = frozenset({"subagent", "task", "agent"})


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

    # -- 内部 --------------------------------------------------------------

    def _part_section_name(self, part) -> Optional[str]:
        kind = getattr(part, "kind", "")
        if kind == ElaChatPartKindType.Reasoning:
            return "thinking"
        if kind == ElaChatPartKindType.Notice:
            return "notices"
        if kind == ElaChatPartKindType.Tool:
            call = getattr(part, "tool_call", None)
            name = str(getattr(call, "name", "") or "").lower()
            if name in SHELL_TOOLS:
                return "shell"
            if name in _EDIT_TOOLS or name in _WRITE_TOOLS:
                return "edit"
            if name in _SUBAGENT_TOOLS:
                return "subagents"
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
