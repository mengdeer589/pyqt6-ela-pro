"""可执行文件身份：记录 shell 的路径 + SHA256，变了就告警/拒绝。

借 OpenShell 的 binary identity：它按 real path 识别程序，并记录 hash，
文件变了后续连接直接拒绝。这里做 Windows 版的最小实现。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BinaryIdentity:
    path: str
    sha256: str
    size: int
    mtime: float


def identify(path: str | Path) -> BinaryIdentity:
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = target.stat()
    return BinaryIdentity(
        path=str(target.resolve()),
        sha256=digest.hexdigest(),
        size=stat.st_size,
        mtime=stat.st_mtime,
    )


def load_store(path: str | Path) -> dict[str, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def save_store(path: str | Path, store: dict[str, str]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def verify(store_path: str | Path, identity: BinaryIdentity) -> tuple[bool, str | None]:
    """对比并更新 baseline；返回 ``(是否变化, 旧 hash)``。"""
    store = load_store(store_path)
    key = os.path.normcase(identity.path)
    old = store.get(key)
    store[key] = identity.sha256
    save_store(store_path, store)
    return (old is not None and old != identity.sha256, old)
