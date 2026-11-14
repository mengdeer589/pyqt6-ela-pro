"""检查 example 是否覆盖了 PyQt6ElaWidgetTools 与 pyqt6_ela_pro 的全部公开控件。

判定口径：控件类名在 ``pyqt6_ela_pro/example/`` 的任意 .py 中出现即可——直接实例化，
或作为宿主组件（如 ``ElaChatWidget`` 内部使用 ``ElaChatToolBar``）的组成部分。
因此工具只保证「组件在示例里被演示过」，不保证每页都有独立小样。

用法：``python tools/check_example_coverage.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PyQt6.QtWidgets import QWidget

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = ROOT / "pyqt6_ela_pro" / "example"


def widget_classes(module, allowed: set[str] | None = None) -> list[str]:
    names = []
    for name in dir(module):
        if name.startswith("_") or (allowed is not None and name not in allowed):
            continue
        obj = getattr(module, name)
        if not isinstance(obj, type) or not issubclass(obj, QWidget):
            continue
        if obj.__module__.startswith("PyQt6"):
            continue
        names.append(name)
    return sorted(names)


def main() -> int:
    import PyQt6ElaWidgetTools as binding
    import pyqt6_ela_pro as project

    text = "\n".join(p.read_text(encoding="utf-8") for p in EXAMPLE_DIR.rglob("*.py"))

    binding_names = widget_classes(binding)
    project_names = widget_classes(project, allowed=set(getattr(project, "__all__", [])))

    missing = []
    for name in binding_names:
        if not re.search(r"\b%s\b" % name, text):
            missing.append(("PyQt6ElaWidgetTools", name))
    for name in project_names:
        if not re.search(r"\b%s\b" % name, text):
            missing.append(("pyqt6_ela_pro", name))

    if missing:
        for source, name in missing:
            print(f"{source}: {name}")
        print(f"\n共 {len(missing)} 个公开控件未在 example 中出现")
        return 1

    print(
        f"example 覆盖检查通过：绑定 {len(binding_names)} 个 + 项目 {len(project_names)} 个公开控件均有演示"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
