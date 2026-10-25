"""静态守卫：说明性文字里不许出现 Markdown 强调。

`_addInfoText()` / `note()` 建出来的是 ``ElaText``，它只吃
``Qt::PlainText`` —— 写进去的 ``**粗体**`` / 三反引号就是**原样显示的星号**。

这个坑踩过三次（chat 页说明行一次、``ElaScrollPage`` 小节又一次），而且症状
很轻（「说明文字里多了几个星号」），没人会当bug 看，所以用机器守住。

只查这两个函数：**Markdown 正文**（`` ElaMarkdownViewer.setMarkdown``）本来就该
带标记，别误伤。
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

#: 会渲染成纯文本的说明性调用（``self._addInfoText`` / 共享零件的 ``note``）
PLAIN_TEXT_CALLS = {"_addInfoText", "note", "_addInfoTextLine"}


def _python_files() -> list[str]:
    return sorted(
        os.path.join(EXAMPLE_DIR, name)
        for name in os.listdir(EXAMPLE_DIR)
        if name.endswith(".py")
    )


def _scan(source: str) -> list[tuple[int, str]]:
    """在**源码**里找出「会渲染成纯文本、却带了 Markdown」的字符串实参。"""
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else (func.id if isinstance(func, ast.Name) else "")
        )
        if name not in PLAIN_TEXT_CALLS:
            continue
        for argument in list(node.args) + [kw.value for kw in node.keywords]:
            if not isinstance(argument, ast.Constant):
                continue
            text = argument.value
            if not isinstance(text, str):  # None / 数字不是文字
                continue
            if "**" in text or "```" in text:
                found.append((argument.lineno, text.replace("\n", " ")[:56]))
    return found


def _violations(path: str) -> list[tuple[int, str]]:
    return _scan(io.open(path, encoding="utf-8-sig").read())


def test_no_markdown_in_plain_text_captions():
    """``ElaText`` 只吃 PlainText：说明文字里的 ``**`` 会原样显示成星号。"""
    problems = []
    for path in _python_files():
        bad = _violations(path)
        if bad:
            problems.append(
                f"{os.path.basename(path)} 的说明文字里带了 Markdown 标记"
                f"（ElaText 不解析）：{bad}"
            )
    assert not problems, "\n".join(problems)


def test_guard_actually_catches_markdown():
    """守卫自己得有效：喂一段带 ``**`` 的进去必须被抓出来。"""
    source = (
        "class P:\n"
        "    def f(self):\n"
        "        self._addInfoText('带 **粗体** 的说明', None)\n"
        "        note(page, '带 ``` 的说明')\n"
    )
    bad = _scan(source)
    assert len(bad) == 2, bad
