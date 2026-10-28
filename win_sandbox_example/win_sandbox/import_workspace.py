"""把外部目录导入沙箱工作区，尊重 ``.gitignore``。

借 OpenShell 的 ``sandbox upload`` 行为：
- Git 仓库里按 ``git ls-files --cached --others --exclude-standard`` 取文件，
  自动跳过 ``node_modules`` / ``.venv`` / ``dist`` 等被忽略内容；
- 非 Git 仓库退化为默认目录黑名单；
- 拒绝绝对路径 / ``..`` / 目标越界；保留 symlink。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_SKIP_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


@dataclass
class ImportResult:
    copied: int = 0
    skipped: int = 0
    blocked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_SENSITIVE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
_SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}


def _is_sensitive(relative: Path) -> bool:
    name = relative.name.lower()
    if name in _SENSITIVE_NAMES:
        return True
    if name.startswith(".env.") or name.startswith("credentials."):
        return True
    return relative.suffix.lower() in _SENSITIVE_SUFFIXES


def _is_within(root: Path, path: Path) -> bool:
    root_text = os.path.normcase(str(root))
    path_text = os.path.normcase(str(path))
    return path_text == root_text or path_text.startswith(root_text + os.sep)


def _git_files(src: Path) -> list[str] | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        probe = subprocess.run(
            [git, "-C", str(src), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if probe.returncode != 0:
        return None
    try:
        listed = subprocess.run(
            [
                git,
                "-C",
                str(src),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listed.returncode != 0:
        return None
    return [
        item.decode("utf-8", "replace") for item in listed.stdout.split(b"\0") if item
    ]


def _walk_files(src: Path) -> list[str]:
    files: list[str] = []
    for root, dirs, names in os.walk(src):
        dirs[:] = [name for name in dirs if name not in _DEFAULT_SKIP_DIRS]
        base = Path(root)
        for name in names:
            files.append(str((base / name).relative_to(src)))
    return files


def _symlink_target(link: Path) -> Path:
    target = Path(os.readlink(link))
    if not target.is_absolute():
        target = link.parent / target
    return target.resolve()


def import_tree(
    src: str | Path,
    dst: str | Path,
    *,
    use_gitignore: bool = True,
    overwrite: bool = True,
    skip_sensitive: bool = True,
) -> ImportResult:
    """把 ``src`` 导入 ``dst``；返回复制 / 跳过 / 拦截 / 错误计数。

    ``skip_sensitive=True`` 默认跳过 ``.env`` / ``*.pem`` / ``id_rsa`` 等
    凭据文件；``skip_sensitive=False`` 才原样导入。
    """
    source_root = Path(src).expanduser().resolve()
    target_root = Path(dst).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"source is not a directory: {source_root}")
    target_root.mkdir(parents=True, exist_ok=True)

    files = _git_files(source_root) if use_gitignore else None
    if files is None:
        files = _walk_files(source_root)

    result = ImportResult()
    for relative_text in files:
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            result.skipped += 1
            result.errors.append(f"unsafe path: {relative_text}")
            continue
        if skip_sensitive and _is_sensitive(relative):
            result.blocked.append(relative_text)
            continue
        source = source_root / relative
        try:
            if not source.exists() and not source.is_symlink():
                result.skipped += 1
                continue
        except OSError as exc:
            result.skipped += 1
            result.errors.append(f"{relative_text}: {exc}")
            continue

        target = (target_root / relative).resolve()
        if not _is_within(target_root, target):
            result.skipped += 1
            result.errors.append(f"escapes destination: {relative_text}")
            continue
        if target.exists() and not overwrite:
            result.skipped += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if source.is_symlink():
                link_target = _symlink_target(source)
                if not _is_within(source_root, link_target):
                    result.blocked.append(relative_text)
                    continue
                link = os.readlink(source)
                if target.exists() or target.is_symlink():
                    target.unlink()
                os.symlink(link, target)
            else:
                shutil.copy2(source, target)
            result.copied += 1
        except OSError as exc:
            result.skipped += 1
            result.errors.append(f"{relative_text}: {exc}")
    return result
