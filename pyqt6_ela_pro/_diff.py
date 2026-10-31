"""纯 diff 模型（无 Qt）：统一 diff 解析、before/after 对拍、行号与统计。

刻意与控件分离：解析 / 统计是纯函数，可单测、可在渲染器 / 审阅面板 / 导出
之间复用；``ElaDiffView`` 只负责把 ``ElaDiffFile`` 画出来。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

#: 行类型
DIFF_CONTEXT = "context"
DIFF_ADD = "add"
DIFF_DEL = "del"
DIFF_HUNK = "hunk"
DIFF_META = "meta"
#: 文件状态
DIFF_MODIFIED = "modified"
DIFF_ADDED = "added"
DIFF_DELETED = "deleted"

#: 单次解析上限（防止一个坏 patch 把 UI 撑爆；view 还会再按渲染行数截断）
MAX_PARSE_LINES = 200_000
#: 单行最大字符（超长 base64 / minified 文件不逐字符排版）
MAX_LINE_CHARS = 20_000

_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def _to_int(value, default: int = 0) -> int:
    """容错取整数（metadata 是外部输入，坏值不能让渲染器抛）。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return default


def _clip(text: str) -> str:
    if len(text) <= MAX_LINE_CHARS:
        return text
    return text[:MAX_LINE_CHARS] + " …"


def _strip_prefix(path: str) -> str:
    text = str(path or "").strip()
    if text.startswith("a/") or text.startswith("b/"):
        return text[2:]
    return text


@dataclass(frozen=True)
class ElaDiffLine:
    """diff 的一行。"""

    #: ``context`` / ``add`` / ``del`` / ``hunk`` / ``meta``
    kind: str
    #: 行内容（不含 ``+`` / ``-`` / `` `` 前缀）
    text: str = ""
    #: 旧文件行号（``None`` = 该行不在旧文件里）
    old_no: Optional[int] = None
    #: 新文件行号（``None`` = 该行不在新文件里）
    new_no: Optional[int] = None


@dataclass(frozen=True)
class ElaDiffFile:
    """一个文件的 diff 快照。"""

    #: 展示路径（尽量去掉 ``a/`` / ``b/`` 前缀）
    path: str
    #: 旧路径（重命名 / 删除时可能不同）
    old_path: str = ""
    #: 新路径
    new_path: str = ""
    #: ``modified`` / ``added`` / ``deleted``
    status: str = DIFF_MODIFIED
    #: 新增行数
    additions: int = 0
    #: 删除行数
    deletions: int = 0
    #: 是否二进制（无 hunk）
    binary: bool = False
    #: 逐行内容
    lines: tuple = field(default_factory=tuple)
    #: 原始 patch（复制 / 复核用；由调用方决定是否保留）
    patch: str = ""

    @property
    def line_count(self) -> int:
        """diff 行数（含 hunk 头）。"""
        return len(self.lines)

    def is_empty(self) -> bool:
        """是否没有任何可展示内容。"""
        return not self.lines and not self.binary


def _new_file(path: str, patch: str = "", status: str = DIFF_MODIFIED) -> ElaDiffFile:
    return ElaDiffFile(
        path=_strip_prefix(path),
        old_path=_strip_prefix(path),
        new_path=_strip_prefix(path),
        status=status,
        patch=patch,
    )


def parseUnifiedDiff(text: str) -> list[ElaDiffFile]:
    """解析统一 diff 文本（``diff --git`` / ``--- +++`` / ``@@``）。

    无法识别的文本返回空列表（调用方回落 ``diffLines``）。单文件 / 多文件都
    支持；``\\ No newline at end of file`` 记为 meta 行。
    """
    raw = str(text or "")
    if not raw.strip():
        return []
    lines = raw.splitlines()
    if len(lines) > MAX_PARSE_LINES:
        lines = lines[:MAX_PARSE_LINES]
    files: list[ElaDiffFile] = []
    current: Optional[dict] = None
    old_no = 0
    new_no = 0
    seen_header = False

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        items = current.get("lines", [])
        additions = sum(1 for line in items if line.kind == DIFF_ADD)
        deletions = sum(1 for line in items if line.kind == DIFF_DEL)
        status = current.get("status")
        if not status:
            status = DIFF_MODIFIED
        files.append(
            ElaDiffFile(
                path=_strip_prefix(current.get("path", "")),
                old_path=_strip_prefix(current.get("old_path", "")),
                new_path=_strip_prefix(current.get("new_path", "")),
                status=status,
                additions=additions,
                deletions=deletions,
                binary=bool(current.get("binary")),
                lines=tuple(items),
                patch=current.get("patch", ""),
            )
        )
        current = None

    for raw_line in lines:
        line = raw_line.rstrip("\r")
        match = _GIT_RE.match(line)
        if match:
            flush()
            current = {
                "path": match.group(2),
                "old_path": match.group(1),
                "new_path": match.group(2),
                "lines": [],
                "patch": raw,
            }
            seen_header = True
            continue
        if line.startswith("--- "):
            if current is None:
                current = {"lines": [], "patch": raw}
            current["old_path"] = line[4:].split("\t", 1)[0].strip()
            if current["old_path"] == "/dev/null":
                current["status"] = DIFF_ADDED
            seen_header = True
            continue
        if line.startswith("+++ "):
            if current is None:
                current = {"lines": [], "patch": raw}
            current["new_path"] = line[4:].split("\t", 1)[0].strip()
            if current["new_path"] == "/dev/null":
                current["status"] = DIFF_DELETED
            else:
                current["path"] = current.get("path") or current["new_path"]
            seen_header = True
            continue
        if current is None:
            continue
        if line.startswith("@@") and _HUNK_RE.match(line):
            hunk = _HUNK_RE.match(line)
            old_no = int(hunk.group(1))
            new_no = int(hunk.group(3))
            current["lines"].append(ElaDiffLine(kind=DIFF_HUNK, text=_clip(line)))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current["lines"].append(
                ElaDiffLine(kind=DIFF_ADD, text=_clip(line[1:]), new_no=new_no)
            )
            new_no += 1
            continue
        if line.startswith("-") and not line.startswith("---"):
            current["lines"].append(
                ElaDiffLine(kind=DIFF_DEL, text=_clip(line[1:]), old_no=old_no)
            )
            old_no += 1
            continue
        if line.startswith(" "):
            current["lines"].append(
                ElaDiffLine(
                    kind=DIFF_CONTEXT,
                    text=_clip(line[1:]),
                    old_no=old_no,
                    new_no=new_no,
                )
            )
            old_no += 1
            new_no += 1
            continue
        if line.startswith("\\"):
            current["lines"].append(ElaDiffLine(kind=DIFF_META, text=_clip(line)))
            continue
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            current["binary"] = True
            current["lines"].append(ElaDiffLine(kind=DIFF_META, text=_clip(line)))
            continue
        # 未识别的 diff 元信息（index / similarity / rename from ...）
        if line.startswith(
            (
                "index ",
                "new file mode",
                "deleted file mode",
                "similarity index",
                "rename from",
                "rename to",
                "old mode",
                "new mode",
                "mode ",
            )
        ):
            current["lines"].append(ElaDiffLine(kind=DIFF_META, text=_clip(line)))
    flush()
    if not seen_header:
        return []
    return [item for item in files if item.path]


def diffLines(before: str, after: str, path: str = "") -> ElaDiffFile:
    """用 ``difflib`` 生成 before/after 的逐行 diff。"""
    old_lines = str(before or "").splitlines()
    new_lines = str(after or "").splitlines()
    status = DIFF_MODIFIED
    if not old_lines and new_lines:
        status = DIFF_ADDED
    elif old_lines and not new_lines:
        status = DIFF_DELETED
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    rows: list[ElaDiffLine] = []
    old_no = 1
    new_no = 1
    additions = 0
    deletions = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append(
                    ElaDiffLine(
                        kind=DIFF_CONTEXT,
                        text=_clip(old_lines[i1 + offset]),
                        old_no=old_no,
                        new_no=new_no,
                    )
                )
                old_no += 1
                new_no += 1
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                rows.append(ElaDiffLine(kind=DIFF_DEL, text=_clip(line), old_no=old_no))
                old_no += 1
                deletions += 1
            for line in new_lines[j1:j2]:
                rows.append(ElaDiffLine(kind=DIFF_ADD, text=_clip(line), new_no=new_no))
                new_no += 1
                additions += 1
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                rows.append(ElaDiffLine(kind=DIFF_DEL, text=_clip(line), old_no=old_no))
                old_no += 1
                deletions += 1
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                rows.append(ElaDiffLine(kind=DIFF_ADD, text=_clip(line), new_no=new_no))
                new_no += 1
                additions += 1
    return ElaDiffFile(
        path=_strip_prefix(path),
        old_path=_strip_prefix(path),
        new_path=_strip_prefix(path),
        status=status,
        additions=additions,
        deletions=deletions,
        lines=tuple(rows),
    )


def diffFileFromAny(data: dict) -> Optional[ElaDiffFile]:
    """把渲染器 metadata 里的一项归一成 ``ElaDiffFile``（容错）。"""
    if not isinstance(data, dict):
        return None
    path = (
        data.get("file")
        or data.get("path")
        or data.get("new_path")
        or data.get("newPath")
        or ""
    )
    patch = data.get("patch")
    if isinstance(patch, str) and patch.strip():
        parsed = parseUnifiedDiff(patch)
        if parsed:
            item = parsed[0]
            return ElaDiffFile(
                path=_strip_prefix(path) or item.path,
                old_path=item.old_path,
                new_path=item.new_path,
                status=str(data.get("status") or item.status),
                additions=_to_int(data.get("additions"), item.additions),
                deletions=_to_int(data.get("deletions"), item.deletions),
                binary=item.binary,
                lines=item.lines,
                patch=patch,
            )
    before = data.get("before")
    after = data.get("after")
    if isinstance(before, str) or isinstance(after, str):
        item = diffLines(before or "", after or "", path)
        return replaceStatus(
            item,
            status=str(data.get("status") or item.status),
            additions=data.get("additions"),
            deletions=data.get("deletions"),
        )
    return None


def replaceStatus(
    item: ElaDiffFile, status: str, additions=None, deletions=None
) -> ElaDiffFile:
    """覆盖状态 / 统计（metadata 显式给了就以 metadata 为准）。"""
    return replace(
        item,
        status=status or item.status,
        additions=item.additions if additions is None else max(0, _to_int(additions)),
        deletions=item.deletions if deletions is None else max(0, _to_int(deletions)),
    )


def filesFromMetadata(value: Iterable) -> list[ElaDiffFile]:
    """把 ``metadata["files"]`` 归一成文件列表（跳过坏项）。"""
    result = []
    for item in value or ():
        parsed = diffFileFromAny(item)
        if parsed is not None:
            result.append(parsed)
    return result


__all__ = [
    "DIFF_ADD",
    "DIFF_ADDED",
    "DIFF_CONTEXT",
    "DIFF_DEL",
    "DIFF_DELETED",
    "DIFF_HUNK",
    "DIFF_META",
    "DIFF_MODIFIED",
    "ElaDiffFile",
    "ElaDiffLine",
    "diffFileFromAny",
    "diffLines",
    "filesFromMetadata",
    "parseUnifiedDiff",
    "replaceStatus",
]
