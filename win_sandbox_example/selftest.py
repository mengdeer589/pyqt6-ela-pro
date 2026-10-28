"""自动验收：不接 UI，直接断言核的行为。

::

    python selftest.py

全 PASS 才算这台北机器能落地这套方案。
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path

from win_sandbox import PolicyDenied, Sandbox, SandboxPolicy

RESULTS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(ok)
    suffix = f"  {detail}" if detail else ""
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")


def long_command(kind: str) -> str:
    if kind == "bash":
        return "sleep 60"
    return "ping -n 60 127.0.0.1 >nul"


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="win_sandbox_selftest_"))
    box = Sandbox(workspace, policy=SandboxPolicy(default_timeout=30))
    try:
        box.prepare()
        shell = box.shell
        print(f"workspace: {workspace}")
        print(f"shell    : {shell.label}")
        print()

        result = box.run("echo hi > ok.txt")
        check(
            "foreground writes workspace",
            result.exit_code == 0 and (workspace / "ok.txt").is_file(),
            f"exit={result.exit_code}",
        )

        blocked = Path.home() / "win_sandbox_selftest_blocked.txt"
        blocked.unlink(missing_ok=True)
        result = box.run(f'echo bad > "{blocked.as_posix()}"')
        check(
            "profile write denied",
            not blocked.exists(),
            f"exit={result.exit_code}",
        )
        blocked.unlink(missing_ok=True)

        try:
            box.resolve("../..")
            check("resolve rejects escape", False)
        except (PolicyDenied, ValueError):
            check("resolve rejects escape", True)

        holder: dict[str, object] = {}

        def worker() -> None:
            holder["result"] = box.run(long_command(shell.kind), timeout=60)

        thread = threading.Thread(target=worker, daemon=True)
        started = time.monotonic()
        thread.start()
        time.sleep(1.0)
        hit = box.cancel_foreground()
        thread.join(10)
        elapsed = time.monotonic() - started
        foreground = holder.get("result")
        check(
            "foreground cancel kills tree",
            hit == 1
            and foreground is not None
            and getattr(foreground, "cancelled", False)
            and elapsed < 5,
            f"hit={hit} elapsed={elapsed:.2f}s",
        )

        task = box.start(long_command(shell.kind))
        time.sleep(1.0)
        check("background task running", task.status() == "running")
        check("background tail readable", task.tail() is not None)
        message = box.cancel_task(task.id)
        time.sleep(0.3)
        check("background cancel", task.status() == "cancelled", message)

        box.close()
        check("close marks task closed", task.status() == "cancelled")
    finally:
        box.close()
        shutil.rmtree(workspace, ignore_errors=True)

    passed = all(RESULTS)
    print()
    print("ALL PASS" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
