"""扫全库的「无主 singleShot」。

扩展自 ``tests/example/test_markdown_page_timers.py``（原先只扫markdown_page.py
一个文件）。同一个坑在库里同样成立：``ElaConfirmDialog.showEvent`` 用的就是
``QTimer.singleShot(0, self._positionDialog)`` —— 无主定时器不随控件销毁。

**规则**：`QTimer.singleShot(ms, callable)` 这种「无 context」形态必须避开。
带 context 的 ``singleShot(ms, ctx, callable)`` 重载**也不能单独当保障**
（实测传了 context 照样崩），所以本守卫只做静态形状检查 + 给出建议写法，
真正稳妥的是「定时器作为 ctx 的子对象」或回调里 ``sip.isdeleted()`` 自查。
"""

from __future__ import annotations

import ast
import pathlib
from PyQt6 import sip

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCANNED = [_ROOT / "pyqt6_ela_pro"]

#: 允许「无 context」的地方：纯数学延迟（``loop.quit`` 等），不碰任何控件。
_SAFE_FIRST_ARG_EXACT = {"loop.quit"}


def _iter_py_files():
    for base in _SCANNED:
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            yield path


def _count_top_level_args(text: str) -> int:
    depth, count = 0, 1
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count


def _is_offender(node: ast.Call) -> bool:
    """这个 ``singleShot`` 调用是否是无主形态。"""
    if ast.unparse(node.func) not in ("QTimer.singleShot", "singleShot"):
        return False
    if len(node.args) < 2:
        return False
    first = node.args[1]
    # lambda 不是 context（它照样是无主回调）
    if isinstance(first, ast.Lambda):
        return True
    if ast.unparse(first) in _SAFE_FIRST_ARG_EXACT:
        return False
    # 写了三个位置参 = 带 context 的重载
    return len(node.args) < 3


def _sites() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 由 ruff 拦
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_offender(node):
                found.append(
                    (
                        str(path.relative_to(_ROOT)),
                        node.lineno,
                        ast.unparse(node),
                    )
                )
    return found


class TestNoUnparentedSingleShotInLibrary:
    def test_every_single_shot_has_a_context(self):
        offenders = _sites()
        assert offenders == [], (
            "这些 singleShot 没有 context 对象（无主定时器），控件销毁后会打到"
            "已释放对象 = 0xC0000409 零 traceback 终止：\n"
            + "\n".join("  {}:{}  {}".format(*o) for o in offenders)
            + "\n\n稳妥写法：t = QTimer(ctx); t.setSingleShot(True); "
            "t.timeout.connect(...) —— 或回调里 sip.isdeleted() 自查。"
        )

    def test_scanner_finds_planted_sites(self, tmp_path):
        """守卫本身要有效：坏形状必须被抓到、安全形状必须放过。"""
        bad = (
            "from PyQt6.QtCore import QTimer\n"
            "def f(w):\n"
            "    QTimer.singleShot(1200, lambda: w.setText('x'))\n"
            "    QTimer.singleShot(50, w.hide)\n"
        )
        good = (
            "from PyQt6.QtCore import QTimer\n"
            "def f(w, loop):\n"
            "    QTimer.singleShot(1200, w, w.hide)\n"
            "    QTimer.singleShot(50, loop.quit)\n"
        )
        assert _count_sites(bad) == 2, "坏形状没被抓全"
        assert _count_sites(good) == 0, "安全形状被误报"

    def test_confirm_dialog_ownerless_shape_is_fixed(self):
        """``ElaConfirmDialog`` 的无主 singleShot 已修（连同其余 7 处）。

        修法是 ``_internal.single_shot_on(ctx, ms, slot)`` —— 定时器本身做成
        ``ctx`` 的子对象，``ctx`` 析构时 Qt 连带销毁并丢掉待触发的 timeout。
        """
        src = (
            _ROOT / "pyqt6_ela_pro" / "ela_confirm_dialog.py"
        ).read_text(encoding="utf-8")
        assert "single_shot_on(self, 0, self._positionDialog)" in src
        assert not _sites_in(
            _ROOT / "pyqt6_ela_pro" / "ela_confirm_dialog.py"
        )


def _sites_in(path: pathlib.Path) -> list[tuple[str, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (str(path.name), node.lineno, ast.unparse(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_offender(node)
    ]


def _count_sites(source: str) -> int:
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_offender(node)
    )
