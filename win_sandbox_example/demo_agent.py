"""脚本化「agent 工具调用序列」：不接 LLM，直接走注册表。

它演示的是适配层被调用的方式：``call_tool("shell", ...)`` /
``call_tool("background_run", ...)``，与真实 agent 收到 tool_call 后做的
事情完全一致。
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path

from agent_adapter import call_tool, install_file_tools, install_sandbox, tool_names


def default_workspace() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "WinSandboxDemo" / "agent_workspace"


def main() -> int:
    box = install_sandbox(default_workspace())
    install_file_tools(box)
    print(f"workspace: {box.workspace}")
    print(f"shell    : {box.shell.label}")
    print(f"tools    : {tool_names()}")

    print("\n== shell ==")
    print(
        call_tool("shell", command="echo from-shell > shell.txt", description="写文件")
    )

    print("\n== write_file ==")
    print(call_tool("write_file", path="from-tool.txt", content="from tool"))

    print("\n== write_file 越界（应失败） ==")
    blocked = Path.home() / "win_sandbox_agent_blocked.txt"
    blocked.unlink(missing_ok=True)
    try:
        call_tool("write_file", path=str(blocked), content="bad")
    except Exception as exc:
        print(f"blocked: {type(exc).__name__}: {exc}")
    print(f"blocked file exists: {blocked.exists()}")
    blocked.unlink(missing_ok=True)

    print("\n== background_run(wait=False) ==")
    command = "sleep 60" if box.shell.kind == "bash" else "ping -n 60 127.0.0.1 >nul"
    output = call_tool("background_run", command=command, wait=False)
    print(output)
    match = re.search(r"([0-9a-f]{8})", output)
    if match:
        task_id = match.group(1)
        time.sleep(1.0)
        print("\n== check_background ==")
        print(call_tool("check_background", task_id=task_id))
        print("\n== cancel_background ==")
        print(call_tool("cancel_background", task_id=task_id))
        time.sleep(0.3)
        print("\n== check_background (after cancel) ==")
        print(call_tool("check_background", task_id=task_id))

    box.close()
    print("\nclosed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
