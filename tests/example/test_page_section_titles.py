"""示例页的节标题不许重复（同一分组内编号也不许撞号）。

用户报的现象：``容器与布局`` 页的「01. ela_ext - ElaDrawer 四方向抽屉」连着出现
两次 —— ``_addDemoContent`` 同时调了 ``_demoDrawer``（内部又调 ``_demoSiSideDrawer``）
和 ``_demoSiSideDrawer``，同一段内容渲染两遍。

同一处还叠着第二层问题：那个页面的编号是 ``01 02 02a 02 03 04 13 01 00``
（两个 ``02``、一个 ``13``），因为 ``_demoScrollPage`` / ``_demoElaDrawerArea``
在 ``_addDemoContent`` 里的调用位置与编号意图对不上。两类都值得机器守住。

分组识别按**渲染顺序**（沿 ``_addDemoContent`` 的调用链展开）而不是源码行号 ——
``_createSectionHeader("=== xxx ===")`` 常常写在包裹它的 demo 方法里，源码位置
与出现顺序无关。编号在 ``=== xxx ===`` 处允许重开（这批页面的既有约定，见
``animation_icon_page.py``），但同一分组内不得重复。
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections import Counter, defaultdict

import pytest

_EXAMPLE_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro" / "example"
)

_TITLE_RE = re.compile(r"^(\d+)\.\s*(.*)$")
_GROUP_RE = re.compile(r"^===.*===$")
_HEADER_CALLS = ("_createHeaderRow", "_createSectionHeader")


def _self_calls(func: ast.AST) -> list[str]:
    """按源码顺序列出 ``self.xxx()`` 的方法名（保持顺序，不能用 set）。"""
    return [
        node.func.attr
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    ]


def _headers_in(func: ast.AST) -> list[str]:
    """该函数里直接创建的节标题 / 分组标记（按源码顺序）。"""
    found: list[str] = []
    for node in ast.walk(func):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _HEADER_CALLS
        ):
            continue
        for arg in node.args[:1]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append(arg.value.strip())
    return found


def _render_order(cls: ast.ClassDef) -> list[str]:
    """页面上各节的**渲染顺序**：沿 ``_addDemoContent`` 展开调用链。

    展开时把一个方法直接创建的标题先输出、再输出它内部调用的方法的标题 ——
    「先标题后内容」正是实际渲染出来的样子。
    """
    methods = {
        item.name: item
        for item in cls.body
        if isinstance(item, ast.FunctionDef)
    }
    adder = methods.get("_addDemoContent")
    if adder is None:  # pragma: no cover - 调用方已筛过
        return []
    out: list[str] = []
    seen: set[str] = set()

    def walk(func: ast.FunctionDef) -> None:
        out.extend(_headers_in(func))
        for name in _self_calls(func):
            target = methods.get(name)
            if target is None or name in seen:
                continue
            seen.add(name)
            walk(target)

    walk(adder)
    return out


def _iter_page_classes() -> list[tuple[str, ast.ClassDef]]:
    for path in sorted(_EXAMPLE_DIR.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 示例文件都应可解析
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(
                isinstance(item, ast.FunctionDef) and item.name == "_addDemoContent"
                for item in node.body
            ):
                yield path.name, node


_PAGES = list(_iter_page_classes())
_IDS = ["{}::{}".format(f, c.name) for f, c in _PAGES]


class TestSectionTitlesUnique:
    """回归：同一页上同一个节标题不许渲染两次。"""

    def test_library_has_pages_to_check(self):
        assert len(_PAGES) >= 10, "示例页没扫到，检查 _iter_page_classes"

    @pytest.mark.parametrize("filename,cls", _PAGES, ids=_IDS)
    def test_no_duplicate_section_title(self, filename, cls):
        titles = [t for t in _render_order(cls) if not _GROUP_RE.match(t)]
        duplicates = {t: n for t, n in Counter(titles).items() if n > 1}
        assert not duplicates, "{} 有重复渲染的节标题：{}".format(
            filename, sorted(duplicates)
        )

    @pytest.mark.parametrize("filename,cls", _PAGES, ids=_IDS)
    def test_numbers_ascend_within_group(self, filename, cls):
        """同一分组内编号必须严格递增（撞号即重复渲染的「视觉版本」）。

        分组有两个来源：显式的 ``=== xxx ===`` 标记，以及**隐式回落** —— 这批页面
        大量用「编号重新从小到大」来切段（``01..07`` 之后又来 ``01..06``），并不
        都写标记。判据因此取「编号比前一个小 ⇒ 新分组」，组内要求严格递增。
        """
        problems = []
        previous = None
        group = "<页首>"
        for title in _render_order(cls):
            if _GROUP_RE.match(title):
                group = title
                previous = None
                continue
            match = _TITLE_RE.match(title)
            if match is None:
                continue
            number = match.group(1)
            value = int(number) if number.isdigit() else None
            if previous is not None and value is not None:
                if value < previous:
                    group = "<隐式分组，始于 {}>".format(group)
                elif value == previous:
                    problems.append(
                        "{}: 分组 {!r} 内编号 {} 连续出现两次（{}）".format(
                            filename, group, value, title
                        )
                    )
            previous = value
        assert not problems, "\n".join(problems)

    @pytest.mark.parametrize("filename,cls", _PAGES, ids=_IDS)
    def test_no_reachable_demo_twice(self, filename, cls):
        """回归：``_addDemoContent`` 不许同时调 A 与 A 内部调到的 B。

        这是标题重复的**成因**（渲染了两遍），比看标题更早一步暴露。
        """
        methods = {
            item.name: item
            for item in cls.body
            if isinstance(item, ast.FunctionDef)
        }
        adder = methods.get("_addDemoContent")
        assert adder is not None
        directly = set(_self_calls(adder))

        problems = []
        for name in sorted(directly):
            inner = set(_self_calls(methods[name])) if name in methods else set()
            # 只看 demo 方法：``_addInfoText`` / ``note`` 这类通用 helper 本来
            # 就会被页面和各个 demo 各自调用一次，不是重复渲染
            overlap = {n for n in inner & directly if n.startswith("_demo")}
            if overlap:
                problems.append(
                    "{}: _addDemoContent 同时调了 {} 与 {}，"
                    "而 {} 内部又调 {} → 同一段内容渲染两遍".format(
                        filename, sorted(overlap), name, name, sorted(overlap)
                    )
                )
        assert not problems, "\n".join(problems)