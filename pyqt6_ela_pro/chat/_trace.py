"""运行轨迹模型：把消息时间线整理成 turn → step → tool / reasoning 的树（纯数据）。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Optional, Tuple

from .message import (
    ElaChatPartKindType,
    ElaChatPlan,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatToolStatusType,
)
from .renderers import parseToolArguments

#: 工具行详情里优先取的参数键
_DETAIL_KEYS = (
    "path",
    "file",
    "file_path",
    "pattern",
    "query",
    "command",
    "url",
    "task",
    "description",
    "prompt",
    "name",
)


def _int(value, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _is_error(status) -> bool:
    return str(status or "") in (
        ElaChatToolStatusType.Error,
        "error",
        "failed",
    )


def _stats_tokens(stats: Optional[ElaChatStats]) -> int:
    if stats is None:
        return 0
    total = int(stats.total_tokens or 0)
    return total if total > 0 else int(stats.contextTokens() or 0)


def _tool_detail(call) -> str:
    data = parseToolArguments(call.arguments)
    for key in _DETAIL_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            text = " ".join(value.strip().split())
            return text[:80] + ("…" if len(text) > 80 else "")
    return ""


def _tool_row(messageId: int, call, step: int) -> "ElaChatTraceRow":
    metadata = call.metadata if isinstance(call.metadata, dict) else {}
    tokens = metadata.get("tokens", metadata.get("total_tokens"))
    cost = metadata.get("cost_usd", metadata.get("cost"))
    return ElaChatTraceRow(
        kind="tool",
        message_id=messageId,
        part_id=call.id,
        parent_id=call.parent_id,
        label=call.title or call.name or "工具",
        detail=_tool_detail(call),
        status=call.status,
        duration_ms=max(0.0, float(call.duration_ms or 0.0)),
        started_at=max(0.0, float(call.started_at or 0.0)),
        tokens=_int(tokens) if isinstance(tokens, (int, float)) else 0,
        cost_usd=float(cost) if isinstance(cost, (int, float)) else 0.0,
        depth=2,
        step=step,
    )


@dataclass(frozen=True)
class ElaChatTraceRow:
    """轨迹里的一行（turn / step / tool / reasoning / plan / permission / compaction）。"""

    kind: str
    message_id: int
    part_id: str = ""
    parent_id: str = ""
    label: str = ""
    detail: str = ""
    status: str = ""
    duration_ms: float = 0.0
    started_at: float = 0.0
    tokens: int = 0
    cost_usd: float = 0.0
    depth: int = 0
    step: int = 0
    children: Tuple["ElaChatTraceRow", ...] = ()

    def walk(self) -> Iterable["ElaChatTraceRow"]:
        """按前序遍历自身与后代。"""
        yield self
        for child in self.children:
            yield from child.walk()

    @property
    def isError(self) -> bool:
        """是否失败行。"""
        return _is_error(self.status)


@dataclass(frozen=True)
class ElaChatTraceResult:
    """一次构建的完整轨迹 + 汇总。"""

    rows: Tuple[ElaChatTraceRow, ...] = field(default_factory=tuple)
    total_duration_ms: float = 0.0
    tool_count: int = 0
    error_count: int = 0
    tokens: int = 0
    cost_usd: float = 0.0

    def isEmpty(self) -> bool:  # noqa: N802 (与 Qt / Ela 命名一致)
        """是否没有任何可展示的行。"""
        return not self.rows

    def flatten(self, limit: int = 0) -> Tuple[ElaChatTraceRow, ...]:
        """前序展平（``limit > 0`` 时截断）。"""
        rows = []
        for row in self.rows:
            for item in row.walk():
                rows.append(item)
                if limit and len(rows) >= limit:
                    return tuple(rows)
        return tuple(rows)


def _reasoning_row(messageId: int, part, step: int) -> ElaChatTraceRow:
    return ElaChatTraceRow(
        kind="reasoning",
        message_id=messageId,
        part_id=part.id,
        label="思考",
        status=part.status,
        duration_ms=max(0.0, float(part.duration_ms or 0.0)),
        depth=2,
        step=step,
    )


def _plan_row(messageId: int, part, step: int) -> ElaChatTraceRow:
    plan = part.plan or ElaChatPlan()
    done, total = plan.progress()
    return ElaChatTraceRow(
        kind="plan",
        message_id=messageId,
        part_id=part.id,
        label="计划",
        detail=f"{done}/{total}",
        status=part.status,
        depth=2,
        step=step,
    )


def _permission_row(messageId: int, part, step: int) -> ElaChatTraceRow:
    request = part.permission
    action = getattr(request, "action", "") if request is not None else ""
    status = getattr(request, "status", "") if request is not None else ""
    return ElaChatTraceRow(
        kind="permission",
        message_id=messageId,
        part_id=part.id,
        label="审批",
        detail=str(action or ""),
        status=str(status or ""),
        depth=2,
        step=step,
    )


def _compaction_row(messageId: int, part, step: int) -> ElaChatTraceRow:
    count = _int(getattr(part, "history_count", 0))
    return ElaChatTraceRow(
        kind="compaction",
        message_id=messageId,
        part_id=part.id,
        label="上下文压缩",
        detail=f"{count} 条" if count else "",
        status=part.status,
        depth=2,
        step=step,
    )


def _step_rows(messageId: int, parts, step: int, turn_start: float):
    stats = None
    for part in parts:
        if part.kind == ElaChatPartKindType.Stats and part.stats is not None:
            stats = part.stats
    tool_rows = {}
    tool_order = []
    others = []
    for part in parts:
        kind = part.kind
        if kind == ElaChatPartKindType.Tool and part.tool_call is not None:
            row = _tool_row(messageId, part.tool_call, step)
            tool_rows[row.part_id] = row
            tool_order.append(row.part_id)
        elif kind == ElaChatPartKindType.Reasoning:
            others.append(_reasoning_row(messageId, part, step))
        elif kind == ElaChatPartKindType.Plan:
            others.append(_plan_row(messageId, part, step))
        elif kind == ElaChatPartKindType.Permission:
            others.append(_permission_row(messageId, part, step))
        elif kind == ElaChatPartKindType.Compaction:
            others.append(_compaction_row(messageId, part, step))
    # 子代理子调用挂到父行；父缺失时保留为顶层工具行。递归建树，
    # 保证多层嵌套时孙调用也在父行 children 里（简单两遍 replace 会丢孙层）。
    children_map: dict = {}
    top_ids = []
    for call_id in tool_order:
        row = tool_rows[call_id]
        if row.parent_id and row.parent_id in tool_rows:
            children_map.setdefault(row.parent_id, []).append(call_id)
        else:
            top_ids.append(call_id)

    def build(call_id: str, depth: int) -> ElaChatTraceRow:
        row = tool_rows[call_id]
        kids = tuple(
            build(child_id, depth + 1) for child_id in children_map.get(call_id, ())
        )
        return replace(row, depth=depth, children=kids)

    top_tools = {call_id: build(call_id, 2) for call_id in top_ids}
    non_tool_rows = {row.part_id: row for row in others}
    children = []
    for part in parts:
        if part.kind == ElaChatPartKindType.Tool and part.tool_call is not None:
            row = top_tools.get(part.tool_call.id)
            if row is not None:
                children.append(row)
        else:
            row = non_tool_rows.get(part.id)
            if row is not None:
                children.append(row)
    duration = float(stats.duration_ms or 0.0) if stats is not None else 0.0
    if duration <= 0 and children:
        duration = max(
            (
                (max(0.0, child.started_at - turn_start) * 1000.0) + child.duration_ms
                for child in children
                if child.started_at > 0
            ),
            default=0.0,
        )
    return ElaChatTraceRow(
        kind="step",
        message_id=messageId,
        part_id=f"step-{step}",
        label=f"第 {step} 步",
        status="",
        duration_ms=duration,
        started_at=min(
            (child.started_at for child in children if child.started_at > 0),
            default=0.0,
        ),
        tokens=_stats_tokens(stats),
        cost_usd=float(stats.cost_usd or 0.0) if stats is not None else 0.0,
        depth=1,
        step=step,
        children=tuple(children),
    )


def buildTraceRows(messages) -> ElaChatTraceResult:
    """把助手消息整理成轨迹树 + 汇总。"""
    rows = []
    total_duration = 0.0
    tool_count = 0
    error_count = 0
    tokens = 0
    cost = 0.0
    for message in messages or ():
        if getattr(message, "role", "") != ElaChatRoleType.Assistant:
            continue
        parts = list(getattr(message, "parts", ()) or ())
        if not parts:
            continue
        groups = {}
        order = []
        for part in parts:
            step = max(1, int(getattr(part, "step", 1) or 1))
            if step not in groups:
                groups[step] = []
                order.append(step)
            groups[step].append(part)
        turn_start = float(getattr(message, "created_at", 0.0) or 0.0)
        step_rows = []
        for step in order:
            step_row = _step_rows(
                int(getattr(message, "id", 0) or 0),
                groups[step],
                step,
                turn_start,
            )
            step_rows.append(step_row)
            tokens += step_row.tokens
            cost += step_row.cost_usd
            for child in step_row.walk():
                if child is step_row:
                    continue
                if child.kind == "tool":
                    tool_count += 1
                    if child.isError:
                        error_count += 1
        duration = float(getattr(message, "duration_ms", 0.0) or 0.0)
        if duration <= 0:
            duration = max((row.duration_ms for row in step_rows), default=0.0)
        turn = ElaChatTraceRow(
            kind="turn",
            message_id=int(getattr(message, "id", 0) or 0),
            part_id="",
            label=str(getattr(message, "title", "") or "回合"),
            detail=str(getattr(message, "agent", "") or ""),
            status=str(getattr(message, "status", "") or ""),
            duration_ms=duration,
            started_at=turn_start,
            tokens=sum(row.tokens for row in step_rows),
            cost_usd=sum(row.cost_usd for row in step_rows),
            depth=0,
            children=tuple(step_rows),
        )
        rows.append(turn)
        total_duration = max(total_duration, duration)
    return ElaChatTraceResult(
        rows=tuple(rows),
        total_duration_ms=total_duration,
        tool_count=tool_count,
        error_count=error_count,
        tokens=tokens,
        cost_usd=cost,
    )


__all__ = [
    "ElaChatTraceResult",
    "ElaChatTraceRow",
    "buildTraceRows",
]
