"""命令行演示：前台命令 / 后台任务 / 取消 / 关闭。

::

    python demo.py probe
    python demo.py run "echo hi > a.txt"
    python demo.py run --cancel-after 2 "ping -n 60 127.0.0.1"
    python demo.py scenario
    python demo.py repl
"""

from __future__ import annotations

import argparse
import os
import tempfile
import threading
import time
from pathlib import Path

from agent_adapter import format_result, install_file_tools
from agent_adapter.tools import install_sandbox
from win_sandbox import RunResult, Sandbox


def default_workspace() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "WinSandboxDemo" / "workspace"


def long_command(shell_kind: str) -> str:
    if shell_kind == "bash":
        return "sleep 60"
    return "ping -n 60 127.0.0.1 >nul"


def make_sandbox(args: argparse.Namespace) -> Sandbox:
    return install_sandbox(
        args.workspace or default_workspace(),
        shell=args.bash,
        force_cmd=args.cmd,
    )


def cmd_probe(args: argparse.Namespace) -> int:
    from win_sandbox.probe import main as probe_main

    argv: list[str] = []
    if args.bash:
        argv.extend(["--bash", args.bash])
    if args.cmd:
        argv.append("--cmd")
    return probe_main(argv)


def cmd_run(args: argparse.Namespace) -> int:
    box = make_sandbox(args)
    try:
        if args.cancel_after is None:
            result = box.run(args.command, timeout=args.timeout)
        else:
            holder: dict[str, RunResult] = {}

            def worker() -> None:
                holder["result"] = box.run(args.command, timeout=args.timeout)

            thread = threading.Thread(target=worker, daemon=True)
            started = time.monotonic()
            thread.start()
            time.sleep(args.cancel_after)
            hit = box.cancel_foreground()
            thread.join(10)
            result = holder.get("result")
            print(
                f"cancel_foreground hit={hit}, "
                f"elapsed={time.monotonic() - started:.2f}s"
            )
            if result is None:
                print("命令没有在 10 秒内返回（异常）")
                return 1
        print(format_result(result, args.command[:60], box))
        return 0
    finally:
        box.close()


def cmd_scenario(args: argparse.Namespace) -> int:
    box = make_sandbox(args)
    print(f"workspace: {box.workspace}")
    print(f"shell    : {box.shell.label}")
    install_file_tools(box)
    try:
        print("\n== 1. 前台：写工作区 ==")
        print(format_result(box.run("echo hi > demo.txt"), "write workspace", box))

        print("\n== 2. 前台：写用户目录（应失败） ==")
        blocked = Path.home() / "win_sandbox_demo_blocked.txt"
        result = box.run(f'echo bad > "{blocked.as_posix()}"')
        print(format_result(result, "write profile", box))
        print(f"blocked file exists: {blocked.exists()}")

        print("\n== 3. 后台任务 ==")
        task = box.start(long_command(box.shell.kind))
        print(f"started: {task.id} ({task.command})")
        time.sleep(1.0)
        print(box.check(task.id))

        print("\n== 4. 取消后台任务 ==")
        print(box.cancel_task(task.id))
        time.sleep(0.3)
        print(box.check(task.id))
        return 0
    finally:
        print("\n== 5. 关闭（杀所有任务） ==")
        box.close()
        print("closed")


def cmd_repl(args: argparse.Namespace) -> int:
    box = make_sandbox(args)
    install_file_tools(box)
    print(f"workspace: {box.workspace}")
    print(f"shell    : {box.shell.label}")
    print(
        "命令: run <cmd> / start <cmd> / tasks / check [id] / cancel <id> / stop / close / exit"
    )
    try:
        while True:
            try:
                line = input("sandbox> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            name, _, rest = line.partition(" ")
            name = name.lower()
            try:
                if name in ("exit", "quit"):
                    break
                if name == "help":
                    print("run/start/tasks/check/cancel/stop/close/exit")
                elif name == "run":
                    print(format_result(box.run(rest), rest[:60], box))
                elif name == "start":
                    task = box.start(rest)
                    print(f"后台任务 {task.id} 已启动: {rest[:80]}")
                elif name == "tasks":
                    print(box.check())
                elif name == "check":
                    print(box.check(rest.strip() or None))
                elif name == "cancel":
                    print(box.cancel_task(rest.strip()))
                elif name == "stop":
                    print(f"cancel_foreground hit={box.cancel_foreground()}")
                elif name == "close":
                    box.close()
                    print("closed")
                else:
                    print(f"未知命令: {name}")
            except Exception as exc:
                print(f"Error: {type(exc).__name__}: {exc}")
    finally:
        box.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Win7 sandbox demo")
    parser.add_argument(
        "--workspace",
        type=Path,
        help=f"沙箱工作区（默认 {default_workspace()}）",
    )
    parser.add_argument("--bash", help="显式 bash.exe 路径")
    parser.add_argument("--cmd", action="store_true", help="强制 cmd.exe")
    sub = parser.add_subparsers(dest="action")

    sub.add_parser("probe", help="能力自检")
    sub.add_parser("scenario", help="跑一套完整场景")
    sub.add_parser("repl", help="交互式 shell")

    run = sub.add_parser("run", help="跑一条前台命令")
    run.add_argument("command")
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument(
        "--cancel-after",
        type=float,
        metavar="SECONDS",
        help="N 秒后模拟点停止（cancel_foreground）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.action is None:
        args.action = "repl"
    if args.action == "probe":
        return cmd_probe(args)
    if args.action == "scenario":
        return cmd_scenario(args)
    if args.action == "run":
        return cmd_run(args)
    return cmd_repl(args)


if __name__ == "__main__":
    raise SystemExit(main())
