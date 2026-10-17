"""源码编码守卫：扫出被写坏的 UTF-8 与替换字符。

为什么需要
----------
AGENTS.md 已经禁掉了用 PowerShell 的 ``Get-Content`` / ``Set-Content`` 读写源文件
（默认 ANSI 编解码会破坏中文注释 → SyntaxError）。但写坏的形式不止一种：本次会话里
就抓到 **5 处「3 个连续替换字符」** —— 那正好是一个中文汉字的 3 个 UTF-8 字节被逐个
替换掉（下面代码里用 ``REPLACEMENT`` 指代那个字符 U+FFFD；本文件自身也不能出现它的
字面量，否则守卫会先把自己拦下来 —— 第一次跑就发生了）。

这些损坏**全在注释与 docstring 里**，所以：

- 运行时**完全无害**，全量测试照样绿；
- 但仓库的注释密度极高（AGENTS.md 本身就是一整面中文），一个词中间突然冒出三个替换
  字符，读者根本看不出原文写的是什么，也就无从判断这段话还成不成立。

所以值得钉住。判据就两条，都不依赖任何库：

1. 文件必须是**合法 UTF-8**（``bytes.decode("utf-8")`` 不抛）；
2. 解码后的文本里**不含 U+FFFD**（替换字符只可能来自写坏，不是源码里真有的字符）。

另外单独盯一个写坏时最容易造成**静默失效**的变体：ASCII 标识符里的字符被改掉。
本会话实测 ``PyQt6ElaWidgetTools`` 被写成 ``Pyqt5ElaWidgetTools`` —— 大小写一换，
import 直接 ``ModuleNotFoundError``（这个至少会炸，不会静默）。真正的静默变体是
中文注释里的**颜色名/尺寸/字段名**被吃掉，那种只能靠人读；本守卫能兜住的是「文件
根本坏掉」这一级。
"""

from __future__ import annotations

import pathlib

import pytest

ROOTS = ("pyqt6_ela_pro", "tests", "example")
SKIP_DIRS = {"__pycache__", ".venv", "build", "dist", ".git"}

#: 替换字符。**本文件不能出现它的字面量**（否则守卫先把自己拦下来）。
REPLACEMENT = chr(0xFFFD)


def _python_files() -> list:
    root = pathlib.Path(__file__).resolve().parents[2]
    out = []
    for name in ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if SKIP_DIRS & set(path.parts):
                continue
            out.append(path)
    return sorted(out)


FILES = _python_files()


def test_scan_covers_the_repository():
    """守卫本身要有效：扫不到文件等于什么都没做。"""
    assert len(FILES) > 100, f"只扫到 {len(FILES)} 个 .py，路径解析可能错了"
    assert any(p.name == "__init__.py" for p in FILES)


@pytest.mark.parametrize(
    "path", FILES, ids=lambda p: str(p.relative_to(FILES[0].parents[2]))
)
def test_source_is_clean_utf8(path: pathlib.Path):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - 失败时才到这里
        pytest.fail(
            f"{path.name} 不是合法 UTF-8（第 {exc.start} 字节附近）："
            f"{raw[max(0, exc.start - 20) : exc.start + 8]!r}"
        )
    if REPLACEMENT in text:
        index = text.index(REPLACEMENT)
        pytest.fail(
            f"{path.name} 含替换字符 U+FFFD（第 {index} 个字符处）——写入时被写坏了："
            f"{ascii(text[max(0, index - 40) : index + 20])}"
        )
