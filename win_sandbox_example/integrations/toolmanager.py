"""适配 ``@ToolManager.register`` 风格的 agent（agent_chat / llm_test 同源）。

你的 agent 里这样接：

.. code-block:: python

    from app.agents import ToolManager, set_tool_mode
    from app.agents.tools import file_tools
    from integrations.toolmanager import install

    box = install(
        workspace,
        tool_manager=ToolManager,
        set_tool_mode=set_tool_mode,
        file_tools=file_tools,
    )
    enabled = get_registered_tools("build")

停止按钮：``box.cancel_foreground()``；退出：``box.close()``。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from win_sandbox import Sandbox, SandboxPolicy, format_result


def install(
    workspace: str | Path,
    *,
    tool_manager: Any,
    set_tool_mode: Any,
    file_tools: Any | None = None,
    grep_tool: Any | None = None,
    get_work_dir: Any | None = None,
    shell: str | None = None,
    force_cmd: bool = False,
    prefer_bundled: bool = False,
    policy: SandboxPolicy | None = None,
    audit=None,
    approval=None,
    contain_file_tools: bool = True,
) -> Sandbox:
    """创建 Sandbox、打 Low 标签、覆盖注册执行工具 + 收口文件类工具。

    :param workspace: 专用 agent 工作区（唯一可写目录）。
    :param tool_manager: ``ToolManager`` 类（提供 ``register``）。
    :param set_tool_mode: ``set_tool_mode(name, modes)``。
    :param file_tools: ``file_tools`` 模块；给了就收口
        ``read_file`` / ``write_file`` / ``edit_file`` / ``glob_file`` /
        ``read_image``。
    :param grep_tool: ``grep_tool`` 模块；给了就收口 ``grep_file``。
    :param get_work_dir: ``tool_registry.get_work_dir``；给了就让相对路径跟随
        当前话题目录（仍必须落在 ``workspace`` 内）。
    :param shell: 显式 bash 路径；``None`` 自动查找，找不到退回 cmd.exe。
    :param force_cmd: 强制 cmd.exe。
    :param policy: 资源 / 超时 / 输出上限 / guard / approval 模式。
    :param audit: ``JsonlAudit`` 或 ``callable(event: dict)``。
    :param approval: ``ApprovalHandler``（配合 ``ApprovalMode.ASK``）。
    :param contain_file_tools: 是否收口文件类工具。
    """
    box = Sandbox(
        workspace,
        shell=shell,
        force_cmd=force_cmd,
        prefer_bundled=prefer_bundled,
        policy=policy or SandboxPolicy(),
        audit=audit,
        approval=approval,
    )
    box.prepare()
    _register_tools(box, tool_manager, set_tool_mode, get_work_dir)
    if contain_file_tools and (file_tools is not None or grep_tool is not None):
        _guard_read_tools(
            box, tool_manager, set_tool_mode, file_tools, grep_tool, get_work_dir
        )
    return box


def _is_within(root: Path, path: Path) -> bool:
    root_text = os.path.normcase(str(root))
    path_text = os.path.normcase(str(path))
    return path_text == root_text or path_text.startswith(root_text + os.sep)


def _current_workdir(box: Sandbox, get_work_dir: Any | None) -> Path:
    """当前话题目录；不在沙箱内（旧话题）就退回工作区根。

    这里刻意不走 ``box.resolve`` —— 旧话题目录是宿主配置问题，不应该
    触发审批弹框。
    """
    if get_work_dir is None:
        return box.workspace
    try:
        cwd = Path(get_work_dir()).resolve()
    except Exception:
        return box.workspace
    return cwd if _is_within(box.workspace, cwd) else box.workspace


def _register_tools(
    box: Sandbox,
    tool_manager: Any,
    set_tool_mode: Any,
    get_work_dir: Any | None,
) -> None:
    description = _build_description(box)

    @tool_manager.register(name="shell", description=description)
    def shell(
        command: Annotated[str, "要执行的命令"],
        workdir: Annotated[str, "工作目录（相对沙箱工作区），留空=当前话题目录"] = "",
        timeout: Annotated[int, "超时秒数"] = 120,
        description: Annotated[str, "命令说明（5-10字）"] = "",
    ) -> str:
        cwd = workdir or _current_workdir(box, get_work_dir)
        result = box.run(command, workdir=cwd, timeout=timeout)
        return format_result(
            result, description.strip() or command[:60], box.workspace, box.policy
        )

    @tool_manager.register(
        name="background_run",
        description=(
            "Run a command in the sandbox. wait=True waits for completion; "
            "wait=False returns a task id immediately for long-running services."
        ),
    )
    def background_run(
        command: Annotated[str, "要执行的命令"],
        wait: Annotated[
            bool, "True=等完成返回输出；False=立即返回任务 id（长驻服务用）"
        ] = True,
        workdir: Annotated[str, "工作目录（相对沙箱工作区），留空=当前话题目录"] = "",
    ) -> str:
        cwd = workdir or _current_workdir(box, get_work_dir)
        if wait:
            result = box.run(command, workdir=cwd, timeout=600)
            return format_result(result, command[:60], box.workspace, box.policy)
        task = box.start(command, workdir=cwd)
        return (
            f"后台任务 {task.id} 已启动: {command[:80]}\n"
            f'用 check_background(task_id="{task.id}") 查看输出，'
            "cancel_background 取消。"
        )

    @tool_manager.register(
        name="check_background",
        description="查看后台任务状态 / 尾部输出；task_id 留空列出所有任务。",
    )
    def check_background(
        task_id: Annotated[str | None, "任务 id；留空列出所有任务"] = None,
    ) -> str:
        return box.check(task_id)

    @tool_manager.register(
        name="cancel_background",
        description="取消指定的后台任务（只杀这个任务的进程树）。",
    )
    def cancel_background(
        task_id: Annotated[str, "要取消的任务 id"],
    ) -> str:
        return box.cancel_task(task_id)

    set_tool_mode("shell", ["build"])
    set_tool_mode("background_run", ["build"])
    set_tool_mode("cancel_background", ["build"])
    set_tool_mode("check_background", ["plan", "build"])


def _guard_read_tools(
    box: Sandbox,
    tool_manager: Any,
    set_tool_mode: Any,
    file_tools: Any | None,
    grep_tool: Any | None,
    get_work_dir: Any | None,
) -> None:
    """收口并审计文件类工具。

    ``read_file`` / ``write_file`` / ``edit_file`` / ``glob_file`` /
    ``read_image`` / ``grep_file`` 都换成同名覆盖，路径先过 ``box.resolve``，
    每次调用发 ``tool_start`` / ``tool_end`` 审计事件。
    """
    if file_tools is not None:
        _register_file_tools(box, tool_manager, set_tool_mode, file_tools, get_work_dir)
        _register_glob_file(box, tool_manager, get_work_dir)
        _register_read_image(box, tool_manager, file_tools, get_work_dir)
    if grep_tool is not None:
        _register_grep_file(box, tool_manager, grep_tool, get_work_dir)
    for name in ("glob_file", "read_image", "grep_file"):
        set_tool_mode(name, ["plan", "build"])


def _register_file_tools(
    box: Sandbox,
    tool_manager: Any,
    set_tool_mode: Any,
    file_tools: Any,
    get_work_dir: Any | None,
) -> None:
    def target_for(path: str, tool: str, operation: str) -> Path:
        candidate = Path(path)
        return box.resolve(
            candidate
            if candidate.is_absolute()
            else _current_workdir(box, get_work_dir) / candidate,
            tool=tool,
            operation=operation,
        )

    @tool_manager.register(
        name="read_file", description="读取沙箱工作区内的文件，带行号。"
    )
    def read_file(
        path: Annotated[str, "文件路径（相对当前目录或绝对路径）"],
        offset: Annotated[int, "起始行号（1-indexed，0=开头）"] = 0,
        limit: Annotated[int, "最多返回行数"] = 200,
    ) -> str:
        target = target_for(path, "read_file", "read")
        with box.tool_scope("read_file", path=str(target)):
            return file_tools.read_file(str(target), offset, limit)

    @tool_manager.register(
        name="write_file", description="写入沙箱工作区内的文件（覆盖）。"
    )
    def write_file(
        path: Annotated[str, "文件路径（相对当前目录或绝对路径）"],
        content: Annotated[str, "文件内容"],
    ) -> str:
        target = target_for(path, "write_file", "write")
        with box.tool_scope("write_file", path=str(target)):
            return file_tools.write_file(str(target), content)

    @tool_manager.register(
        name="edit_file",
        description="替换沙箱工作区内文件的一段文本（old_string 必须唯一）。",
    )
    def edit_file(
        path: Annotated[str, "文件路径（相对当前目录或绝对路径）"],
        old_string: Annotated[str, "被替换的文本（必须唯一）"],
        new_string: Annotated[str, "替换后的文本"],
    ) -> str:
        target = target_for(path, "edit_file", "write")
        with box.tool_scope("edit_file", path=str(target)):
            return file_tools.edit_file(str(target), old_string, new_string)

    set_tool_mode("read_file", ["plan", "build"])
    set_tool_mode("write_file", ["build"])
    set_tool_mode("edit_file", ["build"])


def _register_glob_file(
    box: Sandbox, tool_manager: Any, get_work_dir: Any | None
) -> None:
    @tool_manager.register(
        name="glob_file",
        description="按 glob 查找沙箱工作区内的文件（只接受相对 pattern）。",
    )
    def glob_file(
        pattern: Annotated[str, "相对当前目录的 glob，如 **/*.py"],
        limit: Annotated[int, "结果数量上限"] = 50,
    ) -> str:
        if Path(pattern).is_absolute():
            return "Error: absolute patterns are not allowed in the sandbox"
        if ".." in Path(pattern).parts:
            return "Error: '..' is not allowed in glob patterns"
        base = _current_workdir(box, get_work_dir)
        try:
            with box.tool_scope("glob_file", pattern=pattern):
                matches = sorted(
                    (item for item in base.rglob(pattern) if item.is_file()),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
                if not matches:
                    return f"无匹配: {pattern}"
                shown = matches[: max(1, limit)]
                result = "\n".join(str(item.relative_to(base)) for item in shown)
                if len(matches) > len(shown):
                    result += f"\n... 还有 {len(matches) - len(shown)} 个文件"
                return result
        except (OSError, ValueError) as exc:
            return f"Error: glob failed: {exc}"


def _register_read_image(
    box: Sandbox,
    tool_manager: Any,
    file_tools: Any,
    get_work_dir: Any | None,
) -> None:
    @tool_manager.register(
        name="read_image",
        description="读取沙箱工作区内的图片并发送给模型。",
    )
    def read_image(
        path: Annotated[str, "图片路径（相对当前目录或绝对路径）"],
    ) -> object:
        candidate = Path(path)
        target = box.resolve(
            candidate
            if candidate.is_absolute()
            else _current_workdir(box, get_work_dir) / candidate,
            tool="read_image",
            operation="read",
        )
        with box.tool_scope("read_image", path=str(target)):
            return file_tools.read_image(str(target))


def _register_grep_file(
    box: Sandbox,
    tool_manager: Any,
    grep_tool: Any,
    get_work_dir: Any | None,
) -> None:
    @tool_manager.register(
        name="grep_file",
        description="在工作区内做内容搜索（ripgrep），路径必须在沙箱内。",
    )
    def grep_file(
        pattern: Annotated[str, "正则表达式，如 lazy|LazyFrame"],
        path: Annotated[str, "搜索目录（相对当前目录），留空=当前话题目录"] = "",
        include: Annotated[str, "文件 glob 过滤，逗号分隔"] = "",
        context: Annotated[int, "匹配行前后额外行数"] = 0,
    ) -> str:
        base = _current_workdir(box, get_work_dir)
        if path:
            candidate = Path(path)
            target = box.resolve(
                candidate if candidate.is_absolute() else base / candidate,
                tool="grep_file",
                operation="read",
            )
        else:
            target = base
        if not target.is_dir():
            return f"Error: not a directory: {target}"
        with box.tool_scope("grep_file", pattern=pattern, path=str(target)):
            return grep_tool.grep_file(pattern, str(target), include, context)


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
