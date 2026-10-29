"""README 与 ``chat_guide_page.py`` 的 API 表**机器对账**。

这两处文档**纯文本、无测试守护**，是最容易悄悄过期的地方（AGENTS.md 早就
写过这句）。本文件把「文档提到的名字」与「代码真的有的名字」双向对账，让漂移
变成红灯而不是等读者踩。

三条守卫：

1. **README 工具函数表的签名与代码一致** —— 抓的是「首参类型都写错了」那类
   （历史上 ``svg_to_icon(path, size)`` 实际首参是 SVG **字符串**）；
2. **README 组件表覆盖了全部对外导出的 ``Ela*``** —— 反向（代码有、文档没写）
   才是组件表最容易缺的那一半；
3. **``chat_guide_page.py`` 的 API 速查表里点名的方法确实挂在它声称的类上** ——
   名字在全仓存在但**挂在别的类上**同样是文档过期。

**刻意不查**的：上游 ``PyQt6ElaWidgetTools`` 的 C++ 组件名（``ElaText`` /
``ElaMenu`` / ``ElaListView`` 等，本仓库不定义，README「组件来源」表已说明
出处）、Qt / Win32 API 名、枚举的字符串值、纯散文词。
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = ROOT / "pyqt6_ela_pro"
README = ROOT / "README.md"
GUIDE = PKG / "example" / "chat_guide_page.py"


# ---------------------------------------------------------------------------
# 收集「代码里真实存在的名字」
# ---------------------------------------------------------------------------


def _iter_source_files():
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" in str(path) or "example" in path.parts:
            continue
        yield path


def _exported_names() -> dict[str, str]:
    """本包导出（或定义）的类 / 函数 / 顶层常量 -> 定义文件。"""
    out: dict[str, str] = {}
    for path in _iter_source_files():
        rel = str(path.relative_to(PKG))
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover
            continue
        for name in re.findall(r"^class\s+([A-Za-z_]\w*)", src, re.M):
            out.setdefault(name, rel)
        for name in re.findall(r"^def\s+([A-Za-z_]\w*)", src, re.M):
            out.setdefault(name, rel)
        for m in re.finditer(r"^__all__\s*=\s*\[(.*?)\]", src, re.S | re.M):
            for name in re.findall(r'"([A-Za-z_]\w*)"', m.group(1)):
                out.setdefault(name, rel)
    return out


EXPORTED = _exported_names()


def _readme_backticked_bold() -> dict[str, int]:
    """README 里被反引号或**粗体**点名的标识符 -> 行号。

    两个形态都要收：组件名在「特性」小节多用 ``**ElaXxx**``，在「组件一览」表
    里则一律用 ``| **ElaXxx** |`` —— 只收反引号会漏掉一半（实测漏掉 30+ 个）。
    """
    found: dict[str, int] = {}
    for i, line in enumerate(README.read_text(encoding="utf-8").splitlines(), 1):
        frags = re.findall(r"`([^`\n]+)`", line) + re.findall(
            r"\*\*([^*`\n]+)\*\*", line
        )
        for frag in frags:
            for ident in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", frag):
                found.setdefault(ident, i)
    return found


README_NAMES = _readme_backticked_bold()


# ---------------------------------------------------------------------------
# 1. 工具函数表：签名对不对
# ---------------------------------------------------------------------------

#: README 工具函数表里**参数名 / 类型**与代码不一致就会抓到的重点条目。
#: 历史上的真错：\svg_to_icon(path, size)\ —— 首参写成了「路径」，
#: 实际是 SVG **字符串源码**；``svg_icon_loader(path)`` —— 实际无参。
SIGNATURE_ROWS = [
    ("svg_to_icon", ("svg_data", "size", "color")),
    ("svg_to_pixmap", ("svg_data", "size", "color")),
    ("svg_to_image", ("svg_data", "size", "color")),
    ("svg_icon_loader", ()),
    ("show_notify", ("title", "content", "timeout")),
    ("setResizeReflowDeferred", ("widget", "on", "delayMs")),
]


def _readme_function_row(name: str) -> str | None:
    for line in README.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and f"`{name}(" in line:
            return line
    return None


class TestReadmeToolSignatures:
    @pytest.mark.parametrize("name,params", SIGNATURE_ROWS, ids=[r[0] for r in SIGNATURE_ROWS])
    def test_row_exists(self, name, params):
        assert _readme_function_row(name) is not None, (
            f"README 的「工具函数」表里没有 {name} —— 补一行，或确认它已删除"
        )

    @pytest.mark.parametrize("name,params", SIGNATURE_ROWS, ids=[r[0] for r in SIGNATURE_ROWS])
    def test_first_param_is_svg_source_not_a_path(self, name, params, qapp):
        """首参必须是 SVG **字符串**；README 写 ``path`` 会让读者去传文件路径。"""
        import pyqt6_ela_pro as pkg

        obj = getattr(pkg, name)
        row = _readme_function_row(name) or ""
        if params:
            real_first = list(inspect.signature(obj).parameters)[0]
            assert real_first == params[0], (
                f"{name} 首参实际叫 {real_first!r}，README 那行要跟着改"
            )
            if name.startswith("svg_to_"):
                assert "path" not in row.split("|")[1].replace(name, ""), (
                    f"README 把 {name} 的首参写成了 path，实际是 SVG 源码字符串：{row}"
                )

    def test_loader_takes_no_arguments(self, qapp):
        """``svg_icon_loader`` 是单例句柄，README 旧版写的 ``(path)`` 是错的。"""
        import pyqt6_ela_pro as pkg

        assert not inspect.signature(pkg.svg_icon_loader).parameters
        row = _readme_function_row("svg_icon_loader") or ""
        assert "path" not in row, f"README 把 svg_icon_loader 写成要传 path：{row}"

    def test_documented_free_functions_exist(self, qapp):
        """工具函数表里点名的函数必须真存在，且参数名与表里写的对得上。

        **刻意不查「顶层导出的公开函数全都得在表里」**：``__all__`` 里混着
        令牌名（``textDisabled`` / ``chartPalette``）、markdown / terminal 主题
        注册函数和 blueprint 的内部 helper —— 它们在各自小节里成组出现，不适合
        挤进「工具函数」表。反向覆盖由
        :meth:`TestReadmeComponentTable.test_public_ela_classes_are_documented`
        负责。
        """
        import pyqt6_ela_pro as pkg

        bad = []
        for name, params in SIGNATURE_ROWS:
            obj = getattr(pkg, name, None)
            if obj is None:
                bad.append(f"{name}: 顶层没有导出")
                continue
            real = tuple(inspect.signature(obj).parameters)
            real_required = tuple(
                p
                for p, v in inspect.signature(obj).parameters.items()
                if v.default is inspect.Parameter.empty
            )
            # 表里写的参数名要与代码一致（顺序也一致）
            if params and real[: len(params)] != params:
                bad.append(f"{name}: README 写 {params}，代码是 {real}")
            # 表里必须把必填参数都列出来
            for req in real_required:
                row = _readme_function_row(name) or ""
                if req not in row:
                    bad.append(f"{name}: 必填参数 {req!r} 没出现在 README 那行")
        assert not bad, "\n".join(bad)


# ---------------------------------------------------------------------------
# 2. 组件表：反向覆盖
# ---------------------------------------------------------------------------


def _component_table_text() -> str:
    lines = README.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## 组件一览")
    except StopIteration:  # pragma: no cover
        return ""
    return "\n".join(lines[start:])


#: 组件表是「对外可用的组件」清单，下列名字属于内部实现 / 渲染细节，
#: 刻意不要求出现在 README 里（否则表格会被 30+ 个内部类撑爆）。
INTENTIONAL_UNDOCUMENTED = {
    # blueprint 内部实现（公开入口是 ElaBlueprintCanvas，已记录）
    "ElaBlueprintGraph", "ElaBlueprintNode", "ElaEdge", "ElaEdgeWidget",
    "ElaExecutionController", "ElaNodeContextMenu", "ElaNodeCreationMenu",
    "ElaNodeWidget", "ElaPin", "ElaPinDirectionType", "ElaPinHandle", "ElaTempWire",
    # 基类 / 混入 / 代理（不是宿主直接实例化的东西）
    "ElaAnimatedMixin", "ElaThemeWidget",
}


class TestReadmeComponentTable:
    def test_public_ela_classes_are_documented(self):
        """对外类至少要在 README 里**某处**被提到。

        判据用**全文**而不是「组件一览」表：README 是按特性组织的，同一个类
        常常「特性」小节讲一次、「组件一览」表再列一次（如 ``ElaGhostBox`` /
        ``ElaMenuItem`` 都只在前面出现过）。要求进表会把文档结构绑死在一种排法上。
        """
        readme_text = README.read_text(encoding="utf-8")
        assert "## 组件一览" in readme_text, "README 里的「## 组件一览」小节不见了"
        missing = [
            name
            for name in sorted(EXPORTED)
            if name.startswith("Ela")
            and name not in readme_text
            and name not in INTENTIONAL_UNDOCUMENTED
        ]
        assert not missing, (
            "这些对外类在 README 里完全查不到（代码已导出、文档没写）：\n"
            + "\n".join(
                "  {:32} 定义于 {}".format(n, EXPORTED[n]) for n in missing
            )
        )

    def test_documented_ela_classes_exist(self):
        """反向：README 组件表里的 Ela* 必须真存在（否则是删了没改文档）。

        上游 ``PyQt6ElaWidgetTools`` 的 C++ 组件也算「存在」—— 本仓库不定义
        它们，README「组件来源」表已说明出处（``ElaText`` / ``ElaMenu`` /
        ``ElaListView`` / ``ElaColorDialog`` 等）。
        """
        table = _component_table_text()
        import PyQt6ElaWidgetTools as upstream

        gone = []
        for name in sorted(set(re.findall(r"\*\*(Ela\w+)\*\*", table))):
            if hasattr(upstream, name):
                continue
            if any(name in path.read_text(encoding="utf-8") for path in _iter_source_files()):
                continue
            gone.append(name)
        assert not gone, "README 组件表里的这些类在代码里已经不存在了：" + ", ".join(gone)


# ---------------------------------------------------------------------------
# 3. chat_guide_page 的 API 速查表
# ---------------------------------------------------------------------------


def _guide_doc() -> str:
    src = GUIDE.read_text(encoding="utf-8")
    blocks = []
    pos = 0
    while True:
        i = src.find('r"""', pos)
        if i < 0:
            break
        body = i + 4
        j = src.index('\n"""', body)
        blocks.append(src[body:j])
        pos = j + 1
    return "\n".join(blocks)


#: 小节标题 -> 表格里点名的方法应当挂在它上面的类
#: **标题要写全（含收尾括号）**：只锚前缀的话，「Binder（回合生命周期，宿主主入口）」
#: 改成「Binder（回合生命周期总览）」仍然包含那个前缀，守卫就成了摆设。
GUIDE_SECTIONS = {
    "Binder（回合生命周期，宿主主入口）": "pyqt6_ela_pro.chat:ElaChatStreamBinder",
    "Widget（宿主行为）": "pyqt6_ela_pro.chat:ElaChatWidget",
    "Input（输入区，经 `chatInput()` 调用）": "pyqt6_ela_pro.chat:ElaChatInput",
    "View（消息内容层，经 `chatView()` 调用）": "pyqt6_ela_pro.chat:ElaChatView",
    "Mock 后端（无模型服务跑通全链路）": "pyqt6_ela_pro.chat:ElaChatMockBackend",
}

#: 挂在别处的东西：自由函数、模块级常量、bubble 层 / view 内部协议
#: （文档自己就标注了那些是内部协议，不该按 widget/view 的属性去查）
GUIDE_ELSEWHERE = {
    "registerToolRenderer", "DISCLAIMER_TEXT", "toDict", "fromDict",
    "actions", "footer", "meta", "header", "text", "parts",
    "markdownViewer", "inlineReasoningViewer", "statsBadge", "toolPanels",
    "setAvatarShape", "setActionsHoverReveal",
    "bubble", "contentWidget", "holdFollow", "jumpThreshold", "isBatchActive",
    "guardNestedScroll", "setRenderDeferred", "flushRender", "hasPendingRender",
    "beginText", "appendText", "addToolCall", "setParts", "setStatus",
    "setStepStats", "beginAssistantMessage", "endAssistantMessage",
    "stopGeneration", "setCurrentSessionId", "chatView", "chatInput",
    "inputSurface", "permissionDock", "acceptsMime", "attachMime",
    "filesAdded", "imagePasted", "newTopicButton", "setNewTopicVisible",
    "updateToolResult",
}


def _resolve(dotted: str):
    import importlib

    mod_name, cls_name = dotted.split(":")
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)


def _api_cell_names(row: str) -> list[str]:
    """从表格**第一列**（API 列）抽出 API 名字。

    **只查第一列**：说明列里出现的方法名多半是在讲「这个方法**不是**本类的方法」
    或「在别处的安全边界」，例如 Binder 那行的 ``免写 closeEvent``（``closeEvent``
    是 Qt 的）、Widget 那行的 ``在 beginStep 安全边界``（是 bubble 侧的）。查说明列
    会把它们全判成过期 API。

    同一格里只取「紧跟 ``(`` 的」或「独占整格的」标识符 —— 否则
    ``permissionRequested(id, requestId)`` 里的形参名会被当成方法名。
    """
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    if not cells:
        return []
    first = cells[0]
    names: list[str] = []
    for frag in re.findall(r"`([^`]+)`", first):
        stripped = frag.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stripped):
            names.append(stripped)
            continue
        # `foo(a, b)` 形态：只取函数名
        for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", frag):
            names.append(m.group(1))
    return names


def _parameter_names(cls) -> set[str]:
    """该类所有方法的形参名 —— 用来把文档里的**参数名**误判挡掉。

    靠命名风格猜不行：camelCase 既是本库的参数名约定（``messageId`` /
    ``requestId`` / ``costUsd``），也是方法名约定（``setSelectedIndex``）。
    """
    names: set[str] = set()
    for attr in dir(cls):
        obj = getattr(cls, attr, None)
        target = obj
        if isinstance(obj, property):
            target = obj.fget
        if not callable(target):
            continue
        try:
            params = inspect.signature(target).parameters
        except (TypeError, ValueError):  # 内建 / C++ 方法
            continue
        names.update(params)
    return names


class TestChatGuideApiTable:
    @pytest.mark.parametrize(
        "title,dotted",
        list(GUIDE_SECTIONS.items()),
        ids=[t[:22] for t in GUIDE_SECTIONS],
    )
    def test_section_header_still_matches(self, title, dotted):
        """小节标题改了要同步这张映射表 —— 表格小节改名等于换了一张表。"""
        assert title in _guide_doc(), (
            f"chat_guide_page 里已没有「{title}...」小节；"
            "改标题的话记得同步 GUIDE_SECTIONS"
        )

    @pytest.mark.parametrize(
        "title,dotted",
        list(GUIDE_SECTIONS.items()),
        ids=[t[:22] for t in GUIDE_SECTIONS],
    )
    def test_documented_methods_exist_on_the_claimed_class(self, title, dotted, qapp):
        cls = _resolve(dotted)
        params = _parameter_names(cls)
        doc = _guide_doc()
        # 只看该小节到下一个 "## " 之间的表格行
        start = doc.index(title)
        rest = doc[start + len(title) :]
        end = rest.find("\n## ")
        section = rest[:end] if end > 0 else rest

        missing = []
        for line in section.splitlines():
            if not line.startswith("|"):
                continue
            for name in _api_cell_names(line):
                if not name or name in GUIDE_ELSEWHERE or name in params:
                    continue
                if hasattr(cls, name):
                    continue
                # 只查「看起来像方法」的：小写开头且含大写 / 含下划线
                looks_method = name[0].islower() and (
                    any(c.isupper() for c in name[1:]) or "_" in name
                )
                if not looks_method:
                    continue
                missing.append(name)

        assert not missing, (
            f"「{title}」小节里这些名字在 {cls.__name__} 上不存在（文档过期）："
            + ", ".join(sorted(set(missing)))
        )

    def test_journal_documents_incremental_append(self):
        """追加落盘必须提 `dumpsNewLines()`：`dumps()` 是整份历史，append 会重复重放。"""
        assert "dumpsNewLines()" in _guide_doc()

    def test_binder_auto_connects_exactly_six_signals(self, qapp):
        """文档写「自动接 6 条机械信号」，且括号里要**列全**那 6 个。"""
        import pathlib as _pl

        from pyqt6_ela_pro.chat import binder as binder_mod

        src = _pl.Path(binder_mod.__file__).read_text(encoding="utf-8")
        i = src.index("def connectWorker")
        body = src[i : i + 1200]
        connected = re.findall(r"worker\.(\w+)\.connect", body)
        assert len(connected) == 6, (
            f"connectWorker 实际自动接了 {len(connected)} 条：{connected}；"
            "文档与测试都要跟着改"
        )
        doc = _guide_doc()
        assert "自动接 6 条机械信号" in doc
        # **只查提到「6 条」的整个列表项**：整篇文档里这 6 个名字在别处（worker
        # 鸭子类型表等）也出现过，查全文的话清单漏一个也抓不到；而这个清单在
        # markdown 里**跨了两行**，只看一行同样会漏 —— 所以一路吃到下一个列表项。
        anchor = doc.index("自动接 6 条机械信号")
        item_start = doc.rfind("\n", 0, anchor) + 1
        segment_lines = []
        cursor = item_start
        for _ in range(8):  # 最多吃 8 行，覆盖折行
            nl = doc.find("\n", cursor)
            if nl < 0:
                segment_lines.append(doc[cursor:])
                break
            segment_lines.append(doc[cursor:nl])
            cursor = nl + 1
        segment = "\n".join(segment_lines)
        for name in connected:
            assert f"`{name}`" in segment, (
                f"connectWorker 自动接了 {name!r}，但指南「6 条」清单里没列全"
            )

    def test_thinking_env_values_documented(self):
        """``LLM_TEST_THINKING`` 的真值集合要与 llm_test 实际判定一致。"""
        llm_main = ROOT / "llm_test" / "agent_demo.py"
        src = llm_main.read_text(encoding="utf-8")
        tree = ast.parse(src)
        truthy: set[str] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.In)):
                continue
            if not (isinstance(node.left, ast.Name) and node.left.id == "thinking"):
                continue
            for comparator in node.comparators:
                # 比较对象是一个 **元组字面量**（`thinking in ("1", "true", ...)`），
                # 不是若干个 Constant —— 直接收 Constant 会得到空集
                elements = (
                    comparator.elts
                    if isinstance(comparator, ast.Tuple)
                    else [comparator]
                )
                for element in elements:
                    if isinstance(element, ast.Constant):
                        truthy.add(str(element.value))
        assert truthy, (
            "llm_test 里找不到 `thinking in (...)` 的真值判定 —— "
            "判定写法变了的话这里要跟着改"
        )
        doc = _guide_doc()
        for value in sorted(truthy):
            assert f"`{value}`" in doc, (
                f"LLM_TEST_THINKING 的真值 {value!r} 没写进指南的环境变量表"
            )
