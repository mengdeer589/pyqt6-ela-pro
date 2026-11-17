"""可选依赖只允许出现在 extras，不能回到 base 安装。"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

#: 缺失时必须自动降级或只在构造时抛 ImportError 的依赖
_OPTIONAL = {
    "pywin32",
    "comtypes",
    "pygments",
    "tsdownsample",
    "mermaidx",
    "orjson",
    "polars",
    "matplotlib",
    "pyqtgraph",
}


def _names(entries: list[str]) -> set[str]:
    return {re.split(r"[<>=!~\[\s]", entry, 1)[0].strip().lower() for entry in entries}


def test_optional_dependencies_only_in_extras():
    root = Path(__file__).parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    extras = project["optional-dependencies"]

    assert not (_OPTIONAL & _names(project["dependencies"]))
    assert _OPTIONAL <= _names(extras["all"])
    assert {"matplotlib", "pyqtgraph"} <= _names(extras["canvases"])
    assert "polars" in _names(extras["parquet"])
