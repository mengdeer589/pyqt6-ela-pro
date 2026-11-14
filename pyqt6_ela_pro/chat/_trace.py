"""运行轨迹模型：把消息时间线整理成“用户提问 → 助手响应 → 步骤 → 工具”的树（纯数据）。"""

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

#: 无耗时 / 无起点的分段给一段可见跨度，避免全部叠在 0 点
_DEFAULT_SPAN_MS = 240.0
#: 异常耗时裁剪的下限 / 上限
_MIN_CLIP_MS = 10_000.0
_MAX_CLIP_MS = 600_000.0
#: 轮内空闲间隔超过该值就压缩
_MIN_GAP_MS = 5_000.0
#: 容器行（跨度由子节点并集得出）
_CONTAINER_KINDS = frozenset({"turn", "response", "step"})
#: 子代理 / 工具行在“用户提问 → 响应 → 步骤”层级里的深度
_TOOL_DEPTH = 3


def _user_turn_label(message) -> str:
    text = " ".join(str(getattr(message, "text", "") or "").split())
    if not text:
        return "提问"
    return text[:80] + ("…" if len(text) > 80 else "")


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


def _tool_row(
    messageId: int,
    call,
    step: int,
    startMs: float = 0.0,
    estimated: bool = False,
) -> "ElaChatTraceRow":
    metadata = call.metadata if isinstance(call.metadata, dict) else {}
    tokens = metadata.get("tokens", metadata.get("total_tokens"))
    cost = metadata.get("cost_usd", metadata.get("cost"))
    duration = max(0.0, float(call.duration_ms or 0.0))
    if duration <= 0:
        duration = _DEFAULT_SPAN_MS
        estimated = True
    return ElaChatTraceRow(
        kind="tool",
        message_id=messageId,
        part_id=call.id,
        parent_id=call.parent_id,
        label=call.title or call.name or "工具",
        detail=_tool_detail(call),
        status=call.status,
        duration_ms=duration,
        started_at=max(0.0, float(call.started_at or 0.0)),
        tokens=_int(tokens) if isinstance(tokens, (int, float)) else 0,
        cost_usd=float(cost) if isinstance(cost, (int, float)) else 0.0,
        depth=3,
        step=step,
        start_ms=max(0.0, float(startMs or 0.0)),
        span_ms=duration,
        estimated=estimated,
    )


@dataclass(frozen=True)
class ElaChatTraceRow:
    """轨迹里的一行（turn / response / step / tool / reasoning / plan / permission / compaction）。"""

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
    #: 相对本轮起点的显示位置（毫秒，已压缩空闲间隔）
    start_ms: float = 0.0
    #: 显示跨度（毫秒，已裁剪异常耗时）
    span_ms: float = 0.0
    #: 真实耗时超过全局裁剪阈值
    clipped: bool = False
    #: 起点或耗时缺失，按顺序估算
    estimated: bool = False
    #: 自身或后代存在失败
    error_below: bool = False
    #: 步骤用量快照（仅 step 行）
    stats: Optional[ElaChatStats] = None
    #: 步骤上下文词元数（仅 step 行）
    context_tokens: int = 0

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
    #: 异常耗时裁剪阈值（毫秒）；真实耗时超出部分在界面上截断
    clip_ms: float = 0.0
    #: 被裁剪的 span 数
    clipped_count: int = 0

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


def _reasoning_row(
    messageId: int,
    part,
    step: int,
    startMs: float = 0.0,
    durationMs: float = 0.0,
    estimated: bool = False,
) -> ElaChatTraceRow:
    return ElaChatTraceRow(
        kind="reasoning",
        message_id=messageId,
        part_id=part.id,
        label="思考",
        status=part.status,
        duration_ms=durationMs,
        depth=3,
        step=step,
        start_ms=startMs,
        span_ms=durationMs,
        estimated=estimated,
    )


def _plan_row(
    messageId: int,
    part,
    step: int,
    startMs: float = 0.0,
    durationMs: float = 0.0,
    estimated: bool = False,
) -> ElaChatTraceRow:
    plan = part.plan or ElaChatPlan()
    done, total = plan.progress()
    return ElaChatTraceRow(
        kind="plan",
        message_id=messageId,
        part_id=part.id,
        label="计划",
        detail=f"{done}/{total}",
        status=part.status,
        duration_ms=durationMs,
        depth=3,
        step=step,
        start_ms=startMs,
        span_ms=durationMs,
        estimated=estimated,
    )


def _permission_row(
    messageId: int,
    part,
    step: int,
    startMs: float = 0.0,
    durationMs: float = 0.0,
    estimated: bool = False,
) -> ElaChatTraceRow:
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
        duration_ms=durationMs,
        depth=3,
        step=step,
        start_ms=startMs,
        span_ms=durationMs,
        estimated=estimated,
    )


def _compaction_row(
    messageId: int,
    part,
    step: int,
    startMs: float = 0.0,
    durationMs: float = 0.0,
    estimated: bool = False,
) -> ElaChatTraceRow:
    count = _int(getattr(part, "history_count", 0))
    return ElaChatTraceRow(
        kind="compaction",
        message_id=messageId,
        part_id=part.id,
        label="上下文压缩",
        detail=f"{count} 条" if count else "",
        status=part.status,
        duration_ms=durationMs,
        depth=3,
        step=step,
        start_ms=startMs,
        span_ms=durationMs,
        estimated=estimated,
    )


def _raw_end(row: ElaChatTraceRow) -> float:
    """自身与后代的原始终点（毫秒）。"""
    end = row.start_ms + max(0.0, row.duration_ms)
    for child in row.children:
        end = max(end, _raw_end(child))
    return end


def _step_rows(
    messageId: int,
    parts,
    step: int,
    turn_start: float,
    cursorStart: float = 0.0,
):
    stats = None
    for part in parts:
        if part.kind == ElaChatPartKindType.Stats and part.stats is not None:
            stats = part.stats
    tool_rows = {}
    tool_order = []
    others = []
    cursor = max(0.0, float(cursorStart or 0.0))
    for part in parts:
        kind = part.kind
        if kind == ElaChatPartKindType.Tool and part.tool_call is not None:
            call = part.tool_call
            estimated = False
            if call.started_at > 0 and turn_start > 0:
                start = max(0.0, (call.started_at - turn_start) * 1000.0)
            else:
                start = cursor
                estimated = True
            row = _tool_row(messageId, call, step, start, estimated)
            tool_rows[row.part_id] = row
            tool_order.append(row.part_id)
            cursor = max(cursor, row.start_ms + row.duration_ms)
        else:
            duration = max(0.0, float(part.duration_ms or 0.0))
            estimated = duration <= 0
            if estimated:
                duration = _DEFAULT_SPAN_MS
            if kind == ElaChatPartKindType.Reasoning:
                row = _reasoning_row(messageId, part, step, cursor, duration, estimated)
            elif kind == ElaChatPartKindType.Plan:
                row = _plan_row(messageId, part, step, cursor, duration, estimated)
            elif kind == ElaChatPartKindType.Permission:
                row = _permission_row(
                    messageId, part, step, cursor, duration, estimated
                )
            elif kind == ElaChatPartKindType.Compaction:
                row = _compaction_row(
                    messageId, part, step, cursor, duration, estimated
                )
            else:
                continue
            others.append(row)
            cursor = max(cursor, row.start_ms + duration)

    # 子代理子调用挂到父行；父缺失时保留为顶层工具行。递归建树，
    # 保证多层嵌套时孙调用也在父行 children 里。
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
        if not kids and depth == row.depth:
            return row
        start = min((child.start_ms for child in kids), default=row.start_ms)
        start = min(start, row.start_ms)
        return replace(
            row,
            depth=depth,
            children=kids,
            start_ms=start,
            error_below=row.isError or any(child.error_below for child in kids),
        )

    top_tools = {call_id: build(call_id, _TOOL_DEPTH) for call_id in top_ids}
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

    if children:
        start = min(child.start_ms for child in children)
        end = max(_raw_end(child) for child in children)
        duration = end - start
    else:
        start = cursor
        duration = 0.0
    if stats is not None and stats.duration_ms > duration:
        duration = float(stats.duration_ms)
    row = ElaChatTraceRow(
        kind="step",
        message_id=messageId,
        part_id=f"step-{messageId}-{step}",
        label=f"第 {step} 步",
        status="",
        duration_ms=duration,
        start_ms=start,
        span_ms=duration,
        tokens=_stats_tokens(stats),
        cost_usd=float(stats.cost_usd or 0.0) if stats is not None else 0.0,
        depth=2,
        step=step,
        children=tuple(children),
        error_below=any(child.error_below for child in children),
        stats=stats,
        context_tokens=int(stats.contextTokens() or 0) if stats is not None else 0,
    )
    return row, max(cursor, _raw_end(row))


def _clip_threshold(rows) -> float:
    durations = []
    for row in rows:
        for item in row.walk():
            if item.kind not in _CONTAINER_KINDS and item.duration_ms > 0:
                durations.append(item.duration_ms)
    if not durations:
        return _MIN_CLIP_MS
    durations.sort()
    index = min(len(durations) - 1, int(len(durations) * 0.99))
    return min(_MAX_CLIP_MS, max(_MIN_CLIP_MS, durations[index] * 2.0))


def _needs_finalize(turn: ElaChatTraceRow, clip_ms: float) -> bool:
    """该轮是否需要压缩 / 裁剪（多数轮可直接用原始跨度）。"""
    gap_ms = max(_MIN_GAP_MS, clip_ms * 0.5)
    spans = []
    for item in turn.walk():
        if item.kind in _CONTAINER_KINDS:
            if item.kind in ("step", "response") and item.duration_ms > clip_ms:
                return True
            continue
        if item.duration_ms > clip_ms:
            return True
        spans.append(item)
    spans.sort(key=lambda row: (row.start_ms, row.kind))
    previous_end = 0.0
    for row in spans:
        if row.start_ms > previous_end + gap_ms:
            return True
        previous_end = max(previous_end, row.start_ms + row.duration_ms)
    return False


def _finalize_turn(turn: ElaChatTraceRow, clip_ms: float) -> ElaChatTraceRow:
    """把一轮的原始时间压成显示时间：裁剪异常耗时、压缩空闲间隔。"""
    spans = []

    def collect(row: ElaChatTraceRow) -> None:
        if row.kind not in _CONTAINER_KINDS:
            spans.append(row)
        for child in row.children:
            collect(child)

    collect(turn)
    display = {}
    if spans:
        ordered = sorted(spans, key=lambda row: (row.start_ms, row.kind))
        gap_ms = max(_MIN_GAP_MS, clip_ms * 0.5)
        offset = 0.0
        previous_end = 0.0
        for row in ordered:
            start = row.start_ms - offset
            if start > previous_end + gap_ms:
                cut = start - (previous_end + gap_ms)
                offset += cut
                start -= cut
            duration = min(max(0.0, row.duration_ms), clip_ms)
            end = start + duration
            display[id(row)] = (start, end)
            previous_end = max(previous_end, end)

    def rebuild(row: ElaChatTraceRow):
        kids = []
        child_changed = False
        for child in row.children:
            new_child, changed = rebuild(child)
            kids.append(new_child)
            child_changed = child_changed or changed
        if row.kind in _CONTAINER_KINDS or kids:
            starts = []
            ends = []
            if id(row) in display:
                start, end = display[id(row)]
                starts.append(start)
                ends.append(end)
            elif row.kind in _CONTAINER_KINDS:
                starts.append(row.start_ms)
                ends.append(row.start_ms + min(max(0.0, row.span_ms), clip_ms))
            for child in kids:
                starts.append(child.start_ms)
                ends.append(child.start_ms + child.span_ms)
            start = min(starts) if starts else 0.0
            end = max(ends) if ends else start
        else:
            start, end = display.get(id(row), (0.0, 0.0))
        span = max(0.0, end - start)
        clipped = row.duration_ms > clip_ms
        same_kids = len(kids) == len(row.children) and all(
            new is old for new, old in zip(kids, row.children)
        )
        if (
            not child_changed
            and same_kids
            and abs(start - row.start_ms) < 0.01
            and abs(span - row.span_ms) < 0.01
            and clipped == row.clipped
        ):
            return row, False
        return (
            replace(
                row,
                children=tuple(kids),
                start_ms=start,
                span_ms=span,
                clipped=clipped,
            ),
            True,
        )

    result, _ = rebuild(turn)
    if abs(result.start_ms) < 0.01 and result.span_ms >= 1.0:
        return result
    return replace(result, start_ms=0.0, span_ms=max(1.0, result.span_ms))


def _response_row(
    message,
    turn_start: float,
    cursorStart: float,
    index: int,
):
    """一条助手响应（模型调用）→ 内部步骤树。"""
    parts = list(getattr(message, "parts", ()) or ())
    if not parts:
        return None, cursorStart
    message_id = int(getattr(message, "id", 0) or 0)
    created = float(getattr(message, "created_at", 0.0) or 0.0)
    if created > 0 and turn_start > 0:
        start = max(0.0, (created - turn_start) * 1000.0)
    else:
        start = max(0.0, float(cursorStart or 0.0))
    groups = {}
    order = []
    for part in parts:
        step = max(1, int(getattr(part, "step", 1) or 1))
        if step not in groups:
            groups[step] = []
            order.append(step)
        groups[step].append(part)
    step_rows = []
    cursor = start
    for step in order:
        step_row, cursor = _step_rows(
            message_id,
            groups[step],
            step,
            turn_start,
            cursor,
        )
        step_rows.append(step_row)
    if not step_rows:
        return None, cursor
    duration = float(getattr(message, "duration_ms", 0.0) or 0.0)
    if duration <= 0:
        end = max((_raw_end(row) for row in step_rows), default=start)
        duration = max(1.0, end - start)
    status = str(getattr(message, "status", "") or "")
    agent = str(getattr(message, "agent", "") or "")
    model = str(getattr(message, "model", "") or "")
    detail = " · ".join(part for part in (agent, model) if part)
    row = ElaChatTraceRow(
        kind="response",
        message_id=message_id,
        part_id=f"response-{message_id}",
        label=f"响应 {index}",
        detail=detail,
        status=status,
        duration_ms=max(0.0, duration),
        started_at=created,
        tokens=sum(step.tokens for step in step_rows),
        cost_usd=sum(step.cost_usd for step in step_rows),
        depth=1,
        step=0,
        children=tuple(step_rows),
        start_ms=start,
        span_ms=max(0.0, duration),
        error_below=_is_error(status) or any(step.error_below for step in step_rows),
    )
    return row, max(cursor, _raw_end(row))


def buildTraceRows(messages) -> ElaChatTraceResult:
    """把消息按「用户提问 → 助手响应 → 步骤」整理成轨迹树 + 汇总。"""
    groups = []
    current = None
    for message in messages or ():
        role = getattr(message, "role", "")
        if role == ElaChatRoleType.User:
            current = {"user": message, "responses": []}
            groups.append(current)
        elif role == ElaChatRoleType.Assistant:
            parts = list(getattr(message, "parts", ()) or ())
            if not parts:
                continue
            if current is None:
                current = {"user": None, "responses": []}
                groups.append(current)
            current["responses"].append(message)

    turns = []
    tool_count = 0
    error_count = 0
    tokens = 0
    cost = 0.0
    for group in groups:
        user = group["user"]
        responses_input = group["responses"]
        if not responses_input:
            continue
        first = responses_input[0]
        turn_start = float(getattr(user, "created_at", 0.0) or 0.0)
        if turn_start <= 0:
            turn_start = float(getattr(first, "created_at", 0.0) or 0.0)
        cursor = 0.0
        responses = []
        for index, message in enumerate(responses_input, 1):
            row, cursor = _response_row(message, turn_start, cursor, index)
            if row is not None:
                responses.append(row)
        if not responses:
            continue
        duration = max((_raw_end(row) for row in responses), default=0.0)
        turn = ElaChatTraceRow(
            kind="turn",
            message_id=int(getattr(user, "id", 0) or 0)
            if user is not None
            else int(getattr(first, "id", 0) or 0),
            part_id="",
            label=_user_turn_label(user) if user is not None else "开场",
            detail=responses[0].detail,
            status="error" if any(row.error_below for row in responses) else "done",
            duration_ms=duration,
            started_at=turn_start,
            span_ms=duration,
            tokens=sum(row.tokens for row in responses),
            cost_usd=sum(row.cost_usd for row in responses),
            depth=0,
            children=tuple(responses),
            error_below=any(row.error_below for row in responses),
        )
        turns.append(turn)
        tokens += turn.tokens
        cost += turn.cost_usd
        for row in turn.walk():
            if row.kind == "tool":
                tool_count += 1
                if row.isError:
                    error_count += 1

    clip_ms = _clip_threshold(turns)
    finalized = []
    clipped_count = 0
    total_duration = 0.0
    for turn in turns:
        if _needs_finalize(turn, clip_ms):
            row = _finalize_turn(turn, clip_ms)
        else:
            row = turn
        finalized.append(row)
        total_duration += max(0.0, turn.duration_ms)
        if row is not turn:
            for item in row.walk():
                if item.clipped:
                    clipped_count += 1
    return ElaChatTraceResult(
        rows=tuple(finalized),
        total_duration_ms=total_duration,
        tool_count=tool_count,
        error_count=error_count,
        tokens=tokens,
        cost_usd=cost,
        clip_ms=clip_ms,
        clipped_count=clipped_count,
    )


__all__ = [
    "ElaChatTraceResult",
    "ElaChatTraceRow",
    "buildTraceRows",
]
