"""静态守卫：代码围栏的闭合标记不许用字符串拼接粘上去。

``ElaMarkdownViewer`` 的围栏解析要求围栏标记是**行首第一个非空白字符**
（``ela_markdown_viewer.py`` 里 ``not line.startswith((" ", "\\t")) and
stripped.startswith(_FENCE_MARKERS)``）。于是 ``源码 + "```\\n"`` 这种写法在源码
末行没有换行时会拼出 ``raise SystemExit(main())``` `` —— 闭合标记落到行中间，
被判成**未闭合围栏**（= 流式中间态）。后果有两条，都很静默：

1. 超过 ``_STREAM_HIGHLIGHT_MAX_CHARS``（4096）时**整块丢掉 pygments 着色**，
   看起来像「pygments 没生效」，实则压根没走词法分析；
2. 该 viewer 里后续内容全被吞进代码块。

踩过的就是聊天组件指南页第 2 / 4 节：``llm_test`` 源码快照常量结尾没有换行，
两处 ``+ "```\\n"`` 直接把围栏粘死在末行上（该页两个源码块 4175 / 4340 字符，
双双超过 4096 → 两块代码全无高亮）。

规则只禁一种反模式：**``+`` 的右操作数，其静态文本以 ``` 或 ~~~ 开头** —— 也就是
「这段文字紧跟在前面那段后面」，前面那段末行有没有换行根本无从保证。反过来，
``source + "\\n```\\n"`` 是**正确**写法（换行写在字面量开头就够），不命中；Markdown
正文（``r\"\"\"...```python ...``` ...\"\"\"``）与写在 docstring 里的围栏示例也不在
这条规则里。
"""

from __future__ import annotations

import ast
import io
import os

EXAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pyqt6_ela_pro",
    "example",
)

#: 围栏标记（CommonMark：``` 与 ~~~ 等价）
_FENCES = ("```", "~~~")


def _python_files() -> list[str]:
    return sorted(
        os.path.join(EXAMPLE_DIR, name)
        for name in os.listdir(EXAMPLE_DIR)
        if name.endswith(".py")
    )


def _leading_text(node: ast.expr) -> str | None:
    """取「拼接右操作数」的静态首段：字符串字面量本身 / f-string 的第一段常量。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):  # f-string：只有常量段可知，首段为准
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                return part.value
        return None
    return None


def _scan(source: str) -> list[tuple[int, str]]:
    """找出「把闭合围栏紧贴在上一段文字后面」的 ``+`` 表达式。"""
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
            continue
        head = _leading_text(node.right)
        if head and head.startswith(_FENCES):
            found.append(
                (node.left.end_lineno or node.lineno, head.replace("\n", "\\n")[:48])
            )
    return found


def _violations(path: str) -> list[tuple[int, str]]:
    return _scan(io.open(path, encoding="utf-8-sig").read())


def test_no_glued_closing_fence():
    """围栏必须独占一行：紧贴在 ``+`` 右边的 ``` 会被判成未闭合围栏。"""
    problems = []
    for path in _python_files():
        bad = _violations(path)
        if bad:
            problems.append(
                f"{os.path.basename(path)} 用字符串拼接把闭合围栏粘在了前一段文字后面 {bad}"
            )
    assert not problems, (
        "\n".join(problems)
        + "\n让闭合 ``` 独占一行（如 example/chat_guide_page.py 的 _code_block）"
    )


def test_guard_actually_catches_glued_fence():
    """守卫自己得有效：反例必须被抓出来，正例必须放过。"""
    glued = "def f(src):\n    return '```python\\n' + src + '```\\n'\n"
    assert len(_scan(glued)) == 1, _scan(glued)

    tilde = "def f(src):\n    return src + '~~~\\n'\n"
    assert len(_scan(tilde)) == 1, _scan(tilde)

    fstring = "def g(head, src):\n    return head + f'```python\\n{src}\\n```\\n'\n"
    assert len(_scan(fstring)) == 1, _scan(fstring)

    # 正例：换行写在字面量开头 / 围栏独占一行 / 正文里带围栏 —— 都不该命中
    assert _scan("def h(src):\n    return '```python\\n' + src + '\\n```\\n'\n") == []
    assert (
        _scan("def i(src):\n    return f'```python\\n{src.rstrip()}\\n```\\n'\n") == []
    )
    assert _scan('DOC = """\n```python\nx = 1\n```\n"""\n') == []
