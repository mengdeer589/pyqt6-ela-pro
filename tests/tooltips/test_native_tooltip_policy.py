"""全库 tooltip 政策：QWidget 目标走库内 ``set_tooltip``；非 widget 目标走适配器。

系统托盘由操作系统绘制，只能保留原生；item view / 菜单 / QTextDocument 走
``tooltip_targets`` 的适配器，不再直接调用原生 ``setToolTip``。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pyqt6_ela_pro

#: 允许保留原生 setToolTip 的文件 → 原因
ALLOWED: dict[str, str] = {
    "ela_tray_icon.py": "QSystemTrayIcon 的 tooltip 只能走系统托盘 API",
    "example/tray_host.py": "系统托盘（QSystemTrayIcon）",
}


def _native_tooltip_calls(root: Path) -> list[str]:
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setToolTip"
            ):
                offenders.append(str(path.relative_to(root)).replace("\\", "/"))
    return offenders


def test_no_unexpected_native_tooltip():
    root = Path(pyqt6_ela_pro.__file__).parent
    unexpected = [path for path in _native_tooltip_calls(root) if path not in ALLOWED]
    assert unexpected == [], (
        "QWidget 目标请改用 pyqt6_ela_pro.tooltips.set_tooltip / remove_tooltip；"
        "只有非 widget 目标（系统托盘 / QTextFormat / QAction）才允许原生。"
        f"未授权：{sorted(set(unexpected))}"
    )
