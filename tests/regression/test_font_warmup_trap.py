"""扫全库的「Qt6 一次性字体陷阱」：``QFont().defaultFamily()``。

PyQt6/Qt6 下**首次** ``QFont().defaultFamily()`` 要 ~190ms（解析系统默认字体、初始化
字体引擎；PyQt5/Qt5 几乎为 0）。它会随机落在宿主的第一个页面构造里，让那一页莫名多
190ms（实测落在某个无关演示节，那一节从 4ms 变成 194ms —— 见 ``docs/performance.md``）。

唯一允许的调用点是 ``splash_screen._warmTextStack()``：splash 的职责正是「遮住启动期
工作」，而且它已幂等。库内其他地方需要默认字体族时用 ``QApplication.font().family()``
（0.01ms）。
"""

from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCANNED = [_ROOT / "pyqt6_ela_pro"]
#: 允许出现 ``defaultFamily()`` 的文件（相对 ``_ROOT``，正斜杠）
_ALLOWED = {"pyqt6_ela_pro/splash_screen.py"}


def _iter_py_files():
    for base in _SCANNED:
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            yield path


def _hits(tree: ast.Module, label: str) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "defaultFamily"
        ):
            found.append(f"{label}:{node.lineno}: {ast.unparse(node)}")
    return found


def _sites() -> list[str]:
    found: list[str] = []
    for path in _iter_py_files():
        rel = str(path.relative_to(_ROOT)).replace("\\", "/")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - 由 ruff 拦
            found.append(f"{rel}:{exc.lineno}: SyntaxError {exc.msg}")
            continue
        hits = _hits(tree, rel)
        if rel in _ALLOWED:
            continue
        found.extend(hits)
    return found


class TestNoFontWarmupTrap:
    def test_default_family_only_in_splash(self):
        offenders = _sites()
        assert offenders == [], (
            "``QFont().defaultFamily()`` 是 Qt6 的一次性 ~190ms 陷阱（PyQt5 几乎为 0），\n"
            "库内只允许出现在 splash 的预热里（``_ALLOWED``）。\n"
            "需要默认字体族请用 ``QApplication.font().family()``（0.01ms）：\n"
            + "\n".join("  " + o for o in offenders)
        )

    def test_scanner_finds_planted_sites(self):
        """守卫本身要有效：坏形状必须被抓到。"""
        bad = "from PyQt6.QtGui import QFont\nfam = QFont().defaultFamily()\n"
        assert _hits(ast.parse(bad), "<snippet>") != []
        good = "from PyQt6.QtWidgets import QApplication\nfam = QApplication.font().family()\n"
        assert _hits(ast.parse(good), "<snippet>") == []
