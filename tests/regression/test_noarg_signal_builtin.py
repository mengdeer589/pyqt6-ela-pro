"""库内禁止把信号直连到绑定内建方法（PyQt6 无参信号 bug #22）。"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "pyqt6_ela_pro"

#: 绑定内建方法（list / dict / set 等）。无参 pyqtSignal 直连它们时，
#: PyQt6 6.8.1 的 emit 会在绑定层触发原生崩溃（0xC0000409，无 traceback）。
_BUILTIN_METHODS = {
    "append",
    "extend",
    "insert",
    "add",
    "update",
    "setdefault",
    "pop",
    "remove",
    "discard",
    "clear",
}


def _iter_connect_calls():
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "connect"):
                continue
            if not node.args:
                continue
            receiver = node.args[0]
            if not isinstance(receiver, ast.Attribute):
                continue
            owner = receiver.value
            if not isinstance(owner, ast.Name) or owner.id in ("self", "cls"):
                continue
            if receiver.attr in _BUILTIN_METHODS:
                yield path, node.lineno, receiver.attr


def test_no_signal_connects_builtin_method():
    offenders = [
        f"{path.relative_to(PKG.parent)}:{line}: .connect(...{name})"
        for path, line, name in _iter_connect_calls()
    ]
    assert not offenders, (
        "无参 pyqtSignal() 直连绑定内建方法会在 PyQt6 emit 时原生崩溃（bug #22）；"
        "请改成 lambda / 自定义槽：\n" + "\n".join(offenders)
    )
