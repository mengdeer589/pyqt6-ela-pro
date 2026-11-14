"""校验 pyqt6_ela_pro 对 PyQt6ElaWidgetTools 绑定 API 的使用是否存在。

只做存在性检查，覆盖面刻意收紧以避免误报：

- 直接来自 ``PyQt6ElaWidgetTools`` 的类实例（同名包装类按导入来源区分）
- 绑定枚举成员访问（``ElaThemeType.ThemeColor.X`` / ``ElaIconType.IconName.X``）
- 变量按「同一作用域内最后一次赋值 + isinstance 收窄」推断类型

不检查 ``self.xxx``：项目里大量 mixin 组合，静态无法可靠解析继承链。
用法：``python tools/check_ela_api.py``
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "pyqt6_ela_pro"
BINDING_MODULE = "PyQt6ElaWidgetTools"


def binding_pyi() -> Path:
    spec = importlib.util.find_spec(BINDING_MODULE)
    if spec is None or not spec.origin:
        raise SystemExit(f"未安装 {BINDING_MODULE}")
    pyi = Path(spec.origin).with_name("ElaWidgetTools.pyi")
    if not pyi.exists():
        raise SystemExit(f"缺少绑定存根：{pyi}")
    return pyi


def load_binding_classes(pyi: Path) -> dict[str, dict]:
    """pyi -> {全限定类名: {bases, attrs}}，嵌套类单独登记。"""
    tree = ast.parse(pyi.read_text(encoding="utf-8"))
    classes: dict[str, dict] = {}

    def walk(stmt: ast.ClassDef, prefix: str) -> None:
        name = f"{prefix}.{stmt.name}" if prefix else stmt.name
        info = {"bases": [ast.unparse(b) for b in stmt.bases], "attrs": set()}
        classes[name] = info
        for item in stmt.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                info["attrs"].add(item.name)
            elif isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name):
                        info["attrs"].add(t.id)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                info["attrs"].add(item.target.id)
            elif isinstance(item, ast.ClassDef):
                info["attrs"].add(item.name)
                walk(item, name)

    for stmt in tree.body:
        if isinstance(stmt, ast.ClassDef):
            walk(stmt, "")
    return classes


def qt_class_has(base: str, attr: str) -> bool | None:
    """Qt 基类是否拥有该属性；无法判定返回 None（调用方按「不报」处理）。"""
    try:
        name = base.split(".")[-1]
        for mod in ("QtWidgets", "QtCore", "QtGui"):
            module = importlib.import_module(f"PyQt6.{mod}")
            cls = getattr(module, name, None)
            if cls is not None:
                return hasattr(cls, attr)
        return None
    except Exception:
        return None


def collect_project_classes(files: list[Path]) -> dict[str, dict]:
    """项目内类：{类名: {bases, attrs}}（同名类标记为歧义，跳过继承检查）。"""
    classes: dict[str, dict] = {}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            attrs = set()
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    attrs.add(item.name)
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            attrs.add(t.id)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    attrs.add(item.target.id)
            if node.name in classes:
                classes[node.name]["ambiguous"] = True
                continue
            classes[node.name] = {
                "bases": [ast.unparse(b) for b in node.bases],
                "attrs": attrs,
            }
    return classes


def module_imports(tree: ast.Module) -> tuple[dict[str, str], dict[str, str]]:
    """返回 (绑定类本地名 -> 类名, 项目类本地名 -> 类名)。"""
    binding: dict[str, str] = {}
    project: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        source = node.module or ""
        for alias in node.names:
            local = alias.asname or alias.name
            if source.startswith(BINDING_MODULE):
                binding[local] = alias.name
            elif source.startswith("pyqt6_ela_pro") or node.level:
                project[local] = alias.name
    return binding, project


def target_names(target: ast.AST):
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from target_names(elt)


def isinstance_narrow(test: ast.AST) -> tuple[str, str] | None:
    """``isinstance(x, Cls)`` -> (变量名, 类型标记)。"""
    if not (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == 2
        and isinstance(test.args[0], ast.Name)
        and isinstance(test.args[1], ast.Name)
    ):
        return None
    return test.args[0].id, test.args[1].id


class Checker:
    def __init__(self, binding_classes: dict[str, dict], project_classes: dict[str, dict]):
        self.binding = binding_classes
        self.binding_short = {k.split(".")[-1]: k for k in binding_classes}
        self.project = project_classes
        self.problems: list[str] = []
        self.checked = 0

    def binding_has(self, cls_full: str, attr: str, seen: set[str] | None = None) -> bool | None:
        seen = seen or set()
        if cls_full in seen or cls_full not in self.binding:
            return None
        seen.add(cls_full)
        info = self.binding[cls_full]
        if attr in info["attrs"]:
            return True
        verdict = False
        for base in info["bases"]:
            short = base.split(".")[-1]
            if short in self.binding_short:
                sub = self.binding_has(self.binding_short[short], attr, seen)
            else:
                sub = qt_class_has(base, attr)
            if sub is True:
                return True
            if sub is None:
                verdict = None
        return verdict

    def project_has(self, cls_name: str, attr: str, seen: set[str] | None = None) -> bool | None:
        seen = seen or set()
        info = self.project.get(cls_name)
        if info is None or info.get("ambiguous") or cls_name in seen:
            return None
        seen.add(cls_name)
        if attr in info["attrs"]:
            return True
        verdict = False
        for base in info["bases"]:
            short = base.split(".")[-1]
            if short in self.project:
                sub = self.project_has(short, attr, seen)
            elif short in self.binding_short:
                sub = self.binding_has(self.binding_short[short], attr, seen)
            else:
                sub = qt_class_has(base, attr)
            if sub is True:
                return True
            if sub is None:
                verdict = None
        return verdict

    def resolve_mark(self, mark: str, attr: str) -> bool | None:
        return self.binding_has(mark[5:], attr) if mark.startswith("bind:") else self.project_has(mark[5:], attr)

    def class_mark(self, name: str, binding: dict[str, str], project: dict[str, str]) -> str | None:
        if name in binding:
            return f"bind:{binding[name]}"
        if name in project:
            return f"proj:{project[name]}"
        return None

    def check_file(self, path: Path) -> None:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        binding, project = module_imports(tree)
        rel = path.relative_to(ROOT)

        def visit(node: ast.AST, types: dict[str, str]) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for stmt in node.body:
                    visit(stmt, {})
                return
            if isinstance(node, ast.Lambda):
                return
            if isinstance(node, ast.ClassDef):
                for stmt in node.body:
                    visit(stmt, {})
                return
            if isinstance(node, ast.If):
                visit(node.test, types)
                narrowed = dict(types)
                narrow = isinstance_narrow(node.test)
                if narrow:
                    mark = self.class_mark(narrow[1], binding, project)
                    if mark:
                        narrowed[narrow[0]] = mark
                for stmt in node.body:
                    visit(stmt, narrowed)
                for stmt in node.orelse:
                    visit(stmt, types)
                return
            if isinstance(node, ast.Assign):
                visit(node.value, types)
                mark = None
                if isinstance(node.value, ast.Call):
                    fn = node.value.func
                    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                    if name:
                        mark = self.class_mark(name, binding, project)
                for name in [n for t in node.targets for n in target_names(t)]:
                    if mark:
                        types[name] = mark
                    else:
                        types.pop(name, None)
                return
            if isinstance(node, ast.AnnAssign):
                if node.value is not None:
                    visit(node.value, types)
                if isinstance(node.target, ast.Name):
                    mark = self.class_mark(ast.unparse(node.annotation), binding, project)
                    if mark:
                        types[node.target.id] = mark
                    else:
                        types.pop(node.target.id, None)
                return
            if isinstance(node, (ast.For, ast.AsyncFor)):
                visit(node.iter, types)
                for name in target_names(node.target):
                    types.pop(name, None)
                for stmt in node.body + node.orelse:
                    visit(stmt, types)
                return
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    visit(item.context_expr, types)
                    if item.optional_vars is not None:
                        for name in target_names(item.optional_vars):
                            types.pop(name, None)
                for stmt in node.body:
                    visit(stmt, types)
                return
            if isinstance(node, ast.Try):
                for stmt in node.body:
                    visit(stmt, types)
                for handler in node.handlers:
                    if handler.name:
                        types.pop(handler.name, None)
                    for stmt in handler.body:
                        visit(stmt, types)
                for stmt in node.orelse + node.finalbody:
                    visit(stmt, types)
                return
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    mark = types.get(func.value.id)
                    if mark:
                        self.checked += 1
                        verdict = self.resolve_mark(mark, func.attr)
                        if verdict is False:
                            self.problems.append(
                                f"{rel}:{node.lineno}: '{mark.split(':', 1)[1]}.{func.attr}' 不存在（{ast.unparse(node)[:70]}）"
                            )
            for child in ast.iter_child_nodes(node):
                visit(child, types)

        visit(tree, {})

        # 枚举成员：NS.Enum.MEMBER / NS.MEMBER
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            value = node.value
            if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
                ns, enum_name, member = value.value.id, value.attr, node.attr
                if ns not in binding:
                    continue
                ns_full = self.binding_short.get(binding[ns])
                nested = f"{ns_full}.{enum_name}"
                if ns_full and nested in self.binding:
                    if member not in self.binding[nested]["attrs"]:
                        self.problems.append(
                            f"{rel}:{node.lineno}: 枚举成员 '{ns}.{enum_name}.{member}' 不存在"
                        )
            elif isinstance(value, ast.Name) and value.id in binding:
                ns_full = self.binding_short.get(binding[value.id])
                if ns_full and ns_full in self.binding and node.attr not in self.binding[ns_full]["attrs"]:
                    self.problems.append(
                        f"{rel}:{node.lineno}: 枚举成员 '{value.id}.{node.attr}' 不存在"
                    )


def main() -> int:
    files = sorted(PKG_DIR.rglob("*.py"))
    checker = Checker(load_binding_classes(binding_pyi()), collect_project_classes(files))
    for path in files:
        checker.check_file(path)

    if checker.problems:
        print("\n".join(checker.problems))
        print(f"\n共 {len(checker.problems)} 个问题")
        return 1
    print(
        f"pyqt6_ela_pro 绑定 API 检查通过：{len(files)} 个文件，"
        f"校验 {checker.checked} 处调用，未发现失效方法/枚举成员"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
