"""``ElaText`` / ``ColorText`` 必须显式定字号 —— 全库机器守卫。

``ElaText`` 不调 ``setTextPixelSize`` 就是默认的 **28px**（实测值，见
``ElaText.h``）。这是个静默的坑：不报错、不崩，只是「大」，而且只在某一张卡 /
某一页冒出来，整块的比例就崩掉。

**合规写法有四条**，缺一不可漏判：

* ``setTextPixelSize(px)`` —— 点字号，最常用；
* ``setTextStyle(ElaTextType...)`` —— 上游的语义档位（``ela_spotlight`` /
  ``splash_screen`` 走这条）；
* ``setFont(QFont(...))`` —— 直接换字体。**注意它会覆盖点字号**
  （``setTextPixelSize(18)`` 之后再来一句 ``setFont(QFont(f, 18, Bold))``，
  ``pixelSize()`` 就变回 ``-1``、改用 18 *磅*），所以这一条也算「已定字号」；
* ``ElaText("文字", 12, parent)`` —— 构造的**第二位置参数**就是点字号
  （上游签名 ``ElaText(text, pixelSize, parent)``），建出来就是定好的字号。

守卫查两种形状：① ``x = ElaText(...)`` 而 ``x`` 在该作用域内没定过字号；
② ``ElaText(...)`` 作为实参**直接交给另一个调用**（如
``layout.addWidget(ElaText("启用", row))``）—— 这种交出去之后就没有任何定
字号的机会，实测 ``selection_page`` 的四个参数标签就是这样漏的
（默认 28px，比同页说明文字大一号）。

chat 包已有一条同源守卫（``tests/ela_chat/test_chat_agent_features.py::TestFontScale``，
按 ``MAX_PX = 14`` 卡上限，**运行时**逐控件查）；这里覆盖的是**全库静态**形状，
能在建控件之前就抓出来。

``chat/`` 整包排除：那边大量走 ``getattr(self, "_label", None)`` 取对象再定字号
（如 ``blocks.py`` 的 ``_apply_theme``），静态判据解析不了这种间接引用，只会误报 ——
而运行时守卫对这些控件是逐个查过的。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_PKG = pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro"
#: 由 tests/ela_chat/test_chat_agent_features.py::TestFontScale 覆盖（运行时更准）
_SKIP_DIRS = {"chat"}
_TEXT_CLASSES = {"ElaText", "ColorText"}
_SIZING_METHODS = {"setTextPixelSize", "setTextStyle", "setFont"}


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_text_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _TEXT_CLASSES
    )


def _has_positional_size(call: ast.Call) -> bool:
    """``ElaText(text, 12, parent)`` / ``ElaText(text, pixelSize=12)`` —— 构造即定字号。"""
    if len(call.args) >= 2:
        second = call.args[1]
        if (
            isinstance(second, ast.Constant)
            and isinstance(second.value, int)
            and not isinstance(second.value, bool)
        ):
            return True
    return any(
        kw.arg == "pixelSize"
        and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, int)
        for kw in call.keywords
    )


def _scope_sized(node: ast.AST) -> set[str]:
    """该作用域内被定过字号的控件名（含 ``x = ElaText(..).setTextPixelSize(..)``）。"""
    sized: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Assign, ast.AnnAssign)):
            targets = (
                sub.targets if isinstance(sub, ast.Assign) else [sub.target]
            )
            names = {_target_name(t) for t in targets} - {""}
            value = sub.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr in _SIZING_METHODS
                and _is_text_call(value.func.value)
            ):
                sized |= names
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr in _SIZING_METHODS:
                name = _target_name(sub.func.value)
                if name:
                    sized.add(name)
    return sized


def _offenders() -> list[str]:
    found: list[str] = []
    for path in sorted(_PKG.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        if set(path.relative_to(_PKG).parts) & _SKIP_DIRS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue

        rel = path.relative_to(_PKG).as_posix()

        def scan(scope: ast.AST, scope_label: str, seen_sized: set[str]) -> None:
            sized = _scope_sized(scope) | seen_sized
            for sub in ast.walk(scope):
                if not (isinstance(sub, ast.Assign) and _is_text_call(sub.value)):
                    continue
                if _has_positional_size(sub.value):
                    continue
                for target in sub.targets:
                    name = _target_name(target)
                    if name and name not in sized:
                        found.append(
                            "{}:{}  {}({}) 的 {} = {}() 没定字号".format(
                                rel,
                                sub.lineno,
                                scope_label,
                                getattr(scope, "name", ""),
                                name,
                                sub.value.func.id,
                            )
                        )

        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef):
                scan(cls, "类", set())
        # 模块级函数里的局部 ElaText
        for fn in tree.body:
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scan(fn, "函数", set())

        found.extend(_inline_arg_offenders(tree, rel))
    return found


def _inline_arg_offenders(tree: ast.AST, rel: str) -> list[str]:
    """``ElaText(...)`` 作为别的调用的实参直接交出 —— 没有名字，也就没有
    在交出前定字号的机会（``selection_page`` 的四个参数标签就这样漏的）。"""
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    found: list[str] = []
    for node in ast.walk(tree):
        if not _is_text_call(node):
            continue
        if _has_positional_size(node):
            continue
        parent = parents.get(id(node))
        if not (isinstance(parent, ast.Call) and parent.func is not node):
            continue
        holder = _target_name(parent.func) or "<call>"
        found.append(
            "{}:{}  {}(...) 作为 {} 的实参直接交出，没定字号".format(
                rel, node.lineno, node.func.id, holder
            )
        )
    return found


_OFFENDERS = _offenders()


class TestElaTextAlwaysSized:
    def test_library_has_text_widgets(self):
        """对照组：守卫本身没因为写法不匹配而全库失明。"""
        total = 0
        for path in _PKG.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            if set(path.relative_to(_PKG).parts) & _SKIP_DIRS:
                continue
            total += path.read_text(encoding="utf-8", errors="replace").count(
                "ElaText("
            )
        assert total > 30, "扫到的 ElaText 太少，判据可能失配"

    def test_no_unsized_ela_text(self):
        assert not _OFFENDERS, (
            "以下 ElaText / ColorText 没定字号（默认 28px）：\n"
            + "\n".join(_OFFENDERS)
        )

    @pytest.mark.parametrize("offender", _OFFENDERS)
    def test_offender_list_is_not_empty_when_expected(self, offender):
        """占位：让上面的清单在 ``-k offender`` 下可见，便于逐条修。"""
        assert offender