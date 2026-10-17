"""聊天组件指南页：源码快照一致性 + 代码围栏 / 语法着色的回归测试。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer
from pyqt6_ela_pro.example.chat_guide_page import (
    LLM_TEST_AGENT_DEMO_SOURCE,
    LLM_TEST_MAIN_SOURCE,
    ChatGuidePage,
)

#: 仓库根目录（tests/example/ → 上两级）
_REPO_ROOT = Path(__file__).resolve().parents[2]


#: ``os.environ.get("LLM_TEST_*", "<值>")`` 的兜底默认值。
_ENV_DEFAULT_RE = re.compile(r'os\.environ\.get\("(LLM_TEST_[A-Z_]+)",\s*"[^"]*"\)')

#: 快照里允许出现的 API key 占位值（真 key 一律不许入库）。
_SAFE_KEY_DEFAULTS = frozenset({"not-needed", "", "your-api-key", "<local-default>"})


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").strip("\n")


def _scrub_env_defaults(text: str) -> str:
    """把 env 兜底默认值洗成同一个占位符。

    ``LLM_TEST_BASE_URL`` / ``LLM_TEST_MODEL`` / ``LLM_TEST_API_KEY`` 的默认值是
    **机器本地值**（本地 vLLM 还是 ModelScope、哪个模型、有没有 key），跟着
    开发者的机器漂移。让它参与比对的结果只有两个坏处：守卫天天误报，以及为了
    「同步」把个人端点与**真实凭据**抄进已入库的快照常量。代码本身仍逐行比对。
    """
    return _ENV_DEFAULT_RE.sub(r'os.environ.get("\1", "<local-default>")', text)


def test_snapshot_matches_llm_test_sources():
    cases = (
        ("main.py", LLM_TEST_MAIN_SOURCE),
        ("agent_demo.py", LLM_TEST_AGENT_DEMO_SOURCE),
    )
    for name, snapshot in cases:
        path = _REPO_ROOT / "llm_test" / name
        if not path.is_file():
            # llm_test/ 目前不入库（见 .gitignore）；页面侧的快照常量仍在，
            # 缺文件只能跳过这条漂移校验，不能让它把整个 tests/example 拖挂。
            pytest.skip(f"llm_test/{name} 未入库")
        assert _scrub_env_defaults(_normalize(snapshot)) == _scrub_env_defaults(
            _normalize(path.read_text(encoding="utf-8"))
        ), (
            f"快照与 llm_test/{name} 不一致："
            "请把新源码同步到 example/chat_guide_page.py 的常量"
            "（env 兜底默认值除外，机器本地值不参与比对）"
        )


def test_snapshots_carry_no_real_credentials():
    """快照常量是**已入库**文件，不许出现看起来像真凭据的 env 默认值。"""
    for name, snapshot in (
        ("main.py", LLM_TEST_MAIN_SOURCE),
        ("agent_demo.py", LLM_TEST_AGENT_DEMO_SOURCE),
    ):
        for line in snapshot.splitlines():
            match = _ENV_DEFAULT_RE.search(line)
            if match and match.group(1).endswith("API_KEY"):
                default = re.search(r'"([^"]*)"\s*\)', line).group(1)
                assert default in _SAFE_KEY_DEFAULTS, (
                    f"{name} 快照里的 {match.group(1)} 默认值 {default!r} "
                    f"看起来是真凭据，只允许 {_SAFE_KEY_DEFAULTS}"
                )


def test_guide_page_renders_both_sources(qapp):
    page = ChatGuidePage()
    page.buildDemoContent()  # 内容惰性构建（不 show 的守卫要显式建）
    viewers = page.findChildren(ElaMarkdownViewer)
    assert len(viewers) >= 5

    text = "\n".join(viewer.toPlainText() for viewer in viewers)
    assert "组件栈概览" in text
    assert "四步接入" in text and "class DemoWindow" in text
    assert "关键 API 速查" in text
    assert "真实后端" in text and "class AgentWorker" in text
    assert "运行与依赖" in text

    page.deleteLater()
    qapp.processEvents()


def test_guide_page_code_fences_are_closed(qapp):
    """闭合围栏必须独占一行。

    贴到源码末行（快照常量常无尾换行）会被解析成**未闭合围栏**（= 流式中间态）：
    超过 4096 字符时静默丢掉全部 pygments 着色，同一 viewer 里后续内容还会被
    吞进代码块。白盒断言 ``closed`` 标志，不依赖 pygments 是否安装。
    """
    page = ChatGuidePage()
    page.buildDemoContent()  # 内容惰性构建（不 show 的守卫要显式建）
    blocks = [
        fenced
        for viewer in page.findChildren(ElaMarkdownViewer)
        for fenced in viewer._fenced_blocks
    ]
    assert len(blocks) >= 3, blocks
    unclosed = [(lang, code[:40]) for lang, code, closed in blocks if not closed]
    assert not unclosed, f"围栏没闭合（末行与 ``` 粘连）：{unclosed}"

    page.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("marker", ["raise SystemExit(main())", "class AgentWorker"])
def test_guide_page_sources_are_highlighted(qapp, marker):
    """两个源码快照块必须真的带 pygments 着色。

    判据：代码行内出现**不止一种**前景色（跳过行号槽）。整块无着色时只有基色一种
    → 必挂。颜色比 ``.name()`` 字符串：``QColor.__eq__`` 对 Qt 内部返回的颜色不靠谱。
    """
    pytest.importorskip("pygments")
    page = ChatGuidePage()
    page.buildDemoContent()  # 内容惰性构建（不 show 的守卫要显式建）
    viewer = next(
        v for v in page.findChildren(ElaMarkdownViewer) if marker in v.toPlainText()
    )
    cursor = viewer.document().find(marker)
    assert not cursor.isNull(), marker

    colors = set()
    it = cursor.block().begin()
    while not it.atEnd():
        fragment = it.fragment()
        if fragment.isValid():
            text = fragment.text().strip()
            if text and not text.isdigit():  # 行号槽是纯数字片段
                colors.add(fragment.charFormat().foreground().color().name())
        it += 1
    assert len(colors) >= 2, f"{marker} 所在代码块没有语法着色：{sorted(colors)}"

    page.deleteLater()
    qapp.processEvents()
