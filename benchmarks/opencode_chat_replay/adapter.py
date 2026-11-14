"""opencode session rows -> ElaChatView session bundle."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pyqt6_ela_pro.chat.message import (
    SCHEMA_VERSION,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatToolStatusType,
)

SESSION_SCHEMA_VERSION = 1
DEFAULT_MAX_TEXT = 16 * 1024
DEFAULT_MAX_TOOL_OUTPUT = 16 * 1024
MAX_SUBAGENT_DEPTH = 3
_SUBAGENT_RE = re.compile(r'<subagent\s+sessionID="([^"]+)"')
_SUBAGENT_NAMES = frozenset({"subagent", "task", "agent", "delegate_task"})
_TOOL_STATUS = {
    "completed": ElaChatToolStatusType.Done,
    "done": ElaChatToolStatusType.Done,
    "error": ElaChatToolStatusType.Error,
    "failed": ElaChatToolStatusType.Error,
    "running": ElaChatToolStatusType.Running,
    "pending": ElaChatToolStatusType.Pending,
    "aborted": ElaChatToolStatusType.Aborted,
    "cancelled": ElaChatToolStatusType.Aborted,
    "interrupted": ElaChatToolStatusType.Aborted,
}
_MESSAGE_STATUS = {
    "error": ElaChatStatusType.Error,
    "failed": ElaChatStatusType.Error,
    "aborted": ElaChatStatusType.Stopped,
    "cancelled": ElaChatStatusType.Stopped,
    "interrupted": ElaChatStatusType.Stopped,
}


def _finite(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _clip(text: str, limit: int) -> str:
    text = str(text or "")
    if limit > 0 and len(text) > limit:
        return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"
    return text


def _json_safe(value: Any, limit: int = 0) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item, limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, limit) for item in value]
    if isinstance(value, str):
        return _clip(value, limit)
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if isinstance(value, (int, bool)) or value is None:
        return value
    return _clip(str(value), limit)


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value or "")


def _ms_to_s(value) -> float:
    return max(0.0, _finite(value) / 1000.0)


def _timestamp(ms) -> str:
    value = _finite(ms)
    if value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return ""


def _content_text(content, limit: int = 0) -> str:
    if isinstance(content, str):
        return _clip(content, limit)
    if isinstance(content, dict):
        return _clip(content.get("text") or _json_text(content), limit)
    if isinstance(content, list):
        rows = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                rows.append(item["text"])
            else:
                rows.append(_json_text(item))
        return _clip("\n".join(rows), limit)
    return _clip(str(content or ""), limit)


def _tool_result(state: dict, limit: int) -> str:
    for key in ("output", "content", "result"):
        value = state.get(key)
        if value not in (None, "", [], {}):
            return _content_text(value, limit)
    return ""


def _tool_arguments(state: dict) -> str:
    value = state.get("input")
    if value in (None, "", {}, []):
        value = state.get("arguments")
    if isinstance(value, (dict, list)):
        return _json_text(value)
    return str(value or "")


def _tool_status(state: dict) -> str:
    raw = str(state.get("status") or "").lower()
    if raw:
        return _TOOL_STATUS.get(raw, ElaChatToolStatusType.Done)
    return (
        ElaChatToolStatusType.Done
        if state.get("content") or state.get("output")
        else ElaChatToolStatusType.Running
    )


def _tool_locations(state: dict, metadata: dict) -> list:
    paths = []
    data = state.get("input")
    if isinstance(data, dict):
        for key in ("path", "file", "file_path", "filename"):
            value = data.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
    for item in metadata.get("files") or ():
        if isinstance(item, dict):
            value = item.get("file") or item.get("path")
            if isinstance(value, str) and value:
                paths.append(value)
    result = []
    for path in dict.fromkeys(paths):
        result.append({"path": path, "line": 0})
    return result


def _tool_part(
    part: dict,
    *,
    parent_id: str,
    id_prefix: str,
    step: int,
    max_tool_output: int,
    max_text: int,
    counts: Counter,
) -> tuple[dict, list]:
    name = str(part.get("name") or part.get("tool") or "tool")
    state = part.get("state") if isinstance(part.get("state"), dict) else {}
    raw_id = str(part.get("id") or f"tool-{counts['tool_parts'] + 1}")
    call_id = f"{id_prefix}:{raw_id}" if id_prefix else raw_id
    metadata = state.get("metadata")
    metadata = _json_safe(metadata if isinstance(metadata, dict) else {}, max_text)
    time_data = part.get("time") if isinstance(part.get("time"), dict) else {}
    started = _ms_to_s(time_data.get("created"))
    duration = max(
        0.0,
        _ms_to_s(time_data.get("completed")) - started,
    )
    tool = {
        "id": call_id,
        "name": name,
        "arguments": _clip(_tool_arguments(state), max_tool_output),
        "result": _tool_result(state, max_tool_output),
        "status": _tool_status(state),
        "metadata": metadata,
        "kind": "",
        "title": str(state.get("title") or ""),
        "locations": _tool_locations(state, metadata),
        "parent_id": parent_id,
        "started_at": started,
        "duration_ms": duration * 1000.0,
    }
    counts["tool_parts"] += 1
    if name.lower() in _SUBAGENT_NAMES:
        counts["subagent_calls"] += 1
    text = ""
    part_out = {
        "id": f"{call_id}:part",
        "kind": ElaChatPartKindType.Tool,
        "text": text,
        "status": ElaChatStatusType.Done,
        "tool_call": tool,
        "stats": None,
        "permission": None,
        "plan": None,
        "duration_ms": duration * 1000.0,
        "step": step,
        "notice_type": "",
        "detail": "",
        "history_count": 0,
        "deadline": 0.0,
    }
    return part_out, _child_tool_parts(
        state,
        parent_call_id=call_id,
        id_prefix=f"{id_prefix}:{raw_id}" if id_prefix else raw_id,
        step=step,
        max_tool_output=max_tool_output,
        max_text=max_text,
        counts=counts,
    )


def _subagent_session_id(state: dict) -> str:
    metadata = state.get("metadata")
    if isinstance(metadata, dict):
        direct = metadata.get("sessionID") or metadata.get("session_id")
        if isinstance(direct, str) and direct:
            return direct
    match = _SUBAGENT_RE.search(_content_text(state.get("content")))
    return match.group(1) if match else ""


def _child_tool_parts(
    state: dict,
    *,
    parent_call_id: str,
    id_prefix: str,
    step: int,
    max_tool_output: int,
    max_text: int,
    counts: Counter,
) -> list:
    if not counts.get("_include_children", True):
        return []
    child_id = _subagent_session_id(state) if state else ""
    if not child_id or counts["_depth"] >= MAX_SUBAGENT_DEPTH:
        return []
    db = counts.get("_db")
    if db is None:
        return []
    counts["_depth"] += 1
    counts["child_sessions"].add(child_id)
    rows = db.execute(
        "select data from session_message where session_id=? and type='assistant' order by seq",
        (child_id,),
    )
    result = []
    for row in rows:
        try:
            data = json.loads(row["data"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for part in data.get("content") or ():
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            item, children = _tool_part(
                part,
                parent_id=parent_call_id,
                id_prefix=id_prefix,
                step=step,
                max_tool_output=max_tool_output,
                max_text=max_text,
                counts=counts,
            )
            result.append(item)
            result.extend(children)
    counts["_depth"] -= 1
    return result


def _stats(data: dict, duration_ms: float) -> Optional[dict]:
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    input_tokens = _int(tokens.get("input"))
    cache_read = _int(cache.get("read"))
    cache_write = _int(cache.get("write"))
    prompt = max(0, input_tokens - cache_read - cache_write)
    completion = _int(tokens.get("output"))
    reasoning = _int(tokens.get("reasoning"))
    cost = _finite(data.get("cost"))
    if not (prompt or completion or cache_read or cache_write or cost or duration_ms):
        return None
    duration = max(0.0, _finite(duration_ms))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": input_tokens + completion,
        "reasoning_tokens": reasoning,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "ttft_ms": 0.0,
        "tps": (completion / (duration / 1000.0)) if duration > 0 else 0.0,
        "duration_ms": duration,
        "cost_usd": cost,
    }


def _stats_part(message_id: int, stats: Optional[dict]) -> Optional[dict]:
    if stats is None:
        return None
    return {
        "id": f"stats-{message_id}",
        "kind": ElaChatPartKindType.Stats,
        "text": "",
        "status": ElaChatStatusType.Done,
        "tool_call": None,
        "stats": stats,
        "permission": None,
        "plan": None,
        "duration_ms": _finite(stats.get("duration_ms")),
        "step": 1,
        "notice_type": "",
        "detail": "",
        "history_count": 0,
        "deadline": 0.0,
    }


def _assistant_parts(
    data: dict,
    *,
    message_id: int,
    max_tool_output: int,
    max_text: int,
    counts: Counter,
) -> list:
    parts = []
    for content in data.get("content") or ():
        if not isinstance(content, dict):
            continue
        kind = content.get("type")
        if kind == "reasoning":
            time_data = content.get("time") if isinstance(content.get("time"), dict) else {}
            duration = max(0.0, _ms_to_s(time_data.get("completed")) - _ms_to_s(time_data.get("created")))
            parts.append(
                {
                    "id": f"reasoning-{message_id}-{len(parts)}",
                    "kind": ElaChatPartKindType.Reasoning,
                    "text": _clip(content.get("text") or "", max_text),
                    "status": ElaChatStatusType.Done,
                    "tool_call": None,
                    "stats": None,
                    "permission": None,
                    "plan": None,
                    "duration_ms": duration * 1000.0,
                    "step": 1,
                    "notice_type": "",
                    "detail": "",
                    "history_count": 0,
                    "deadline": 0.0,
                }
            )
            counts["reasoning_parts"] += 1
        elif kind == "text":
            parts.append(
                {
                    "id": f"text-{message_id}-{len(parts)}",
                    "kind": ElaChatPartKindType.Text,
                    "text": _clip(content.get("text") or "", max_text),
                    "status": ElaChatStatusType.Done,
                    "tool_call": None,
                    "stats": None,
                    "permission": None,
                    "plan": None,
                    "duration_ms": 0.0,
                    "step": 1,
                    "notice_type": "",
                    "detail": "",
                    "history_count": 0,
                    "deadline": 0.0,
                }
            )
            counts["text_parts"] += 1
        elif kind == "tool":
            item, children = _tool_part(
                content,
                parent_id="",
                id_prefix="",
                step=1,
                max_tool_output=max_tool_output,
                max_text=max_text,
                counts=counts,
            )
            parts.append(item)
            parts.extend(children)
    return parts


def _user_message(row: dict, message_id: int, max_text: int) -> dict:
    data = json.loads(row["data"])
    text = data.get("text") or (data.get("metadata") or {}).get("displayText") or ""
    attachments = []
    for item in data.get("files") or ():
        if not isinstance(item, dict):
            continue
        name = item.get("name") or "file"
        raw = item.get("data")
        size = max(0, (len(raw) * 3) // 4) if isinstance(raw, str) else 0
        attachments.append(
            {
                "name": name,
                "path": "",
                "size": size,
                "digest": "",
                "mime": str(item.get("mime") or ""),
            }
        )
    return {
        "schema": SCHEMA_VERSION,
        "id": message_id,
        "role": ElaChatRoleType.User,
        "text": _clip(text, max_text),
        "status": ElaChatStatusType.Done,
        "created_at": _ms_to_s((data.get("time") or {}).get("created")),
        "title": "",
        "agent": "",
        "model": "",
        "model_variant": "",
        "timestamp": _timestamp((data.get("time") or {}).get("created")),
        "delivery": "",
        "mentions": [],
        "reasoning": "",
        "reasoning_ms": 0.0,
        "duration_ms": 0.0,
        "tool_calls": [],
        "attachments": attachments,
        "stats": None,
        "error": "",
        "error_type": "",
        "parts": [],
    }


def _assistant_message(row: dict, message_id: int, max_tool_output: int, max_text: int, counts: Counter) -> dict:
    data = json.loads(row["data"])
    time_data = data.get("time") if isinstance(data.get("time"), dict) else {}
    created = _finite(time_data.get("created"))
    completed = _finite(time_data.get("completed"))
    duration = max(0.0, completed - created)
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    stats = _stats(data, duration)
    parts = _assistant_parts(
        data,
        message_id=message_id,
        max_tool_output=max_tool_output,
        max_text=max_text,
        counts=counts,
    )
    stats_part = _stats_part(message_id, stats)
    if stats_part is not None:
        parts.append(stats_part)
        counts["stats_parts"] += 1
    finish = str(data.get("finish") or "").lower()
    error = str(data.get("error") or "")
    status = _MESSAGE_STATUS.get(finish, ElaChatStatusType.Done)
    if error:
        status = ElaChatStatusType.Error
    return {
        "schema": SCHEMA_VERSION,
        "id": message_id,
        "role": ElaChatRoleType.Assistant,
        "text": "",
        "status": status,
        "created_at": _ms_to_s(created),
        "title": str(model.get("id") or ""),
        "agent": str(data.get("agent") or ""),
        "model": str(model.get("id") or ""),
        "model_variant": str(model.get("variant") or ""),
        "timestamp": _timestamp(created),
        "delivery": "",
        "mentions": [],
        "reasoning": "",
        "reasoning_ms": 0.0,
        "duration_ms": duration,
        "tool_calls": [],
        "attachments": [],
        "stats": stats,
        "error": error,
        "error_type": str(data.get("finish") or "") if error else "",
        "parts": parts,
    }


def _compaction_message(row: dict, message_id: int, max_text: int) -> dict:
    data = json.loads(row["data"])
    time_data = data.get("time") if isinstance(data.get("time"), dict) else {}
    created = _finite(time_data.get("created"))
    stats = _stats(data, 0.0)
    part = {
        "id": f"compaction-{message_id}",
        "kind": ElaChatPartKindType.Compaction,
        "text": _clip(data.get("summary") or "", max_text),
        "status": ElaChatStatusType.Done,
        "tool_call": None,
        "stats": stats,
        "permission": None,
        "plan": None,
        "duration_ms": 0.0,
        "step": 1,
        "notice_type": "",
        "detail": str(data.get("reason") or ""),
        "history_count": 0,
        "deadline": 0.0,
    }
    return {
        "schema": SCHEMA_VERSION,
        "id": message_id,
        "role": ElaChatRoleType.Assistant,
        "text": "",
        "status": ElaChatStatusType.Done,
        "created_at": _ms_to_s(created),
        "title": "compaction",
        "agent": "",
        "model": "",
        "model_variant": "",
        "timestamp": _timestamp(created),
        "delivery": "",
        "mentions": [],
        "reasoning": "",
        "reasoning_ms": 0.0,
        "duration_ms": 0.0,
        "tool_calls": [],
        "attachments": [],
        "stats": stats,
        "error": "",
        "error_type": "",
        "parts": [part],
    }


def _system_message(row, message_id: int, max_text: int) -> Optional[dict]:
    data = json.loads(row["data"])
    kind = str(row["type"] or "")
    if kind == "agent-switched":
        text = f"agent: {data.get('previous') or '?'} → {data.get('agent') or '?'}"
    else:
        text = data.get("text") or ""
    if not str(text).strip():
        return None
    time_data = data.get("time") if isinstance(data.get("time"), dict) else {}
    created = _finite(time_data.get("created"))
    return {
        "schema": SCHEMA_VERSION,
        "id": message_id,
        "role": ElaChatRoleType.System,
        "text": _clip(str(text), max_text),
        "status": ElaChatStatusType.Done,
        "created_at": _ms_to_s(created),
        "title": "",
        "agent": "",
        "model": "",
        "model_variant": "",
        "timestamp": _timestamp(created),
        "delivery": "",
        "mentions": [],
        "reasoning": "",
        "reasoning_ms": 0.0,
        "duration_ms": 0.0,
        "tool_calls": [],
        "attachments": [],
        "stats": None,
        "error": "",
        "error_type": "",
        "parts": [],
    }


def load_bundle(
    db_path: Path,
    session_id: str,
    *,
    mode: str = "stress",
    include_children: bool = True,
    max_tool_output: Optional[int] = None,
    max_text: Optional[int] = None,
) -> dict:
    if mode not in ("stress", "typical"):
        raise ValueError("mode 必须是 'stress' 或 'typical'")
    if max_tool_output is None:
        max_tool_output = 0 if mode == "stress" else DEFAULT_MAX_TOOL_OUTPUT
    if max_text is None:
        max_text = 0 if mode == "stress" else DEFAULT_MAX_TEXT
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        session = db.execute(
            "select * from session_v2 where id=?", (session_id,)
        ).fetchone()
        if session is None:
            raise ValueError(f"session 不存在：{session_id}")
        rows = list(
            db.execute(
                "select id, type, seq, time_created, data from session_message "
                "where session_id=? order by seq",
                (session_id,),
            )
        )
        counts = Counter(
            {"_depth": 0, "_db": db, "_include_children": include_children}
        )
        counts["child_sessions"] = set()
        messages = []
        next_id = 1
        skipped = Counter()
        for row in rows:
            kind = str(row["type"] or "")
            if kind == "user":
                messages.append(_user_message(row, next_id, max_text))
                next_id += 1
            elif kind == "assistant":
                messages.append(
                    _assistant_message(
                        row,
                        next_id,
                        max_tool_output,
                        max_text,
                        counts,
                    )
                )
                next_id += 1
            elif kind == "compaction":
                messages.append(_compaction_message(row, next_id, max_text))
                next_id += 1
            elif kind == "agent-switched":
                message = _system_message(row, next_id, max_text)
                if message is not None:
                    messages.append(message)
                    next_id += 1
            else:
                skipped[kind] += 1
        child_messages = 0
        for child_id in sorted(counts["child_sessions"]):
            row = db.execute(
                "select count(*) from session_message where session_id=?",
                (child_id,),
            ).fetchone()
            child_messages += _int(row[0]) if row else 0
        extra = {
            "source": "opencode.db",
            "session_id": session_id,
            "mode": mode,
            "max_tool_output": max_tool_output,
            "max_text": max_text,
            "counts": {
                "source_messages": len(rows),
                "included_messages": len(messages),
                "child_sessions": len(counts["child_sessions"]),
                "child_source_messages": child_messages,
                "tool_parts": counts["tool_parts"],
                "subagent_calls": counts["subagent_calls"],
                "reasoning_parts": counts["reasoning_parts"],
                "text_parts": counts["text_parts"],
                "stats_parts": counts["stats_parts"],
                "skipped_types": dict(skipped),
            },
            "child_session_ids": sorted(counts["child_sessions"]),
        }
        return {
            "schema": SESSION_SCHEMA_VERSION,
            "session": {
                "id": session_id,
                "title": str(session["title"] or "opencode session"),
                "created_at": _ms_to_s(session["time_created"]),
                "message_count": len(messages),
                "work_dir": str(session["directory"] or ""),
            },
            "view": {
                "reasoning_style": "collapse",
                "stats_mode": "footer",
                "tool_grouping": True,
                "avatar_visible": True,
                "user_bubble_ratio": 0.9,
                "content_max_width": 768,
            },
            "messages": messages,
            "extra": extra,
        }
    finally:
        db.close()


def validate_bundle(bundle: dict) -> None:
    from pyqt6_ela_pro.chat.message import ElaChatMessage

    for row in bundle.get("messages") or ():
        ElaChatMessage.fromDict(row)


__all__ = ["load_bundle", "validate_bundle", "SESSION_SCHEMA_VERSION"]
