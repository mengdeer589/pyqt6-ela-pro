"""Win7 免管理员沙箱能力探测（spike）。

默认自动选 shell：有 Git Bash 就用，没有就退回 `cmd.exe`（Win7 自带）。
沙箱原语本身不依赖 bash。

::

    python -m llm_test.local_sandbox.probe
    python -m llm_test.local_sandbox.probe --bash "C:/Program Files/Git/bin/bash.exe"
    python -m llm_test.local_sandbox.probe --keep

只读系统状态、只改自己创建的临时目录；不碰注册表、不装服务、不需要管理员。
"""

from __future__ import annotations

import argparse
import platform
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

from .proc import (
    INTEGRITY_LOW,
    RunResult,
    SandboxLimits,
    current_integrity,
    integrity_name,
    is_user_admin,
    process_in_job,
    run_in_sandbox,
    sandbox_env,
    set_low_integrity_label,
    spawn,
)
from .shells import detect_shell

_LIMITS = SandboxLimits(max_processes=32, memory_mb=1024, timeout_s=30.0)


def _print_environment(shell_label: str) -> None:
    # 控制台输出用英文：Win7 中文控制台是 GBK，英文标签不受代码页影响。
    print("== Environment ==")
    print(f"  OS              : {platform.platform()}")
    print(f"  Python          : {sys.version.split()[0]}")
    print(f"  Admin           : {'yes' if is_user_admin() else 'no'}")
    print(
        "  Parent in job   : "
        + ("yes (Win7 cannot nest jobs)" if process_in_job() else "no")
    )
    print(f"  Host integrity  : {integrity_name(current_integrity())}")
    print(f"  shell           : {shell_label}")


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _report(name: str, ok: bool, detail: str) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    return ok


def _script_path(workspace: Path) -> Path:
    return workspace / ".sandbox" / f"probe_{uuid.uuid4().hex[:8]}.bat"


def _run_lines(
    shell: Sequence[str],
    kind: str,
    workspace: Path,
    env: dict[str, str],
    lines: list[str],
    *,
    low_integrity: bool,
) -> RunResult:
    """cmd 下把命令写进 .bat（避免命令行引号地狱），bash 下直接用 ; 连接。"""
    if kind == "cmd":
        script = _script_path(workspace)
        script.write_text(
            "@echo off\r\n" + "\r\n".join(lines) + "\r\n", encoding="mbcs"
        )
        command = str(script)
    else:
        command = "; ".join(lines)
    return run_in_sandbox(
        command,
        shell=shell,
        workdir=workspace,
        env=env,
        limits=_LIMITS,
        low_integrity=low_integrity,
    )


def _write_lines(kind: str, workspace_file: str, target: Path) -> list[str]:
    quoted = str(target) if kind == "cmd" else target.as_posix()
    return [f"echo ok > {workspace_file}", f'echo bad > "{quoted}"']


def _test_label(workspace: Path) -> bool:
    ok, detail = set_low_integrity_label(workspace)
    return _report("low-integrity label on workspace", ok, "rc=0" if ok else detail)


def _test_baseline(
    shell: Sequence[str],
    kind: str,
    workspace: Path,
    env: dict[str, str],
    parent_integrity: int,
) -> bool:
    """对照组：不降完整性时，工作区和用户目录都应该可写。"""
    control = Path.home() / "elaw_sandbox_probe_control.txt"
    _unlink(control)
    result = _run_lines(
        shell,
        kind,
        workspace,
        env,
        _write_lines(kind, "work_base.txt", control),
        low_integrity=False,
    )
    wrote_workspace = (workspace / "work_base.txt").is_file()
    wrote_profile = control.is_file()
    _unlink(control)
    ok = (
        wrote_workspace and wrote_profile and result.child_integrity == parent_integrity
    )
    detail = (
        f"child={integrity_name(result.child_integrity)}"
        f" workspace={'writable' if wrote_workspace else 'denied'}"
        f" profile={'writable' if wrote_profile else 'denied'}"
    )
    return _report("control (no downgrade)", ok, detail)


def _test_low_integrity(
    shell: Sequence[str], kind: str, workspace: Path, env: dict[str, str]
) -> bool:
    """低完整性时：工作区（已打 Low 标签）可写，用户目录必须被拒绝。"""
    blocked = Path.home() / "elaw_sandbox_probe_blocked.txt"
    _unlink(blocked)
    result = _run_lines(
        shell,
        kind,
        workspace,
        env,
        _write_lines(kind, "work_low.txt", blocked),
        low_integrity=True,
    )
    wrote_workspace = (workspace / "work_low.txt").is_file()
    bypassed = blocked.is_file()
    _unlink(blocked)
    ok = result.child_integrity == INTEGRITY_LOW and wrote_workspace and not bypassed
    detail = (
        f"child={integrity_name(result.child_integrity)}"
        f" workspace={'writable' if wrote_workspace else 'denied'}"
        f" profile={'writable (leak!)' if bypassed else 'denied as expected'}"
    )
    return _report("low-integrity write containment", ok, detail)


def _test_job(
    shell: Sequence[str], kind: str, workspace: Path, env: dict[str, str]
) -> bool:
    """Job 必须收住整棵进程树：TerminateJobObject 之后活动进程归零。"""
    if kind == "cmd":
        script = _script_path(workspace)
        script.write_text(
            "@echo off\r\nping -n 30 127.0.0.1 >nul\r\nping -n 30 127.0.0.1 >nul\r\n",
            encoding="mbcs",
        )
        argv = [*shell, str(script)]
    else:
        argv = [*shell, "sleep 30 & sleep 30"]

    stdout_path = workspace / ".sandbox" / "job_stdout.txt"
    stderr_path = workspace / ".sandbox" / "job_stderr.txt"
    process = spawn(
        argv,
        workdir=workspace,
        env=env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        limits=_LIMITS,
    )
    before = 0
    after = -1
    exited = False
    try:
        time.sleep(1.0)
        before = process.active_processes()
        process.terminate()
        exited = process.wait(5.0)
        deadline = time.time() + 3.0
        after = process.active_processes()
        while after and time.time() < deadline:
            time.sleep(0.1)
            after = process.active_processes()
    finally:
        process.close()
    ok = exited and before >= 1 and after == 0
    return _report(
        "job process-tree teardown",
        ok,
        f"active {before} -> {after}, exited={exited}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Win7 no-admin sandbox capability probe"
    )
    parser.add_argument(
        "--bash",
        help="path to bash.exe; omit to auto-detect (falls back to cmd.exe)",
    )
    parser.add_argument(
        "--cmd",
        action="store_true",
        help="force cmd.exe even if bash.exe is available",
    )
    parser.add_argument("--keep", action="store_true", help="keep the temp workspace")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("Windows only")
        return 2

    try:
        shell = detect_shell(args.bash, args.cmd)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    _print_environment(shell.label)

    parent_integrity = current_integrity()
    workspace = Path(tempfile.mkdtemp(prefix="elaw_sandbox_probe_"))
    results: list[bool] = []

    print("\n== Capabilities ==")
    try:
        # 先打标签再建 .sandbox，子目录才能继承 Low。
        results.append(_test_label(workspace))
        env = sandbox_env(workspace)

        results.append(
            _test_baseline(
                list(shell.argv), shell.kind, workspace, env, parent_integrity
            )
        )
        results.append(
            _test_low_integrity(list(shell.argv), shell.kind, workspace, env)
        )
        results.append(_test_job(list(shell.argv), shell.kind, workspace, env))
    finally:
        if args.keep:
            print(f"\nworkspace kept at: {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)

    passed = all(results)
    print("\n== Verdict ==")
    if passed:
        print("  All checks passed: low-integrity token + Job Object is viable (P1).")
    elif not results[0]:
        print("  Integrity label unavailable: a Low child cannot write the workspace.")
        print(
            "  Fallback: Job Object + file path checks + audit (no write containment)."
        )
    else:
        print("  Some checks failed: see the FAIL lines above.")
        print("  A common cause is the parent process already being inside a job.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
