"""把 ``win_sandbox`` 接到具体 agent 框架的适配层。

- ``toolmanager``：``@ToolManager.register`` 风格（agent_chat / llm_test 同源）。
- ``agent_chat_example``：agent_chat 的具体 import 路径示例，不自动导入。
"""

from .toolmanager import install

__all__ = ["install"]
