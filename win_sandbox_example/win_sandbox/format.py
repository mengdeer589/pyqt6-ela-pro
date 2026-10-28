"""把 ``RunResult`` 格式化成模型可读的文本（截断 + 完整输出落盘）。"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from .proc import RunResult
from .sandbox import SandboxPolicy


def format_result(
    result: RunResult, title: str, workspace: Path, policy: SandboxPolicy
) -> str:
    text = result.stdout
    if result.stderr.strip():
        text += f"\n[stderr]\n{result.stderr.strip()}"
    text = text.strip() or "(no output)"
    text, truncated = _truncate(text, workspace, policy)

    header = f"[{title}]"
    if result.exit_code != 0:
        header += f" exit: {result.exit_code}"
    if result.cancelled:
        header += " (cancelled, process tree killed)"
    elif result.timed_out:
        header += " (timeout, process tree killed)"
    if truncated:
        header += " [output truncated, full output saved to file]"
    return f"{header}\n{text}"


def _truncate(text: str, workspace: Path, policy: SandboxPolicy) -> tuple[str, bool]:
    if len(text.encode("utf-8")) <= policy.max_output_bytes:
        return text, False
    lines = text.splitlines(keepends=True)
    tail: deque[str] = deque(maxlen=policy.tail_lines)
    used = 0
    for line in reversed(lines):
        size = len(line.encode("utf-8"))
        if used + size > policy.tail_bytes and tail:
            break
        tail.appendleft(line)
        used += size
    out_dir = workspace / ".shell_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"shell_output_{abs(hash(text)):x}.txt"
    path.write_text(text, encoding="utf-8")
    kb = len(text.encode("utf-8")) // 1024
    return (
        f"......(完整输出 {kb}KB，已保存到 {path})\n\n{''.join(tail)}",
        True,
    )
