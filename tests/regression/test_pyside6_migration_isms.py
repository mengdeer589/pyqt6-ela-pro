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
- **PyQt6 取消了 QPoint ↔ QPointF 的隐式转换**（PyQt5 有）：``QRectF.contains``
  只收 ``QPointF`` / ``QRectF`` / ``(float, float)``，传 ``QPoint`` 直接 ``TypeError``
  —— 在 Qt 事件回调里即进程终止。判据是「已知类型的接收者 + 已知类型的实参」：
  只认同文件里能追到 ``QRectF(...)`` / ``QRect(...)`` 赋值的属性、局部变量与
  ``-> QRectF`` 方法，避免把合法的 ``QRect.contains(QPoint)`` 误判。
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


#: 只接受 ``QPointF`` 的 ``QRectF`` 方法（传 ``QPoint`` 即 TypeError）。
_QRECTF_ONLY_METHODS = {
    "contains",
    "intersects",
    "intersected",
    "united",
    "moveTo",
    "moveCenter",
    "moveTopLeft",
    "translate",
    "translated",
}
#: 只接受 ``QPointF`` / ``QRectF`` 的 ``QPainterPath`` 方法。
_QPATH_POINTF_METHODS = {
    "contains",
    "intersects",
    "united",
    "intersected",
    "subtracted",
    "simplified",
    "moveTo",
    "lineTo",
    "arcTo",
    "quadTo",
    "cubicTo",
    "addRect",
    "addRoundedRect",
    "addEllipse",
    "addText",
    "addPolygon",
}
#: 只接受 ``QPoint`` / ``QRect`` 的方法（反向：传 QPointF/QRectF 同样 TypeError）。
_INT_GEOM_METHODS = {"contains", "intersects", "intersected", "united", "translated"}

#: 参与类型追踪的构造函数（名字 → 类别）。
_GEOM_KINDS = {
    "QRectF": "rectf",
    "QRect": "rect",
    "QPointF": "pointf",
    "QPoint": "point",
    "QPainterPath": "path",
}


def _self_attr_name(target: ast.expr) -> str | None:
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        return target.attr
    return None


def _annotated_name(node: ast.expr) -> str | None:
    """``X: QRectF`` 里的 ``QRectF``。"""
    ann = node
    return ann.id if isinstance(ann, ast.Name) else None


def _infer_geom_kind(expr: ast.expr) -> str | None:
    """从表达式推断几何类型（直接构造 / ``.toPoint()`` / ``.position()`` / ``.rect()``）。

    构造名优先于后缀：``QPointF(event.position().toPoint())`` 是 ``QPointF``，
    里面那个 ``.toPoint()`` 只是入参。
    """
    if isinstance(expr, ast.Call):
        fn = expr.func
        if isinstance(fn, ast.Name) and fn.id in _GEOM_KINDS:
            return _GEOM_KINDS[fn.id]
    text = ast.unparse(expr)
    if "QPointF(" in text:
        return "pointf"
    if "QRectF(" in text:
        return "rectf"
    if "QPoint(" in text:
        return "point"
    if "QRect(" in text:
        return "rect"
    if ".toPoint()" in text:
        return "point"
    if ".position()" in text:
        return "pointf"
    if ".rect()" in text or ".geometry()" in text:
        return "rect"
    return None


def _collect_geom_names(
    scope: ast.AST, *, attrs_only: bool = False
) -> dict[str, set[str]]:
    """收集可证明是 ``QRectF`` / ``QRect`` / ``QPoint`` / ``QPainterPath`` 的名字。

    类作用域只收 ``self.X = ...`` 属性与 ``-> QRectF`` 方法名；函数作用域收局部变量。
    只认同文件里的直接构造，不做跨模块推断。
    """
    names: dict[str, set[str]] = {kind: set() for kind in _GEOM_KINDS.values()}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            name = None
            for target in node.targets:
                attr = _self_attr_name(target)
                if attr:
                    name = attr
                elif isinstance(target, ast.Name) and not attrs_only:
                    name = target.id
            kind = _infer_geom_kind(node.value)
            if name and kind:
                names[kind].add(name)
        elif isinstance(node, ast.AnnAssign):
            name = _self_attr_name(node.target) or (
                node.target.id
                if isinstance(node.target, ast.Name) and not attrs_only
                else None
            )
            kind = _annotated_name(node.annotation)
            if name and kind in _GEOM_KINDS:
                names[_GEOM_KINDS[kind]].add(name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ret = node.returns
            kind = ret.id if isinstance(ret, ast.Name) else None
            if kind in _GEOM_KINDS:
                names[_GEOM_KINDS[kind]].add(node.name)
    return names


def _receiver_name(call: ast.Call) -> str | None:
    """``x.f()`` / ``self.x.f()`` / ``f().contains()`` 的接收者名字。"""
    if not isinstance(call.func, ast.Attribute):
        return None
    recv = call.func.value
    if isinstance(recv, ast.Name):
        return recv.id
    if isinstance(recv, ast.Call):
        inner = recv.func
        if isinstance(inner, ast.Name):
            return inner.id
        return _self_attr_name(inner) if isinstance(inner, ast.Attribute) else None
    if isinstance(recv, ast.Attribute):
        return _self_attr_name(recv)
    return None


def _is_qpoint_expr(expr: ast.expr) -> bool:
    text = ast.unparse(expr)
    return ".toPoint()" in text or "QPoint(" in text


def _is_qpointf_expr(expr: ast.expr) -> bool:
    text = ast.unparse(expr)
    if ".toPoint()" in text:
        return False
    return "QPointF(" in text or ".position()" in text


def _is_qrect_expr(expr: ast.expr) -> bool:
    """看起来是 ``QRect``（``QRectF(...)`` 折算后不算）。"""
    text = ast.unparse(expr)
    if "QRectF(" in text:
        return False
    return "QRect(" in text or ".rect()" in text or ".geometry()" in text


def _is_named(expr: ast.expr, names: set[str]) -> bool:
    """实参是不是本作用域里追踪到指定类型的名字（``p`` / ``self._p``）。"""
    if isinstance(expr, ast.Name):
        return expr.id in names
    attr = _self_attr_name(expr)
    return attr is not None and attr in names


def _scan_geometry(tree: ast.Module, label: str) -> list[str]:
    """QRectF / QPainterPath 收 QPoint/QRect、QRect 收 QPointF/QRectF。"""
    found: list[str] = []
    scopes: list[tuple[ast.AST, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            scopes.append((node, True))
    scopes.extend(
        (node, False)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for scope, attrs_only in scopes:
        class_names = _collect_geom_names(scope, attrs_only=attrs_only)
        if not any(class_names.values()):
            continue
        # 类里的方法各自还有局部变量：逐个方法并上类级属性一起判。
        bodies = (
            [
                child
                for child in ast.walk(scope)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if attrs_only
            else [scope]
        )
        for body in bodies:
            local_names = _collect_geom_names(body)
            names = {
                kind: class_names[kind] | local_names[kind]
                for kind in _GEOM_KINDS.values()
            }
            for node in ast.walk(body):
                if not isinstance(node, ast.Call):
                    continue
                name = _receiver_name(node)
                if name is None or not isinstance(node.func, ast.Attribute):
                    continue
                method = node.func.attr
                args = [*node.args, *[kw.value for kw in node.keywords]]
                if name in names["rectf"] and method in _QRECTF_ONLY_METHODS:
                    if any(
                        _is_qpoint_expr(a)
                        or _is_qrect_expr(a)
                        or _is_named(a, names["point"])
                        or _is_named(a, names["rect"])
                        for a in args
                    ):
                        found.append(
                            f"{label}:{node.lineno}: QRectF.{method} 收到 QPoint/QRect"
                            f"（PyQt6 无隐式转换）—— {ast.unparse(node)[:100]}"
                        )
                elif name in names["path"] and method in _QPATH_POINTF_METHODS:
                    if any(
                        _is_qpoint_expr(a)
                        or _is_qrect_expr(a)
                        or _is_named(a, names["point"])
                        or _is_named(a, names["rect"])
                        for a in args
                    ):
                        found.append(
                            f"{label}:{node.lineno}: QPainterPath.{method} 收到"
                            f" QPoint/QRect —— {ast.unparse(node)[:100]}"
                        )
                elif name in names["rect"] and method in _INT_GEOM_METHODS:
                    if any(
                        _is_qpointf_expr(a)
                        or _is_named(a, names["pointf"])
                        or _is_named(a, names["rectf"])
                        for a in args
                    ):
                        found.append(
                            f"{label}:{node.lineno}: QRect.{method} 收到 QPointF/QRectF"
                            f" —— {ast.unparse(node)[:100]}"
                        )
    return found


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
                '（它恒为真值；判 0 应写，example: `int(getattr(x, "value", x)) != 0`）'
            )
        elif (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.Not)
            and _is_enum_truthiness(node.operand)
        ):
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


def _geometry_sites() -> list[str]:
    found: list[str] = []
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 由 ruff 拦
            continue
        found.extend(_scan_geometry(tree, str(path.relative_to(_ROOT))))
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


class TestGeometryImplicitConversions:
    """PyQt6 取消了 QPoint ↔ QPointF / QRect ↔ QRectF 的隐式转换。

    ``QRectF.contains(QPoint)`` 会抛 ``TypeError``；这种调用几乎都在 Qt 事件回调里
    （鼠标按下 / 移动），宿主按「未捕获异常 = 进程终止」处理，表现为整个程序退出。
    """

    def test_no_qpoint_qpointf_mixups(self):
        offenders = _geometry_sites()
        assert offenders == [], (
            "这些调用在 PyQt6 下必抛 TypeError（无隐式转换）：\n"
            + "\n".join("  " + o for o in offenders)
            + "\n\nQRectF 收 QPointF：``rectf.contains(event.position())``；"
            "QRect 收 QPoint：``rect.contains(event.position().toPoint())``。"
        )

    def test_geometry_scanner_finds_planted_sites(self):
        bad = (
            "from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF\n"
            "class A:\n"
            "    def __init__(self):\n"
            "        self._box = QRectF()\n"
            "    def on_press(self, event):\n"
            "        self._box.contains(event.position().toPoint())\n"
            "        path = QPainterPath()\n"
            "        path.moveTo(QPoint(1, 2))\n"
            "        inner = QRectF(0, 0, 4, 4)\n"
            "        inner.intersects(event.rect())\n"
            "        frame = QRect(0, 0, 4, 4)\n"
            "        frame.contains(event.position())\n"
            "        p = event.position().toPoint()\n"
            "        self._box.contains(p)\n"
        )
        good = (
            "from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF\n"
            "class A:\n"
            "    def __init__(self):\n"
            "        self._box = QRectF()\n"
            "    def on_press(self, event):\n"
            "        p = event.position()\n"
            "        if self._box.contains(p):\n"
            "            pass\n"
            "        path = QPainterPath()\n"
            "        path.addRoundedRect(QRectF(event.rect()), 4, 4)\n"
            "        frame = QRect(0, 0, 4, 4)\n"
            "        frame.contains(event.position().toPoint())\n"
            "        frame.contains(event.rect())\n"
        )
        assert len(_scan_geometry(ast.parse(bad), "<snippet>")) == 5, "坏形状没被抓全"
        assert _scan_geometry(ast.parse(good), "<snippet>") == [], "安全形状被误报"
