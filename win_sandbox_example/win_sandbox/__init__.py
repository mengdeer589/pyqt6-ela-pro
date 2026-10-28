"""Win7 免管理员沙箱：低完整性令牌 + Job Object + 工作区低完整性标签。

核不依赖任何 agent 框架，只依赖标准库与 ctypes。适配你自己的 agent 时，
只需要把 ``Sandbox.run()`` / ``start()`` / ``check()`` / ``cancel_task()``
包进你的工具注册器。
"""

from .approval import ApprovalDecision, ApprovalHandler, ApprovalRequest
from .audit import (
    AuditLike,
    JsonlAudit,
    command_digest,
    command_preview,
    read_events,
)
from .errors import PolicyDenied
from .format import format_result
from .identity import BinaryIdentity, identify, verify as verify_identity
from .import_workspace import ImportResult, import_tree
from .proc import (
    INTEGRITY_HIGH,
    INTEGRITY_LOW,
    INTEGRITY_MEDIUM,
    INTEGRITY_SYSTEM,
    INTEGRITY_UNTRUSTED,
    RunResult,
    SandboxLimits,
    SandboxProcess,
    clean_stderr,
    current_integrity,
    integrity_name,
    is_user_admin,
    process_in_job,
    run_in_sandbox,
    sandbox_env,
    set_low_integrity_label,
    spawn,
)
from .sandbox import (
    ApprovalMode,
    GuardMode,
    Sandbox,
    SandboxPolicy,
    SandboxTask,
)
from .services import Service, port_open
from .shells import Shell, detect_shell, find_bash
from .templates import (
    SandboxTemplate,
    create_sandbox,
    get_template,
    list_templates,
    register_template,
)

__all__ = [
    "INTEGRITY_HIGH",
    "INTEGRITY_LOW",
    "INTEGRITY_MEDIUM",
    "INTEGRITY_SYSTEM",
    "INTEGRITY_UNTRUSTED",
    "ApprovalDecision",
    "ApprovalHandler",
    "ApprovalMode",
    "ApprovalRequest",
    "AuditLike",
    "BinaryIdentity",
    "GuardMode",
    "ImportResult",
    "JsonlAudit",
    "PolicyDenied",
    "RunResult",
    "Sandbox",
    "SandboxLimits",
    "SandboxPolicy",
    "SandboxProcess",
    "SandboxTask",
    "SandboxTemplate",
    "Service",
    "Shell",
    "clean_stderr",
    "command_digest",
    "command_preview",
    "create_sandbox",
    "current_integrity",
    "detect_shell",
    "find_bash",
    "format_result",
    "get_template",
    "identify",
    "import_tree",
    "integrity_name",
    "is_user_admin",
    "list_templates",
    "port_open",
    "process_in_job",
    "read_events",
    "register_template",
    "run_in_sandbox",
    "sandbox_env",
    "set_low_integrity_label",
    "spawn",
    "verify_identity",
]
