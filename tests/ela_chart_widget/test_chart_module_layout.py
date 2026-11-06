"""charts 包结构守卫：分层依赖与重建方法归属。"""

from __future__ import annotations

import ast
from pathlib import Path

import pyqt6_ela_pro.charts as charts_pkg
from pyqt6_ela_pro.charts import core
from pyqt6_ela_pro.charts.core import _shared

CHARTS_DIR = Path(charts_pkg.__file__).parent

#: 目录前缀 → 禁止运行时 import 的图表子模块前缀
FORBIDDEN_IMPORTS = {
    "core/": ("components", "interact", "series_cartesian", "series_hierarchy"),
    "axes/": ("core",),
    "components/": ("core.widget",),
    "interact/": ("core.widget",),
    "series_cartesian/": ("core.widget",),
    "series_hierarchy/": ("core.widget",),
}


def _iter_modules():
    for path in CHARTS_DIR.rglob("*.py"):
        rel = path.relative_to(CHARTS_DIR).as_posix()
        yield rel, path


def _matches(rel: str, prefix: str) -> bool:
    return rel == prefix or rel.startswith(prefix)


def _target(node: ast.ImportFrom) -> str:
    return node.module or ""


def test_layering_has_no_reverse_imports():
    offenders = []
    for rel, path in _iter_modules():
        forbidden = []
        for prefix, names in FORBIDDEN_IMPORTS.items():
            if _matches(rel, prefix):
                forbidden.extend(names)
        if not forbidden:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # 只看模块级运行时导入；TYPE_CHECKING 与函数内延迟导入不算。
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            target = _target(node)
            for name in forbidden:
                if target == name or target.startswith(name + "."):
                    offenders.append(f"{rel}:{node.lineno} -> {target}")
    assert not offenders, offenders


def test_registry_shared_module_does_not_load_widget():
    tree = ast.parse(Path(_shared.__file__).read_text(encoding="utf-8"))
    top_level = [
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level
    ]
    assert not any(module and module.startswith("widget") for module in top_level)


def test_rebuild_stages_live_in_chart_option():
    for name in (
        "_rebuild",
        "_rebuild_header",
        "_rebuild_coords",
        "_rebuild_series",
        "_rebuild_components",
        "_rebuild_legend_items",
    ):
        assert getattr(core.ElaChartWidget, name).__module__ == (
            "pyqt6_ela_pro.charts.core.chart_option"
        )
