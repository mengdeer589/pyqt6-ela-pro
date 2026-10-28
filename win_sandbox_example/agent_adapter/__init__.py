"""适配层示例：极简注册表 + 沙箱工具 + 文件工具收口。"""

from .file_guard import install_file_tools
from .registry import TOOLS, call_tool, register_tool, tool_names
from .tools import format_result, install_sandbox, sandbox

__all__ = [
    "TOOLS",
    "call_tool",
    "format_result",
    "install_file_tools",
    "install_sandbox",
    "register_tool",
    "sandbox",
    "tool_names",
]
