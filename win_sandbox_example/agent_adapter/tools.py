"""把 ``win_sandbox`` 接成 4 个 agent 工具。

复制到你自己的 agent 时，只把 ``from .registry import register_tool``
换成你的注册器，并调整 schema 的格式；上面的函数体不用改。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from win_sandbox import RunResult, Sandbox, SandboxPolicy
from win_sandbox import format_result as _format_core

from .registry import register_tool

_sandbox: Sandbox | None = None

SHELL_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "要执行的命令"},
        "workdir": {
            "type": "string",
            "description": "工作目录（相对沙箱工作区），留空=工作区根",
        },
        "timeout": {
            "type": "integer",
            "description": "超时秒数",
            "default": 120,
        },
        "description": {"type": "string", "description": "命令说明（5-10字）"},
    },
    "required": ["command"],
}

BACKGROUND_RUN_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "要执行的命令"},
        "wait": {
            "type": "boolean",
            "description": "True=等命令结束返回输出；False=立即返回任务 id（长驻服务用）",
            "default": True,
        },
        "workdir": {
            "type": "string",
            "description": "工作目录（相对沙箱工作区），留空=工作区根",
        },
    },
    "required": ["command"],
}

CHECK_BACKGROUND_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": ["string", "null"],
            "description": "任务 id；留空列出所有任务",
        }
    },
}

CANCEL_BACKGROUND_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {"task_id": {"type": "string", "description": "要取消的任务 id"}},
    "required": ["task_id"],
}


def sandbox() -> Sandbox:
    if _sandbox is None:
        raise RuntimeError("install_sandbox() 必须先调用")
    return _sandbox


def install_sandbox(
    workspace: str | Path,
    *,
    shell: str | None = None,
    force_cmd: bool = False,
    policy: SandboxPolicy | None = None,
    audit=None,
) -> Sandbox:
    """创建 Sandbox、打标签并注册 4 个工具。"""
    global _sandbox
    box = Sandbox(
        workspace,
        shell=shell,
        force_cmd=force_cmd,
        policy=policy or SandboxPolicy(),
        audit=audit,
    )
    box.prepare()
    _sandbox = box
    _install_tools(box)
    return box


def format_result(result: RunResult, title: str, box: Sandbox) -> str:
    return _format_core(result, title, box.workspace, box.policy)


def _build_description(box: Sandbox) -> str:
    if box.shell.kind == "bash":
        syntax = (
            "Shell: Git Bash (MSYS2) on Windows.\n"
            "- Chain commands with `&&`, `||`, `;`; use single quotes for literal text\n"
            "- Command substitution: `$(...)`\n"
            "- Use forward slashes for paths, e.g. `C:/path/to/file`\n"
        )
    else:
        syntax = (
            "Shell: cmd.exe on Windows.\n"
            "- Chain commands with `&&` or `&`; quote paths that contain spaces\n"
            "- Environment variables: `%NAME%`\n"
            "- Use backslashes for paths, e.g. `C:\\path\\to\\file`\n"
        )
    return (
        "Execute a command in a low-integrity sandbox on Windows.\n"
        "Returns command output with [stdout]/[stderr] markers.\n"
        "\n"
        "[SANDBOX]\n"
        f"Workspace (the only writable tree): {box.workspace}\n"
        "Processes run at Low integrity: writes outside the workspace are denied.\n"
        "The whole process tree is killed when the command times out.\n"
        "\n"
        "[USAGE]\n"
        "- Do not use `cd` inside the command; use the `workdir` parameter.\n"
        "- Default timeout: 120s (override via `timeout`).\n"
        "- Output capped; full output is saved to a file when larger.\n"
        "- Prefer read_file / write_file / edit_file / glob_file for file operations.\n"
        "\n"
        f"{syntax}"
    )


def _install_tools(box: Sandbox) -> None:
    description = _build_description(box)

    @register_tool("shell", description=description, parameters=SHELL_PARAMS)
    def shell(
        command: str,
        workdir: str = "",
        timeout: int = 120,
        description: str = "",
    ) -> str:
        result = box.run(command, workdir=workdir, timeout=timeout)
        return format_result(result, description.strip() or command[:60], box)

    @register_tool(
        "background_run",
        description=(
            "Run a command in the sandbox. wait=True waits for completion; "
            "wait=False returns a task id immediately for long-running services."
        ),
        parameters=BACKGROUND_RUN_PARAMS,
    )
    def background_run(command: str, wait: bool = True, workdir: str = "") -> str:
        if wait:
            result = box.run(command, workdir=workdir, timeout=600)
            return format_result(result, command[:60], box)
        task = box.start(command, workdir=workdir)
        return (
            f"后台任务 {task.id} 已启动: {command[:80]}\n"
            f'用 check_background(task_id="{task.id}") 查看输出，'
            "cancel_background 取消。"
        )

    @register_tool(
        "check_background",
        description="查看后台任务状态 / 尾部输出；task_id 留空列出所有任务。",
        parameters=CHECK_BACKGROUND_PARAMS,
    )
    def check_background(task_id: str | None = None) -> str:
        return box.check(task_id)

    @register_tool(
        "cancel_background",
        description="取消指定的后台任务（只杀这个任务的进程树）。",
        parameters=CANCEL_BACKGROUND_PARAMS,
    )
    def cancel_background(task_id: str) -> str:
        return box.cancel_task(task_id)
