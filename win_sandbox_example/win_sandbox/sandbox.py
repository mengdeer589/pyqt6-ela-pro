"""Sandbox 门面：前台命令 / 后台任务 / 取消 / 审计。

前台命令和后台任务用**不同的 Job**：

- ``run()`` 用当前前台 Job，``cancel_foreground()`` 只会杀它；
- ``start()`` 每个任务一个独立 Job，``cancel_task()`` 只杀指定任务；
- ``close()`` 才全部收掉。

这样 UI 的「停止」不会误杀正在跑的后台服务。
"""

from __future__ import annotations

import locale
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .approval import ApprovalDecision, ApprovalHandler, ApprovalRequest
from .audit import AuditLike, JsonlAudit, call_sink, command_digest, command_preview
from .errors import PolicyDenied
from .identity import BinaryIdentity, identify, verify as verify_identity
from .proc import (
    RunResult,
    SandboxLimits,
    SandboxProcess,
    clean_stderr,
    run_in_sandbox,
    sandbox_env,
    set_low_integrity_label,
    spawn,
)
from .services import Service
from .shells import Shell, detect_shell


class GuardMode(str, Enum):
    """audit：只记录不拦截；enforce：拦截并抛 ``PolicyDenied``。"""

    AUDIT = "audit"
    ENFORCE = "enforce"


class ApprovalMode(str, Enum):
    """deny：直接拒绝；ask：交给宿主审批回调。"""

    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class SandboxPolicy:
    """沙箱策略。默认值按「跑构建 / 测试」估的。"""

    low_integrity: bool = True
    max_processes: int = 64
    memory_mb: int = 2048
    default_timeout: float = 120.0
    max_output_bytes: int = 200_000
    tail_lines: int = 200
    tail_bytes: int = 60 * 1024
    label_recursive: bool = True
    guard_mode: GuardMode = GuardMode.ENFORCE
    approval_mode: ApprovalMode = ApprovalMode.DENY
    approval_rate_limit: int = 5
    retain_workspace: bool = True
    verify_binary: bool = True
    recheck_binary: bool = True
    strict_binary: bool = False
    max_task_output_bytes: int = 50 * 1024 * 1024


def _is_within(root: Path, path: Path) -> bool:
    root_text = os.path.normcase(str(root))
    path_text = os.path.normcase(str(path))
    return path_text == root_text or path_text.startswith(root_text + os.sep)


def _read_tail(path: Path, max_bytes: int, encoding: str) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode(encoding, errors="replace")
    except OSError:
        return ""


class SandboxTask:
    """一个后台任务：独立 Job + 独立输出文件。"""

    def __init__(
        self,
        task_id: str,
        command: str,
        process: SandboxProcess,
        stdout_path: Path,
        stderr_path: Path,
        started_at: float,
        policy: SandboxPolicy,
        label: str = "",
        on_output_limit: Callable[[SandboxTask], None] | None = None,
    ) -> None:
        self.id = task_id
        self.command = command
        self.process = process
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self.started_at = started_at
        self.label = label
        self._policy = policy
        self._on_output_limit = on_output_limit
        self._cancelled = False
        self._finished = False
        self._exit_code: int | None = None
        self._closed = False
        self._limit_hit = False
        self._monitor_stop = threading.Event()
        self._monitor: threading.Thread | None = None

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def output_bytes(self) -> int:
        total = 0
        for path in (self.stdout_path, self.stderr_path):
            try:
                total += path.stat().st_size
            except OSError:
                pass
        return total

    @property
    def output_limit_hit(self) -> bool:
        return self._limit_hit

    def start_monitor(self, max_bytes: int) -> None:
        if max_bytes <= 0:
            return
        self._monitor = threading.Thread(
            target=self._monitor_output,
            args=(max_bytes,),
            name=f"SandboxTask-{self.id}",
            daemon=True,
        )
        self._monitor.start()

    def _monitor_output(self, max_bytes: int) -> None:
        while not self._monitor_stop.wait(2.0):
            if self._finished or self._cancelled or self._closed:
                return
            if self.output_bytes() <= max_bytes:
                continue
            self._limit_hit = True
            self.cancel()
            if self._on_output_limit is not None:
                try:
                    self._on_output_limit(self)
                except Exception:
                    pass
            return

    def refresh(self) -> None:
        """刷新完成状态；完成时不关 Job（留给 close / TTL 清理）。"""
        if self._finished or self._cancelled or self._closed:
            return
        if self.process.active_processes() == 0:
            self._exit_code = self.process.exit_code()
            self._finished = True

    def status(self) -> str:
        if self._cancelled:
            return "cancelled"
        if self._closed and not self._finished:
            return "cancelled"
        self.refresh()
        if not self._finished:
            return "running"
        return "done" if self._exit_code == 0 else "failed"

    def exit_code(self) -> int | None:
        if self._finished:
            return self._exit_code
        if self._cancelled or self._closed:
            return None
        if self.process.active_processes() == 0:
            return self.process.exit_code()
        return None

    def tail(self, max_chars: int = 3000) -> str:
        """读 stdout/stderr 的尾部；运行中也安全（文件是共享读写的）。"""
        encoding = locale.getpreferredencoding(False)
        chunks: list[str] = []
        for index, path in enumerate((self.stdout_path, self.stderr_path)):
            text = _read_tail(path, self._policy.tail_bytes, encoding)
            if index == 1:
                text = clean_stderr(text)
            if text.strip():
                chunks.append(text.rstrip())
        text = "\n".join(chunks).strip()
        return text[-max_chars:] if max_chars and len(text) > max_chars else text

    def cancel(self) -> None:
        if self._cancelled or self._finished or self._closed:
            return
        self._monitor_stop.set()
        self.process.terminate()
        self._cancelled = True

    def close(self) -> None:
        if self._closed:
            return
        self._monitor_stop.set()
        if not self._cancelled and not self._finished:
            try:
                self.cancel()
            except Exception:
                pass
        self.process.close()
        self._closed = True


class Sandbox:
    """一个工作区 + 一个 shell + 一组前台/后台进程。"""

    def __init__(
        self,
        workspace: str | Path,
        *,
        shell: str | None = None,
        force_cmd: bool = False,
        prefer_bundled: bool = False,
        policy: SandboxPolicy | None = None,
        audit: AuditLike | None = None,
        approval: ApprovalHandler | None = None,
        identity_store: str | Path | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.policy = policy or SandboxPolicy()
        self.shell: Shell = detect_shell(shell, force_cmd, prefer_bundled)
        self._audit = audit
        if isinstance(self._audit, JsonlAudit) and _is_within(
            self.workspace, self._audit.path.resolve()
        ):
            raise RuntimeError(
                "audit.jsonl 不能放在沙箱工作区内："
                "低完整性子进程可以写工作区，会篡改审计"
            )
        self._approval = approval
        self._identity_store = (
            Path(identity_store)
            if identity_store is not None
            else self._default_identity_store()
        )
        self._env: dict[str, str] | None = None
        self._prepared = False
        self._closed = False
        self._lock = threading.Lock()
        self._identity_lock = threading.Lock()
        self._foreground: set[threading.Event] = set()
        self._tasks: dict[str, SandboxTask] = {}
        self._services: dict[str, Service] = {}
        self._approval_times: list[float] = []
        self.shell_identity: BinaryIdentity | None = None

    def _default_identity_store(self) -> Path:
        base = os.environ.get("LOCALAPPDATA") or str(self.workspace.parent)
        return Path(base) / "WinSandbox" / "shell_identity.json"

    # -- 生命周期 ---------------------------------------------------------

    def prepare(self) -> None:
        """建目录、打 Low 标签、构造子进程环境；可重复调用。"""
        if self._prepared:
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.policy.low_integrity:
            ok, detail = set_low_integrity_label(
                self.workspace, recursive=self.policy.label_recursive
            )
            if not ok:
                raise RuntimeError(f"无法给工作区打低完整性标签: {detail}")
        # 必须先打标签再建 .sandbox，子目录才能继承 Low。
        self._env = sandbox_env(self.workspace)
        if self.policy.verify_binary:
            self._verify_shell_binary()
        self._prepared = True
        self._emit(
            {
                "event": "prepare",
                "severity": "info",
                "workspace": str(self.workspace),
                "shell": self.shell.label,
                "low_integrity": self.policy.low_integrity,
                "guard_mode": self.policy.guard_mode.value,
                "shell_sha256": (
                    self.shell_identity.sha256 if self.shell_identity else None
                ),
            }
        )

    def _verify_shell_binary(self) -> None:
        try:
            identity = identify(Path(self.shell.argv[0]))
        except OSError as exc:
            self._emit(
                {
                    "event": "binary_identity",
                    "severity": "high" if self.policy.strict_binary else "medium",
                    "error": str(exc),
                }
            )
            if self.policy.strict_binary:
                raise RuntimeError(
                    f"无法读取 shell 可执行文件，拒绝启动: {exc}"
                ) from exc
            return
        self.shell_identity = identity
        try:
            changed, previous = verify_identity(self._identity_store, identity)
        except OSError as exc:
            self._emit(
                {
                    "event": "binary_identity",
                    "severity": "high" if self.policy.strict_binary else "medium",
                    "path": identity.path,
                    "error": str(exc),
                }
            )
            if self.policy.strict_binary:
                raise RuntimeError(f"无法写入 shell 身份基线，拒绝启动: {exc}") from exc
            return
        self._emit(
            {
                "event": "binary_identity",
                "severity": "high" if changed else "info",
                "path": identity.path,
                "sha256": identity.sha256,
                "changed": changed,
                "previous": previous,
            }
        )
        if changed and self.policy.strict_binary:
            raise RuntimeError(
                f"shell binary changed: {identity.path} "
                f"(previous {previous}, now {identity.sha256})"
            )

    def _recheck_shell_binary(self) -> None:
        """每条命令前校验一次；变化时审计 high，strict 模式直接拒绝。"""
        if not (self.policy.verify_binary and self.policy.recheck_binary):
            return
        try:
            identity = identify(Path(self.shell.argv[0]))
        except OSError as exc:
            self._emit(
                {
                    "event": "binary_identity",
                    "severity": "high" if self.policy.strict_binary else "medium",
                    "error": str(exc),
                }
            )
            if self.policy.strict_binary:
                raise RuntimeError(f"无法校验 shell: {exc}") from exc
            return
        with self._identity_lock:
            previous = self.shell_identity
            if previous is None:
                self.shell_identity = identity
                return
            if identity.sha256 == previous.sha256:
                return
            self.shell_identity = identity
        self._emit(
            {
                "event": "binary_identity",
                "severity": "high",
                "path": identity.path,
                "sha256": identity.sha256,
                "changed": True,
                "previous": previous.sha256,
            }
        )
        if self.policy.strict_binary:
            raise RuntimeError(
                f"shell binary changed: {identity.path} "
                f"(previous {previous.sha256}, now {identity.sha256})"
            )

    def close(self) -> None:
        if self._closed:
            return
        self.cancel_foreground()
        with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            task.close()
        with self._lock:
            self._services.clear()
        self._closed = True
        self._emit({"event": "close", "severity": "info"})
        if not self.policy.retain_workspace:
            shutil.rmtree(self.workspace, ignore_errors=True)

    # -- 路径 -------------------------------------------------------------

    def resolve(
        self,
        path: str | Path,
        *,
        tool: str = "file_tool",
        operation: str = "read",
    ) -> Path:
        """解析到工作区内的绝对路径；越界按策略拒绝 / 审计 / 审批。"""
        candidate = Path(path)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.workspace / candidate).resolve()
        )
        if _is_within(self.workspace, resolved):
            return resolved
        return self._handle_outside(tool, resolved, operation)

    def _handle_outside(self, tool: str, path: Path, operation: str) -> Path:
        suggestion = (
            f"Use a path under {self.workspace}, or ask the user to import the "
            "file into the sandbox workspace."
        )
        if self.policy.guard_mode is GuardMode.AUDIT:
            self._emit(
                {
                    "event": "deny",
                    "severity": "medium",
                    "tool": tool,
                    "path": str(path),
                    "operation": operation,
                    "reason": "outside_workspace",
                    "enforced": False,
                }
            )
            return path

        if self.policy.approval_mode is ApprovalMode.ASK and self._approval:
            if not self._allow_approval_request():
                self._emit(
                    {
                        "event": "approval_rate_limited",
                        "severity": "medium",
                        "tool": tool,
                        "path": str(path),
                        "operation": operation,
                    }
                )
                raise PolicyDenied(
                    tool,
                    str(path),
                    "too many approval requests",
                    "Wait a minute and retry, or move the file into the workspace.",
                )
            request = ApprovalRequest(
                tool=tool,
                path=str(path),
                operation=operation,
                reason="outside_workspace",
                suggestion=suggestion,
            )
            try:
                decision = self._approval(request)
            except Exception as exc:
                decision = ApprovalDecision(
                    approved=False, note=f"approval handler failed: {exc}"
                )
            if decision.approved:
                self._emit(
                    {
                        "event": "approval",
                        "severity": "info",
                        "tool": tool,
                        "path": str(path),
                        "operation": operation,
                    }
                )
                return path
            self._emit(
                {
                    "event": "deny",
                    "severity": "medium",
                    "tool": tool,
                    "path": str(path),
                    "operation": operation,
                    "reason": "user_denied",
                    "enforced": True,
                }
            )
            raise PolicyDenied(tool, str(path), "user denied access", suggestion)

        self._emit(
            {
                "event": "deny",
                "severity": "medium",
                "tool": tool,
                "path": str(path),
                "operation": operation,
                "reason": "outside_workspace",
                "enforced": True,
            }
        )
        raise PolicyDenied(tool, str(path), "outside the sandbox workspace", suggestion)

    def _allow_approval_request(self) -> bool:
        limit = self.policy.approval_rate_limit
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            self._approval_times = [
                stamp for stamp in self._approval_times if now - stamp < 60.0
            ]
            if len(self._approval_times) >= limit:
                return False
            self._approval_times.append(now)
        return True

    def resolve_workdir(self, value: str | Path, *, tool: str = "shell") -> Path:
        if not value:
            return self.workspace
        cwd = self.resolve(value, tool=tool, operation="execute")
        if not cwd.is_dir():
            raise ValueError(f"workdir does not exist: {value}")
        return cwd

    # -- 前台命令 ---------------------------------------------------------

    def run(
        self,
        command: str,
        *,
        workdir: str | Path = "",
        timeout: float | None = None,
    ) -> RunResult:
        """同步跑一条命令并等它结束；``cancel_foreground()`` 可以中止。"""
        self._ensure_ready()
        self._recheck_shell_binary()
        cwd = self.resolve_workdir(workdir)
        seconds = float(timeout if timeout is not None else self.policy.default_timeout)
        limits = SandboxLimits(
            max_processes=self.policy.max_processes,
            memory_mb=self.policy.memory_mb,
            timeout_s=seconds,
        )
        cancel_event = threading.Event()
        with self._lock:
            self._foreground.add(cancel_event)
        run_command, script = self._prepare_command(command)
        started = time.monotonic()
        try:
            result = run_in_sandbox(
                run_command,
                shell=list(self.shell.argv),
                workdir=cwd,
                env=self._env_block(),
                limits=limits,
                low_integrity=self.policy.low_integrity,
                max_output_bytes=self.policy.max_output_bytes,
                cancel_event=cancel_event,
            )
        finally:
            with self._lock:
                self._foreground.discard(cancel_event)
            if script is not None:
                script.unlink(missing_ok=True)
        self._emit(
            {
                "event": "run",
                "severity": "info",
                "tool": "shell",
                "command_preview": command_preview(command),
                "command_sha256": command_digest(command),
                "workdir": str(cwd),
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "cancelled": result.cancelled,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
        return result

    def cancel_foreground(self) -> int:
        """中止正在跑的前台命令（UI 停止按钮），返回命中的命令数。"""
        with self._lock:
            events = list(self._foreground)
        for event in events:
            event.set()
        return len(events)

    # -- 后台任务 ---------------------------------------------------------

    def start(
        self, command: str, *, workdir: str | Path = "", label: str = ""
    ) -> SandboxTask:
        """启动一个独立 Job 的后台任务，立即返回。"""
        self._ensure_ready()
        self._recheck_shell_binary()
        cwd = self.resolve_workdir(workdir, tool="background_run")
        task_id = uuid.uuid4().hex[:8]
        task_dir = self.workspace / ".sandbox" / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        run_command, _ = self._prepare_command(command)
        process = spawn(
            [*self.shell.argv, run_command],
            workdir=cwd,
            env=self._env_block(),
            stdout_path=task_dir / "stdout.txt",
            stderr_path=task_dir / "stderr.txt",
            limits=SandboxLimits(
                max_processes=self.policy.max_processes,
                memory_mb=self.policy.memory_mb,
                timeout_s=0.0,
            ),
            low_integrity=self.policy.low_integrity,
        )
        task = SandboxTask(
            task_id=task_id,
            command=command,
            process=process,
            stdout_path=task_dir / "stdout.txt",
            stderr_path=task_dir / "stderr.txt",
            started_at=time.monotonic(),
            policy=self.policy,
            label=label,
            on_output_limit=lambda item: self._emit(
                {
                    "event": "output_limit",
                    "severity": "medium",
                    "task_id": item.id,
                    "bytes": item.output_bytes(),
                    "limit": self.policy.max_task_output_bytes,
                }
            ),
        )
        task.start_monitor(self.policy.max_task_output_bytes)
        with self._lock:
            self._tasks[task_id] = task
        self._emit(
            {
                "event": "start",
                "severity": "info",
                "tool": "background_run",
                "task_id": task_id,
                "command_preview": command_preview(command),
                "command_sha256": command_digest(command),
                "pid": process.pid,
            }
        )
        return task

    def tasks(self) -> list[SandboxTask]:
        with self._lock:
            return list(self._tasks.values())

    def check(self, task_id: str | None = None) -> str:
        """返回任务状态 + 尾部输出；``task_id=None`` 时列出全部。"""
        with self._lock:
            tasks = list(self._tasks.values())
            selected = self._tasks.get(task_id) if task_id else None
        if task_id is None:
            if not tasks:
                return "没有后台任务"
            return "\n".join(
                f"{task.id}: {task.status()} ({task.elapsed_s():.0f}s) "
                f"{task.command[:60]}"
                for task in tasks
            )
        if selected is None:
            return f"任务不存在: {task_id}"
        status = selected.status()
        text = f"任务 {selected.id}: {status} ({selected.elapsed_s():.0f}s)"
        code = selected.exit_code()
        if code is not None and status != "running":
            text += f" exit={code}"
        tail = selected.tail()
        if tail:
            text += f"\n最近输出:\n{tail}"
        return text

    def cancel_task(self, task_id: str) -> str:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return f"任务不存在: {task_id}"
        status = task.status()
        if status != "running":
            return f"任务 {task_id} 已结束 ({status})"
        task.cancel()
        self._prune_services()
        self._emit({"event": "cancel", "severity": "info", "task_id": task_id})
        return f"任务 {task_id} 已取消"

    # -- 服务暴露 ---------------------------------------------------------

    def expose(self, task_id: str, port: int, name: str = "") -> Service:
        """登记一个后台任务监听的本地端口；返回可点的 URL。"""
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"任务不存在: {task_id}")
        if task.status() != "running":
            raise RuntimeError(f"任务 {task_id} 未在运行")
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError(f"invalid port: {port}")
        service = Service(
            task_id=task_id,
            port=port,
            name=name or f"service-{port}",
        )
        with self._lock:
            self._services[service.id] = service
        self._emit(
            {
                "event": "service_expose",
                "severity": "info",
                "service_id": service.id,
                "task_id": task_id,
                "port": service.port,
                "url": service.url,
            }
        )
        return service

    def services(self) -> list[Service]:
        self._prune_services()
        with self._lock:
            return list(self._services.values())

    def unexpose(self, service_id: str) -> bool:
        with self._lock:
            service = self._services.pop(service_id, None)
        if service is not None:
            self._emit(
                {
                    "event": "service_unexpose",
                    "severity": "info",
                    "service_id": service_id,
                }
            )
            return True
        return False

    def _prune_services(self) -> None:
        """任务结束 / 被取消后，对应 URL 立即失效。"""
        with self._lock:
            tasks = dict(self._tasks)
            stale = [
                service_id
                for service_id, service in self._services.items()
                if tasks.get(service.task_id) is None
                or tasks[service.task_id].status() != "running"
            ]
            for service_id in stale:
                self._services.pop(service_id, None)

    # -- 审计 -------------------------------------------------------------

    def emit(self, event: dict) -> None:
        """给适配层用的公开审计入口。"""
        self._emit(event)

    @contextmanager
    def tool_scope(self, tool: str, **fields):
        """包住一次文件类工具调用，自动发 ``tool_start`` / ``tool_end``。"""
        record = {"tool": tool, **fields}
        self._emit({"event": "tool_start", "severity": "info", **record})
        try:
            yield record
        except Exception as exc:
            self._emit(
                {
                    "event": "tool_error",
                    "severity": "medium",
                    **record,
                    "error": type(exc).__name__,
                    "message": str(exc)[:200],
                }
            )
            raise
        else:
            self._emit({"event": "tool_end", "severity": "info", **record})

    # -- 内部 -------------------------------------------------------------

    def _ensure_ready(self) -> None:
        if not self._prepared:
            raise RuntimeError("Sandbox.prepare() 必须先调用")
        if self._closed:
            raise RuntimeError("Sandbox 已关闭")

    def _env_block(self) -> dict[str, str]:
        if self._env is None:
            raise RuntimeError("Sandbox.prepare() 必须先调用")
        return self._env

    def _prepare_command(self, command: str) -> tuple[str, Path | None]:
        """cmd 下把命令写进 .bat：命令行里嵌套引号会被 cmd 解析坏。"""
        if self.shell.kind != "cmd":
            return command, None
        script = self.workspace / ".sandbox" / f"cmd_{uuid.uuid4().hex[:8]}.bat"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "@echo off\r\n" + command + "\r\n", encoding="mbcs", errors="replace"
        )
        return str(script), script

    def _emit(self, event: dict) -> None:
        call_sink(self._audit, {"ts": time.time(), **event})
