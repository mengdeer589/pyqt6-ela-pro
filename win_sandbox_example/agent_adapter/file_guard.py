"""文件工具的路径收口示例。

沙箱只拦 shell 里的写；宿主侧的 ``write_file("C:/Users/...")`` 仍然能落盘。
凡是文件工具，都要先过 ``box.resolve()``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from win_sandbox import Sandbox

from .registry import register_tool

READ_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径（相对工作区或绝对路径）"},
        "offset": {"type": "integer", "description": "起始行号（1-indexed，0=开头）"},
        "limit": {"type": "integer", "description": "最多返回行数", "default": 200},
    },
    "required": ["path"],
}

WRITE_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径（相对工作区或绝对路径）"},
        "content": {"type": "string", "description": "文件内容"},
    },
    "required": ["path", "content"],
}

EDIT_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径（相对工作区或绝对路径）"},
        "old_string": {"type": "string", "description": "被替换的文本（必须唯一）"},
        "new_string": {"type": "string", "description": "替换后的文本"},
    },
    "required": ["path", "old_string", "new_string"],
}

GLOB_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "相对工作区的 glob，如 **/*.py"},
        "limit": {"type": "integer", "description": "结果上限", "default": 50},
    },
    "required": ["pattern"],
}


def install_file_tools(box: Sandbox) -> None:
    @register_tool(
        "read_file",
        description="读取沙箱工作区内的文件，带行号。",
        parameters=READ_PARAMS,
    )
    def read_file(path: str, offset: int = 0, limit: int = 200) -> str:
        target = box.resolve(path, tool="read_file", operation="read")
        with box.tool_scope("read_file", path=str(target)):
            if not target.is_file():
                return f"Error: 文件不存在或不是文件: {target}"
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            start = max(0, offset - 1) if offset > 0 else 0
            selected = lines[start : start + max(1, limit)]
            body = "\n".join(
                f"{start + index + 1}: {line}" for index, line in enumerate(selected)
            )
            return f"文件: {target} ({total} 行)\n{body}\n--- 显示 {len(selected)}/{total} 行 ---"

    @register_tool(
        "write_file",
        description="写入沙箱工作区内的文件（覆盖）。",
        parameters=WRITE_PARAMS,
    )
    def write_file(path: str, content: str) -> str:
        target = box.resolve(path, tool="write_file", operation="write")
        with box.tool_scope("write_file", path=str(target)):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"已写入 {target} ({len(content)} 字符)"

    @register_tool(
        "edit_file",
        description="替换沙箱工作区内文件的一段文本（old_string 必须唯一）。",
        parameters=EDIT_PARAMS,
    )
    def edit_file(path: str, old_string: str, new_string: str) -> str:
        target = box.resolve(path, tool="edit_file", operation="write")
        with box.tool_scope("edit_file", path=str(target)):
            if not target.is_file():
                return f"Error: 文件不存在: {target}"
            text = target.read_text(encoding="utf-8", errors="replace")
            count = text.count(old_string)
            if count == 0:
                return "Error: old_string 不存在"
            if count > 1:
                return f"Error: old_string 出现 {count} 次，必须唯一"
            target.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
            return f"已编辑 {target}"

    @register_tool(
        "glob_file",
        description="按 glob 查找沙箱工作区内的文件（不支持绝对路径）。",
        parameters=GLOB_PARAMS,
    )
    def glob_file(pattern: str, limit: int = 50) -> str:
        if Path(pattern).is_absolute():
            raise ValueError("absolute patterns are not allowed")
        if ".." in Path(pattern).parts:
            raise ValueError("'..' is not allowed in glob patterns")
        with box.tool_scope("glob_file", pattern=pattern):
            matches = sorted(
                (item for item in box.workspace.rglob(pattern) if item.is_file()),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if not matches:
                return f"无匹配: {pattern}"
            shown = matches[: max(1, limit)]
            lines = [str(item.relative_to(box.workspace)) for item in shown]
            result = "\n".join(lines) or "(no files)"
            if len(matches) > len(shown):
                result += f"\n... 还有 {len(matches) - len(shown)} 个"
            return result
