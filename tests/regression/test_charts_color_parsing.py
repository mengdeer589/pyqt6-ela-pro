"""charts 包的颜色解析必须走 ``_colors.parse_color``（``charts._utils`` 转出）。

``QColor`` **不认** ECharts / CSS 的 ``rgb()`` / ``rgba()`` 写法：单参数
``QColor("rgba(84,112,198,0.38)")`` 拿到的是一个无效色，绘制出来是**纯黑**，
且没有任何报错。用户直接抄 ECharts 示例就会踩到（折线面积渐变曾整片发黑、
日历热力配色关不掉也是它的下游）。

凡是「颜色字符串来自 option / 数据」的位置都必须经 ``parse_color`` —— 它对
十六进制 / 具名色的结果与 ``QColor`` 完全一致，只多认 rgb 函数式。

允许的单参数 ``QColor(...)`` 形态：
- ``QColor()``（空色，0 参数；数值构造 ``QColor(r, g, b[, a])`` 也不是单参数）
- ``T(...)`` / ``eTheme.getThemeColor(...)``（主题令牌）
- ``parse_color(...)`` / ``QColor(...)``（已解析后的 QColor 拷贝）
- 全大写常量（``ON_FILL_WHITE`` 等）

``_tokens.py``（主题令牌表：全是自产 hex 常量）整文件豁免。
"""

from __future__ import annotations

import ast
import pathlib

_CHARTS = pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro" / "charts"
_EXEMPT_FILES = {"_tokens.py"}
_SAFE_CALLS = {"T", "parse_color", "QColor", "getThemeColor"}


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return getattr(node, "attr", "")


def _dynamic_qcolor_args(source: str):
    """→ [(行号, 参数表达式)]：单参数且参数不是安全形态的 ``QColor(...)``。"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node.func) != "QColor" or len(node.args) != 1:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Call) and _call_name(arg.func) in _SAFE_CALLS:
            continue
        if isinstance(arg, ast.Name) and arg.id.isupper():
            continue
        if isinstance(arg, ast.Constant):
            continue
        yield node.lineno, ast.unparse(arg)


def test_no_dynamic_single_arg_qcolor():
    problems = []
    scanned = 0
    for path in sorted(_CHARTS.rglob("*.py")):
        if path.name in _EXEMPT_FILES:
            continue
        scanned += 1
        rel = path.relative_to(_CHARTS.parent.parent).as_posix()
        for lineno, expr in _dynamic_qcolor_args(path.read_text(encoding="utf-8")):
            problems.append(f"{rel}:{lineno}: QColor({expr}) → 改用 parse_color(...)")
    assert scanned > 30, f"只扫到 {scanned} 个文件，路径守卫可能失效"
    assert not problems, "颜色字符串必须经 parse_color 解析：\n" + "\n".join(problems)
