"""agent_chat 的具体接入示例（你的项目替换 import 即可）。

在 ``start_main.py`` 里、``create_async_agent`` **之前**调用：

.. code-block:: python

    from integrations.agent_chat_example import install_for_agent_chat

    sandbox, enabled = install_for_agent_chat()
    agent = create_async_agent(enabled_tools=enabled, ...)

``enabled`` 是完整 build 工具集（含沙箱版 ``shell`` / ``background_*``）。
"""

from __future__ import annotations

from pathlib import Path

from app.agents import ToolManager, get_registered_tools, set_tool_mode
from app.agents.tool_registry import get_work_dir
from app.agents.tools import file_tools, grep_tool

from integrations.toolmanager import install

DEFAULT_SANDBOX_WORKSPACE = Path.cwd() / "runtime" / "agent_workspace"


def install_for_agent_chat(
    workspace: str | Path | None = None,
    *,
    audit=None,
    approval=None,
    policy=None,
    prefer_bundled: bool = True,
) -> tuple[object, set[str]]:
    box = install(
        workspace or DEFAULT_SANDBOX_WORKSPACE,
        tool_manager=ToolManager,
        set_tool_mode=set_tool_mode,
        file_tools=file_tools,
        grep_tool=grep_tool,
        get_work_dir=get_work_dir,
        audit=audit,
        approval=approval,
        policy=policy,
        prefer_bundled=prefer_bundled,
    )
    return box, get_registered_tools("build")
