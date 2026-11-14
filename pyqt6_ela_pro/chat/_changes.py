"""回合变更汇总：从工具 metadata / 参数派生文件变更（纯数据，无 Qt）。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Tuple

from .._diff import ElaDiffFile, diffLines, filesFromMetadata
from .message import ElaChatPart, ElaChatToolCall
from .renderers import parseToolArguments


@dataclass(frozen=True)
class ElaChatTurnChanges:
    """一条助手消息内的文件变更汇总（按路径合并）。"""

    #: 合并后的文件 diff 列表
    files: Tuple[ElaDiffFile, ...] = field(default_factory=tuple)
    #: 新增行数合计
    additions: int = 0
    #: 删除行数合计
    deletions: int = 0

    @property
    def count(self) -> int:
        """变更文件数。"""
        return len(self.files)

    def isEmpty(self) -> bool:  # noqa: N802 (与 Qt / Ela 命名一致)
        """是否没有任何文件变更。"""
        return not self.files


def filesFromToolCall(call: ElaChatToolCall) -> list:
    """从工具调用提取文件变更：``metadata["files"]`` 优先，参数兜底。"""
    if call is None:
        return []
    metadata = call.metadata if isinstance(call.metadata, dict) else {}
    raw = metadata.get("files")
    if isinstance(raw, list):
        files = filesFromMetadata(raw)
        if files:
            return files
    data = parseToolArguments(call.arguments)
    path = str(data.get("path") or data.get("file") or data.get("file_path") or "")
    before = data.get("oldString")
    if before is None:
        before = data.get("old_string")
    after = data.get("newString")
    if after is None:
        after = data.get("new_string")
    if isinstance(before, str) or isinstance(after, str):
        return [diffLines(before or "", after or "", path)]
    content = data.get("content")
    if isinstance(content, str) and path:
        return [diffLines("", content, path)]
    return []


_WRITE_TOOLS = frozenset({"edit", "write", "patch", "apply_patch", "multiedit"})


def _line_count(text: str) -> int:
    text = str(text or "")
    return len(text.splitlines())


def _patch_counts(patch: str) -> tuple[int, int]:
    additions = deletions = 0
    for line in str(patch or "").splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def summaryChangesFromParts(parts: Iterable[ElaChatPart]) -> ElaChatTurnChanges:
    """轻量汇总：只算路径 / 增删行，不解析 diff 行（展开时再走完整解析）。"""
    merged: dict = {}
    order = []
    for part in parts or ():
        call = getattr(part, "tool_call", None)
        if call is None:
            continue
        metadata = call.metadata if isinstance(call.metadata, dict) else {}
        raw = metadata.get("files")
        candidates = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("file") or item.get("path") or "")
                if not path:
                    continue
                patch = str(item.get("patch") or "")
                additions = item.get("additions")
                deletions = item.get("deletions")
                if (
                    not isinstance(additions, int)
                    or isinstance(additions, bool)
                    or not isinstance(deletions, int)
                    or isinstance(deletions, bool)
                ):
                    counted = _patch_counts(patch)
                    if not isinstance(additions, int) or isinstance(additions, bool):
                        additions = counted[0]
                    if not isinstance(deletions, int) or isinstance(deletions, bool):
                        deletions = counted[1]
                candidates.append(
                    (
                        path,
                        additions,
                        deletions,
                        str(item.get("status") or "modified"),
                        patch,
                    )
                )
        elif (call.name or "").lower() in _WRITE_TOOLS:
            data = parseToolArguments(call.arguments)
            path = str(
                data.get("path") or data.get("file") or data.get("file_path") or ""
            )
            if path:
                before = data.get("oldString")
                if before is None:
                    before = data.get("old_string")
                after = data.get("newString")
                if after is None:
                    after = data.get("new_string")
                content = data.get("content")
                if isinstance(before, str) or isinstance(after, str):
                    candidates.append(
                        (
                            path,
                            _line_count(after),
                            _line_count(before),
                            "modified",
                            "",
                        )
                    )
                elif isinstance(content, str):
                    candidates.append((path, _line_count(content), 0, "added", ""))
        for path, additions, deletions, status, patch in candidates:
            existing = merged.get(path)
            if existing is None:
                merged[path] = [
                    additions,
                    deletions,
                    status,
                    patch,
                ]
                order.append(path)
            else:
                existing[0] += additions
                existing[1] += deletions
    files = [
        ElaDiffFile(
            path=path,
            old_path=path,
            new_path=path,
            status=merged[path][2],
            additions=merged[path][0],
            deletions=merged[path][1],
            patch=merged[path][3],
        )
        for path in order
    ]
    return ElaChatTurnChanges(
        files=tuple(files),
        additions=sum(item.additions for item in files),
        deletions=sum(item.deletions for item in files),
    )


def changesFromParts(parts: Iterable[ElaChatPart]) -> ElaChatTurnChanges:
    """按路径合并一条消息里全部工具调用的文件变更。"""
    merged: dict = {}
    order = []
    for part in parts or ():
        call = getattr(part, "tool_call", None)
        if call is None:
            continue
        for item in filesFromToolCall(call):
            key = item.path or item.new_path or item.old_path
            if not key:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = item
                order.append(key)
                continue
            merged[key] = replace(
                existing,
                additions=existing.additions + item.additions,
                deletions=existing.deletions + item.deletions,
                lines=item.lines or existing.lines,
                patch=item.patch or existing.patch,
                status=item.status or existing.status,
                binary=existing.binary or item.binary,
            )
    files = [merged[key] for key in order]
    return ElaChatTurnChanges(
        files=tuple(files),
        additions=sum(item.additions for item in files),
        deletions=sum(item.deletions for item in files),
    )


def changesFromPartsOrMessage(source) -> ElaChatTurnChanges:
    """接受 parts 列表或带 ``parts`` 的消息快照。"""
    if source is None:
        return ElaChatTurnChanges()
    parts = getattr(source, "parts", source)
    return changesFromParts(parts)


__all__ = [
    "ElaChatTurnChanges",
    "changesFromParts",
    "changesFromPartsOrMessage",
    "filesFromToolCall",
    "summaryChangesFromParts",
]
