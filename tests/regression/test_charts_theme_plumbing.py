"""静态守卫：charts 里每个颜色 ``T()`` 调用都必须带图表上下文。

图表主题是**实例级**的：``T("color.text.primary", self.chart)``。漏传
``chart`` 会静默退回全局默认主题，表现为「只有某个组件不跟主题变」——
这类漏点无法靠逐个组件的渲染测试穷举，所以用 AST 扫全包。
"""

from __future__ import annotations

import ast
import pathlib

_CHARTS = pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro" / "charts"

#: 令牌层自身（内部转发）与主题定义表（没有图表上下文）
_EXEMPT_FILES = {"_tokens.py", "_theme.py"}


def _is_token_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "T"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value.startswith("color.")
    )


def test_every_color_token_call_passes_chart_context():
    problems = []
    scanned = 0
    for path in sorted(_CHARTS.rglob("*.py")):
        if path.name in _EXEMPT_FILES:
            continue
        scanned += 1
        rel = path.relative_to(_CHARTS.parent.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not _is_token_call(node):
                continue
            key = node.args[0].value
            if key == "color.ramp":
                problems.append(
                    f"{rel}:{node.lineno}: color.ramp 必须用 theme_ramp(chart)"
                )
                continue
            if len(node.args) < 2:
                problems.append(f"{rel}:{node.lineno}: T({key!r}) 缺少图表上下文")
    assert scanned > 30, f"只扫到 {scanned} 个文件，路径守卫可能失效"
    assert not problems, "颜色令牌必须带图表上下文：\n" + "\n".join(problems)
