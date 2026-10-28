"""一致性验收（conformance）：把同一套场景跑在不同机器上。

对照 OpenShell 的 ``openshell-conformance``：不是「我这儿能跑」，
而是「Win7 / Win10 / Win11、bash / cmd、管理员 / 非管理员跑的是同一套断言」。

::

    python conformance.py
    python conformance.py --json report.json
    python conformance.py --keep
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from win_sandbox import (
    ApprovalDecision,
    ApprovalMode,
    GuardMode,
    JsonlAudit,
    PolicyDenied,
    Sandbox,
    SandboxPolicy,
    create_sandbox,
    identify,
    import_tree,
    port_open,
    read_events,
    verify_identity,
)

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    suffix = f"  {detail}" if detail else ""
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")


def make_box(
    root: Path,
    name: str,
    *,
    policy: SandboxPolicy | None = None,
    audit=None,
    approval=None,
) -> Sandbox:
    box = Sandbox(
        root / name,
        policy=policy or SandboxPolicy(verify_binary=False),
        audit=audit,
        approval=approval,
    )
    box.prepare()
    return box


def check_write_containment(root: Path) -> None:
    box = make_box(root, "write")
    blocked = Path.home() / "win_sandbox_conformance_blocked.txt"
    blocked.unlink(missing_ok=True)
    try:
        result = box.run("echo hi > ok.txt")
        blocked_result = box.run(f'echo bad > "{blocked.as_posix()}"')
        check(
            "write containment",
            result.exit_code == 0
            and (box.workspace / "ok.txt").is_file()
            and not blocked.exists(),
            f"workspace exit={result.exit_code} profile exit={blocked_result.exit_code}",
        )
    finally:
        blocked.unlink(missing_ok=True)
        box.close()


def check_deny_message(root: Path) -> None:
    box = make_box(root, "deny")
    outside = Path.home() / "win_sandbox_conformance_deny.txt"
    try:
        try:
            box.resolve(outside, tool="write_file", operation="write")
        except PolicyDenied as exc:
            message = exc.to_message()
            check(
                "explainable denial",
                "[denied]" in message and "outside the sandbox workspace" in message,
                message.splitlines()[0],
            )
        else:
            check("explainable denial", False, "not denied")
    finally:
        box.close()


def check_audit(root: Path) -> None:
    audit_path = root / "audit.jsonl"
    box = make_box(root, "audit", audit=JsonlAudit(audit_path))
    outside = Path.home() / "win_sandbox_conformance_audit.txt"
    try:
        box.run("echo hi")
        try:
            box.resolve(outside, tool="write_file", operation="write")
        except PolicyDenied:
            pass
    finally:
        box.close()
    events = read_events(audit_path)
    names = {event["event"] for event in events}
    run_event = next((event for event in events if event["event"] == "run"), {})
    check(
        "audit events",
        {"prepare", "run", "deny", "close"} <= names
        and "command_sha256" in run_event
        and "command" not in run_event,
        ",".join(sorted(names)),
    )


def check_audit_mode(root: Path) -> None:
    audit_path = root / "audit_mode.jsonl"
    box = make_box(
        root,
        "audit_mode",
        policy=SandboxPolicy(verify_binary=False, guard_mode=GuardMode.AUDIT),
        audit=JsonlAudit(audit_path),
    )
    outside = Path.home() / "win_sandbox_conformance_audit_mode.txt"
    try:
        allowed = box.resolve(outside, tool="write_file", operation="write")
    finally:
        box.close()
    events = read_events(audit_path)
    deny = next((event for event in events if event["event"] == "deny"), {})
    check(
        "audit mode allows + logs",
        allowed == outside.resolve() and deny.get("enforced") is False,
        f"enforced={deny.get('enforced')}",
    )


def check_approval(root: Path) -> None:
    calls: list[object] = []

    def approve(request):
        calls.append(request)
        return ApprovalDecision(True)

    box = make_box(
        root,
        "approval",
        policy=SandboxPolicy(verify_binary=False, approval_mode=ApprovalMode.ASK),
        approval=approve,
    )
    folder = Path.home() / "win_sandbox_conformance_approved"
    try:
        first = box.resolve(folder / "a.txt", tool="write_file", operation="write")
        second = box.resolve(folder / "b.txt", tool="write_file", operation="write")
    finally:
        box.close()
    check(
        "approval asks every time",
        first == (folder / "a.txt").resolve()
        and second == (folder / "b.txt").resolve()
        and len(calls) == 2,
        f"prompts={len(calls)}",
    )


def check_import(root: Path) -> None:
    if shutil.which("git") is None:
        check("gitignore + sensitive import", True, "SKIP: git not installed")
        return
    src = root / "import_src"
    src.mkdir(parents=True)
    (src / ".gitignore").write_text("ignored.txt\nnode_modules/\n", encoding="utf-8")
    (src / "keep.txt").write_text("keep", encoding="utf-8")
    (src / "ignored.txt").write_text("ignore", encoding="utf-8")
    (src / ".env").write_text("SECRET=1", encoding="utf-8")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "x.js").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(src), "init"], capture_output=True, timeout=20)
    dst = root / "import_dst"
    result = import_tree(src, dst)
    check(
        "gitignore + sensitive import",
        (dst / "keep.txt").is_file()
        and not (dst / "ignored.txt").exists()
        and not (dst / ".env").exists()
        and not (dst / "node_modules").exists()
        and ".env" in result.blocked,
        f"copied={result.copied} blocked={result.blocked} errors={len(result.errors)}",
    )


def check_templates(root: Path) -> None:
    retained = create_sandbox(root / "templates", "generic")
    retained_path = retained.workspace
    retained.close()
    ephemeral = create_sandbox(root / "templates", "ephemeral")
    ephemeral_path = ephemeral.workspace
    ephemeral.close()
    check(
        "template retention",
        retained_path.exists() and not ephemeral_path.exists(),
        f"retained={retained_path.exists()} ephemeral={ephemeral_path.exists()}",
    )


def check_service(root: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    box = make_box(root, "service")
    task = None
    try:
        python = Path(sys.executable).as_posix()
        task = box.start(f'"{python}" -m http.server {port} --bind 127.0.0.1')
        ready = False
        for _ in range(50):
            if port_open("127.0.0.1", port):
                ready = True
                break
            time.sleep(0.1)
        if not ready:
            check("service exposure", False, "server did not start")
            return
        service = box.expose(task.id, port, "web")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(service.url, timeout=3) as response:
            status = response.status
        box.cancel_task(task.id)
        task = None
        time.sleep(0.2)
        services = box.services()
        check(
            "service exposure",
            status == 200 and services == [],
            f"status={status} services_after_cancel={len(services)}",
        )
    finally:
        if task is not None:
            task.cancel()
        box.close()


def check_identity(root: Path) -> None:
    fake = root / "fake_binary.exe"
    fake.write_bytes(b"one")
    store = root / "identity.json"
    first, _ = verify_identity(store, identify(fake))
    second, _ = verify_identity(store, identify(fake))
    fake.write_bytes(b"two")
    third, old = verify_identity(store, identify(fake))
    check(
        "binary identity",
        first is False and second is False and third is True and bool(old),
        f"first={first} same={second} changed={third}",
    )


def check_audit_outside(root: Path) -> None:
    workspace = root / "audit_inside"
    try:
        Sandbox(workspace, audit=JsonlAudit(workspace / "audit.jsonl"))
    except RuntimeError:
        check("audit outside workspace", True)
    else:
        check("audit outside workspace", False, "constructor accepted inside path")


def check_output_cap(root: Path) -> None:
    box = make_box(root, "output_cap")
    python = Path(sys.executable).as_posix()
    command = f'"{python}" -c "print(\'x\'*1000000)"'
    try:
        result = box.run(command, timeout=60)
        check(
            "foreground output cap",
            "output truncated" in result.stdout and len(result.stdout) < 300_000,
            f"len={len(result.stdout)}",
        )
    finally:
        box.close()


def check_background_output_limit(root: Path) -> None:
    box = make_box(
        root,
        "task_limit",
        policy=SandboxPolicy(verify_binary=False, max_task_output_bytes=1024),
    )
    python = Path(sys.executable).as_posix()
    command = (
        f'"{python}" -c "import sys,time; '
        "sys.stdout.write('x'*20000); sys.stdout.flush(); time.sleep(10)\""
    )
    task = None
    try:
        task = box.start(command)
        time.sleep(3.0)
        check(
            "background output limit",
            task.output_limit_hit and task.status() == "cancelled",
            f"bytes={task.output_bytes()} status={task.status()}",
        )
    finally:
        if task is not None:
            task.cancel()
        box.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Win7 sandbox conformance")
    parser.add_argument("--json", help="write a JSON report to this path")
    parser.add_argument("--keep", action="store_true", help="keep the temp root")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("Windows only")
        return 2

    root = Path(tempfile.mkdtemp(prefix="win_sandbox_conformance_"))
    print(f"root  : {root}")
    print(f"python: {sys.version.split()[0]}")
    print(f"os    : {platform.platform()}")
    print()
    try:
        check_write_containment(root)
        check_deny_message(root)
        check_audit(root)
        check_audit_mode(root)
        check_approval(root)
        check_import(root)
        check_templates(root)
        check_service(root)
        check_identity(root)
        check_audit_outside(root)
        check_output_cap(root)
        check_background_output_limit(root)
    finally:
        if args.keep:
            print(f"\nkept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    passed = all(item["ok"] for item in RESULTS)
    print()
    print("ALL PASS" if passed else "SOME CHECKS FAILED")

    if args.json:
        report = {
            "platform": platform.platform(),
            "python": sys.version,
            "root": str(root),
            "checks": RESULTS,
            "passed": passed,
        }
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"report: {args.json}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
