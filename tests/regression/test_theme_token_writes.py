"""机器守卫：组件不得用 ``setThemeColor`` 覆写全局主题令牌。

唯一允许的写入点是 ``_theme.py`` 的强调色 API；组件局部外观必须走
``_theme`` / ``_styles`` 的读取层或 per-widget 绘制。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "pyqt6_ela_pro"
ALLOWED = {LIB / "_theme.py"}


def _iter_sources():
    for path in sorted(LIB.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


def test_no_theme_token_writes_outside_theme_module():
    offenders = []
    for path in _iter_sources():
        if path in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setThemeColor"
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], (
        "库内只有 _theme.py 可以写全局主题令牌；组件局部外观请用读取层 / 自绘：\n"
        + "\n".join(offenders)
    )
