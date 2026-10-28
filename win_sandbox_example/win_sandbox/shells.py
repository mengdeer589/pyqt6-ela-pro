"""选择 shell：Git Bash（装了就用）或 cmd.exe（Win7 自带）。

沙箱原语不绑定 shell —— 这里只负责给出命令前缀，真正的隔离在 ``proc`` 里。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Shell:
    """``argv`` 是命令前缀，例如 ``(bash, "-c")`` 或 ``(cmd.exe, "/c")``。"""

    argv: tuple[str, ...]
    kind: str  # "bash" | "cmd"
    label: str


def _is_wsl_launcher(path: Path) -> bool:
    """``C:\\Windows\\System32\\bash.exe`` 是 WSL 入口，不是 Git Bash。"""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    for base in (system_root / "System32", system_root / "SysWOW64"):
        try:
            resolved.relative_to(base)
        except ValueError:
            continue
        return True
    return False


def find_bash(*, prefer_bundled: bool = False) -> Path | None:
    """常见 Git for Windows / MSYS2 安装位置；找不到返回 None。

    ``prefer_bundled=False``（默认）不信任当前工作目录里的
    ``git-for-windows``：那可能是克隆下来的仓库内容，属于供应链入口。
    需要用随项目携带的 Git 时显式传 ``prefer_bundled=True``。
    """
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    )
    bundled = Path.cwd() / "git-for-windows" / "usr" / "bin" / "bash.exe"
    candidates: list[Path] = [
        program_files / "Git" / "bin" / "bash.exe",
        program_files_x86 / "Git" / "bin" / "bash.exe",
        program_files / "Git" / "usr" / "bin" / "bash.exe",
        program_files_x86 / "Git" / "usr" / "bin" / "bash.exe",
        Path("C:/msys64/usr/bin/bash.exe"),
        Path("C:/tools/msys64/usr/bin/bash.exe"),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Programs" / "Git" / "bin" / "bash.exe"
        )

    # PATH 放最后：Win10/11 的 System32 里有一个 WSL 的 bash.exe，
    # 它会跑进 Linux VM，路径语义和 Git Bash 完全不同。
    which = shutil.which("bash")
    if which:
        candidates.append(Path(which))

    if prefer_bundled:
        candidates.insert(0, bundled)
    else:
        candidates.append(bundled)

    for candidate in candidates:
        try:
            if candidate.is_file() and not _is_wsl_launcher(candidate):
                return candidate
        except OSError:
            continue

    git = shutil.which("git")
    if git:
        git_path = Path(git)
        for relative in ("../bin/bash.exe", "../usr/bin/bash.exe"):
            candidate = (git_path.parent / relative).resolve()
            if candidate.is_file():
                return candidate
    return None


def detect_shell(
    explicit: str | None = None,
    force_cmd: bool = False,
    prefer_bundled: bool = False,
) -> Shell:
    """选 shell：显式 bash > 自动查找 bash > cmd.exe。

    :param explicit: 显式 bash 路径（优先级最高）。
    :param force_cmd: 强制 ``cmd.exe``。
    :param prefer_bundled: 优先使用当前目录的 ``git-for-windows``。
    :raises FileNotFoundError: 显式路径不存在，或 bash / cmd 都找不到。
    """
    if explicit and force_cmd:
        raise ValueError("explicit bash and force_cmd cannot be combined")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"bash not found: {path}")
        return Shell((str(path), "-c"), "bash", f"bash: {path}")

    if not force_cmd:
        bash = find_bash(prefer_bundled=prefer_bundled)
        if bash is not None:
            return Shell((str(bash), "-c"), "bash", f"bash: {bash}")

    comspec = Path(os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"))
    if not comspec.is_file():
        raise FileNotFoundError("neither bash.exe nor cmd.exe found")
    return Shell((str(comspec), "/c"), "cmd", f"cmd: {comspec} (bash not found)")
