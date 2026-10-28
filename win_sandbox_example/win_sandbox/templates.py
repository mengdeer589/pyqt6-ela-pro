"""沙箱模板 + 保留 / 一次性工作区。

模板就是一组 ``SandboxPolicy`` + 工作区子目录 + shell 选择；没有 YAML，
直接用 dataclass，宿主可以自己注册。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import Sandbox, SandboxPolicy


@dataclass(frozen=True)
class SandboxTemplate:
    name: str
    description: str
    workspace_subdir: str
    policy: SandboxPolicy = field(default_factory=SandboxPolicy)
    shell: str | None = None
    force_cmd: bool = False
    import_gitignore: bool = True


_BUILTINS: dict[str, SandboxTemplate] = {
    "generic": SandboxTemplate(
        name="generic",
        description="通用工作区：默认超时 / 内存，保留文件",
        workspace_subdir="workspace",
    ),
    "python": SandboxTemplate(
        name="python",
        description="Python 项目：更长超时 / 更大内存",
        workspace_subdir="python",
        policy=SandboxPolicy(default_timeout=180.0, memory_mb=4096),
    ),
    "node": SandboxTemplate(
        name="node",
        description="Node 项目：更长超时 / 更大内存",
        workspace_subdir="node",
        policy=SandboxPolicy(default_timeout=180.0, memory_mb=4096),
    ),
    "ephemeral": SandboxTemplate(
        name="ephemeral",
        description="一次性工作区：close() 时删除",
        workspace_subdir="scratch",
        policy=SandboxPolicy(retain_workspace=False),
    ),
}

_REGISTRY: dict[str, SandboxTemplate] = dict(_BUILTINS)


def register_template(template: SandboxTemplate) -> None:
    _REGISTRY[template.name] = template


def get_template(name: str) -> SandboxTemplate:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(
            f"unknown template: {name}; available: {', '.join(sorted(_REGISTRY))}"
        ) from exc


def list_templates() -> list[SandboxTemplate]:
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def create_sandbox(
    root: str | Path,
    template: str | SandboxTemplate,
    *,
    audit=None,
    approval=None,
    identity_store: str | Path | None = None,
) -> Sandbox:
    """按模板创建并 ``prepare()`` 一个 Sandbox。"""
    selected = get_template(template) if isinstance(template, str) else template
    workspace = Path(root).expanduser().resolve() / selected.workspace_subdir
    box = Sandbox(
        workspace,
        shell=selected.shell,
        force_cmd=selected.force_cmd,
        policy=selected.policy,
        audit=audit,
        approval=approval,
        identity_store=identity_store,
    )
    box.prepare()
    return box
