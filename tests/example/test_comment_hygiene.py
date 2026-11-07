"""示例页注释卫生：分区横幅、超长块、截断 docstring 与历史叙事。"""

from __future__ import annotations

import ast
import io
import os
import re
import tokenize
from collections.abc import Iterator

EXAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pyqt6_ela_pro",
    "example",
)

BANNER = re.compile(r"[\u2500\u2550]{2,}|^#\s*--")
HISTORY = re.compile(
    "实测|此前|原来|原先|曾经|旧实现|踩过|当时|以前|老版本|早期版本|时代测"
)
BAD_END = ("，", "、", "——", "的", "个", "（", "「", "：")
DIRECTIVE = ("noqa", "pragma:", "type: ignore", "noinspection", "pyright:")


def _python_files() -> list[str]:
    return sorted(
        os.path.join(EXAMPLE_DIR, name)
        for name in os.listdir(EXAMPLE_DIR)
        if name.endswith(".py")
    )


def _comments(src: str) -> list[tokenize.TokenInfo]:
    return [
        tok
        for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type == tokenize.COMMENT
    ]


def _blocks(lines: list[str], comments) -> Iterator[list[tokenize.TokenInfo]]:
    block: list[tokenize.TokenInfo] = []
    for tok in comments:
        line = lines[tok.start[0] - 1]
        if line[: tok.start[1]].strip():
            if block:
                yield block
                block = []
            continue
        if block and tok.start[0] == block[-1].start[0] + 1:
            block.append(tok)
        else:
            if block:
                yield block
            block = [tok]
    if block:
        yield block


def _scan(src: str, name: str = "sample.py") -> list[str]:
    issues: list[str] = []
    lines = src.splitlines()
    tree = ast.parse(src)

    for block in _blocks(lines, _comments(src)):
        texts = [tok.string.strip() for tok in block]
        first = block[0].start[0]
        if any(BANNER.search(text) for text in texts):
            issues.append(f"{name}:{first} 分区横幅")
        if len(block) > 3:
            issues.append(f"{name}:{first} 注释块 {len(block)} 行（上限 3）")
        if any(HISTORY.search(text) for text in texts):
            issues.append(f"{name}:{first} 历史叙事")
        if not any(any(d in text for d in DIRECTIVE) for text in texts):
            last = texts[-1]
            if last.endswith(BAD_END):
                issues.append(f"{name}:{block[-1].start[0]} 注释断在半句：{last[-30:]}")
            if last.endswith(("在", "会", "要", "被", "就")):
                issues.append(
                    f"{name}:{block[-1].start[0]} 注释疑似未写完：{last[-30:]}"
                )

    nodes = [tree] + [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for node in nodes:
        doc = ast.get_docstring(node, clean=True)
        if not doc:
            continue
        node_name = getattr(node, "name", "<module>")
        line_no = getattr(node, "lineno", 1)
        content = [line.strip() for line in doc.splitlines() if line.strip()]
        if isinstance(node, ast.Module):
            if len(content) != 1:
                issues.append(f"{name}:{line_no} 模块 docstring 必须单行")
            if content and not content[0].endswith("。"):
                issues.append(f"{name}:{line_no} 模块 docstring 未以「。」结尾")
        elif node_name.startswith("_demo") and len(content) > 1:
            issues.append(f"{name}:{line_no} {node_name} 的 docstring 必须单行")
        elif len(content) > 2:
            issues.append(
                f"{name}:{line_no} {node_name} docstring {len(content)} 行（上限 2）"
            )
        if content:
            last = content[-1]
            if last.endswith(BAD_END) or last.endswith("?"):
                issues.append(
                    f"{name}:{line_no} {node_name} docstring 断在半句：{last[-30:]}"
                )
    return issues


def test_guard_scans_all_pages():
    files = _python_files()
    assert len(files) >= 35, f"只扫到 {len(files)} 个页面，路径解析可能错了"


def test_example_comment_hygiene():
    problems = []
    for path in _python_files():
        src = io.open(path, encoding="utf-8").read()
        problems.extend(_scan(src, os.path.basename(path)))
    assert not problems, "示例页注释/docstring 不合规：\n" + "\n".join(problems)


def test_guard_catches_known_bad_samples():
    bad = '''"""[demo] 模块?"""

# ── 侧边栏 ──
# 实测：以前这样
# 第二行
# 第三行
# 第四行

def f():
    """半句话，"""

# 上一行会一直挂到下一行
'''
    issues = _scan(bad)
    kinds = " ".join(issues)
    assert "分区横幅" in kinds
    assert "历史叙事" in kinds
    assert "上限 3" in kinds
    assert "docstring" in kinds
    assert "未以「。」结尾" in kinds or "未写完" in kinds

    good = '''"""演示模块。"""

# 必须保持短小。
def f():
    """做一件事。"""
    return None
'''
    assert _scan(good) == []
