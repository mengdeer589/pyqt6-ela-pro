"""顶层懒加载守卫：基础 import 不拉起重型子系统，``__all__`` 仍逐个可解析。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HEAVY = (
    "pyqt6_ela_pro.charts",
    "pyqt6_ela_pro.chat",
    "pyqt6_ela_pro.ela_markdown_viewer",
    "pyqt6_ela_pro.browser_embedder",
    "pyqt6_ela_pro.blueprint",
    "pyqt6_ela_pro.selection_assistant",
)


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_base_import_defers_heavy_modules():
    code = (
        "import sys, pyqt6_ela_pro\n"
        f"print([m for m in sys.modules if m in {HEAVY!r}])\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_every_all_name_resolves_including_star_import():
    code = """
import pyqt6_ela_pro as p

missing = []
for name in p.__all__:
    try:
        getattr(p, name)
    except Exception as exc:
        missing.append((name, type(exc).__name__))

namespace = {}
exec("from pyqt6_ela_pro import *", namespace)
exported = {key for key in namespace if key != "__builtins__"}
print(len(p.__all__), len(exported), missing)
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
    total, exported, missing = result.stdout.strip().split(" ", 2)
    assert missing == "[]"
    assert int(total) == int(exported)


def test_submodule_attribute_imports_on_demand():
    code = """
import sys
import pyqt6_ela_pro as p

assert "pyqt6_ela_pro.charts" not in sys.modules
charts = p.charts
assert charts.ElaChartWidget is not None
assert "pyqt6_ela_pro.charts" in sys.modules
print("ok")
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_dir_exposes_lazy_names_and_unknown_raises():
    code = """
import pyqt6_ela_pro as p

names = dir(p)
assert "ElaChartWidget" in names
assert "ElaChatWidget" in names
assert "ElaBlueprintCanvas" in names
assert "charts" in names
try:
    p.not_a_real_attribute
except AttributeError:
    print("ok")
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
