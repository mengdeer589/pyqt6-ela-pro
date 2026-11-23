"""守卫：``QTextBlock`` 片段迭代期间不得修改文档。

片段迭代器在任何文档改写（删字 / 插入 / 字符格式合并）后立即失效，下一次
``iterator += 1`` 读已释放内存 = 0xC0000005（无 traceback）。所有片段遍历必须
「先收集 (position, length, format)，迭代结束后再应用」。

扫描器按**类内调用图传递**：循环里调用同一类的 helper 同样算违规
（bug #1 的 mutation 就藏在 ``_replace_image_with_placeholder`` 里）。
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_ROOT = _REPO_ROOT / "pyqt6_ela_pro"

#: 会改动 QTextDocument 片段结构 / 字符格式的方法
_MUTATING_METHODS = frozenset(
    {
        "mergeCharFormat",
        "setCharFormat",
        "removeSelectedText",
        "insertText",
        "insertFragment",
        "insertImage",
        "insertBlock",
        "insertTable",
        "deleteChar",
        "deletePreviousChar",
    }
)

_FunctionKey = tuple[Optional[str], str]


def _is_fragment_iterator_loop(node: ast.While) -> bool:
    test = node.test
    return (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Call)
        and isinstance(test.operand.func, ast.Attribute)
        and test.operand.func.attr == "atEnd"
    )


def _direct_mutation(body) -> bool:
    for stmt in body:
        for sub in ast.walk(stmt):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in _MUTATING_METHODS
            ):
                return True
    return False


def _collect_functions(tree) -> list:
    """模块顶层函数 + 类直接方法：``[(类名, 函数名, body)]``。"""
    functions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append((None, node.name, node.body))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append((node.name, item.name, item.body))
    return functions


def _call_target(call: ast.Call, class_name: Optional[str]) -> Optional[_FunctionKey]:
    """把调用解析成同类方法 / 同模块顶层函数；解析不了返回 ``None``。"""
    func = call.func
    if isinstance(func, ast.Attribute):
        if (
            isinstance(func.value, ast.Name)
            and func.value.id in ("self", "cls")
            and class_name is not None
        ):
            return (class_name, func.attr)
        return None
    if isinstance(func, ast.Name):
        return (None, func.id)
    return None


def _mutating_functions(tree) -> set:
    """传递闭包：直接改文档的函数，以及只调用这些函数的同类包装函数。"""
    functions = _collect_functions(tree)
    mutating = set()
    for class_name, name, body in functions:
        if _direct_mutation(body):
            mutating.add((class_name, name))
    changed = True
    while changed:
        changed = False
        for class_name, name, body in functions:
            key = (class_name, name)
            if key in mutating:
                continue
            for stmt in body:
                for call in ast.walk(stmt):
                    if (
                        isinstance(call, ast.Call)
                        and _call_target(call, class_name) in mutating
                    ):
                        mutating.add(key)
                        changed = True
                        break
                if key in mutating:
                    break
    return mutating


def _fragment_loops(tree) -> list:
    """``[(类名, while 节点)]``（嵌套函数沿用外层类名）。"""
    loops = []

    def walk(node, class_name):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, child.name)
            else:
                if isinstance(child, ast.While) and _is_fragment_iterator_loop(child):
                    loops.append((class_name, child))
                walk(child, class_name)

    walk(tree, None)
    return loops


def _offenders(source: str, name: str) -> list:
    tree = ast.parse(source)
    mutating = _mutating_functions(tree)
    found = []
    for class_name, loop in _fragment_loops(tree):
        for stmt in loop.body:
            for sub in ast.walk(stmt):
                if not isinstance(sub, ast.Call):
                    continue
                if (
                    isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in _MUTATING_METHODS
                ):
                    found.append(f"{name}:{sub.lineno}: {sub.func.attr}()")
                    continue
                target = _call_target(sub, class_name)
                if target in mutating:
                    found.append(f"{name}:{sub.lineno}: {target[1]}()（间接改文档）")
    return found


class TestScanner:
    def test_catches_direct_mutation(self):
        source = textwrap.dedent(
            """
            def render(block):
                iterator = block.begin()
                while not iterator.atEnd():
                    document.removeSelectedText()
                    iterator += 1
            """
        )
        assert _offenders(source, "<memory>")

    def test_catches_module_helper_indirection(self):
        source = textwrap.dedent(
            """
            def mutate(document):
                document.removeSelectedText()

            def render(block):
                iterator = block.begin()
                while not iterator.atEnd():
                    mutate(document)
                    iterator += 1
            """
        )
        assert _offenders(source, "<memory>")

    def test_catches_same_class_method_indirection(self):
        """bug #1 的形状：mutation 藏在同类方法里。"""
        source = textwrap.dedent(
            """
            class Viewer:
                def mutate(self):
                    self.cursor.removeSelectedText()

                def render(self, block):
                    iterator = block.begin()
                    while not iterator.atEnd():
                        self.mutate()
                        iterator += 1
            """
        )
        assert _offenders(source, "<memory>")


def test_no_document_mutation_during_fragment_iteration():
    offenders = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        offenders.extend(_offenders(source, str(path.relative_to(_REPO_ROOT))))
    assert not offenders, (
        "片段迭代内改文档（迭代器立即失效 → 0xC0000005）：\n" + "\n".join(offenders)
    )
