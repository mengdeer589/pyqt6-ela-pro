"""扫全库的 **PySide6 / PyQt5 遗留写法** —— 这些形态在 PyQt6 下**必然失败**，不是风格问题。

文件名里的 ``pyside6`` 是历史遗留（它诞生于 PyQt5 → PySide6 那一轮）；当前栈是
**PyQt6**，所以规则已整体翻转：ban 的是 PySide6 写法，允许并要求 PyQt6 写法。

只收「一定失败」的形态（风格别名交给 lint）。规则：

- ``x.connect(a, b)``：**PyQt5** 的「连接时附带实参」重载；PyQt6/PySide6 的两位置参
  重载都是 ``connect(上下文 QObject, 槽)``，写成 ``connect(槽, 额外实参)`` 必 ``TypeError``。
  判据：第一个位置参是绑定方法（``obj.method``）/ lambda 时，第二个位置参即「额外实参」。
- ``Signal`` / ``Slot`` / ``Property`` / ``shiboken6`` / ``QVariant``：PySide6 名字，PyQt6 里不存在。
- ``PySide6`` / ``shiboken6`` 的 import、``PyQt5`` / ``PySide2`` 的 import。
- `.exec_()` / `.print_()`：PyQt6 已去掉尾下划线（``print`` 是唯一需要的那个）。
- **Qt6 已删除的实例方法**（PySide6 时代曾是合法调用，例如 ``event.localPos()``）：
  ``localPos`` / ``screenPos`` / ``windowPos`` / ``posF`` / ``delta`` / ``scrollType`` /
  ``grabWidget`` / ``setMatrix`` / ``resetMatrix`` / ``toTime_t`` / ``fromTime_t`` /
  ``byteCount`` / ``desktopWidget``。这些**只按「调用形态」判**（``xxx.localPos(``），
  避免误伤同名变量。注意 ``globalPos`` **不在**名单里：``QContextMenuEvent`` 在
  PyQt6 仍只有 ``globalPos()``（没有 ``globalPosition()``）。
- 上游绑定的枚举参数只收枚举成员：写成 ``setDisplayMode(0)`` 会抛
  ``TypeError: argument 1 has unexpected type 'int'``（实测，窗口构造期即炸）。
"""

from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCANNED = [p for p in (_ROOT / "pyqt6_ela_pro", _ROOT / "llm_test") if p.is_dir()]

#: PyQt6 里不存在的名字（命中即运行期 NameError）。
_BANNED_NAMES = {"Signal", "Slot", "Property", "shiboken6", "shiboken2", "QVariant"}
#: PyQt6 之外的绑定模块（命中即 ModuleNotFoundError / 混栈）。
_BANNED_MODULES = {"PySide2", "PySide6", "shiboken2", "shiboken6", "PyQt5"}

#: Qt6 已删除 / 改名的实例方法（按「调用形态」判，避免误伤同名变量）。
_BANNED_METHOD_CALLS = {
    "localPos",
    "localPosF",
    "screenPos",
    "screenPosF",
    "windowPos",
    "windowPosF",
    "posF",
    "delta",
    "scrollType",
    "grabWidget",
    "setMatrix",
    "resetMatrix",
    "toTime_t",
    "fromTime_t",
    "byteCount",
    "desktopWidget",
    "exec_",  # 尾下划线形态，PyQt6 只有 exec()
    "print_",  # 同上：QTextDocument.print
}

#: 返回**上游枚举成员**的调用：PyQt6 里枚举成员恒为真，不能直接当布尔用
#: （``getElaIcon()`` 返回 ``IconName.None_``，PySide6 时代是 int 0 → 曾是 falsy）。
_ENUM_TRUTHINESS_CALLS = {"getElaIcon"}

#: 上游绑定里**实测**只收枚举成员的方法 → 哪些位置参必须是枚举成员（按 .h 的签名）。
_ENUM_ONLY_ARG_POSITIONS = {
    "setDisplayMode": (0,),
    "setWindowButtonFlags": (0,),
    "setTextStyle": (0,),
    "setThemeMode": (0,),
    "getThemeColor": (0, 1),
    "setThemeColor": (0, 1),
}
_ENUM_ONLY_ARG_NAMES = {
    "displayMode",
    "buttonFlags",
    "textStyle",
    "themeMode",
    "themeColor",
}


def _is_int_constant(node: ast.expr) -> bool:
    """裸 int 字面量（``True`` / ``False`` 不算 —— bool 是合法实参）。"""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    )


def _iter_py_files():
    for base in _SCANNED:
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            yield path


def _is_enum_truthiness(node: ast.expr) -> bool:
    """节点是否是「拿枚举成员当布尔」的调用（PyQt6 下这类写法必错）。"""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _ENUM_TRUTHINESS_CALLS
    )


def _looks_like_slot(node: ast.expr) -> bool:
    """第一个位置参是否「槽的写法」（不是上下文 QObject 的写法）。"""
    if isinstance(node, (ast.Lambda, ast.Attribute)):
        return True
    return isinstance(node, ast.Call) and "partial" in ast.unparse(node.func)


def _scan_tree(tree: ast.Module, label: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            found.append(f"{label}:{node.lineno}: {node.id} 是 PySide6 名字")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _BANNED_METHOD_CALLS
        ):
            # 只按**调用形态**判（``xxx.delta()``）：``obj.delta`` 这类属性读取
            # 可能是别的库的同名成员（如 OpenAI 分片的 ``choice.delta``）。
            found.append(
                f"{label}:{node.lineno}: .{node.func.attr}() 在 Qt6/PyQt6 不存在"
            )
        elif isinstance(node, (ast.If, ast.While)) and _is_enum_truthiness(node.test):
            found.append(
                f"{label}:{node.lineno}: {ast.unparse(node.test)} 不能拿枚举成员当布尔"
                "（它恒为真值；判 0 应写，example: `int(getattr(x, \"value\", x)) != 0`）"
            )
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and _is_enum_truthiness(node.operand):
            found.append(
                f"{label}:{node.lineno}: not {ast.unparse(node.operand)} 不能用于枚举真值判断"
            )
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _BANNED_MODULES:
                found.append(f"{label}:{node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _BANNED_MODULES:
                    found.append(f"{label}:{node.lineno}: import {alias.name}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
            and len(node.args) >= 2
            and _looks_like_slot(node.args[0])
        ):
            found.append(f"{label}:{node.lineno}: {ast.unparse(node)}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            positions = _ENUM_ONLY_ARG_POSITIONS.get(node.func.attr, ())
            bad_args = [
                i
                for i in positions
                if i < len(node.args) and _is_int_constant(node.args[i])
            ]
            bad_kwargs = [
                kw.arg
                for kw in node.keywords
                if kw.arg in _ENUM_ONLY_ARG_NAMES and _is_int_constant(kw.value)
            ]
            if bad_args or bad_kwargs:
                found.append(
                    f"{label}:{node.lineno}: {ast.unparse(node)} —— 枚举参数收到 int 字面量"
                )
    return found


def _sites() -> list[str]:
    found: list[str] = []
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - 由 ruff 拦
            found.append(f"{path}:{exc.lineno}: SyntaxError {exc.msg}")
            continue
        found.extend(_scan_tree(tree, str(path.relative_to(_ROOT))))
    return found


def _count_sites(source: str) -> int:
    return len(_scan_tree(ast.parse(source), "<snippet>"))


class TestNoBindingsLeftovers:
    def test_no_qt5_or_pyside_forms(self):
        offenders = _sites()
        assert offenders == [], (
            "这些写法在 PyQt6 下必然失败（PySide6 / PyQt5 遗留）：\n"
            + "\n".join("  " + o for o in offenders)
            + "\n\n带额外实参的连接用 lambda 固定实参："
            " ``btn.clicked.connect(lambda _checked=False, m=mode: self._onMode(m))``。"
        )

    def test_scanner_finds_planted_sites(self):
        """守卫本身要有效：坏形状必须被抓到、安全形状必须放过。"""
        bad = (
            "from PySide6.QtCore import QPoint\n"
            "import shiboken6\n"
            "class A:\n"
            "    sig = Signal()\n"
            "    def f(self, btn, mode, event):\n"
            "        btn.clicked.connect(self._onMode, mode)\n"
            "        self.menu.exec_()\n"
            "        event.localPos()\n"
            "        if label.getElaIcon():\n"
            "            nav.setDisplayMode(0)\n"
            "        eTheme.getThemeColor(mode, 0)\n"
        )
        good = (
            "from PyQt6.QtCore import pyqtSignal\n"
            "from PyQt6 import sip\n"
            "class A:\n"
            "    changed = pyqtSignal(object)\n"
            "    def f(self, btn, mode, other, event):\n"
            "        btn.clicked.connect(lambda _checked=False, m=mode: self._onMode(m))\n"
            "        self.changed.connect(other, other._onChanged)\n"
            "        btn.clicked.connect(self._onMode)\n"
            "        event.globalPos()\n"  # QContextMenuEvent 只有 globalPos
            "        sip.isdeleted(btn)\n"
            "        nav.setDisplayMode(ElaNavigationType.NavigationDisplayMode.Maximal, False)\n"
            "        eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase)\n"
        )
        assert _count_sites(bad) == 9, "坏形状没被抓全"
        assert _count_sites(good) == 0, "安全形状被误报"
