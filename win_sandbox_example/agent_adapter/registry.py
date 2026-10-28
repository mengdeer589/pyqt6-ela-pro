"""极简装饰器工具注册表 —— 只是用来演示适配层。

换成你自己 agent 的 ``@register_tool`` 即可；``tools.py`` 里四个函数的
逻辑（调用哪个 Sandbox 方法、返回什么文本）不用改。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]


TOOLS: dict[str, ToolSpec] = {}


def register_tool(
    name: str, *, description: str, parameters: dict[str, Any]
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        TOOLS[name] = ToolSpec(name, description, parameters, func)
        return func

    return decorator


def call_tool(name: str, **kwargs: Any) -> Any:
    spec = TOOLS.get(name)
    if spec is None:
        raise KeyError(f"unknown tool: {name}")
    return spec.func(**kwargs)


def tool_names() -> list[str]:
    return sorted(TOOLS)
