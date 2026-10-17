"""全库守卫：容错 ``except`` 必须含 ``OverflowError``。

``OverflowError`` 继承 ``ArithmeticError``，**不是** ``ValueError`` 的子类，
所以 ``except (TypeError, ValueError)`` 看着齐全、实则漏一个子类。触发路径
不需要恶意构造：

* ``float(10 ** 400)`` —— option / API 响应里写个大整数
* ``int(float("inf"))``
* ``np.asarray([10 ** 400], dtype=np.float64)``

而这些转换点大多由 ``resizeEvent`` / ``paintEvent`` / 信号槽 / 定时器无保护
地调用 —— 异常穿透 Qt 回调边界就是 **0xC0000409 静默终止**（零 traceback）。

本库已因此栽过三次：``chat/message._as_int``、``journal._int``（丢词元恢复
链路）、``charts`` 的坐标轴与 tooltip 路径。**三次都只修了被症状指到的那几处**
—— 所以守卫从 charts 扩到全库，一扫就找出 ``chat/`` 与内容渲染里还有 9 处
同类漏网（其中 ``chat/blocks.py`` 的注释里就写着「异常穿透 Qt 回调 = 0xC0000409
静默 abort」，作者已知道这是崩溃路径却漏了这个子类）。

## 为什么判据里只收五个函数

``len`` / ``min`` / ``max`` / ``sum`` / ``abs`` / ``range`` **永不**抛
OverflowError（``len`` 抛 TypeError，空序列的 ``min``/``max`` 抛 ValueError，
``range`` 的浮点参数抛 TypeError）。把它们算进来会让守卫在全库扫出成片误报
（实测 17 处命中里 16 处是这类）—— **守卫一旦开始误报就等于没有守卫**。

## 为什么有 ``_UNREACHABLE`` 白名单

剩下的命中全是 ``int(<字符串>)``：``int("inf")`` 抛的是 ``ValueError`` 而非
OverflowError，所以按类型就不可能触发。这类站点仍要求列出 ``OverflowError``
是**故意**的 —— 它强制每个新点都被人看一眼并写下理由，而不是悄悄放过。
白名单以「文件 + 所在函数」为键（不用行号：行号会随任何编辑整体挪位，按行号
钉的白名单下一次重构就失效了）。
"""

from __future__ import annotations

import ast
import pathlib

_PKG = pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro"

#: 「把外部值转数值」的容错点。命中即要求列出 ``OverflowError``。
#: 判据是 try 体里**出现了会抛 OverflowError 的转换调用**，而不是逐个文件
#: 名单 —— 名单会过期。
_NUMERIC_CALLS = {
    "int",
    "float",
    "complex",
    "round",
    "asarray",
}

#: 可达性分析判定为「不可能抛 OverflowError」的站点 → 理由。
#: 新增条目前请先确认真的不可达（见模块 docstring）。
_UNREACHABLE: dict[tuple[str, str], str] = {
    (
        "ela_markdown_viewer.py",
        "_toggle_code_block_expanded",
    ): "入参标注 str（折叠链接 href 由库自己生成），int(str) 只抛 ValueError/TypeError",
    ("ela_markdown_viewer.py", "_toggle_fold_expanded"): "同上",
    ("ela_markdown_viewer.py", "_toggle_task_by_ordinal"): "同上",
    (
        "example/charts_page.py",
        "_onGenBigData",
    ): "两处都是 int(QLineEdit.text())，文本输入",
    (
        "ela_shimmer.py",
        "_onTick",
    ): "except 是防 RuntimeError（C++ 对象已销毁）的；try 体里 float() 只喂模块常量 _FRAME_MS",
}


def _caught_names(node: ast.expr) -> list[str] | None:
    """返回显式列出的异常类名。

    返回 ``None`` 表示「不检查」：``except Exception`` / ``except BaseException``
    什么都接住；单个类型名（``except TypeError``）是作者明确声明过的语义，
    硬要它列 ``OverflowError`` 属于过度约束。
    """
    if not isinstance(node, ast.Tuple):
        return None
    names = [ast.unparse(e) for e in node.elts]
    if any(n in ("Exception", "BaseException") for n in names):
        return None
    if len(names) < 2:
        return None
    return names


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    return {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _enclosing_function(node: ast.AST, parents: dict[int, ast.AST]) -> str:
    """节点所在的函数 / 方法名（找不到用 ``<module>``）。"""
    current: ast.AST | None = node
    while current is not None and id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def _handlers() -> list[tuple[str, int, str, list[str]]]:
    """扫出「所在 try 体做了会溢出转换」的 except handler。

    判据落在**外层 try 语句**而不是单个 handler：这些容错点常写成
    ``try: a = float(x) except (..): ...`` 里再套一层的情况，只看 handler
    自身的 body 会漏（实测在 charts 里漏掉 30+ 处，等于守卫失效）。
    """
    found: list[tuple[str, int, str, list[str]]] = []
    for path in sorted(_PKG.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = _parents(tree)
        rel = str(path.relative_to(_PKG)).replace("\\", "/")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            calls = {
                n.func.id
                for n in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            if not (calls & _NUMERIC_CALLS):
                continue
            func = _enclosing_function(node, parents)
            for handler in node.handlers:
                if handler.type is None:
                    continue  # 裸 except：什么都接住
                caught = _caught_names(handler.type)
                if caught is None:
                    continue
                found.append((rel, handler.lineno, func, caught))
    return found


def _uncovered() -> tuple[list[str], set[tuple[str, str]]]:
    """返回 (违规站点描述, 命中的白名单键集合)。"""
    offenders: list[str] = []
    allowlisted: set[tuple[str, str]] = set()
    for rel, line, func, names in _handlers():
        if "OverflowError" in names:
            continue
        key = (rel, func)
        if key in _UNREACHABLE:
            allowlisted.add(key)
            continue
        offenders.append(f"{rel}:{line}  in {func}()  except ({', '.join(names)})")
    return offenders, allowlisted


def test_no_reachable_handler_omits_overflow_error():
    offenders, _ = _uncovered()
    assert not offenders, (
        "这些容错点会把外部值转数值，但 except 里没有 OverflowError —— "
        "float(10 ** 400) 抛的正是它（ArithmeticError 的子类，不是 ValueError "
        "的子类），漏掉就穿透 Qt 回调 = 0xC0000409：\n"
        + "\n".join("  " + o for o in offenders)
    )


def test_unreachable_allowlist_has_no_stale_entries():
    """白名单条目必须真被用到。

    过期条目比没有条目更糟 —— 它会让人以为「这类站点已经审过了」，而实际上
    那个函数早就改了实现。
    """
    _offenders, allowlisted = _uncovered()
    stale = {k: v for k, v in _UNREACHABLE.items() if k not in allowlisted}
    assert not stale, f"白名单有已无对应站点的条目（删掉它们）：{list(stale)}"


def test_scan_actually_finds_handlers():
    """守卫本身要有效：扫不到东西说明判据写坏了。"""
    assert len(_handlers()) >= 40, f"只扫到 {len(_handlers())} 处，判据可能失效"
